"""Document stage — render the data to a PDF, then critique it visually.

This is the heaviest stage: it owns a generator, a critic, a gateway, and the
render **loop** sub-graph (generate → critique → fix → re-render). The critic is
a deterministic guard (did a PDF appear? track consecutive render failures) plus
a vision-model judgment, returning a structured ``Verdict``.

``build_loop(ctx)`` returns a nested Graph suitable for use as a node in the
outer pipeline. All configuration — render backend, model names, threshold,
paths — comes from the ``StageContext`` bound into each node at build time.
"""
from __future__ import annotations

import os
import time

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from strands.multiagent import GraphBuilder
from strands_tools import file_write, file_read, shell, editor

from seed_data import prompts, MODELS
from seed_data.tools import read_json_file, random_roll
from seed_data.stages.base import (
    StageContext, Verdict, CritiqueIssue, FunctionNode, rejected,
)

# Renderers that consume an HTML file (via render_html_to_pdf). Anything else
# (e.g. "reportlab") is a Python-script renderer run through shell.
HTML_RENDERERS = ("xhtml2pdf", "weasyprint")

GENERATOR_NAME = "doc_generator"
CRITIC_NAME = "doc_critic"
GATEWAY_NAME = "doc_gateway"

MAX_CONSECUTIVE_RENDER_FAILURES = 3


def _is_html(renderer: str) -> bool:
    return renderer in HTML_RENDERERS


def build_generator(ctx: StageContext) -> Agent:
    """Build the doc-generator agent (HTML or ReportLab-script flavor)."""
    is_html = _is_html(ctx.renderer)
    prompt_template = "doc_generator_html" if is_html else "doc_generator"
    system_prompt = prompts.render(
        prompt_template,
        schema_json=_schema_json(ctx),
        steering=ctx.steering,
        extra=ctx.extra,
        output_path=ctx.output_path,
        data_json_path=ctx.data_json_path,
        threshold=ctx.threshold,
        script_path=ctx.script_path,
        enable_preview=False,
    )

    # ReportLab flavor: append the cheat sheet to the system prompt.
    if ctx.renderer == "reportlab":
        cheatsheet = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "prompts", "reportlab_cheatsheet.md"
        )
        if os.path.exists(cheatsheet):
            with open(cheatsheet) as f:
                system_prompt += f"\n\nReportLab Reference:\n{f.read()}"

    tools = [file_write, editor, read_json_file, random_roll]
    if is_html:
        # Bind the renderer backend into this generator's own render tool — no
        # global env var, so concurrent workers with different renderers are safe.
        from seed_data.tools import make_render_tool
        tools.append(make_render_tool(ctx.renderer))
    else:
        tools.append(shell)

    # Nova models have 1M context and strict message ordering — no sliding window.
    model_id = MODELS.get(ctx.models.doc, {}).get("model_id", ctx.models.doc)
    if "amazon.nova" in model_id:
        conv_manager = NullConversationManager()
    else:
        conv_manager = SlidingWindowConversationManager(
            window_size=10, should_truncate_results=True, per_turn=True,
        )

    return Agent(
        name=GENERATOR_NAME,
        model=make_model(ctx.models.doc, thinking_budget=4096, role="doc", session=ctx.session),
        system_prompt=system_prompt,
        tools=tools,
        conversation_manager=conv_manager,
    )


def _schema_json(ctx: StageContext) -> str:
    import json
    return json.dumps(ctx.schema_dict, indent=2)


def build_critic(ctx: StageContext) -> FunctionNode:
    """Build the doc-critic node: render guard + vision-model judgment → Verdict.

    Tracks consecutive render failures across retries via a mutable counter held
    on the node instance (not module globals), raising if the renderer never
    produces a PDF after ``MAX_CONSECUTIVE_RENDER_FAILURES`` tries.
    """
    render_failures = {"count": 0}

    def _run(task_text: str, ctx: StageContext) -> str:
        is_html = _is_html(ctx.renderer)

        # Guard: did the render produce a PDF?
        if not os.path.exists(ctx.output_path):
            render_failures["count"] += 1
            n = render_failures["count"]
            print(f"\n--- Doc Critic: REJECTED (PDF not found, render failure {n}/{MAX_CONSECUTIVE_RENDER_FAILURES}) ---")
            if n >= MAX_CONSECUTIVE_RENDER_FAILURES:
                raise RuntimeError(
                    f"PDF rendering failed {MAX_CONSECUTIVE_RENDER_FAILURES} times in a row. "
                    f"The {ctx.renderer} renderer could not produce a PDF at {ctx.output_path}. "
                    f"Check that {ctx.renderer} and any required system libraries are correctly installed."
                )
            if is_html:
                fix = (f'Call render_html_to_pdf(html_path="{ctx.script_path}", '
                       f'pdf_path="{ctx.output_path}") to generate the PDF')
            else:
                fix = f'Call shell(command="python {ctx.script_path}") to generate the PDF'
            return Verdict(
                accepted=False, score=0,
                summary="PDF was not generated.",
                feedback=f"PDF not created at {ctx.output_path}.\nFIX: {fix}",
                issues=[CritiqueIssue(category="completeness", severity="critical",
                                      description=f"PDF not created at {ctx.output_path}", fix_hint=fix)],
            ).as_node_text()

        render_failures["count"] = 0  # reset on successful render
        mtime = os.path.getmtime(ctx.output_path)
        print(f"\n--- Doc Critic: {os.path.basename(ctx.output_path)} "
              f"({time.strftime('%H:%M:%S', time.localtime(mtime))}, "
              f"{os.path.getsize(ctx.output_path):,}b) ---")

        # Vision-model judgment (delegates to the existing critique helper).
        from seed_data.critique import critique_document
        data_json_str = None
        if os.path.exists(ctx.data_json_path):
            with open(ctx.data_json_path) as f:
                data_json_str = f.read()
        result = critique_document(
            pdf_path=ctx.output_path, model=ctx.models.critic, threshold=ctx.threshold,
            steering=ctx.steering,
            sample_pdfs=ctx.sample_pdfs if ctx.critic_samples else None,
            data_json=data_json_str, session=ctx.session,
        )

        accepted_ = result["verdict"] == "accepted"
        feedback = result["text"]
        if not accepted_:
            if is_html:
                rerun = (f"Fix the issues above in the existing HTML at {ctx.script_path}. "
                         f"Use editor to make targeted changes, then call "
                         f'render_html_to_pdf(html_path="{ctx.script_path}", pdf_path="{ctx.output_path}")')
            else:
                rerun = (f"Fix the issues above in the existing script at {ctx.script_path}. "
                         f"Use editor to make targeted changes, then re-run: "
                         f'shell(command="python {ctx.script_path}")')
            feedback = f"{result['text']}\n\n{rerun}"

        return Verdict(
            accepted=accepted_,
            score=int(result.get("score", 0)),
            summary=result["text"].splitlines()[0] if result.get("text") else "",
            feedback=feedback,
        ).as_node_text()

    return FunctionNode(func=_run, name=CRITIC_NAME, ctx=ctx)


def build_gateway(ctx: StageContext) -> FunctionNode:
    """Rewrite the incoming task into a clear PDF-generation instruction."""
    def _run(task_text: str, ctx: StageContext) -> str:
        if _is_html(ctx.renderer):
            return (
                f"Generate the PDF. Read data from {ctx.data_json_path} using read_json_file. "
                f"Write an HTML file to {ctx.script_path}, then call "
                f'render_html_to_pdf(html_path="{ctx.script_path}", pdf_path="{ctx.output_path}").'
            )
        return (
            f"Generate the PDF. Read data from {ctx.data_json_path} using read_json_file. "
            f"Write a Python script to {ctx.script_path}, run it with "
            f'shell(command="python {ctx.script_path}"), and save the PDF to {ctx.output_path}.'
        )
    return FunctionNode(func=_run, name=GATEWAY_NAME, ctx=ctx)


def build_loop(ctx: StageContext, timeout: int = 3600):
    """Build the doc render loop as a nested Graph node.

    gateway → generator → critic, looping critic → generator on reject.
    """
    gateway = build_gateway(ctx)
    generator = build_generator(ctx)
    critic = build_critic(ctx)

    inner = GraphBuilder()
    inner.add_node(gateway, GATEWAY_NAME)
    inner.add_node(generator, GENERATOR_NAME)
    inner.add_node(critic, CRITIC_NAME)
    inner.add_edge(GATEWAY_NAME, GENERATOR_NAME)
    inner.add_edge(GENERATOR_NAME, CRITIC_NAME)
    inner.add_edge(CRITIC_NAME, GENERATOR_NAME, condition=rejected(CRITIC_NAME))
    inner.set_entry_point(GATEWAY_NAME)
    inner.set_max_node_executions(100)
    inner.set_execution_timeout(timeout)
    inner.reset_on_revisit(False)
    return inner.build()


# imported late to avoid a heavy import at module load if unused
from seed_data.utils import make_model  # noqa: E402

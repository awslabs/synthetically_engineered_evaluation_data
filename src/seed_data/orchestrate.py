"""Document Generation Orchestrator — Strands Graph Workflow.

Outer graph (reset_on_revisit=True):
  data_generator → data_critic → doc_loop → [augmentor → aug_critic]

Inner sub-graph "doc_loop" (reset_on_revisit=False):
  doc_generator → doc_critic → (loop on reject)
"""
import json
import os
import uuid

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from strands.multiagent import GraphBuilder
from strands_tools import file_write, file_read, shell, editor

from seed_data.critique import critique_document, critique_data
from seed_data.tools import save_json_file, read_json_file, random_roll
from seed_data.nodes import (
    FunctionNode, was_rejected_visual, was_rejected_data,
    data_accepted, aug_rejected,
)
from seed_data.utils import sha256_file, make_model, load_schema_dir
from seed_data import prompts, MODELS

# Renderers that consume an HTML file (via the render_html_to_pdf tool). Anything
# else (e.g. "reportlab") is a Python-script renderer run through shell.
HTML_RENDERERS = ("xhtml2pdf", "weasyprint")


def _build_doc_loop(
    output_path, data_json_path, script_path, schema_json, steering, extra,
    doc_model, critic_model, threshold, timeout, sample_pdfs=None, critic_samples=True,
    enable_preview=False, renderer="xhtml2pdf",
):
    """Build the inner doc_generator ↔ doc_critic sub-graph."""

    is_html = renderer in HTML_RENDERERS
    prompt_template = "doc_generator_html" if is_html else "doc_generator"
    doc_gen_prompt = prompts.render(
        prompt_template, schema_json=schema_json, steering=steering,
        extra=extra, output_path=output_path,
        data_json_path=data_json_path, threshold=threshold,
        script_path=script_path, enable_preview=enable_preview,
    )

    # Append reportlab cheat sheet to system prompt (not as pre-seeded messages,
    # which can break message ordering after sliding window trims).
    if renderer == "reportlab":
        cheatsheet_path = os.path.join(os.path.dirname(__file__), "prompts", "reportlab_cheatsheet.md")
        if os.path.exists(cheatsheet_path):
            with open(cheatsheet_path) as f:
                doc_gen_prompt += f"\n\nReportLab Reference:\n{f.read()}"

    tools = [file_write, editor, read_json_file, random_roll]
    if is_html:
        # Tell the render_html_to_pdf tool which backend to use for this run.
        os.environ["HTML_RENDERER"] = renderer
        from seed_data.tools import render_html_to_pdf
        tools.append(render_html_to_pdf)
    else:
        tools.append(shell)
    if enable_preview:
        from seed_data.tools import preview_pdf
        tools.append(preview_pdf)

    # Nova models have 1M context — no need for sliding window, and it breaks
    # their strict message ordering requirements. Other models need it.
    model_id = MODELS.get(doc_model, {}).get("model_id", doc_model)
    if "amazon.nova" in model_id:
        conv_manager = NullConversationManager()
    else:
        conv_manager = SlidingWindowConversationManager(
            window_size=10,
            should_truncate_results=True,
            per_turn=True,
        )

    doc_generator = Agent(
        name="doc_generator",
        model=make_model(doc_model, thinking_budget=4096, role="doc"),
        system_prompt=doc_gen_prompt,
        tools=tools,
        conversation_manager=conv_manager,
    )

    _render_failures = [0]  # mutable counter accessible in closure

    def _doc_critic_fn(task_text):
        if not os.path.exists(output_path):
            _render_failures[0] += 1
            print(f"\n--- Doc Critic: REJECTED (PDF not found, render failure {_render_failures[0]}/3) ---")
            if _render_failures[0] >= 3:
                raise RuntimeError(
                    f"PDF rendering failed 3 times in a row. "
                    f"The {renderer} renderer could not produce a PDF at {output_path}. "
                    f"Check that {renderer} and any required system libraries are correctly installed."
                )
            if is_html:
                fix = (
                    f'Call render_html_to_pdf(html_path="{script_path}", '
                    f'pdf_path="{output_path}") to generate the PDF'
                )
            else:
                fix = f'Call shell(command="python {script_path}") to generate the PDF'
            return (
                f"CRITIQUE FEEDBACK — Score: 0/10 — REJECTED\n"
                f"VERDICT:rejected\n\n"
                f"Summary: PDF was not generated.\n\n"
                f"Issues:\n"
                f"- [critical] PDF not created at {output_path}\n"
                f"  FIX: {fix}"
            )
        _render_failures[0] = 0  # reset on successful render
        mtime = os.path.getmtime(output_path)
        import time as _time
        print(f"\n--- Doc Critic: {os.path.basename(output_path)} "
              f"({_time.strftime('%H:%M:%S', _time.localtime(mtime))}, "
              f"{os.path.getsize(output_path):,}b) ---")
        # Load data JSON so critic knows what fields are in scope
        data_json_str = None
        if os.path.exists(data_json_path):
            with open(data_json_path) as _f:
                data_json_str = _f.read()
        result = critique_document(
            pdf_path=output_path, model=critic_model, threshold=threshold,
            steering=steering, sample_pdfs=sample_pdfs if critic_samples else None,
            data_json=data_json_str,
        )
        # Format as clear retry instructions for the generator
        if result["verdict"] == "rejected":
            if is_html:
                rerun_instruction = (
                    f"Fix the issues above in the existing HTML at {script_path}. "
                    f"Use editor to make targeted changes, then call "
                    f'render_html_to_pdf(html_path="{script_path}", pdf_path="{output_path}")'
                )
            else:
                rerun_instruction = (
                    f"Fix the issues above in the existing script at {script_path}. "
                    f"Use editor to make targeted changes, then re-run: "
                    f'shell(command="python {script_path}")'
                )
            return (
                f"CRITIQUE FEEDBACK — Score: {result['score']}/10 — REJECTED\n\n"
                f"{result['text']}\n\n"
                f"{rerun_instruction}"
            )
        return result["text"]

    doc_critic = FunctionNode(func=_doc_critic_fn, name="doc_critic")

    # Gateway node rewrites the incoming task (which may contain data-gen instructions
    # from the outer graph) into a clear PDF generation task for the doc_generator.
    def _doc_gateway(task_text):
        if is_html:
            return (
                f"Generate the PDF. Read data from {data_json_path} using read_json_file. "
                f"Write an HTML file to {script_path}, then call "
                f'render_html_to_pdf(html_path="{script_path}", pdf_path="{output_path}").'
            )
        return (
            f"Generate the PDF. Read data from {data_json_path} using read_json_file. "
            f"Write a Python script to {script_path}, run it with "
            f'shell(command="python {script_path}"), and save the PDF to {output_path}.'
        )

    doc_gateway = FunctionNode(func=_doc_gateway, name="doc_gateway")

    inner = GraphBuilder()
    inner.add_node(doc_gateway, "doc_gateway")
    inner.add_node(doc_generator, "doc_generator")
    inner.add_node(doc_critic, "doc_critic")
    inner.add_edge("doc_gateway", "doc_generator")
    inner.add_edge("doc_generator", "doc_critic")
    inner.add_edge("doc_critic", "doc_generator", condition=was_rejected_visual)
    inner.set_entry_point("doc_gateway")
    inner.set_max_node_executions(100)
    # High default timeout as a safety net — max_node_executions is the real guardrail.
    inner.set_execution_timeout(timeout)
    inner.reset_on_revisit(False)
    return inner.build()


def orchestrate(
    schema_dir: str,
    output_dir: str = "./output",
    extra_instructions: str = None,
    data_model: str = "sonnet",
    doc_model: str = "sonnet",
    critic_model: str = "haiku",
    aug_model: str = "sonnet",
    threshold: int = 7,
    max_attempts: int = 5,
    timeout: int = 3600,
    augment: bool = False,
    critic_samples: bool = True,
    renderer: str = "xhtml2pdf",
    enable_preview: bool = False,
    verbose: bool = True,
) -> dict:
    """Build and execute the document generation graph."""
    schema, steering, sample_pdfs = load_schema_dir(schema_dir)
    doctype = schema.get("title", schema.get("document_type", "document")).lower()
    doc_id = uuid.uuid4().hex

    # Output subdirectories — files go directly to their final location
    pdfs_dir = os.path.join(output_dir, "pdfs")
    data_dir = os.path.join(output_dir, "data")
    scripts_dir = os.path.join(output_dir, "generation_scripts")
    config_dir = os.path.join(output_dir, "config")
    for d in (pdfs_dir, data_dir, scripts_dir, config_dir):
        os.makedirs(d, exist_ok=True)

    output_path = os.path.join(pdfs_dir, f"{doc_id}.pdf")
    data_json_path = os.path.join(data_dir, f"{doc_id}.json")
    script_ext = ".html" if renderer in HTML_RENDERERS else ".py"
    script_path = os.path.join(scripts_dir, f"{doc_id}{script_ext}")

    os.environ["CRITIC_MODEL"] = critic_model
    os.environ["OUTPUT_DIR"] = output_dir

    extra = extra_instructions or ""

    schema_json = json.dumps(schema, indent=2)
    from strands_tools.calculator import calculator

    data_gen_prompt = prompts.render(
        "data_generator", schema_json=schema_json, steering=steering,
        extra=extra, data_json_path=data_json_path,
    )
    data_generator = Agent(
        name="data_generator",
        model=make_model(data_model, thinking_budget=4096, role="data"),
        system_prompt=data_gen_prompt,
        tools=[save_json_file, calculator, random_roll],
    )

    # --- Data critic ---
    def _data_critic_fn(task_text):
        if not os.path.exists(data_json_path):
            return json.dumps({
                "score": 0, "verdict": "rejected",
                "issues": [{"category": "completeness", "severity": "critical",
                            "description": f"Data file not found at {data_json_path}. "
                            "You must call save_json_file to save the JSON data."}],
                "summary": "Data was not saved to disk.",
            })

        # Programmatic JSON Schema validation before LLM critique
        import jsonschema
        with open(data_json_path) as _f:
            data = json.load(_f)
        errors = list(jsonschema.Draft7Validator(schema).iter_errors(data))
        if errors:
            issues = [
                {
                    "category": "schema",
                    "severity": "critical",
                    "description": f"{'.' .join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}",
                }
                for e in errors
            ]
            print(f"\n--- Data Critic: Schema validation failed ({len(errors)} error(s)) ---")
            for issue in issues:
                print(f"  {issue['description']}")
            return json.dumps({
                "score": 0, "verdict": "rejected",
                "issues": issues,
                "summary": f"{len(errors)} JSON Schema validation error(s) — fix before LLM critique.",
            })

        result = critique_data(
            data_json_path=data_json_path, schema=schema,
            steering=steering, model=critic_model, threshold=threshold,
        )
        return json.dumps(result)

    data_critic = FunctionNode(func=_data_critic_fn, name="data_critic")

    # --- Doc loop sub-graph ---
    doc_loop = _build_doc_loop(
        output_path=output_path, data_json_path=data_json_path,
        script_path=script_path, schema_json=schema_json,
        steering=steering, extra=extra, doc_model=doc_model,
        critic_model=critic_model, threshold=threshold, timeout=timeout,
        sample_pdfs=sample_pdfs, critic_samples=critic_samples,
        enable_preview=enable_preview, renderer=renderer,
    )

    # --- Outer graph ---
    builder = GraphBuilder()
    builder.add_node(data_generator, "data_generator")
    builder.add_node(data_critic, "data_critic")
    builder.add_node(doc_loop, "doc_loop")
    builder.add_edge("data_generator", "data_critic")
    builder.add_edge("data_critic", "doc_loop", condition=data_accepted)
    builder.add_edge("data_critic", "data_generator", condition=was_rejected_data)

    # --- Optional augmentation ---
    if augment:
        from seed_data.augment import apply_augmentation as aug_apply_tool
        from seed_data.augment import critique_augmented_document

        aug_dir = os.path.join(output_dir, "augmented")
        os.makedirs(aug_dir, exist_ok=True)
        aug_path = os.path.join(aug_dir, f"{doc_id}_augmented.pdf")
        # The tool writes next to the input PDF — we'll move it in the critic
        _tool_aug_path = os.path.splitext(output_path)[0] + "_augmented.pdf"
        aug_prompt = prompts.render(
            "augmentor", pdf_path=output_path, steering=steering, extra=extra,
        )
        augmentor_agent = Agent(
            name="augmentor",
            model=make_model(aug_model),
            system_prompt=aug_prompt,
            tools=[aug_apply_tool],
        )

        # Gateway rewrites task for augmentor — same pattern as doc_gateway
        def _aug_gateway(task_text):
            return (
                f"Apply realistic document aging/degradation effects to the PDF at: {output_path}\n"
                f"Call apply_augmentation with pdf_path=\"{output_path}\" and your chosen config."
            )

        aug_gateway = FunctionNode(func=_aug_gateway, name="aug_gateway")

        def _aug_critic_fn(task_text):
            # Move augmented PDF from tool output location to augmented/ dir
            if os.path.exists(_tool_aug_path) and _tool_aug_path != aug_path:
                import shutil
                shutil.move(_tool_aug_path, aug_path)
            # Move aug_config to config/ dir
            tool_config = _tool_aug_path.replace("_augmented.pdf", "_aug_config.json")
            if os.path.exists(tool_config):
                import shutil
                shutil.move(tool_config, os.path.join(config_dir, f"{doc_id}_aug_config.json"))

            if not os.path.exists(aug_path):
                return json.dumps({
                    "score": 0, "verdict": "rejected",
                    "issues": [{"category": "completeness", "severity": "critical",
                                "description": "Augmented PDF not found", "fix_hint": ""}],
                    "summary": "Augmented PDF was not generated.",
                })
            result = critique_augmented_document(
                pdf_path=aug_path, model=critic_model, threshold=threshold,
            )
            return json.dumps(result)

        aug_critic_node = FunctionNode(func=_aug_critic_fn, name="aug_critic")
        builder.add_node(aug_gateway, "aug_gateway")
        builder.add_node(augmentor_agent, "augmentor")
        builder.add_node(aug_critic_node, "aug_critic")
        builder.add_edge("doc_loop", "aug_gateway")
        builder.add_edge("aug_gateway", "augmentor")
        builder.add_edge("augmentor", "aug_critic")
        builder.add_edge("aug_critic", "augmentor", condition=aug_rejected)

    # Augmentation adds 3+ nodes (gateway, augmentor, aug_critic) plus retries
    aug_budget = 8 if augment else 0
    builder.set_max_node_executions(max_attempts * 2 + 4 + aug_budget)
    # High default timeout as a safety net — max_node_executions is the real guardrail.
    builder.set_execution_timeout(timeout)
    # Outer graph resets — sub-graph handles its own persistence
    builder.reset_on_revisit(True)
    builder.set_entry_point("data_generator")
    graph = builder.build()

    if verbose:
        print(f"Schema dir: {schema_dir}")
        print(f"Doctype:    {doctype}")
        print(f"Output:     {output_path}")
        print(f"Models:     data={data_model}  doc={doc_model}  critic={critic_model}")
        if augment:
            print(f"Augment:    enabled (model={aug_model})")
        print(f"Threshold:  {threshold}/10")
        print(f"Max tries:  {max_attempts}")
        print("=" * 60)

    # --- Execute ---
    try:
        result = graph(
            f"Generate realistic {doctype} data as JSON and save it using save_json_file. "
            f"The doc_generator will use your output to render the PDF."
        )
    except Exception as e:
        return {
            "success": False, "path": None, "doc_id": doc_id,
            "doctype": doctype, "sha256": None, "size_bytes": 0, "error": str(e),
        }

    # --- Token usage ---
    token_usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}

    def _collect_tokens(res):
        """Recursively collect token usage from graph results (including sub-graphs)."""
        if not hasattr(res, "results"):
            return
        for _, node_result in res.results.items():
            nr = node_result.result if hasattr(node_result, "result") else node_result
            # If it's a nested MultiAgentResult, recurse
            if hasattr(nr, "results"):
                _collect_tokens(nr)
            elif hasattr(nr, "metrics"):
                usage = getattr(nr.metrics, "accumulated_usage", {})
                if usage:
                    token_usage["inputTokens"] += usage.get("inputTokens", 0)
                    token_usage["outputTokens"] += usage.get("outputTokens", 0)
                    token_usage["totalTokens"] += (
                        usage.get("inputTokens", 0) + usage.get("outputTokens", 0)
                    )

    _collect_tokens(result)

    # --- Results ---
    if os.path.exists(output_path):
        execution_order = []
        if hasattr(result, "execution_order"):
            execution_order = [n.node_id for n in result.execution_order]
        verdict = "unknown"
        if hasattr(result, "results"):
            # Check doc_loop result (nested graph) or doc_critic directly
            for key in ("doc_loop", "doc_critic"):
                nr = result.results.get(key)
                if nr:
                    ct = str(nr.result).lower().replace("*", "").replace(" ", "")
                    if "verdict:accepted" in ct:
                        verdict = "accepted"
                        break
                    elif "verdict:rejected" in ct:
                        verdict = "rejected"
                        break
        aug_pdf_path = os.path.join(output_dir, "augmented", f"{doc_id}_augmented.pdf")
        return {
            "success": True, "path": output_path, "data_json": data_json_path,
            "augmented_path": aug_pdf_path if augment and os.path.exists(aug_pdf_path) else None,
            "doc_id": doc_id, "doctype": doctype,
            "sha256": sha256_file(output_path),
            "size_bytes": os.path.getsize(output_path),
            "verdict": verdict, "execution_order": execution_order,
            "token_usage": token_usage, "error": None,
        }
    return {
        "success": False, "path": output_path, "doc_id": doc_id,
        "doctype": doctype, "sha256": None, "size_bytes": 0,
        "verdict": "error", "token_usage": token_usage,
        "error": "PDF was not created",
    }

"""Pipeline orchestration — wires stages into a graph and runs one document.

This is the thin orchestrator the stage refactor was aiming for: it builds a
``StageContext``, assembles a self-contained graph from stage builders (each node
holds its own ctx), invokes it, and returns a typed ``GeneratedDoc``. Batch and
packet generation compose this same graph.
"""
from __future__ import annotations

import json
import os
import uuid

from pydantic import BaseModel, Field
from strands.multiagent import GraphBuilder

from seed_data.utils import load_schema_dir, sha256_file
from seed_data.stages.base import StageContext, ModelConfig, Verdict, verdict_of, accepted, rejected
from seed_data.stages import data as data_stage
from seed_data.stages import document as doc_stage
from seed_data.stages import augment_stage


class GeneratedDoc(BaseModel):
    """Typed result of generating one document."""
    success: bool
    doc_id: str
    doctype: str
    pdf_path: str | None = None
    data_json_path: str | None = None
    augmented_path: str | None = None
    verdict: str = "unknown"          # accepted | rejected | error | unknown
    score: int | None = None
    sha256: str | None = None
    size_bytes: int = 0
    execution_order: list[str] = Field(default_factory=list)
    token_usage: dict = Field(default_factory=lambda: {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0})
    error: str | None = None

    @property
    def data(self) -> dict | None:
        """The ground-truth JSON label for this document, loaded lazily.

        This is the paired label eval users want alongside the PDF. Returns None
        if the data file is missing.
        """
        if not self.data_json_path or not os.path.exists(self.data_json_path):
            return None
        with open(self.data_json_path) as f:
            return json.load(f)


def build_context(
    schema_dir: str | None = None,
    output_dir: str = "./output",
    extra: str = "",
    models: ModelConfig | None = None,
    threshold: int = 7,
    renderer: str = "xhtml2pdf",
    critic_samples: bool = True,
    doc_id: str | None = None,
    session=None,
    *,
    resolved: tuple[dict, str, list[str]] | None = None,
) -> StageContext:
    """Assemble the StageContext for one document.

    Provide either ``schema_dir`` (loaded from disk) or a pre-``resolved``
    ``(schema_dict, steering, sample_pdfs)`` triple (e.g. from a ``Schema``).
    """
    if resolved is not None:
        schema, steering, sample_pdfs = resolved
    elif schema_dir is not None:
        schema, steering, sample_pdfs = load_schema_dir(schema_dir)
    else:
        raise ValueError("build_context requires either schema_dir or resolved=...")
    doc_id = doc_id or uuid.uuid4().hex

    pdfs_dir = os.path.join(output_dir, "pdfs")
    data_dir = os.path.join(output_dir, "data")
    scripts_dir = os.path.join(output_dir, "generation_scripts")
    config_dir = os.path.join(output_dir, "config")
    for d in (pdfs_dir, data_dir, scripts_dir, config_dir):
        os.makedirs(d, exist_ok=True)

    script_ext = ".html" if renderer in doc_stage.HTML_RENDERERS else ".py"
    return StageContext(
        schema_dict=schema, steering=steering, sample_pdfs=sample_pdfs, extra=extra,
        output_path=os.path.join(pdfs_dir, f"{doc_id}.pdf"),
        data_json_path=os.path.join(data_dir, f"{doc_id}.json"),
        script_path=os.path.join(scripts_dir, f"{doc_id}{script_ext}"),
        models=models or ModelConfig(),
        threshold=threshold, renderer=renderer, critic_samples=critic_samples,
        output_dir=output_dir, session=session,
    )


def _collect_tokens(result) -> dict:
    """Recursively sum token usage across the graph and sub-graphs."""
    usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}

    def _walk(res):
        if not hasattr(res, "results"):
            return
        for node_result in res.results.values():
            for agent_result in node_result.get_agent_results():
                metrics = getattr(agent_result, "metrics", None)
                acc = getattr(metrics, "accumulated_usage", None) if metrics else None
                if acc:
                    usage["inputTokens"] += acc.get("inputTokens", 0)
                    usage["outputTokens"] += acc.get("outputTokens", 0)
            nr = getattr(node_result, "result", None)
            if hasattr(nr, "results"):
                _walk(nr)

    _walk(result)
    usage["totalTokens"] = usage["inputTokens"] + usage["outputTokens"]
    return usage


# The task string handed to a pipeline graph's entry node.
PIPELINE_TASK = (
    "Generate realistic {doctype} data as JSON and save it using save_json_file. "
    "The doc_generator will use your output to render the PDF."
)


def build_pipeline_graph(
    ctx: StageContext,
    *,
    max_attempts: int = 5,
    timeout: int = 3600,
    augment: bool = False,
):
    """Build the full single-document pipeline as a self-contained Graph.

    Every node has ``ctx`` baked in, so this graph needs no external
    ``invocation_state`` and can be invoked directly *or* composed as a node
    inside a larger graph (e.g. batch fan-out, where N of these run concurrently).

    data_generator → data_critic → [doc render loop] → (augment stage).
    """
    builder = GraphBuilder()
    builder.add_node(data_stage.build_generator(ctx), data_stage.GENERATOR_NAME)
    builder.add_node(data_stage.build_critic(ctx), data_stage.CRITIC_NAME)
    builder.add_node(doc_stage.build_loop(ctx, timeout=timeout), "doc_loop")

    builder.add_edge(data_stage.GENERATOR_NAME, data_stage.CRITIC_NAME)
    builder.add_edge(data_stage.CRITIC_NAME, data_stage.GENERATOR_NAME,
                     condition=rejected(data_stage.CRITIC_NAME))
    builder.add_edge(data_stage.CRITIC_NAME, "doc_loop", condition=accepted(data_stage.CRITIC_NAME))

    if augment:
        augment_stage.add_to_graph(builder, ctx, after_node="doc_loop")

    aug_budget = 8 if augment else 0
    builder.set_max_node_executions(max_attempts * 2 + 4 + aug_budget)
    builder.set_execution_timeout(timeout)
    builder.reset_on_revisit(True)
    builder.set_entry_point(data_stage.GENERATOR_NAME)
    return builder.build()


def generate(
    schema_dir: str | None = None,
    output_dir: str = "./output",
    extra: str = "",
    models: ModelConfig | None = None,
    threshold: int = 7,
    max_attempts: int = 5,
    timeout: int = 3600,
    renderer: str = "xhtml2pdf",
    critic_samples: bool = True,
    augment: bool = False,
    verbose: bool = True,
    session=None,
    *,
    resolved: tuple[dict, str, list[str]] | None = None,
) -> GeneratedDoc:
    """Generate one document through the staged pipeline.

    data_generator → data_critic → [doc render loop] → (augment stage) → done.

    Provide either ``schema_dir`` or a pre-``resolved`` schema triple.
    """
    ctx = build_context(
        schema_dir=schema_dir, output_dir=output_dir, extra=extra,
        models=models, threshold=threshold, renderer=renderer,
        critic_samples=critic_samples, resolved=resolved, session=session,
    )
    doc_id = os.path.splitext(os.path.basename(ctx.output_path))[0]

    graph = build_pipeline_graph(ctx, max_attempts=max_attempts, timeout=timeout, augment=augment)

    if verbose:
        print(f"Doctype:    {ctx.doctype}")
        print(f"Output:     {ctx.output_path}")
        print(f"Models:     data={ctx.models.data}  doc={ctx.models.doc}  critic={ctx.models.critic}")
        if augment:
            print(f"Augment:    enabled (model={ctx.models.aug})")
        print(f"Threshold:  {ctx.threshold}/10   Renderer: {ctx.renderer}")
        print("=" * 60)

    # --- Execute. The graph is self-contained: ctx is baked into its nodes,
    # so no invocation_state is needed and the graph is safe to fan out. ---
    try:
        result = graph(PIPELINE_TASK.format(doctype=ctx.doctype))
    except Exception as e:
        return GeneratedDoc(
            success=False, doc_id=doc_id, doctype=ctx.doctype,
            data_json_path=ctx.data_json_path, verdict="error", error=str(e),
        )

    return result_from(ctx, result, augment=augment)


def result_from(ctx: StageContext, result, *, augment: bool = False) -> GeneratedDoc:
    """Build a typed GeneratedDoc from a pipeline graph's result + its context.

    Shared by single-document runs and by the batch aggregator (which passes each
    worker's own sub-result). ``result`` is a Strands GraphResult/MultiAgentResult
    whose ``.results`` contains the pipeline's nodes (``doc_loop`` / ``doc_critic``).
    """
    doc_id = os.path.splitext(os.path.basename(ctx.output_path))[0]
    tokens = _collect_tokens(result)
    execution_order = [n.node_id for n in getattr(result, "execution_order", [])]

    if os.path.exists(ctx.output_path):
        v = verdict_of(result, "doc_loop") or verdict_of(result, doc_stage.CRITIC_NAME)
        aug_path = augment_stage._aug_output_path(ctx)
        return GeneratedDoc(
            success=True, doc_id=doc_id, doctype=ctx.doctype,
            pdf_path=ctx.output_path, data_json_path=ctx.data_json_path,
            augmented_path=aug_path if augment and os.path.exists(aug_path) else None,
            verdict="accepted" if (v and v.accepted) else ("rejected" if v else "unknown"),
            score=v.score if v else None,
            sha256=sha256_file(ctx.output_path),
            size_bytes=os.path.getsize(ctx.output_path),
            execution_order=execution_order, token_usage=tokens,
        )

    return GeneratedDoc(
        success=False, doc_id=doc_id, doctype=ctx.doctype,
        data_json_path=ctx.data_json_path, verdict="error",
        execution_order=execution_order, token_usage=tokens,
        error="PDF was not created",
    )

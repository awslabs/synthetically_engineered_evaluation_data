"""Batch stage — generate N diverse documents via concurrent graph fan-out.

Two phases:

1. **Plan** — a scenario-planner agent turns one ``brief`` into ``count`` distinct
   scenario strings (structured output).
2. **Fan out** — each scenario gets its own :func:`build_pipeline_graph` (a
   self-contained graph with its ``StageContext`` baked in), added as a **sibling
   node** under a coordinator. Strands runs the siblings **concurrently**, natively.

Each worker's result is read back out of the outer ``GraphResult`` and turned into
a typed ``GeneratedDoc`` by the same :func:`result_from` the single-document path
uses — so batch and single-doc share one result-extraction path.

Concurrency note: the Python Strands SDK runs all ready siblings at once (no
native cap; that lives in the TS SDK's ``maxConcurrency``). Throttling is handled
per-call by the adaptive boto retry config in ``seed_data.utils.BOTO_CONFIG``, so
we do not add any semaphore/wave machinery on top of the graph.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from strands import Agent
from strands.multiagent import GraphBuilder
from strands.multiagent.base import MultiAgentBase, NodeResult, Status, MultiAgentResult
from strands.agent.agent_result import AgentResult
from strands.types.content import ContentBlock, Message

from seed_data.utils import make_model
from seed_data.stages.base import ModelConfig
from seed_data.stages.pipeline import (
    GeneratedDoc, build_context, build_pipeline_graph, result_from, PIPELINE_TASK,
    _EMPTY_RESULT,
)

logger = logging.getLogger(__name__)


class _ScenarioPlan(BaseModel):
    """Structured output from the scenario planner."""
    scenarios: list[str] = Field(description="Distinct, specific scenario briefs — one per document")


def plan_scenarios(
    count: int, brief: str, model: str = "sonnet", session=None,
    *, seed: int | None = None, verbose: bool = True,
) -> list[str]:
    """Turn one brief into ``count`` distinct, specific scenario strings.

    ``brief`` is the caller's raw brief. The determinism ``seed`` is folded in here
    rather than by the caller so the seed instruction reaches only the planner: the
    fallback below pads with ``brief``, and padding with a pre-seeded string wrote
    "[Deterministic seed: N...]" into every document's generation guidance.
    """
    system_prompt = (
        "You are a scenario planner for synthetic document generation. Given a "
        "high-level brief, produce exactly N distinct, specific scenario briefs — "
        "each describing one document to generate. Vary entities, industries, "
        "locations, time periods, amounts, and structure so the documents are "
        "diverse. Each scenario must be self-contained and concrete."
    )
    agent = Agent(model=make_model(model, session=session), system_prompt=system_prompt)
    result = agent(
        f"Brief: {_seeded_brief(brief, seed)}\n\nProduce exactly {count} distinct scenario briefs.",
        structured_output_model=_ScenarioPlan,
    )
    # `structured_output` is None on a guardrail/content-filter refusal. Treated as
    # zero scenarios so the padding below fills every slot with the raw brief: this
    # function is sugar for "vary one brief N ways", and falling back to N copies of
    # the brief still generates the N documents that were asked for. Unguarded,
    # `.scenarios` raised an AttributeError that named neither the step nor the cause.
    plan = result.structured_output
    scenarios = list(plan.scenarios) if plan is not None else []

    shortfall = count - len(scenarios)
    if shortfall > 0:
        # A warning, not just a print: the documents still generate and
        # `BatchResult` will report N/N succeeded, so this degradation is otherwise
        # invisible to a programmatic caller. `logs.configure_progress_logging`
        # attaches a stderr handler, and an embedding host can capture the record.
        cause = ("returned no structured output (likely a content-filter or "
                 "guardrail refusal)" if plan is None
                 else f"returned only {len(scenarios)} of {count} scenarios")
        logger.warning(
            "Scenario planning %s — padding %d document(s) with the unvaried brief; "
            "those documents will not be diverse", cause, shortfall,
        )
        if verbose:
            print(f"  Scenario planning {cause} — padding {shortfall} "
                  "document(s) with the unvaried brief")
        scenarios += [brief] * shortfall

    return scenarios[:count]


class _CoordinatorNode(MultiAgentBase):
    """Entry node the worker pipeline graphs fan out from."""
    def __init__(self, name: str = "coordinator"):
        super().__init__()
        self.name = name

    async def invoke_async(self, task, invocation_state=None, **kwargs):
        ar = AgentResult(stop_reason="end_turn",
                         message=Message(role="assistant", content=[ContentBlock(text=str(task))]),
                         metrics=None, state=None)
        return MultiAgentResult(status=Status.COMPLETED,
                                results={self.name: NodeResult(result=ar, status=Status.COMPLETED)})


def build_batch_graph(
    contexts: list,
    *,
    max_attempts: int = 5,
    timeout: int = 3600,
    augment: bool = False,
):
    """Fan out one self-contained pipeline graph per context, as sibling nodes.

        coordinator ─┬─→ worker_0 (pipeline graph)
                     ├─→ worker_1 (pipeline graph)   (Strands runs these
                     └─→ worker_N (pipeline graph)    concurrently, natively)

    Returns ``(graph, worker_names)`` where ``worker_names[i]`` is the node name
    for ``contexts[i]`` — used to pull each worker's result back out afterward.
    """
    builder = GraphBuilder()
    builder.add_node(_CoordinatorNode(), "coordinator")
    builder.set_entry_point("coordinator")

    worker_names = []
    for i, ctx in enumerate(contexts):
        name = f"worker_{i}"
        pipeline = build_pipeline_graph(
            ctx, max_attempts=max_attempts, timeout=timeout, augment=augment,
            # Same reasoning as `generate`: the 600s default node cap overrode
            # the caller's timeout for the whole per-document render loop.
            node_timeout=timeout,
        )
        builder.add_node(pipeline, name)
        builder.add_edge("coordinator", name)
        worker_names.append(name)

    builder.set_max_node_executions(len(contexts) + 2)
    builder.set_execution_timeout(timeout * max(len(contexts), 1) + 60)
    return builder.build(), worker_names


def generate_batch(
    *,
    resolved: tuple[dict, str, list] | None = None,
    schema_dir: str | None = None,
    count: int,
    brief: str,
    output_dir: str = "./output",
    models: ModelConfig | None = None,
    threshold: int = 7,
    max_attempts: int = 5,
    timeout: int = 3600,
    renderer: str = "xhtml2pdf",
    critic_samples: bool = True,
    augment: bool = False,
    verbose: bool = True,
    session=None,
    seed: int | None = None,
    on_document=None,
) -> list[GeneratedDoc]:
    """Plan ``count`` scenarios, then generate them via a concurrent graph fan-out.

    Provide either ``schema_dir`` or a pre-``resolved`` schema triple. Returns one
    ``GeneratedDoc`` per scenario, ordered to match the planned scenarios.

    Args:
        session: optional boto3 Session for in-process use (else env credentials).
        seed: optional seed for scenario planning, for regression-stable sets.
        on_document: optional ``callback(index, total, GeneratedDoc)`` invoked as
            each document's result is collected (for host-side progress UIs).
    """
    models = models or ModelConfig()

    if verbose:
        print(f"Planning {count} scenarios from brief: {brief}")
    # The raw brief, with `seed` passed alongside: `plan_scenarios` folds the seed
    # into the planner prompt only, keeping it out of the padding fallback.
    scenarios = plan_scenarios(
        count, brief, model=models.batch, session=session, seed=seed, verbose=verbose,
    )
    if verbose:
        for i, s in enumerate(scenarios):
            print(f"  [{i}] {s[:90]}")

    # One StageContext (own paths, own doc_id) per scenario.
    contexts = [
        build_context(
            schema_dir=schema_dir, resolved=resolved, output_dir=output_dir,
            extra=scenario, models=models, threshold=threshold,
            renderer=renderer, critic_samples=critic_samples, session=session,
        )
        for scenario in scenarios
    ]

    if verbose:
        print(f"Fanning out {len(contexts)} pipeline graphs concurrently...")
    graph, worker_names = build_batch_graph(
        contexts, max_attempts=max_attempts, timeout=timeout, augment=augment,
    )
    # Guarded: Strands' graph is fail-fast, so one worker raising cancels its
    # siblings and the exception propagates out of `generate_batch` — losing every
    # `GeneratedDoc`, including documents that had already rendered successfully.
    # main's per-document try/except did not have this exposure. Falling through to
    # the per-worker extraction below lets `result_from` report each context from the
    # filesystem, so finished work survives a sibling's failure.
    batch_error: str | None = None
    try:
        result = graph(PIPELINE_TASK.format(doctype=contexts[0].doctype if contexts else "document"))
    except Exception as e:
        logger.warning("Batch graph raised, recovering per-document results: %s", e)
        batch_error = str(e)
        result = _EMPTY_RESULT

    # Pull each worker's sub-result out of the outer result and extract it with
    # the same result_from() the single-document path uses.
    docs = []
    for i, (ctx, name) in enumerate(zip(contexts, worker_names)):
        node_result = result.results.get(name)
        sub = getattr(node_result, "result", None) if node_result else None
        if sub is not None and hasattr(sub, "results"):
            doc = result_from(ctx, sub, augment=augment)
        else:
            # Worker didn't run / no sub-result — fall back to inspecting its ctx.
            doc = result_from(ctx, _EMPTY_RESULT, augment=augment)
        # A document with nothing on disk after a batch-level failure should name that
        # failure. `result_from` has already set the generic "PDF was not created" by
        # this point, so append rather than only filling an empty field — the batch
        # error is the actual cause and the generic text is the symptom.
        if batch_error and not doc.success:
            detail = f"Batch run failed: {batch_error}"
            doc = doc.model_copy(update={
                "error": f"{doc.error} ({detail})" if doc.error else detail
            })
        docs.append(doc)
        if on_document is not None:
            on_document(i, len(contexts), doc)

    if verbose:
        ok = sum(1 for d in docs if d.success)
        print(f"\nBatch complete: {ok}/{len(docs)} succeeded")
    return docs


def _seeded_brief(brief: str, seed: int | None) -> str:
    """Fold a determinism seed into the planner brief.

    There is no global RNG to set — scenario diversity comes from the LLM — so a
    seed is expressed as an explicit instruction the planner can anchor on,
    yielding regression-stable-ish sets for the same (brief, seed, model).
    """
    if seed is None:
        return brief
    return f"{brief}\n\n[Deterministic seed: {seed}. Produce the same scenarios for this seed.]"

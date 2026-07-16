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
)


class _ScenarioPlan(BaseModel):
    """Structured output from the scenario planner."""
    scenarios: list[str] = Field(description="Distinct, specific scenario briefs — one per document")


def plan_scenarios(count: int, brief: str, model: str = "sonnet", session=None) -> list[str]:
    """Turn one brief into ``count`` distinct, specific scenario strings."""
    system_prompt = (
        "You are a scenario planner for synthetic document generation. Given a "
        "high-level brief, produce exactly N distinct, specific scenario briefs — "
        "each describing one document to generate. Vary entities, industries, "
        "locations, time periods, amounts, and structure so the documents are "
        "diverse. Each scenario must be self-contained and concrete."
    )
    agent = Agent(model=make_model(model, session=session), system_prompt=system_prompt)
    result = agent(
        f"Brief: {brief}\n\nProduce exactly {count} distinct scenario briefs.",
        structured_output_model=_ScenarioPlan,
    )
    scenarios = list(result.structured_output.scenarios)
    if len(scenarios) < count:  # defend against a short response
        scenarios += [brief] * (count - len(scenarios))
    return scenarios[:count]


class _CoordinatorNode(MultiAgentBase):
    """Entry node the worker pipeline graphs fan out from."""
    def __init__(self, name: str = "coordinator"):
        super().__init__(); self.name = name

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
    scenarios = plan_scenarios(count, _seeded_brief(brief, seed), model=models.batch, session=session)
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
    result = graph(PIPELINE_TASK.format(doctype=contexts[0].doctype if contexts else "document"))

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


class _EmptyResult:
    """Stand-in with no node results, for a worker that produced nothing."""
    results: dict = {}
    execution_order: list = []


_EMPTY_RESULT = _EmptyResult()

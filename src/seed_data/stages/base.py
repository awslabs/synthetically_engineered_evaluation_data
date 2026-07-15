"""Shared foundation for pipeline stages.

This module defines the typed objects and graph primitives that every stage
builds on:

- ``ModelConfig`` / ``StageContext`` — the configuration and per-document state
  every stage needs. A ``StageContext`` is **baked into each node at construction
  time**, so a pipeline graph is fully self-contained: it needs no external
  ``invocation_state`` and can be composed as a node inside a larger graph (e.g.
  N pipelines fanned out for a batch, running concurrently).
- ``Verdict`` — the structured result every critic returns, so edge conditions can
  read ``verdict.accepted`` instead of grepping free text.
- ``FunctionNode`` — a custom graph node that runs a deterministic Python function
  bound to a ``StageContext`` (the canonical Strands pattern for hybrid AI +
  business-logic workflows).
- ``verdict_of`` / edge-condition helpers — read a node's structured ``Verdict``
  out of the graph state.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from strands.multiagent.base import MultiAgentBase, NodeResult, Status, MultiAgentResult
from strands.agent.agent_result import AgentResult
from strands.types.content import ContentBlock, Message


class ModelConfig(BaseModel):
    """Which model each agent uses. Names resolve via ``seed_data.MODELS``."""
    data: str = "sonnet"
    doc: str = "sonnet"
    critic: str = "haiku"
    aug: str = "sonnet"
    batch: str = "sonnet"


class StageContext(BaseModel):
    """Everything a stage needs, shared across generator and critic.

    Carries the loaded schema/steering, the resolved output paths for this one
    document, and the run configuration. Baked into each stage node at build
    time, so the pipeline graph is self-contained and composable.
    """
    model_config = {"arbitrary_types_allowed": True}

    # --- inputs ---
    # Named schema_dict (not "schema") — pydantic's BaseModel reserves "schema".
    schema_dict: dict
    steering: str = ""
    sample_pdfs: list[str] = Field(default_factory=list)
    extra: str = ""

    # --- resolved paths for this document ---
    output_path: str      # final PDF
    data_json_path: str   # ground-truth JSON (also the data-gen target)
    script_path: str      # HTML or .py the doc generator writes

    # --- configuration ---
    models: ModelConfig = Field(default_factory=ModelConfig)
    threshold: int = 7
    renderer: str = "xhtml2pdf"
    critic_samples: bool = True
    output_dir: str = "./output"
    # Optional boto3 Session for in-process use (container/Lambda/AgentCore). If
    # None, models resolve credentials from the environment (AWS_PROFILE).
    session: object | None = None

    @property
    def doctype(self) -> str:
        return str(self.schema_dict.get("title", self.schema_dict.get("document_type", "document"))).lower()


class CritiqueIssue(BaseModel):
    """A single issue found during critique."""
    category: str = Field(description="e.g. layout, typography, content, math, completeness, schema")
    severity: str = Field(description="One of: critical, major, minor")
    description: str = Field(description="Specific constructive feedback")
    fix_hint: str = Field(default="", description="Actionable fix suggestion for the generator")


class Verdict(BaseModel):
    """Structured critic result. Replaces stringly-typed 'verdict:rejected' text.

    ``feedback`` holds the rich, human-readable critique the generator reads on a
    retry; ``accepted``/``score`` drive the graph's control flow.
    """
    accepted: bool
    score: int = Field(ge=0, le=10)
    summary: str = ""
    feedback: str = ""
    issues: list[CritiqueIssue] = Field(default_factory=list)

    def as_node_text(self) -> str:
        """Serialize for a graph node's output message.

        Includes an explicit ``verdict:accepted|rejected`` marker so both the
        structured path (``verdict_of``) and any text-based inspection agree.
        """
        marker = "verdict:accepted" if self.accepted else "verdict:rejected"
        return f"{marker}\n{self.model_dump_json()}"

    @classmethod
    def from_node_text(cls, text: str) -> "Verdict | None":
        """Parse a Verdict back out of a node's output text, if present."""
        # The JSON payload is emitted on its own by as_node_text; find it.
        start = text.find("{")
        if start == -1:
            return None
        try:
            return cls.model_validate_json(text[start:])
        except Exception:
            return None


class FunctionNode(MultiAgentBase):
    """Run a deterministic Python function as a graph node.

    The function is bound to its ``StageContext`` at construction and receives
    ``(task_text, ctx)`` when invoked, returning a string (the node's output).
    Binding ``ctx`` at build time (rather than reading shared ``invocation_state``)
    is what makes a pipeline graph self-contained and safe to fan out.
    """

    def __init__(self, func, name: str, ctx: "StageContext"):
        super().__init__()
        self.func = func
        self.name = name
        self.ctx = ctx

    async def invoke_async(self, task, invocation_state=None, **kwargs):
        task_text = task if isinstance(task, str) else str(task)
        result_text = self.func(task_text, self.ctx)
        agent_result = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=str(result_text))]),
            metrics=None,
            state=None,
        )
        return MultiAgentResult(
            status=Status.COMPLETED,
            results={self.name: NodeResult(result=agent_result, status=Status.COMPLETED)},
        )


# ---------------------------------------------------------------------------
# Edge conditions — read a node's structured Verdict from graph state
# ---------------------------------------------------------------------------
def verdict_of(state, node_name: str) -> Verdict | None:
    """Extract the Verdict a critic node emitted, or None if absent.

    Works for both the in-run ``GraphState`` (edge conditions) and the post-run
    ``GraphResult``. Uses ``NodeResult.get_agent_results()`` — the canonical
    Strands accessor — to reach the node's output text regardless of how deeply
    the result is nested.
    """
    node_result = state.results.get(node_name)
    if not node_result:
        return None
    for agent_result in node_result.get_agent_results():
        verdict = Verdict.from_node_text(str(agent_result))
        if verdict is not None:
            return verdict
    return None


def accepted(node_name: str):
    """Edge condition: traverse when ``node_name`` emitted an accepting Verdict."""
    def _cond(state):
        v = verdict_of(state, node_name)
        return bool(v and v.accepted)
    return _cond


def rejected(node_name: str):
    """Edge condition: traverse when ``node_name`` emitted a rejecting Verdict."""
    def _cond(state):
        v = verdict_of(state, node_name)
        return bool(v and not v.accepted)
    return _cond

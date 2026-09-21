"""Tests for seed_data.stages.data — the deterministic data-critic guard.

Only the LLM-free parts: the JSON-Schema validation gate and the pre-LLM
Verdict short-circuits (missing file, schema errors). The LLM judgment path
requires Bedrock and is exercised in integration/ad-hoc runs.
"""
import json
import os

from seed_data.stages.base import StageContext, ModelConfig
from seed_data.stages import data as data_stage


SCHEMA = {
    "type": "object",
    "title": "widget",
    "properties": {
        "name": {"type": "string"},
        "count": {"type": "integer"},
    },
    "required": ["name", "count"],
}


def _ctx(tmp_path, data_obj=None) -> StageContext:
    data_path = os.path.join(tmp_path, "doc.json")
    if data_obj is not None:
        with open(data_path, "w") as f:
            json.dump(data_obj, f)
    return StageContext(
        schema_dict=SCHEMA,
        output_path=os.path.join(tmp_path, "doc.pdf"),
        data_json_path=data_path,
        script_path=os.path.join(tmp_path, "doc.html"),
        models=ModelConfig(),
        threshold=5,
    )


def test_schema_errors_detects_missing_required(tmp_path):
    issues = data_stage._schema_errors(SCHEMA, {"name": "x"})  # missing 'count'
    assert issues and any("count" in i.description for i in issues)
    assert all(i.severity == "critical" and i.category == "schema" for i in issues)


def test_schema_errors_detects_wrong_type(tmp_path):
    issues = data_stage._schema_errors(SCHEMA, {"name": "x", "count": "not-an-int"})
    assert issues


def test_schema_errors_empty_when_valid():
    assert data_stage._schema_errors(SCHEMA, {"name": "x", "count": 3}) == []


def test_critique_rejects_when_file_missing(tmp_path):
    ctx = _ctx(str(tmp_path), data_obj=None)  # no file written
    v = data_stage.critique(ctx)
    assert v.accepted is False and v.score == 0
    assert "not" in v.feedback.lower()


def test_critique_rejects_on_schema_violation_without_llm(tmp_path):
    # Invalid data → the deterministic gate rejects BEFORE any LLM call.
    ctx = _ctx(str(tmp_path), data_obj={"name": "x"})  # missing 'count'
    v = data_stage.critique(ctx)
    assert v.accepted is False and v.score == 0
    assert v.issues and v.issues[0].category == "schema"


def test_build_critic_returns_named_function_node(tmp_path):
    node = data_stage.build_critic(_ctx(str(tmp_path)))
    assert node.name == data_stage.CRITIC_NAME


def test_critique_rejects_when_critic_returns_no_structured_output(tmp_path, monkeypatch):
    """A guardrail refusal on the critic is a rejecting Verdict, not an AttributeError.

    `structured_output` is None when the model refuses. Unguarded, `llm.score` raised
    `AttributeError: 'NoneType' object has no attribute 'score'` — a crash inside the
    critic node that named neither the step nor the cause.
    """
    class _Result:
        structured_output = None

    class _FakeAgent:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Result()

    monkeypatch.setattr(data_stage, "Agent", _FakeAgent)
    monkeypatch.setattr(data_stage, "make_model", lambda *a, **k: None)

    # Valid data, so the deterministic gates pass and the LLM path is reached.
    ctx = _ctx(str(tmp_path), data_obj={"name": "x", "count": 3})
    v = data_stage.critique(ctx)

    assert v.accepted is False and v.score == 0
    assert v.issues and v.issues[0].severity == "critical"
    # The feedback must say the data was not validated, not that it was found wanting.
    assert "guardrail" in v.feedback.lower() or "content-filter" in v.feedback.lower()


def test_critic_refusal_does_not_walk_the_retry_edge(tmp_path, monkeypatch):
    """A refusal must be terminal, not retryable.

    The data already passed the schema gates, so regenerating produces equally valid
    data for the same unwilling critic. Marked retryable, this walked the
    critic->generator edge and burned the node budget on ~7 pointless regenerations
    before the document failed anyway, never reaching the doc stage.
    """
    from seed_data.stages.base import accepted, rejected

    class _Result:
        structured_output = None

    class _FakeAgent:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Result()

    monkeypatch.setattr(data_stage, "Agent", _FakeAgent)
    monkeypatch.setattr(data_stage, "make_model", lambda *a, **k: None)

    v = data_stage.critique(_ctx(str(tmp_path), data_obj={"name": "x", "count": 3}))
    assert v.retryable is False

    # Neither edge fires, so the graph stops at the critic instead of looping.
    class _State:
        results = {data_stage.CRITIC_NAME: _NodeResult(v)}

    assert rejected(data_stage.CRITIC_NAME)(_State()) is False
    assert accepted(data_stage.CRITIC_NAME)(_State()) is False


def test_ordinary_rejection_still_retries(tmp_path):
    """The retryable default must keep the normal quality loop working."""
    from seed_data.stages.base import rejected

    # A schema violation: actionable feedback, so regenerating is the right response.
    v = data_stage.critique(_ctx(str(tmp_path), data_obj={"name": "x"}))
    assert v.accepted is False and v.retryable is True

    class _State:
        results = {data_stage.CRITIC_NAME: _NodeResult(v)}

    assert rejected(data_stage.CRITIC_NAME)(_State()) is True


class _NodeResult:
    """Minimal stand-in for Strands' NodeResult, as `verdict_of` consumes it."""
    def __init__(self, verdict):
        self._text = verdict.as_node_text()

    def get_agent_results(self):
        return [self._text]

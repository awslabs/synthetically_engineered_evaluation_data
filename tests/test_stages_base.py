"""Tests for seed_data.stages.base — the shared stage foundation.

LLM-free: exercises the pydantic models, Verdict serialization, StageContext
state plumbing, FunctionNode, and the verdict-based edge conditions.
"""
import pytest

from seed_data.stages.base import (
    ModelConfig, StageContext, Verdict, CritiqueIssue,
    FunctionNode, verdict_of, accepted, rejected,
)


def make_ctx(**overrides) -> StageContext:
    base = dict(
        schema_dict={"title": "invoice", "type": "object"},
        # Placeholder paths only — these tests never touch the filesystem, so any
        # non-empty strings work. Kept relative (not /tmp) to avoid a hardcoded
        # world-writable temp path (bandit B108).
        output_path="_fake/pdfs/doc.pdf",
        data_json_path="_fake/data/doc.json",
        script_path="_fake/scripts/doc.html",
    )
    base.update(overrides)
    return StageContext(**base)


# --- ModelConfig ------------------------------------------------------------

def test_model_config_defaults():
    m = ModelConfig()
    assert m.data and m.doc and m.critic and m.aug and m.batch


def test_model_config_partial_override():
    m = ModelConfig(doc="gpt-oss")
    assert m.doc == "gpt-oss"
    assert m.critic == ModelConfig().critic  # untouched fields keep defaults


# --- StageContext -----------------------------------------------------------

def test_doctype_from_title():
    assert make_ctx(schema_dict={"title": "W2 Form"}).doctype == "w2 form"


def test_doctype_falls_back_to_document_type_then_default():
    assert make_ctx(schema_dict={"document_type": "Lease"}).doctype == "lease"
    assert make_ctx(schema_dict={}).doctype == "document"




# --- Verdict serialization --------------------------------------------------

@pytest.mark.parametrize("accepted_flag", [True, False])
def test_verdict_node_text_roundtrip(accepted_flag):
    v = Verdict(
        accepted=accepted_flag, score=7, summary="s", feedback="f",
        issues=[CritiqueIssue(category="math", severity="major", description="d")],
    )
    text = v.as_node_text()
    marker = "verdict:accepted" if accepted_flag else "verdict:rejected"
    assert text.splitlines()[0] == marker
    back = Verdict.from_node_text(text)
    assert back.accepted == accepted_flag
    assert back.score == 7
    assert len(back.issues) == 1
    assert back.issues[0].category == "math"


def test_verdict_from_node_text_garbage_returns_none():
    assert Verdict.from_node_text("no json here") is None


def test_verdict_score_bounds():
    with pytest.raises(Exception):
        Verdict(accepted=True, score=11)
    with pytest.raises(Exception):
        Verdict(accepted=True, score=-1)


# --- Edge conditions via a fake graph state ---------------------------------

class _FakeAgentResult:
    def __init__(self, text): self._text = text
    def __str__(self): return self._text


class _FakeNodeResult:
    def __init__(self, text): self._text = text
    def get_agent_results(self): return [_FakeAgentResult(self._text)]
    def __str__(self): return self._text


class _FakeState:
    def __init__(self, mapping): self.results = mapping


def _state_with(node, verdict: Verdict):
    return _FakeState({node: _FakeNodeResult(verdict.as_node_text())})


def test_verdict_of_reads_structured_result():
    v = Verdict(accepted=True, score=9)
    got = verdict_of(_state_with("data_critic", v), "data_critic")
    assert got is not None and got.accepted and got.score == 9


def test_verdict_of_missing_node_returns_none():
    assert verdict_of(_FakeState({}), "nope") is None


def test_accepted_and_rejected_conditions():
    acc_state = _state_with("c", Verdict(accepted=True, score=8))
    rej_state = _state_with("c", Verdict(accepted=False, score=2))
    assert accepted("c")(acc_state) is True
    assert accepted("c")(rej_state) is False
    assert rejected("c")(rej_state) is True
    assert rejected("c")(acc_state) is False


def test_conditions_are_false_when_node_absent():
    empty = _FakeState({})
    assert accepted("c")(empty) is False
    assert rejected("c")(empty) is False


# --- FunctionNode -----------------------------------------------------------

def test_function_node_invokes_with_bound_context():
    import asyncio
    seen = {}

    def fn(task_text, ctx):
        seen["task"] = task_text
        seen["doctype"] = ctx.doctype
        return "RESULT"

    ctx = make_ctx()
    node = FunctionNode(func=fn, name="probe", ctx=ctx)   # ctx bound at construction
    result = asyncio.run(node.invoke_async("hello"))
    assert seen["task"] == "hello"
    assert seen["doctype"] == "invoice"
    # output text is reachable via the canonical accessor
    texts = [str(ar) for nr in result.results.values() for ar in nr.get_agent_results()]
    assert "RESULT" in texts[0]

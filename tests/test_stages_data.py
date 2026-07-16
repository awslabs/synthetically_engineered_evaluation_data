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

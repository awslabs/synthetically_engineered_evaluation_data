"""Cross-modality evaluation tests (Milestone 4 §4.2).

Two new capabilities, each borrowed from the *other* modality:
- ``critique_structured`` — doc-gen's LLM critique pointed at tabular data
  (mocked here; the real thing calls Bedrock).
- ``evaluate_document_labels`` — tabular-style quantitative scoring pointed at
  document ground-truth JSON (pure Python, exercised for real).

Also guards the dependency contract: the document-side helpers must import and
run in the lean base install, i.e. without the ``[structured]`` extra (pandas).
"""
import builtins
import json
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from seed_data.evaluation import (
    DocumentLabelReport,
    critique_structured,
    evaluate_document_labels,
)
from seed_data.evaluation.critique import StructuredCritiqueResult, StructuredIssue
from seed_data.schema.models import (
    Cardinality,
    EntitySchema,
    FieldDefinition,
    InferredSchema,
    RelationshipDefinition,
)


def _schema():
    return InferredSchema(entities=[
        EntitySchema(entity_name="Order", fields=[
            FieldDefinition(name="order_id", type="string"),
            FieldDefinition(name="total", type="number"),
            FieldDefinition(name="status", type="enum", enum_values=["open", "closed"]),
            FieldDefinition(name="notes", type="string", nullable=True),
        ]),
    ])


# --- critique_structured (mocked LLM) ---------------------------------------

def _mock_agent(result_model):
    """Build a fake Strands Agent whose call returns ``result_model``."""
    agent = MagicMock()
    agent.return_value = MagicMock(structured_output=result_model)
    return agent


def test_critique_structured_mock():
    critique = StructuredCritiqueResult(
        score=8,
        issues=[StructuredIssue(entity="Order", field="total", category="consistency",
                                severity="minor", description="rounding looks synthetic")],
        summary="mostly consistent",
    )
    with patch("strands.Agent", return_value=_mock_agent(critique)), \
         patch("seed_data.utils.make_model", return_value=object()):
        result = critique_structured(
            {"Order": [{"order_id": "A1", "total": 10.0, "status": "open"}]},
            _schema(),
        )

    assert result["score"] == 8
    assert result["verdict"] == "accepted"       # 8 >= default threshold 7
    assert result["summary"] == "mostly consistent"
    assert result["issues"][0]["field"] == "total"


def test_critique_structured_rejects_below_threshold():
    critique = StructuredCritiqueResult(score=4, issues=[], summary="inconsistent dates")
    with patch("strands.Agent", return_value=_mock_agent(critique)), \
         patch("seed_data.utils.make_model", return_value=object()):
        result = critique_structured({"Order": [{"order_id": "A1"}]}, _schema(), threshold=7)
    assert result["verdict"] == "rejected"


def test_critique_structured_refusal_yields_error_verdict():
    """Regression: a guardrail refusal returns structured_output=None, and the
    `critique.score` comparison sat outside the try — so an AttributeError escaped
    and broke this function's documented contract that an unreachable or unwilling
    reviewer yields verdict="error" rather than crashing a finished run."""
    with patch("strands.Agent", return_value=_mock_agent(None)), \
         patch("seed_data.utils.make_model", return_value=object()):
        result = critique_structured({"Order": [{"order_id": "A1"}]}, _schema())

    assert result["verdict"] == "error"
    assert result["score"] == 0
    assert "no structured output" in result["error"]


def test_critique_structured_accepts_json_path(tmp_path):
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({"Order": [{"order_id": "A1", "total": 5.0}]}))
    critique = StructuredCritiqueResult(score=9, issues=[], summary="clean")

    captured = {}

    def _agent_factory(*args, **kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _mock_agent(critique)

    with patch("strands.Agent", side_effect=_agent_factory), \
         patch("seed_data.utils.make_model", return_value=object()):
        result = critique_structured(str(data_file), _schema())

    assert result["score"] == 9
    # the record read from disk made it into the rendered prompt
    assert "A1" in captured["system_prompt"]


def test_critique_structured_includes_relationships_in_prompt():
    schema = InferredSchema(entities=[
        EntitySchema(entity_name="Order", fields=[FieldDefinition(name="customer_id", type="string")],
                     structured_relationships=[RelationshipDefinition(
                         source_entity="Order", source_field="customer_id",
                         target_entity="Customer", target_field="id",
                         cardinality=Cardinality.ONE_TO_MANY)]),
    ])
    critique = StructuredCritiqueResult(score=7, issues=[], summary="ok")
    captured = {}

    def _agent_factory(*args, **kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _mock_agent(critique)

    with patch("strands.Agent", side_effect=_agent_factory), \
         patch("seed_data.utils.make_model", return_value=object()):
        critique_structured({"Order": [{"customer_id": "C1"}]}, schema)

    assert "Order.customer_id -> Customer.id" in captured["system_prompt"]


def test_critique_structured_llm_error_is_advisory():
    """A transport/model failure must not crash a finished generation run."""
    def _boom(*args, **kwargs):
        raise RuntimeError("bedrock unreachable")

    with patch("strands.Agent", side_effect=_boom), \
         patch("seed_data.utils.make_model", return_value=object()):
        result = critique_structured({"Order": [{"order_id": "A1"}]}, _schema())

    assert result["verdict"] == "error"
    assert result["score"] == 0
    assert "bedrock unreachable" in result["error"]


def test_critique_structured_empty_schema_raises():
    with pytest.raises(ValueError, match="no entities"):
        critique_structured({}, InferredSchema(entities=[]))


def test_critique_structured_samples_large_datasets():
    """Only a head sample of each entity is sent to the model."""
    critique = StructuredCritiqueResult(score=7, issues=[], summary="ok")
    captured = {}

    def _agent_factory(*args, **kwargs):
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return _mock_agent(critique)

    big = {"Order": [{"order_id": f"A{i}", "total": float(i)} for i in range(500)]}
    with patch("strands.Agent", side_effect=_agent_factory), \
         patch("seed_data.utils.make_model", return_value=object()):
        critique_structured(big, _schema())

    # last row (A499) must NOT be in the prompt; the sample is truncated
    assert "A499" not in captured["system_prompt"]
    assert "sampled" in captured["system_prompt"].lower() or "of 500" in captured["system_prompt"]


# --- evaluate_document_labels (real, pure-Python) ---------------------------

def test_evaluate_document_labels_coverage():
    labels = [
        {"order_id": "A1", "total": 10.0, "status": "open", "notes": "rush"},
        {"order_id": "A2", "total": 20.0, "status": "closed", "notes": "n/a"},
    ]
    report = evaluate_document_labels(labels, _schema())
    assert isinstance(report, DocumentLabelReport)
    assert report.document_count == 2
    assert report.coverage_score == 1.0        # every field appears
    assert report.completeness_score == 1.0    # every required field populated
    assert report.overall_score == 1.0


def test_evaluate_document_labels_completeness_penalizes_missing_required():
    labels = [
        {"order_id": "A1"},                 # total + status missing (both required)
        {"order_id": "A2", "total": 5.0},   # status missing
    ]
    report = evaluate_document_labels(labels, _schema())
    # doc1: 1/3 required present; doc2: 2/3 -> mean 0.5
    assert report.completeness_score == pytest.approx(0.5)
    assert report.overall_score < 1.0


def test_evaluate_document_labels_flags_never_populated_fields():
    labels = [{"order_id": "A1", "total": 1.0, "status": "open"}] * 3   # notes never set
    report = evaluate_document_labels(labels, _schema())
    assert report.per_field_presence["notes"] == 0.0
    assert any("notes" in issue for issue in report.issues)


def test_evaluate_document_labels_single_dict():
    report = evaluate_document_labels(
        {"order_id": "A1", "total": 1.0, "status": "open", "notes": "x"}, _schema()
    )
    assert report.document_count == 1
    assert report.coverage_score == 1.0


def test_evaluate_document_labels_nested_fields():
    schema = InferredSchema(entities=[
        EntitySchema(entity_name="Invoice", fields=[
            FieldDefinition(name="id", type="string"),
            FieldDefinition(name="customer", type="object", children=[
                FieldDefinition(name="name", type="string"),
                FieldDefinition(name="city", type="string"),
            ]),
        ]),
    ])
    labels = [
        {"id": "I1", "customer": {"name": "Acme", "city": "Denver"}},
        {"id": "I2", "customer": {"name": "Globex"}},   # city missing
    ]
    report = evaluate_document_labels(labels, schema)
    assert report.field_count == 3                      # id, customer.name, customer.city
    assert report.per_field_presence["customer.name"] == 1.0
    assert report.per_field_presence["customer.city"] == 0.5


def test_evaluate_document_labels_empty_input():
    report = evaluate_document_labels([], _schema())
    assert report.document_count == 0
    assert report.overall_score == 0.0
    assert any("No document labels" in issue for issue in report.issues)


def test_evaluate_document_labels_multi_entity_select():
    schema = InferredSchema(entities=[
        EntitySchema(entity_name="Customer", fields=[FieldDefinition(name="cid", type="string")]),
        EntitySchema(entity_name="Order", fields=[FieldDefinition(name="oid", type="string")]),
    ])
    report = evaluate_document_labels([{"oid": "O1"}], schema, entity_name="Order")
    assert report.per_field_presence == {"oid": 1.0}


def test_evaluate_document_labels_unknown_entity_raises():
    with pytest.raises(KeyError, match="Nope"):
        evaluate_document_labels([{}], _schema(), entity_name="Nope")


def test_evaluate_document_labels_treats_empty_string_as_absent():
    labels = [{"order_id": "", "total": 1.0, "status": "open", "notes": "x"}]
    report = evaluate_document_labels(labels, _schema())
    assert report.per_field_presence["order_id"] == 0.0


# --- dependency contract: base install (no pandas) --------------------------

def test_document_evaluation_works_without_structured_extra():
    """`evaluate_document_labels` is a document-side feature: it must import and
    run in the lean base install, i.e. without the `[structured]` extra
    (pandas/numpy/scipy).

    Run in a subprocess so blocking pandas can't pollute this interpreter's
    already-imported modules (reloading `metrics` in-process would swap out the
    `EvaluationReport` class other modules hold a reference to)."""
    import subprocess
    import sys

    program = textwrap.dedent(
        """
        import builtins
        real_import = builtins.__import__
        blocked = {"pandas", "numpy", "scipy", "openpyxl"}
        def guard(name, *a, **k):
            if name.split(".")[0] in blocked:
                raise ImportError("simulated missing dep: " + name)
            return real_import(name, *a, **k)
        builtins.__import__ = guard

        # Importing the package and the document-side helpers must not need pandas.
        from seed_data.evaluation import evaluate_document_labels, DocumentLabelReport
        from seed_data.schema.models import InferredSchema, EntitySchema, FieldDefinition
        schema = InferredSchema(entities=[EntitySchema(entity_name="Order", fields=[
            FieldDefinition(name="order_id", type="string"),
            FieldDefinition(name="total", type="number"),
            FieldDefinition(name="status", type="enum", enum_values=["open", "closed"]),
        ])])
        report = evaluate_document_labels(
            [{"order_id": "A1", "total": 1.0, "status": "open"}], schema)
        assert report.completeness_score == 1.0
        print("OK")
        """
    )
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout


def test_run_evaluation_import_error_is_clear_without_pandas():
    """Touching the tabular scorer without pandas raises ImportError, not at import time."""
    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0] == "pandas":
            raise ImportError("simulated: no pandas")
        return real_import(name, *args, **kwargs)

    from seed_data.evaluation import run_evaluation

    with patch.object(builtins, "__import__", side_effect=guard):
        with pytest.raises(ImportError):
            run_evaluation({}, _schema())

"""Evaluation metric tests — diversity, fidelity, coverage, structural, and the
`run_evaluation` aggregator. Pure Python/pandas/numpy; no Bedrock needed.
"""
import pytest

pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")
pytest.importorskip("numpy", reason="requires the [structured] optional dependencies")

import pandas as pd  # noqa: E402

from seed_data.evaluation.metrics import EvaluationReport, run_evaluation  # noqa: E402
from seed_data.schema.models import (  # noqa: E402
    EntitySchema,
    FieldDefinition,
    InferredSchema,
    RelationshipDefinition,
)
from seed_data.schema.models import Cardinality  # noqa: E402


def _customer_schema() -> InferredSchema:
    return InferredSchema(entities=[
        EntitySchema(
            entity_name="Customer",
            fields=[
                FieldDefinition(name="id", type="integer", unique=True),
                FieldDefinition(name="age", type="integer", min_value=18, max_value=90),
                FieldDefinition(name="status", type="enum",
                                enum_values=["active", "inactive", "pending"]),
            ],
        )
    ])


def _customer_data(n: int = 20) -> dict[str, list[dict]]:
    statuses = ["active", "inactive", "pending"]
    return {"Customer": [
        {"id": i, "age": 18 + (i % 60), "status": statuses[i % 3]}
        for i in range(n)
    ]}


# --- run_evaluation aggregate ----------------------------------------------

def test_run_evaluation_returns_report():
    report = run_evaluation(_customer_data(), _customer_schema())
    assert isinstance(report, EvaluationReport)
    assert "Customer" in report.entity_reports
    assert report.entity_reports["Customer"].record_count == 20
    # scores are all in [0, 1]
    for score in (report.overall_diversity_score, report.overall_fidelity_score,
                  report.overall_coverage_score, report.overall_structural_score,
                  report.overall_quality_score):
        assert 0.0 <= score <= 1.0


def test_run_evaluation_empty_entity_flagged():
    report = run_evaluation({"Customer": []}, _customer_schema())
    assert any("no records" in issue.lower() for issue in report.issues)
    assert report.entity_reports["Customer"].record_count == 0


def test_run_evaluation_quality_gate():
    # A trivially uniform dataset should still produce a boolean gate decision.
    report = run_evaluation(_customer_data(), _customer_schema(), quality_threshold=0.99)
    assert isinstance(report.passes_quality_gate, bool)
    # threshold of 0.99 is very unlikely to pass on synthetic uniform data
    assert report.passes_quality_gate == (report.overall_quality_score >= 0.99)


def test_run_evaluation_missing_entity_key():
    # Schema has an entity that the data dict doesn't provide.
    report = run_evaluation({}, _customer_schema())
    assert report.entity_reports["Customer"].record_count == 0
    assert any("no records" in i.lower() for i in report.issues)


# --- referential integrity (structural) ------------------------------------

def _order_schema() -> InferredSchema:
    return InferredSchema(entities=[
        EntitySchema(
            entity_name="Customer",
            fields=[FieldDefinition(name="id", type="integer", unique=True)],
        ),
        EntitySchema(
            entity_name="Order",
            fields=[
                FieldDefinition(name="id", type="integer", unique=True),
                FieldDefinition(name="customer_id", type="integer"),
            ],
            structured_relationships=[
                RelationshipDefinition(
                    source_entity="Order", source_field="customer_id",
                    target_entity="Customer", target_field="id",
                    cardinality=Cardinality.ONE_TO_MANY,
                )
            ],
        ),
    ])


def test_run_evaluation_detects_broken_fk():
    data = {
        "Customer": [{"id": 1}, {"id": 2}],
        # customer_id 99 has no matching parent → broken referential integrity
        "Order": [{"id": 10, "customer_id": 1}, {"id": 11, "customer_id": 99}],
    }
    report = run_evaluation(data, _order_schema())
    assert report.structural.get("referential_integrity", 1.0) < 1.0
    assert any("referential integrity" in i.lower() for i in report.issues)


def test_run_evaluation_intact_fk():
    data = {
        "Customer": [{"id": 1}, {"id": 2}],
        "Order": [{"id": 10, "customer_id": 1}, {"id": 11, "customer_id": 2}],
    }
    report = run_evaluation(data, _order_schema())
    assert report.structural.get("referential_integrity", 0.0) == 1.0


# --- individual metric scorers ---------------------------------------------

def test_diversity_metric_more_diverse_scores_higher():
    from seed_data.evaluation.diversity import DiversityMetrics

    schema = _customer_schema().entities[0]
    scorer = DiversityMetrics()

    diverse = pd.DataFrame(_customer_data(30)["Customer"])
    uniform = pd.DataFrame([
        {"id": i, "age": 30, "status": "active"} for i in range(30)
    ])

    diverse_score = scorer.overall_diversity_score(diverse, schema)["overall_score"]
    uniform_score = scorer.overall_diversity_score(uniform, schema)["overall_score"]
    assert diverse_score >= uniform_score

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


# --- review round 4: the quality gate could not detect its own failures --------

def test_dangling_fks_do_not_score_perfect_referential_integrity():
    """100% dangling FKs scored 1.0 and passed the gate.

    `referential_integrity_score` skipped any relationship whose parent frame was
    empty or lacked the key column, then returned 1.0 because `total_refs == 0` —
    reporting perfect integrity for the worst possible result.
    """
    from seed_data.evaluation.metrics import run_evaluation
    from seed_data.schema.models import InferredSchema

    schema = InferredSchema.model_validate({"entities": [{
        "entity_name": "Order", "description": "o",
        "fields": [{"name": "id", "type": "integer"},
                   {"name": "customer_id", "type": "integer"}],
        "structured_relationships": [{
            "source_entity": "Order", "source_field": "customer_id",
            "target_entity": "Customer", "target_field": "id",
            "cardinality": "one_to_many"}]}]})

    # No Customer rows at all: every customer_id points at nothing.
    report = run_evaluation({"Order": [{"id": 1, "customer_id": 99},
                                       {"id": 2, "customer_id": 98}]}, schema)

    assert report.structural["referential_integrity"] == 0.0
    assert any("referential integrity" in i.lower() for i in report.issues)


def test_no_fk_values_is_still_vacuously_perfect():
    """The 1.0 for "nothing referenced" must survive — it is a different case."""
    from seed_data.evaluation.metrics import run_evaluation
    from seed_data.schema.models import InferredSchema

    schema = InferredSchema.model_validate({"entities": [{
        "entity_name": "Order", "description": "o",
        "fields": [{"name": "id", "type": "integer"},
                   {"name": "customer_id", "type": "integer"}],
        "structured_relationships": [{
            "source_entity": "Order", "source_field": "customer_id",
            "target_entity": "Customer", "target_field": "id",
            "cardinality": "one_to_many"}]}]})

    # Rows exist but every FK is null — nothing is referenced, so nothing is dangling.
    report = run_evaluation({"Order": [{"id": 1, "customer_id": None}]}, schema)
    assert report.structural["referential_integrity"] == 1.0


def test_entropy_penalizes_unused_enum_values():
    """Mode collapse was undetectable: entropy normalized by *observed* cardinality."""
    import pandas as pd
    from seed_data.evaluation.diversity import DiversityMetrics

    metrics = DiversityMetrics()
    two_of_three = pd.Series(["active"] * 500 + ["inactive"] * 500)

    # 2 of 3 allowed values, perfectly balanced: previously exactly 1.0.
    assert metrics.per_column_entropy(two_of_three, n_possible=3) < 0.95
    # All three used: still maximal.
    all_three = pd.Series(["a"] * 333 + ["b"] * 333 + ["c"] * 334)
    assert metrics.per_column_entropy(all_three, n_possible=3) == pytest.approx(1.0, abs=1e-3)
    # No declared domain: observed count is the only denominator available.
    assert metrics.per_column_entropy(two_of_three) == pytest.approx(1.0, abs=1e-3)


def test_nested_values_do_not_drop_every_metric():
    """A list/dict cell raised, and the blanket except dropped 3 of 4 metric families.

    `InferredSchema` supports nested object/array fields, so this is valid data;
    it scored 0.25 overall and failed the gate.
    """
    from seed_data.evaluation.metrics import run_evaluation
    from seed_data.schema.models import InferredSchema

    schema = InferredSchema.model_validate({"entities": [{
        "entity_name": "Invoice", "description": "i", "fields": [
            {"name": "id", "type": "integer"},
            {"name": "line_items", "type": "array"},
            {"name": "status", "type": "enum", "enum_values": ["open", "paid", "void"]}]}]})

    report = run_evaluation({"Invoice": [
        {"id": 1, "line_items": [{"sku": "a"}, {"sku": "b"}], "status": "open"},
        {"id": 2, "line_items": [{"sku": "c"}], "status": "paid"},
        {"id": 3, "line_items": [{"sku": "d"}], "status": "void"},
    ]}, schema)

    assert report.issues == [], f"nested data must evaluate cleanly, got {report.issues}"
    assert report.overall_quality_score > 0.5
    assert report.passes_quality_gate is True


# --- review round 5: more "the gate cannot see its own failures" ---------------

def test_data_sharing_no_columns_with_the_schema_fails_the_gate():
    """Every "nothing examined" path returned a perfect score.

    Data whose columns don't overlap the schema at all scored fidelity 1.0,
    coverage 1.0 and type_conformance 1.0, passing the gate with no issue recorded.
    """
    from seed_data.evaluation.metrics import run_evaluation
    from seed_data.schema.models import InferredSchema

    schema = InferredSchema.model_validate({"entities": [{
        "entity_name": "Customer", "description": "c", "fields": [
            {"name": "id", "type": "integer"},
            {"name": "email", "type": "email"},
            {"name": "age", "type": "integer"}]}]})

    report = run_evaluation({"Customer": [{"foo": 1, "bar": "x"}, {"foo": 2, "bar": "y"}]}, schema)
    assert report.passes_quality_gate is False
    assert report.overall_quality_score < 0.5


def test_non_numeric_cell_does_not_blind_the_distribution_check():
    """`astype(float)` raised, and the blanket except dropped fidelity + coverage."""
    from seed_data.evaluation.metrics import run_evaluation
    from seed_data.schema.models import InferredSchema

    schema = InferredSchema.model_validate({"entities": [{
        "entity_name": "T", "description": "t", "fields": [
            {"name": "amount", "type": "float",
             "distribution": {"type": "normal", "params": {"mean": 10, "std": 2}}}]}]})

    report = run_evaluation({"T": [{"amount": 10.0}, {"amount": 9.0}, {"amount": ""}]}, schema)
    assert report.issues == [], f"should not error out, got {report.issues}"
    assert report.overall_fidelity_score > 0.0


def test_degenerate_distribution_scores_an_exact_match_as_perfect():
    """`std == 0` pinned the theoretical CDF at 0.5, so exact data scored KS 0.5."""
    from seed_data.evaluation.fidelity import FidelityMetrics

    metrics = FidelityMetrics()
    assert metrics.distribution_distance_ks(pd.Series([5, 5, 5, 5]), 5.0, 0.0) == 0.0
    assert metrics.distribution_distance_ks(pd.Series([5, 5, 9, 9]), 5.0, 0.0) == 0.5
    assert metrics.distribution_distance_ks(pd.Series([1, 2, 3, 4]), 5.0, 0.0) == 1.0


def test_missing_weights_do_not_penalize_the_data():
    """Empty `weights` passed the isinstance check, so JSD returned its 1.0 sentinel.

    That scored perfectly balanced data worst-possible for a *schema* omission.
    """
    from seed_data.evaluation.fidelity import FidelityMetrics
    from seed_data.schema.models import EntitySchema

    schema = EntitySchema.model_validate({
        "entity_name": "T", "description": "t", "fields": [
            {"name": "status", "type": "enum", "enum_values": ["a", "b"],
             "distribution": {"type": "categorical_weighted", "params": {}}}]})
    data = pd.DataFrame([{"status": "a"}, {"status": "b"}, {"status": "a"}, {"status": "b"}])

    result = FidelityMetrics().overall_fidelity_score(data, schema)
    assert "status" not in result["distribution_distances"], "an empty spec must be skipped"
    assert result["overall_score"] == pytest.approx(1.0)


def test_integer_conformance_rejects_floats_and_bools():
    """`int(value)` truncates and accepts bools, blinding the metric."""
    from seed_data.evaluation.structural import StructuralMetrics

    metrics = StructuralMetrics()
    assert metrics._conforms_to_type(4, "integer") is True
    assert metrics._conforms_to_type(4.0, "integer") is True      # integral float is fine
    assert metrics._conforms_to_type(3.7, "integer") is False
    assert metrics._conforms_to_type(True, "integer") is False

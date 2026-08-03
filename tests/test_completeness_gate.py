"""Completeness (row-count) quality-gate tests.

The quality gate used to score only the *shape* of whatever data came back —
diversity, fidelity, coverage, structural integrity — and never the amount. A run
that delivered a quarter of the requested rows reported "Quality PASSED", because
the few rows it did produce were perfectly diverse and faithful. These tests pin
the row-count dimension that closes that hole.
"""
import pytest

from seed_data.common.config import QUALITY_THRESHOLDS, completeness_score


# --- the score itself -------------------------------------------------------

def test_completeness_score_is_a_ratio():
    assert completeness_score(20, 20) == 1.0
    assert completeness_score(10, 20) == 0.5
    assert completeness_score(0, 20) == 0.0


def test_completeness_score_clamps_overshoot():
    """Overshooting must not exceed 1.0.

    `loop.py` averages the dimensions to rank attempts; an unclamped 2.0 would let
    a run that returned double the rows outvote genuinely bad diversity.
    """
    assert completeness_score(40, 20) == 1.0


@pytest.mark.parametrize("target", [0, -1])
def test_completeness_score_handles_non_positive_target(target):
    """A zero/negative target is complete, not empty.

    Scoring 0.0 would fail a gate that no amount of generation could satisfy,
    deadlocking the retry loop until max attempts.
    """
    assert completeness_score(0, target) == 1.0


# --- threshold registration -------------------------------------------------

def test_completeness_is_a_registered_quality_dimension():
    assert "completeness" in QUALITY_THRESHOLDS
    # Below 1.0 on purpose: the LLM routinely lands a few rows under target, and
    # demanding an exact count would burn every retry on a fine dataset.
    assert 0.0 < QUALITY_THRESHOLDS["completeness"] < 1.0


def test_every_threshold_dimension_is_computed_by_both_evaluators():
    """A new dimension in QUALITY_THRESHOLDS must be scored at every gate site.

    Both evaluators iterate the dict and read `scores.get(dim, 0.0)`, so a
    dimension added to the config but not computed reads as 0.0 and fails every
    attempt forever. This test is the tripwire for that.
    """
    pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")

    import inspect

    from seed_data.structured import loop, pipeline

    for module in (loop, pipeline):
        src = inspect.getsource(module)
        for dim in QUALITY_THRESHOLDS:
            assert f'"{dim}"' in src, (
                f"{module.__name__} never computes '{dim}', but the gate requires it"
            )


# --- the gate in the graph pipeline -----------------------------------------

def _two_entity_schema():
    from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema

    return InferredSchema(entities=[
        EntitySchema(entity_name="Customer",
                     fields=[FieldDefinition(name="id", type="integer", unique=True)]),
        EntitySchema(entity_name="Order",
                     fields=[FieldDefinition(name="id", type="integer", unique=True)]),
    ])


def test_gate_uses_worst_entity_not_the_mean():
    """One healthy entity must not mask a collapsed one.

    This dataset is chosen to separate the two aggregations: a full Customer table
    (20/20 → 1.0) beside a half-empty Order table (10/20 → 0.5) averages to exactly
    the 0.75 threshold, so a mean-based gate would pass it — while the worst entity
    scores 0.5 and fails. Averaging would let the half-empty entity ship.
    """
    schema = _two_entity_schema()
    data = {"Customer": [{}] * 20, "Order": [{}] * 10}
    target = 20

    worst = min(
        completeness_score(len(data.get(e.entity_name, [])), target)
        for e in schema.entities
    )
    mean = sum(
        completeness_score(len(data.get(e.entity_name, [])), target)
        for e in schema.entities
    ) / 2

    assert worst == 0.5
    assert mean == 0.75
    assert worst < QUALITY_THRESHOLDS["completeness"] <= mean, (
        "this dataset must fail on the worst entity and pass on the mean, "
        "which is exactly why the gate uses min()"
    )


def test_missing_entity_counts_as_zero_rows():
    """An entity absent from the payload is the most complete failure there is.

    Skipping absent entities (rather than scoring them 0) would let the pipeline
    pass by simply not emitting an entity at all.
    """
    schema = _two_entity_schema()
    data = {"Customer": [{}] * 20}  # Order missing entirely

    worst = min(
        completeness_score(len(data.get(e.entity_name, [])), 20)
        for e in schema.entities
    )
    assert worst == 0.0


def _run_evaluate(schema, tmp_path, target_count, data):
    """Drive the graph's evaluate node with a fixed payload, and return its state.

    ``build_graph_pipeline`` closes over its node functions, so the node is reached
    through the built graph: seed ``PipelineState`` with what the generation step
    would have produced, then call the evaluate node directly. No Bedrock, no
    graph traversal.
    """
    import json

    from seed_data.structured import pipeline as pl

    graph, _ctx, ps = pl.build_graph_pipeline(
        schema, output_dir=str(tmp_path), export_format="csv",
        target_count=target_count,
    )
    ps.gen_result_json = json.dumps({"data": data})
    graph.nodes["evaluate"].executor.func("")
    return ps


@pytest.fixture
def perfect_shape_scores(monkeypatch):
    """Stub every non-completeness dimension to a perfect 1.0.

    Isolates the new gate: with diversity/fidelity/coverage/structural all passing,
    row count is the only thing that can fail — which is exactly the bug, since
    perfect shape scores on a quarter of the rows used to report "Quality PASSED".
    """
    pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")

    class _PerfectReport:
        overall_diversity_score = 1.0
        overall_fidelity_score = 1.0
        overall_coverage_score = 1.0
        overall_structural_score = 1.0
        issues: list[str] = []

    monkeypatch.setattr(
        "seed_data.evaluation.metrics.run_evaluation",
        lambda data, sch: _PerfectReport(),
    )
    # Post-processing would filter these synthetic rows on unrelated grounds; pass
    # them through so the assertion is about the gate, not about validation.
    monkeypatch.setattr(
        "seed_data.structured.postprocessing.pipeline.PostProcessingPipeline.run",
        lambda self, data: type("_Result", (), {"data": data})(),
    )


def test_evaluate_step_fails_a_short_run(perfect_shape_scores, tmp_path):
    """Regression: 5 of 20 requested rows must FAIL where it used to PASS."""
    short = {"Customer": [{"id": i} for i in range(5)],
             "Order": [{"id": i} for i in range(5)]}
    ps = _run_evaluate(_two_entity_schema(), tmp_path, 20, short)

    assert ps.evaluation_scores["completeness"] == 0.25
    assert ps.quality_passed is False, (
        "a 5-of-20-row run with perfect shape scores must not pass the gate"
    )


def test_evaluate_step_passes_a_full_run(perfect_shape_scores, tmp_path):
    """The gate must not block healthy runs — the other half of the regression."""
    full = {"Customer": [{"id": i} for i in range(20)],
            "Order": [{"id": i} for i in range(20)]}
    ps = _run_evaluate(_two_entity_schema(), tmp_path, 20, full)

    assert ps.evaluation_scores["completeness"] == 1.0
    assert ps.quality_passed is True


def test_evaluate_step_tolerates_slight_undershoot(perfect_shape_scores, tmp_path):
    """A few rows under target must still pass.

    The threshold is deliberately below 1.0: the LLM routinely returns slightly
    fewer rows than asked, and failing that would spend every retry re-generating
    a dataset that was fine.
    """
    near = {"Customer": [{"id": i} for i in range(19)],
            "Order": [{"id": i} for i in range(18)]}
    ps = _run_evaluate(_two_entity_schema(), tmp_path, 20, near)

    assert ps.evaluation_scores["completeness"] == 0.9
    assert ps.quality_passed is True


def test_evaluate_step_flags_the_shortfall_in_scores(perfect_shape_scores, tmp_path):
    """The failing dimension must be visible to the caller, not just logged.

    `run_structured` surfaces `evaluation_scores` in its StructuredResult, so a
    user who got a short dataset can see which gate rejected it.
    """
    lopsided = {"Customer": [{"id": i} for i in range(20)], "Order": []}
    ps = _run_evaluate(_two_entity_schema(), tmp_path, 20, lopsided)

    assert ps.evaluation_scores["completeness"] == 0.0
    assert ps.quality_passed is False

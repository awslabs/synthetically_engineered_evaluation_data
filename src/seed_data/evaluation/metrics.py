"""Evaluation reports for both modalities.

``run_evaluation`` scores *structured* data and needs the ``[structured]`` extra
(pandas et al.); its heavy imports are deferred into the function so this module
stays importable in the lean base install. ``evaluate_document_labels`` scores
*document* ground-truth JSON with pure Python, so it runs without that extra.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema

logger = logging.getLogger(__name__)


class EntityEvaluationReport(BaseModel):
    entity_name: str
    record_count: int = 0
    diversity: dict = Field(default_factory=dict)
    fidelity: dict = Field(default_factory=dict)
    coverage: dict = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    entity_reports: dict[str, EntityEvaluationReport] = Field(default_factory=dict)
    structural: dict = Field(default_factory=dict)
    overall_diversity_score: float = 0.0
    overall_fidelity_score: float = 0.0
    overall_coverage_score: float = 0.0
    overall_structural_score: float = 0.0
    overall_quality_score: float = 0.0
    passes_quality_gate: bool = False
    issues: list[str] = Field(default_factory=list)


class DocumentLabelReport(BaseModel):
    """Quantitative scoring of document ground-truth JSON labels.

    Documents are generated one at a time with an LLM critique loop; there is no
    population to run tabular statistics over. What *can* be measured is how
    completely each generated label object fills the schema — the counterpart of
    tabular coverage for the document modality.
    """

    document_count: int = 0
    field_count: int = 0
    # Fraction of required (non-nullable) leaf fields that are present and
    # non-null, averaged over documents. 1.0 = every required field populated.
    completeness_score: float = 0.0
    # Fraction of *all* schema leaf fields that appear at least once across the
    # whole set — the document analogue of tabular coverage.
    coverage_score: float = 0.0
    overall_score: float = 0.0
    per_field_presence: dict[str, float] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


def _leaf_fields(fields: list[FieldDefinition], prefix: str = "") -> list[tuple[str, FieldDefinition]]:
    """Flatten a (possibly nested) field list into ``(dotted_path, field)`` leaves.

    Object fields recurse into their children; every other field — including
    arrays and scalars — is a leaf. The dotted path keys ``per_field_presence``.
    """
    leaves: list[tuple[str, FieldDefinition]] = []
    for field in fields:
        path = f"{prefix}{field.name}"
        if field.type == "object" and field.children:
            leaves.extend(_leaf_fields(field.children, prefix=f"{path}."))
        else:
            leaves.append((path, field))
    return leaves


def _lookup(record: dict, path: str):
    """Resolve a dotted path against a nested dict. Returns ``_MISSING`` if absent."""
    cur = record
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


_MISSING = object()


def evaluate_document_labels(
    labels: list[dict] | dict,
    schema: InferredSchema | EntitySchema,
    entity_name: str | None = None,
) -> DocumentLabelReport:
    """Score document ground-truth labels for completeness and coverage.

    This is the document-modality counterpart to :func:`run_evaluation`. It is
    pure Python (no pandas), so it works in the lean base install.

    Args:
        labels: One label dict, or a list of them — the ground-truth JSON emitted
            alongside each generated document.
        schema: The ``InferredSchema`` (or a single ``EntitySchema``) the
            documents were generated from.
        entity_name: Which entity to score against when ``schema`` is a
            multi-entity ``InferredSchema``. Defaults to the first entity.

    Returns:
        A :class:`DocumentLabelReport`.
    """
    if isinstance(labels, dict):
        labels = [labels]

    entity = _resolve_entity(schema, entity_name)
    leaves = _leaf_fields(entity.fields)
    report = DocumentLabelReport(document_count=len(labels), field_count=len(leaves))

    if not leaves:
        report.issues.append(f"Entity '{entity.entity_name}' declares no fields to score against.")
        return report
    if not labels:
        report.issues.append("No document labels provided.")
        return report

    required_leaves = [(p, f) for p, f in leaves if f.is_required]
    present_counts = {path: 0 for path, _ in leaves}
    completeness_per_doc = []

    for record in labels:
        if not isinstance(record, dict):
            report.issues.append(f"Skipped a non-object label (got {type(record).__name__}).")
            continue

        for path, _ in leaves:
            value = _lookup(record, path)
            if value is not _MISSING and value is not None and value != "":
                present_counts[path] += 1

        if required_leaves:
            got = sum(
                1 for path, _ in required_leaves
                if _lookup(record, path) not in (_MISSING, None, "")
            )
            completeness_per_doc.append(got / len(required_leaves))
        else:
            completeness_per_doc.append(1.0)

    n = len(labels)
    report.per_field_presence = {path: present_counts[path] / n for path in present_counts}
    report.completeness_score = (
        sum(completeness_per_doc) / len(completeness_per_doc) if completeness_per_doc else 0.0
    )
    report.coverage_score = (
        sum(1 for c in present_counts.values() if c > 0) / len(leaves) if leaves else 0.0
    )
    report.overall_score = 0.5 * report.completeness_score + 0.5 * report.coverage_score

    never_seen = [path for path, c in present_counts.items() if c == 0]
    if never_seen:
        preview = ", ".join(never_seen[:5])
        more = f" (+{len(never_seen) - 5} more)" if len(never_seen) > 5 else ""
        report.issues.append(f"Fields never populated in any document: {preview}{more}")

    return report


def _resolve_entity(
    schema: InferredSchema | EntitySchema, entity_name: str | None
) -> EntitySchema:
    if isinstance(schema, EntitySchema):
        return schema
    if not schema.entities:
        raise ValueError("InferredSchema has no entities to evaluate against.")
    if entity_name is None:
        return schema.entities[0]
    for entity in schema.entities:
        if entity.entity_name == entity_name:
            return entity
    available = ", ".join(e.entity_name for e in schema.entities)
    raise KeyError(f"No entity named {entity_name!r} in schema. Available: {available}")


def run_evaluation(
    data: dict[str, list[dict]],
    schema: InferredSchema,
    quality_threshold: float = 0.7,
) -> EvaluationReport:
    """Run all evaluation metrics on generated data and produce a report.

    Args:
        data: Map of entity name to list of record dicts.
        schema: The InferredSchema used for generation.
        quality_threshold: Minimum overall_quality_score to pass the gate.

    Returns:
        EvaluationReport with per-entity and aggregate scores.
    """
    # Deferred: these scorers pull in pandas/numpy/scipy from the `[structured]`
    # extra. Keeping the import here lets the base install load this module (for
    # `evaluate_document_labels` and the report models) without that stack.
    import pandas as pd

    from .coverage import CoverageMetrics
    from .diversity import DiversityMetrics
    from .fidelity import FidelityMetrics
    from .structural import StructuralMetrics

    diversity_scorer = DiversityMetrics()
    fidelity_scorer = FidelityMetrics()
    coverage_scorer = CoverageMetrics()
    structural_scorer = StructuralMetrics()

    all_dfs: dict[str, pd.DataFrame] = {}
    entity_reports: dict[str, EntityEvaluationReport] = {}
    issues: list[str] = []

    diversity_scores = []
    fidelity_scores = []
    coverage_scores = []

    for entity_schema in schema.entities:
        name = entity_schema.entity_name
        records = data.get(name, [])
        if not isinstance(records, list):
            issues.append(f"Entity '{name}' has invalid data (expected list, got {type(records).__name__})")
            records = []
        df = pd.DataFrame(records) if records else pd.DataFrame()
        all_dfs[name] = df

        report = EntityEvaluationReport(entity_name=name, record_count=len(records))

        if df.empty:
            issues.append(f"Entity '{name}' has no records")
            entity_reports[name] = report
            continue

        try:
            report.diversity = diversity_scorer.overall_diversity_score(df, entity_schema)
            report.fidelity = fidelity_scorer.overall_fidelity_score(df, entity_schema)
            report.coverage = coverage_scorer.overall_coverage_score(df, entity_schema)
        except Exception as e:
            logger.warning("Evaluation failed for entity '%s': %s", name, e)
            issues.append(f"Entity '{name}' evaluation error: {e}")
            entity_reports[name] = report
            continue

        diversity_scores.append(report.diversity.get("overall_score", 0.0))
        fidelity_scores.append(report.fidelity.get("overall_score", 0.0))
        coverage_scores.append(report.coverage.get("overall_score", 0.0))

        cvr = report.fidelity.get("constraint_violation_rate", 0.0)
        if cvr > 0.1:
            issues.append(f"Entity '{name}' has high constraint violation rate: {cvr:.1%}")

        entity_reports[name] = report

    structural_result = structural_scorer.overall_structural_score(all_dfs, schema)

    overall_diversity = sum(diversity_scores) / len(diversity_scores) if diversity_scores else 0.0
    overall_fidelity = sum(fidelity_scores) / len(fidelity_scores) if fidelity_scores else 0.0
    overall_coverage = sum(coverage_scores) / len(coverage_scores) if coverage_scores else 0.0
    overall_structural = structural_result.get("overall_score", 0.0)

    overall_quality = (
        0.25 * overall_diversity + 0.30 * overall_fidelity + 0.20 * overall_coverage + 0.25 * overall_structural
    )

    if structural_result.get("referential_integrity", 1.0) < 0.8:
        issues.append(
            f"Low referential integrity: {structural_result['referential_integrity']:.1%}"
        )

    return EvaluationReport(
        entity_reports=entity_reports,
        structural=structural_result,
        overall_diversity_score=overall_diversity,
        overall_fidelity_score=overall_fidelity,
        overall_coverage_score=overall_coverage,
        overall_structural_score=overall_structural,
        overall_quality_score=overall_quality,
        passes_quality_gate=overall_quality >= quality_threshold,
        issues=issues,
    )

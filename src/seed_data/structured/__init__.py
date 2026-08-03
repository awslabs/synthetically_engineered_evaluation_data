"""Structured-data generation engine.

Internal engine. The supported public surface is ``Generator.generate_structured``
(see :mod:`seed_data.api`); ``run_structured`` here is what that facade verb calls.

Requires the optional ``[structured]`` dependencies (pandas/numpy/scipy/openpyxl).
"""

import json
import logging

from seed_data.schema.models import InferredSchema

logger = logging.getLogger(__name__)


def run_structured(
    schema: InferredSchema,
    *,
    target_count: int = 100,
    export_format: str = "csv",
    output_dir: str = "./output",
    models=None,
    threshold: int = 7,
    session=None,
    verbose: bool = True,
):
    """Generate structured data for a resolved :class:`InferredSchema`.

    Runs the graph pipeline (distribution inference → sampling → bulk generation
    → evaluation with retry/schema-revision loops → export) and returns a typed
    ``StructuredResult``.

    Args:
        schema: the resolved schema to generate data for.
        target_count: target records per entity.
        export_format: one of ``json`` / ``csv`` / ``excel`` / ``parquet``.
        output_dir: directory to write output files to.
        models: optional ``ModelConfig`` (currently advisory; the pipeline agents
            build their own Bedrock models from ``common.config``).
        threshold: quality threshold carried from the Generator (advisory).
        session: optional boto3 Session.
        verbose: print progress.

    Returns:
        ``StructuredResult`` with output paths, per-entity row counts, and scores.
    """
    from seed_data.api import StructuredResult
    from seed_data.structured.pipeline import run_graph_pipeline

    try:
        _summary, ps = run_graph_pipeline(
            schema,
            output_dir=output_dir,
            export_format=export_format,
            target_count=target_count,
        )
    except Exception as e:  # noqa: BLE001 - surface failures as a typed result
        logger.exception("Structured generation failed")
        return StructuredResult(
            success=False,
            schema=schema,
            format=export_format,
            error=str(e),
        )

    output_paths: list[str] = []
    row_counts: dict[str, int] = {}
    if ps.export_json:
        try:
            export = json.loads(ps.export_json)
            output_paths = export.get("files", [])
            row_counts = export.get("record_counts", {})
        except (json.JSONDecodeError, TypeError):
            logger.warning("Could not parse export summary")

    # The pipeline can run to completion yet write nothing — e.g. every record
    # failed a non-null constraint and was filtered out. That is still a failure,
    # but without an explanatory `error` the CLI prints a bare "FAILED: None".
    # Surface whatever the pipeline knows about why.
    error = None
    if not output_paths:
        if ps.evaluation_issues:
            error = "No data exported. Evaluation issues: " + "; ".join(ps.evaluation_issues)
        else:
            error = (
                "No data exported — the pipeline produced no records "
                "(all records may have been filtered by validation)."
            )

    return StructuredResult(
        success=bool(output_paths),
        schema=schema,
        output_paths=output_paths,
        format=export_format,
        row_counts=row_counts,
        evaluation=ps.evaluation_scores,
        error=error,
    )


__all__ = ["run_structured"]

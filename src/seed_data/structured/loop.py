"""Metrics-driven generation loop.

Generates data, evaluates against quality thresholds, and retries failed
entities with feedback. Replaces the separate sample → bulk → post-processing
→ evaluation sequence with a single tool that loops until quality passes.
"""

import json
import logging

from strands import tool

from seed_data.evaluation.metrics import run_evaluation
from seed_data.common.config import (
    MAX_GENERATION_ATTEMPTS,
    QUALITY_THRESHOLDS,
    completeness_score,
)
from seed_data.schema.models import InferredSchema
from seed_data.structured.postprocessing.pipeline import PostProcessingConfig, PostProcessingPipeline

logger = logging.getLogger(__name__)


def _run_post_processing(data: dict[str, list[dict]], schema: InferredSchema) -> dict[str, list[dict]]:
    """Run post-processing (validate + correct + filter) on data."""
    config = PostProcessingConfig()
    pipeline = PostProcessingPipeline(schema, config)
    result = pipeline.run(data)
    # run() already applied corrections and filtering; return that data directly.
    # (Re-deriving from result.validation would silently no-op: it is the
    # post-correction re-validation, whose fixable_count is 0.)
    return result.data


def _evaluate_entity(
    entity_name: str, records: list[dict], schema: InferredSchema, target_count: int
) -> dict:
    """Run evaluation on a single entity and return scores.

    ``target_count`` is required for the completeness dimension: the other scores
    describe the records that exist, and only this one notices that too few were
    produced.
    """
    report = run_evaluation({entity_name: records}, schema)
    entity_report = report.entity_reports.get(entity_name)
    if not entity_report:
        return {"passed": False, "scores": {}, "issues": ["No evaluation data"]}

    scores = {
        "diversity": entity_report.diversity.get("overall_score", 0.0),
        "fidelity": entity_report.fidelity.get("overall_score", 0.0),
        "coverage": entity_report.coverage.get("overall_score", 0.0),
        "structural": report.overall_structural_score,
        "completeness": completeness_score(len(records), target_count),
    }

    failed_dimensions = []
    for dim, threshold in QUALITY_THRESHOLDS.items():
        if scores.get(dim, 0.0) < threshold:
            failed_dimensions.append(f"{dim}: {scores[dim]:.2f} < {threshold}")

    return {
        "passed": len(failed_dimensions) == 0,
        "scores": scores,
        "failed_dimensions": failed_dimensions,
        "issues": report.issues,
    }


@tool
def generation_loop(
    entity_schema_definitions: str,
    sample_records_json: str,
    target_count: str = "40",
    seed: int | None = None,
) -> str:
    """Generate data with metrics-driven retry loop.

    Generates bulk records, runs post-processing and evaluation, then retries
    entities that fail quality thresholds. Accepts the best attempt for each
    entity after max retries.

    Args:
        entity_schema_definitions: JSON string of the InferredSchema with distributions.
        sample_records_json: JSON string of sample records from sample generation.
        target_count: Target number of records per entity.
        seed: optional RNG seed making the programmatic columns reproducible. Each
            attempt offsets it, so a retry redraws instead of reproducing the
            values that just failed the gate.

    Returns:
        JSON with final data, evaluation scores, and attempt history.
    """
    logger.info("Generation loop started")

    try:
        target = int(target_count)
    except (ValueError, TypeError):
        target = 40

    schema_json = entity_schema_definitions
    try:
        schema = InferredSchema.model_validate_json(schema_json)
    except Exception as e:
        return json.dumps({"error": f"Schema parse error: {e}"})

    # Parse sample records
    try:
        samples = json.loads(sample_records_json)
        if "data" in samples and isinstance(samples["data"], dict):
            samples = samples["data"]
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Sample records parse error: {e}"})

    # Get the raw function underneath the @tool decorator
    from seed_data.structured.generation import bulk_generation_agent as _bulk_tool
    _bulk_generate = _bulk_tool._tool_func

    entity_names = [e.entity_name for e in schema.entities]
    attempt_history: dict[str, list[dict]] = {name: [] for name in entity_names}
    best_data: dict[str, list[dict]] = {}
    best_scores: dict[str, float] = {name: -1.0 for name in entity_names}

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        logger.info("Generation attempt %d/%d", attempt, MAX_GENERATION_ATTEMPTS)

        # Generate ALL entities together (preserves FK relationships)
        try:
            gen_result_json = _bulk_generate(
                entity_schema_definitions=schema_json,
                sample_records_json=json.dumps({"data": samples}),
                target_count=str(target),
                seed=None if seed is None else seed + attempt,
            )
            gen_data = json.loads(gen_result_json)
            if "data" in gen_data:
                gen_data = gen_data["data"]
        except Exception as e:
            logger.warning("Generation attempt %d failed: %s", attempt, e)
            for name in entity_names:
                attempt_history[name].append({"attempt": attempt, "error": str(e), "scores": {}})
            continue

        # Post-process all entities together
        corrected = _run_post_processing(gen_data, schema)

        # Evaluate per-entity and decide keep/retry
        all_passed = True
        for entity_name in entity_names:
            records = corrected.get(entity_name, [])
            if not records:
                attempt_history[entity_name].append({
                    "attempt": attempt, "error": "No records generated", "scores": {},
                })
                all_passed = False
                continue

            eval_result = _evaluate_entity(entity_name, records, schema, target)
            # `scores` now includes completeness, so this mean no longer prefers a
            # tiny immaculate batch over a full one: a 5-of-20-row attempt scoring
            # 1.0 on every shape metric lands below a 19-row attempt that scores
            # slightly worse on them. Previously row count was invisible here and
            # the short attempt won `best_data`.
            overall = sum(eval_result["scores"].values()) / max(len(eval_result["scores"]), 1)

            attempt_history[entity_name].append({
                "attempt": attempt,
                "record_count": len(records),
                "scores": eval_result["scores"],
                "passed": eval_result["passed"],
                "failed_dimensions": eval_result.get("failed_dimensions", []),
            })

            if overall > best_scores[entity_name]:
                best_scores[entity_name] = overall
                best_data[entity_name] = records

            if not eval_result["passed"]:
                all_passed = False

        if all_passed:
            logger.info("All entities passed quality gate on attempt %d", attempt)
            break

    # Accept best data for each entity
    accepted_data: dict[str, list[dict]] = {}
    for entity_name in entity_names:
        accepted_data[entity_name] = best_data.get(entity_name, [])
        logger.info(
            "Entity '%s' — accepted %d records (best score: %.3f)",
            entity_name, len(accepted_data[entity_name]), best_scores[entity_name],
        )

    # Final overall evaluation
    final_report = run_evaluation(accepted_data, schema)

    output = {
        "data": accepted_data,
        "schema_json": schema_json,
        "evaluation": {
            "overall_quality_score": final_report.overall_quality_score,
            "passes_quality_gate": final_report.passes_quality_gate,
            "diversity": final_report.overall_diversity_score,
            "fidelity": final_report.overall_fidelity_score,
            "coverage": final_report.overall_coverage_score,
            "structural": final_report.overall_structural_score,
            "issues": final_report.issues,
        },
        "attempt_history": attempt_history,
        "record_counts": {k: len(v) for k, v in accepted_data.items()},
    }

    logger.info(
        "Generation loop complete — quality: %.3f, passes: %s",
        final_report.overall_quality_score,
        final_report.passes_quality_gate,
    )

    return json.dumps(output, indent=2)

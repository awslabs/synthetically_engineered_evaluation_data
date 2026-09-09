"""Graph-based pipeline with conditional retry and schema revision.

Graph structure:
  schema_extraction → distribution_inference → sample_generation → bulk_generation → evaluate
                                                                         ↑                |
                                                                         └────────────────┘ quality failed (retry)
         ↑                                                                                |
         └──────── schema_revision ←──────────────────────────────────────────────────────┘ 3x fail → revise
                                                                                          |
                                                                                          └→ export (quality passed)

Key behaviors:
- Generation retry: evaluate fails → back to bulk_generation with feedback
- Schema revision: 3 generation failures → revise schema, re-run from distributions
- Export: quality passes → export final data
"""

import json
import logging

from strands.agent.agent_result import AgentResult
from strands.multiagent import GraphBuilder
from strands.multiagent.base import MultiAgentBase, MultiAgentResult, NodeResult, Status
from strands.types.content import ContentBlock, Message

from seed_data.common.config import (
    QUALITY_THRESHOLDS,
    completeness_score,
)
from seed_data.schema.models import InferredSchema

logger = logging.getLogger(__name__)

MAX_GENERATION_RETRIES = 3
MAX_SCHEMA_REVISIONS = 2

# Node-execution budget, derived rather than guessed. Strands stops the graph
# silently once the cap is hit, so a cap below the graph's own retry budget cut the
# run off mid-loop: the `evaluate` that would have set `quality_passed = True`
# never ran, `export` never ran, and the run reported "No data exported" instead of
# the best-effort dataset it had decided to accept.
#
#   attempt        = bulk_generation + evaluate                            = 2
#   pass           = distribution_inference + sample_generation + attempts = 2 + 3*2 = 8
#   revision       = schema_revision + a full pass                         = 1 + 8   = 9
#   worst case     = first pass + 2 revisions + export        = 8 + 2*9 + 1 = 27
_EXECUTIONS_PER_ATTEMPT = 2
_EXECUTIONS_PER_PASS = 2 + MAX_GENERATION_RETRIES * _EXECUTIONS_PER_ATTEMPT
_EXECUTIONS_PER_REVISION = 1 + _EXECUTIONS_PER_PASS
MAX_NODE_EXECUTIONS = (
    _EXECUTIONS_PER_PASS + MAX_SCHEMA_REVISIONS * _EXECUTIONS_PER_REVISION + 1
)


# ---------------------------------------------------------------------------
# FunctionNode — wraps a plain function as a graph node
# ---------------------------------------------------------------------------


class FunctionNode(MultiAgentBase):
    """Execute a Python function as a graph node."""

    def __init__(self, func, name: str):
        super().__init__()
        self.func = func
        self.name = name

    async def invoke_async(self, task, invocation_state=None, **kwargs):
        result_text = self.func(task if isinstance(task, str) else str(task))
        agent_result = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=str(result_text))]),
            metrics=None,
            state=None,
        )
        return MultiAgentResult(
            status=Status.COMPLETED,
            results={self.name: NodeResult(result=agent_result, status=Status.COMPLETED)},
        )


# ---------------------------------------------------------------------------
# Tool function loader
# ---------------------------------------------------------------------------


def _accept_schema(candidate: str, current: str, step: str) -> str:
    """Return ``candidate`` if it is a usable schema, else keep ``current``.

    Every step that reassigns ``PipelineState.schema_json`` overwrites the *only*
    copy of the schema, so a step that returns something unusable — a refusal, a
    truncated response, an entity-less shell — loses the real schema and every
    later stage generates against nothing. Refusing the replacement keeps the run
    on the last known-good schema instead.
    """
    try:
        parsed = InferredSchema.model_validate_json(candidate)
    except Exception as e:
        logger.warning("%s returned an unusable schema (%s) — keeping the previous one", step, e)
        return current
    if not parsed.entities:
        logger.warning("%s returned a schema with no entities — keeping the previous one", step)
        return current
    return candidate


# ---------------------------------------------------------------------------
# Pipeline state — shared across nodes via closure
# ---------------------------------------------------------------------------


class PipelineState:
    """Mutable state passed between graph nodes via closure."""

    def __init__(self):
        self.schema_json: str = ""
        self.sample_json: str = ""
        self.gen_result_json: str = ""
        self.generation_attempts: int = 0
        self.schema_revisions: int = 0
        self.quality_passed: bool = False
        self.evaluation_issues: list[str] = []
        self.evaluation_scores: dict[str, float] = {}
        self.export_json: str = ""


# ---------------------------------------------------------------------------
# Condition functions for graph edges
# ---------------------------------------------------------------------------


def _quality_passed(graph_state) -> bool:
    """Route to export if evaluation passed."""
    node_result = graph_state.results.get("evaluate")
    if not node_result:
        return False
    text = str(getattr(node_result, "result", ""))
    return '"quality_passed": true' in text.lower() or '"quality_passed":true' in text.lower()


def _should_retry_generation(graph_state) -> bool:
    """Route back to generation if quality failed but retries remain."""
    node_result = graph_state.results.get("evaluate")
    if not node_result:
        return False
    text = str(getattr(node_result, "result", ""))
    return '"retry": "generation"' in text.lower() or '"retry":"generation"' in text.lower()


def _should_revise_schema(graph_state) -> bool:
    """Route to schema revision if generation retries exhausted."""
    node_result = graph_state.results.get("evaluate")
    if not node_result:
        return False
    text = str(getattr(node_result, "result", ""))
    return '"retry": "schema"' in text.lower() or '"retry":"schema"' in text.lower()


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------


def build_graph_pipeline(
    schema: InferredSchema,
    output_dir: str = "./output",
    export_format: str = "json",
    target_count: int = 40,
    seed: int | None = None,
    model: str | None = None,
    session=None,
):
    """Build a graph pipeline with conditional retry loops and schema revision.

    Takes an already-resolved :class:`InferredSchema` (schema extraction is the
    ``plan`` step, kept separate). The graph starts at distribution inference.

    ``seed`` is forwarded to bulk generation, making the programmatic columns
    reproducible. Each generation attempt offsets it by the attempt number: a
    retry that redrew the identical values would fail the quality gate the same
    way forever, so the retry loop needs fresh draws while the run as a whole
    stays reproducible.

    ``model`` and ``session`` reach the agents through their plain implementation
    functions rather than the ``@tool`` wrappers, whose signatures deliberately
    exclude both.

    Returns:
        (graph, task_context, state) — invoke with ``graph(task_context)``; the
        shared :class:`PipelineState` carries the final data/scores after the run.
    """
    from seed_data.ingest.extract import extract_schema
    from seed_data.structured.distributions.inference import infer_distributions
    from seed_data.structured.exporter import export_data
    from seed_data.structured.generation import generate_bulk
    from seed_data.structured.sampling import generate_samples

    ps = PipelineState()
    ps.schema_json = schema.model_dump_json()

    _export = export_data._tool_func if hasattr(export_data, "_tool_func") else export_data

    # --- Node functions ---

    def distribution_step(task_text):
        logger.info("Graph: distribution inference")
        result = infer_distributions(ps.schema_json, model=model, session=session)
        ps.schema_json = _accept_schema(result, ps.schema_json, "Distribution inference")
        return result

    def sample_step(task_text):
        logger.info("Graph: sample generation")
        result = generate_samples(ps.schema_json, model=model, session=session)
        ps.sample_json = result
        return result

    def generation_step(task_text):
        ps.generation_attempts += 1
        logger.info("Graph: bulk generation (attempt %d/%d)", ps.generation_attempts, MAX_GENERATION_RETRIES)
        result = generate_bulk(
            entity_schema_definitions=ps.schema_json,
            sample_records_json=ps.sample_json,
            target_count=str(target_count),
            seed=None if seed is None else seed + ps.generation_attempts,
            model=model,
            session=session,
        )
        ps.gen_result_json = result
        return result

    def evaluate_step(task_text):
        """Evaluate quality and decide next action: export, retry generation, or revise schema."""
        logger.info("Graph: evaluation")
        from seed_data.evaluation.metrics import run_evaluation
        from seed_data.structured.postprocessing.pipeline import PostProcessingConfig, PostProcessingPipeline

        # Parse generated data
        try:
            gen_data = json.loads(ps.gen_result_json)
            if "data" in gen_data:
                gen_data = gen_data["data"]
        except (json.JSONDecodeError, TypeError):
            gen_data = {}

        # Filter to actual entity lists
        data = {k: v for k, v in gen_data.items() if isinstance(v, list)}

        if not data:
            logger.warning("No data to evaluate")
            if ps.generation_attempts >= MAX_GENERATION_RETRIES:
                if ps.schema_revisions < MAX_SCHEMA_REVISIONS:
                    return json.dumps({"quality_passed": False, "retry": "schema", "reason": "No data generated after max retries"})
                return json.dumps({"quality_passed": True, "retry": "none", "reason": "Max revisions reached, accepting empty"})
            return json.dumps({"quality_passed": False, "retry": "generation", "reason": "No data generated"})

        # Post-process
        try:
            schema = InferredSchema.model_validate_json(ps.schema_json)
            pp_pipeline = PostProcessingPipeline(schema, PostProcessingConfig())
            pp_result = pp_pipeline.run(data)
            # run() already corrected and filtered on its own copy; take that
            # result directly. Re-deriving from pp_result.validation cannot work —
            # it is the post-correction re-validation, whose fixable_count is 0.
            data = pp_result.data
        except Exception as e:
            logger.warning("Post-processing failed: %s", e)

        # Evaluate
        try:
            schema = InferredSchema.model_validate_json(ps.schema_json)
            report = run_evaluation(data, schema)
        except Exception as e:
            logger.warning("Evaluation failed: %s", e)
            return json.dumps({"quality_passed": True, "retry": "none", "reason": f"Evaluation error: {e}"})

        # Worst entity, not the mean: averaging lets a healthy entity mask one
        # that collapsed, which is exactly the failure this gate exists to catch.
        # Entities absent from `data` count as 0 rows rather than being skipped —
        # a missing entity is the most complete failure there is.
        worst_completeness = min(
            (
                completeness_score(len(data.get(e.entity_name, [])), target_count)
                for e in schema.entities
            ),
            default=1.0,
        )

        scores = {
            "diversity": report.overall_diversity_score,
            "fidelity": report.overall_fidelity_score,
            "coverage": report.overall_coverage_score,
            "structural": report.overall_structural_score,
            "completeness": worst_completeness,
        }
        ps.evaluation_scores = scores
        ps.evaluation_issues = report.issues

        # Check thresholds
        failed_dims = [
            f"{dim}: {scores[dim]:.2f} < {thresh}"
            for dim, thresh in QUALITY_THRESHOLDS.items()
            if scores.get(dim, 0.0) < thresh
        ]

        if not failed_dims:
            ps.quality_passed = True
            # Store corrected data back for export
            ps.gen_result_json = json.dumps({"data": data})
            logger.info("Quality PASSED — scores: %s", scores)
            return json.dumps({"quality_passed": True, "retry": "none", "scores": scores})

        logger.info("Quality FAILED — %s", failed_dims)

        if ps.generation_attempts >= MAX_GENERATION_RETRIES:
            if ps.schema_revisions < MAX_SCHEMA_REVISIONS:
                return json.dumps({
                    "quality_passed": False,
                    "retry": "schema",
                    "reason": f"Failed after {MAX_GENERATION_RETRIES} attempts: {failed_dims}",
                    "scores": scores,
                })
            else:
                # Accept what we have — max revisions exhausted
                ps.quality_passed = True
                ps.gen_result_json = json.dumps({"data": data})
                logger.info("Max revisions exhausted — accepting best result")
                return json.dumps({"quality_passed": True, "retry": "none", "scores": scores, "note": "accepted after max revisions"})

        return json.dumps({
            "quality_passed": False,
            "retry": "generation",
            "reason": f"Quality below thresholds: {failed_dims}",
            "scores": scores,
            "attempt": ps.generation_attempts,
        })

    def schema_revision_step(task_text):
        """Revise schema based on generation failures."""
        ps.schema_revisions += 1
        ps.generation_attempts = 0
        logger.info("Graph: schema revision (revision %d/%d)", ps.schema_revisions, MAX_SCHEMA_REVISIONS)

        issues_text = "; ".join(ps.evaluation_issues[:5]) if ps.evaluation_issues else "quality thresholds not met"
        scores_text = ", ".join(f"{k}={v:.2f}" for k, v in ps.evaluation_scores.items())

        revision_instructions = (
            f"The generated data failed quality evaluation (scores: {scores_text}). "
            f"Issues: {issues_text}. "
            "Revise the schema to address these problems: loosen overly tight constraints, "
            "ensure enum fields have enough values for diversity, ensure numeric ranges "
            "allow sufficient variety, and verify relationships are correctly defined."
        )

        # `current_schema`, not `schema_input`: the schema being revised is an
        # InferredSchema dump (a top-level `entities` list), and `schema_input` means
        # a *source* definition — a JSON Schema or SQL DDL — to extract from. Sent as
        # the latter it was both mislabelled and, before this, dropped from the prompt
        # entirely, so the reviser saw only "loosen overly tight constraints…" with no
        # schema attached and its invention replaced the real one.
        result = extract_schema(
            current_schema=ps.schema_json,
            override_instructions=revision_instructions,
            model=model,
            session=session,
        )
        ps.schema_json = _accept_schema(result, ps.schema_json, "Schema revision")
        return result

    def export_step(task_text):
        logger.info("Graph: export")
        gen_data = json.loads(ps.gen_result_json)
        data = gen_data.get("data", gen_data)
        data = {k: v for k, v in data.items() if isinstance(v, list)}
        result = _export(
            data_json=json.dumps(data),
            export_format=export_format,
            output_dir=output_dir,
        )
        ps.export_json = result
        return result

    # --- Build graph ---
    builder = GraphBuilder()

    builder.add_node(FunctionNode(distribution_step, "distribution_inference"), "distribution_inference")
    builder.add_node(FunctionNode(sample_step, "sample_generation"), "sample_generation")
    builder.add_node(FunctionNode(generation_step, "bulk_generation"), "bulk_generation")
    builder.add_node(FunctionNode(evaluate_step, "evaluate"), "evaluate")
    builder.add_node(FunctionNode(schema_revision_step, "schema_revision"), "schema_revision")
    builder.add_node(FunctionNode(export_step, "export"), "export")

    # Linear path (schema is seeded from the resolved InferredSchema)
    builder.add_edge("distribution_inference", "sample_generation")
    builder.add_edge("sample_generation", "bulk_generation")
    builder.add_edge("bulk_generation", "evaluate")

    # Conditional edges from evaluate
    builder.add_edge("evaluate", "export", condition=_quality_passed)
    builder.add_edge("evaluate", "bulk_generation", condition=_should_retry_generation)
    builder.add_edge("evaluate", "schema_revision", condition=_should_revise_schema)

    # After schema revision, re-run from distribution inference
    builder.add_edge("schema_revision", "distribution_inference")

    builder.set_entry_point("distribution_inference")
    builder.set_execution_timeout(3600)
    builder.set_max_node_executions(MAX_NODE_EXECUTIONS)
    builder.reset_on_revisit(False)

    task_context = _build_task_context(schema, output_dir, export_format, target_count)
    return builder.build(), task_context, ps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_graph_pipeline(
    schema: InferredSchema,
    output_dir: str = "./output",
    export_format: str = "json",
    target_count: int = 40,
    seed: int | None = None,
    model: str | None = None,
    session=None,
) -> tuple[str, "PipelineState"]:
    """Run the graph-based pipeline end-to-end.

    Args:
        schema: The resolved :class:`InferredSchema` to generate data for.
        output_dir: Directory to write output files.
        export_format: Export format.
        target_count: Target records per entity.
        seed: optional RNG seed for the programmatic generation columns.
        model: optional model key for the pipeline's agents.
        session: optional boto3 Session for the pipeline's agents.

    Returns:
        (summary_string, final_pipeline_state).
    """
    graph, task_context, ps = build_graph_pipeline(
        schema, output_dir, export_format, target_count, seed, model, session,
    )

    logger.info("Starting graph pipeline")
    result = graph(task_context)
    logger.info("Graph pipeline complete")

    return str(result), ps


def _build_task_context(
    schema: InferredSchema,
    output_dir: str,
    export_format: str,
    target_count: int,
) -> str:
    """Build the initial task string for the graph."""
    entity_names = ", ".join(e.entity_name for e in schema.entities)
    parts = [
        "Generate synthetic data for the following schema.",
        f"Entities: {entity_names}",
        f"Target: {target_count} records per entity",
        f"Export: {export_format} to {output_dir}",
    ]
    return "\n".join(parts)

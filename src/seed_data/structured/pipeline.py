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
)
from seed_data.schema.models import InferredSchema

logger = logging.getLogger(__name__)

MAX_GENERATION_RETRIES = 3
MAX_SCHEMA_REVISIONS = 2


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


def _get_tool_func(tool_name: str):
    """Get the raw function from a @tool decorated function."""
    import importlib

    _TOOL_MODULES = {
        "schema_extraction_agent": "seed_data.ingest.extract",
        "distribution_inference_agent": "seed_data.structured.distributions.inference",
        "sample_generation_agent": "seed_data.structured.sampling",
        "bulk_generation_agent": "seed_data.structured.generation",
        "export_data": "seed_data.structured.exporter",
    }

    module = importlib.import_module(_TOOL_MODULES[tool_name])
    tool_obj = getattr(module, tool_name)
    if hasattr(tool_obj, "_tool_func"):
        return tool_obj._tool_func
    return tool_obj


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
):
    """Build a graph pipeline with conditional retry loops and schema revision.

    Takes an already-resolved :class:`InferredSchema` (schema extraction is the
    ``ingest`` step, kept separate). The graph starts at distribution inference.

    Returns:
        (graph, task_context, state) — invoke with ``graph(task_context)``; the
        shared :class:`PipelineState` carries the final data/scores after the run.
    """
    ps = PipelineState()
    ps.schema_json = schema.model_dump_json()

    # Load tool functions
    _dist_infer = _get_tool_func("distribution_inference_agent")
    _sample_gen = _get_tool_func("sample_generation_agent")
    _bulk_gen = _get_tool_func("bulk_generation_agent")
    _export = _get_tool_func("export_data")

    # --- Node functions ---

    def distribution_step(task_text):
        logger.info("Graph: distribution inference")
        result = _dist_infer(schema_json=ps.schema_json)
        ps.schema_json = result
        return result

    def sample_step(task_text):
        logger.info("Graph: sample generation")
        result = _sample_gen(entity_schema_definitions=ps.schema_json)
        ps.sample_json = result
        return result

    def generation_step(task_text):
        ps.generation_attempts += 1
        logger.info("Graph: bulk generation (attempt %d/%d)", ps.generation_attempts, MAX_GENERATION_RETRIES)
        result = _bulk_gen(
            entity_schema_definitions=ps.schema_json,
            sample_records_json=ps.sample_json,
            target_count=str(target_count),
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

        scores = {
            "diversity": report.overall_diversity_score,
            "fidelity": report.overall_fidelity_score,
            "coverage": report.overall_coverage_score,
            "structural": report.overall_structural_score,
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

        # Use schema override tool to fix issues
        from seed_data.ingest.extract import schema_extraction_agent as _se_tool
        _schema_revise = _se_tool._tool_func

        revision_instructions = (
            f"The generated data failed quality evaluation (scores: {scores_text}). "
            f"Issues: {issues_text}. "
            "Revise the schema to address these problems: loosen overly tight constraints, "
            "ensure enum fields have enough values for diversity, ensure numeric ranges "
            "allow sufficient variety, and verify relationships are correctly defined."
        )

        result = _schema_revise(
            schema_input=ps.schema_json,
            schema_format="json_schema",
            override_instructions=revision_instructions,
        )
        ps.schema_json = result
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
    # Enough for: 4 linear + 3 retries + 2 schema revisions × (3 retries each) = ~20 max
    builder.set_max_node_executions(25)
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
) -> tuple[str, "PipelineState"]:
    """Run the graph-based pipeline end-to-end.

    Args:
        schema: The resolved :class:`InferredSchema` to generate data for.
        output_dir: Directory to write output files.
        export_format: Export format.
        target_count: Target records per entity.

    Returns:
        (summary_string, final_pipeline_state).
    """
    graph, task_context, ps = build_graph_pipeline(
        schema, output_dir, export_format, target_count
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

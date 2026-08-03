from pydantic import BaseModel, Field

from seed_data.evaluation.metrics import EvaluationReport, run_evaluation
from seed_data.schema.models import InferredSchema

from .corrector import RecordCorrector
from .validator import RecordValidator, ValidationResult, Violation


class PostProcessingConfig(BaseModel):
    quality_threshold: float = Field(default=0.7, description="Minimum quality score to pass the gate")
    max_regeneration_attempts: int = Field(default=2, description="Max times to request re-generation")
    overproduce_factor: float = Field(default=1.5, description="Generate N * factor records, then filter to N")
    enable_correction: bool = Field(default=True, description="Whether to auto-correct fixable violations")
    enable_filtering: bool = Field(default=True, description="Whether to filter unfixable records")


class PostProcessingResult(BaseModel):
    # The corrected + filtered dataset — the actual output callers must export.
    # Correction and filtering happen on an internal copy; without surfacing it
    # here, callers can only see the *counts* and would have to redo the work
    # (and can't: `validation` below is the post-correction re-validation, whose
    # `fixable_count` is already 0). Consume this, don't re-derive.
    data: dict[str, list[dict]] = Field(default_factory=dict)
    original_count: dict[str, int] = Field(default_factory=dict)
    corrected_count: int = 0
    filtered_count: int = 0
    final_count: dict[str, int] = Field(default_factory=dict)
    validation: ValidationResult | None = None
    evaluation: EvaluationReport | None = None
    passes_quality_gate: bool = False
    needs_regeneration: bool = False
    regeneration_gap: dict[str, int] = Field(default_factory=dict)


class PostProcessingPipeline:
    """Orchestrates validate → correct → filter → evaluate → quality gate."""

    def __init__(self, schema: InferredSchema, config: PostProcessingConfig | None = None):
        self.schema = schema
        self.config = config or PostProcessingConfig()
        self.validator = RecordValidator()
        self.corrector = RecordCorrector()

    def run(
        self,
        data: dict[str, list[dict]],
        target_counts: dict[str, int] | None = None,
    ) -> PostProcessingResult:
        """Execute the full post-processing pipeline.

        Args:
            data: Generated records per entity.
            target_counts: Desired final record count per entity. If None, keeps all valid.

        Returns:
            PostProcessingResult with metrics and final data state.
        """
        original_count = {name: len(records) for name, records in data.items()}

        validation = self.validator.validate_dataset(data, self.schema)

        corrected_count = 0
        if self.config.enable_correction and validation.fixable_count > 0:
            data = self.corrector.correct_dataset(data, validation.violations, self.schema)
            corrected_count = validation.fixable_count
            validation = self.validator.validate_dataset(data, self.schema)

        filtered_count = 0
        if self.config.enable_filtering and validation.violations:
            data, filtered_count = self._filter_invalid_records(data, validation.violations)

        evaluation = run_evaluation(data, self.schema, self.config.quality_threshold)

        regeneration_gap = {}
        if target_counts:
            for name, target in target_counts.items():
                current = len(data.get(name, []))
                if current < target:
                    regeneration_gap[name] = target - current

        final_count = {name: len(records) for name, records in data.items()}
        needs_regeneration = bool(regeneration_gap) or not evaluation.passes_quality_gate

        return PostProcessingResult(
            data=data,
            original_count=original_count,
            corrected_count=corrected_count,
            filtered_count=filtered_count,
            final_count=final_count,
            validation=validation,
            evaluation=evaluation,
            passes_quality_gate=evaluation.passes_quality_gate,
            needs_regeneration=needs_regeneration,
            regeneration_gap=regeneration_gap,
        )

    def _filter_invalid_records(
        self, data: dict[str, list[dict]], violations: list[Violation]
    ) -> tuple[dict[str, list[dict]], int]:
        """Remove records with unfixable violations."""
        unfixable_records: dict[str, set[int]] = {}
        for v in violations:
            if not v.fixable:
                unfixable_records.setdefault(v.entity, set()).add(v.record_index)

        filtered_count = 0
        result = {}
        for name, records in data.items():
            bad_indices = unfixable_records.get(name, set())
            if bad_indices:
                filtered_count += len(bad_indices)
                result[name] = [r for idx, r in enumerate(records) if idx not in bad_indices]
            else:
                result[name] = records

        return result, filtered_count

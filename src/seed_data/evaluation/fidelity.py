import math
import re

import pandas as pd

from seed_data.evaluation.diversity import _hashable
from seed_data.schema.models import DistributionType, EntitySchema, FieldDefinition
from seed_data.structured.distributions.generator import positive_param, scalar_param


def _is_missing(value) -> bool:
    """Scalar null test that tolerates nested values.

    ``pd.isna`` on a list or dict returns an *elementwise array*, so the surrounding
    ``if`` raised ``ValueError: The truth value of an array ... is ambiguous`` — which
    ``run_evaluation``'s blanket ``except`` turned into a dropped entity, taking
    diversity and coverage down with it. A populated list or dict is never missing,
    which is the answer every caller here wants.
    """
    if isinstance(value, (list, dict, set, tuple)):
        return False
    result = pd.isna(value)
    # An ndarray cell still yields an array; count it missing only if every element is.
    return bool(result.all()) if hasattr(result, "all") else bool(result)


class FidelityMetrics:
    """Measures how well generated data conforms to schema constraints and target distributions."""

    def constraint_violation_rate(self, data: pd.DataFrame, schema: EntitySchema) -> float:
        """Fraction of (record, field) cells that violate schema constraints.

        Returns 0.0 for perfect conformance, 1.0 for all cells violating.
        """
        if data.empty:
            return 0.0

        # FK fields should not be range-checked (their valid values come from the parent)
        fk_fields = {
            rel.source_field
            for rel in schema.structured_relationships
            if rel.source_entity == schema.entity_name
        }

        total_cells = 0
        violations = 0

        for field in schema.fields:
            if field.name not in data.columns:
                continue
            if field.name in fk_fields:
                continue
            series = data[field.name]
            total_cells += len(series)

            for idx, value in series.items():
                if _is_missing(value):
                    if field.requires_value:
                        violations += 1
                    continue

                if self._violates_constraint(value, field):
                    violations += 1

        if total_cells == 0:
            # Two different situations reach here, and conflating them was a defect in
            # both directions:
            #
            #   (a) No schema field appears in the data at all — the records share no
            #       columns with their schema. Scoring that 0.0 violations reported
            #       perfect fidelity for data that matches nothing, and it passed the
            #       gate with no issue recorded.
            #   (b) Every field that *is* present was skipped as a foreign key. That is
            #       an ordinary junction table (`OrderItem(order_id, product_id)`);
            #       there is simply nothing for this metric to check, and scoring it a
            #       total violation failed a perfectly good entity.
            #
            # So key off overlap, not off the counter.
            present = [f for f in schema.fields if f.name in data.columns]
            if schema.fields and not present:
                return 1.0
            return 0.0
        return violations / total_cells

    def _violates_constraint(self, value, field: FieldDefinition) -> bool:
        """Check if a single value violates field constraints."""
        if field.type in ("integer", "float") and field.min_value is not None:
            try:
                if float(value) < field.min_value:
                    return True
            except (ValueError, TypeError):
                return True

        if field.type in ("integer", "float") and field.max_value is not None:
            try:
                if float(value) > field.max_value:
                    return True
            except (ValueError, TypeError):
                return True

        if field.type == "integer":
            try:
                int(value)
            except (ValueError, TypeError):
                return True

        if field.enum_values and field.type in ("string", "enum") and str(value) not in field.enum_values:
            return True

        if field.pattern and field.type in ("string", "email", "phone", "enum"):
            try:
                if not re.match(field.pattern, str(value)):
                    return True
            except re.error:
                pass

        if field.min_length is not None and len(str(value)) < field.min_length:
            return True

        if field.max_length is not None and len(str(value)) > field.max_length:
            return True

        return False

    def distribution_distance_ks(self, observed: pd.Series, target_mean: float, target_std: float) -> float:
        """Kolmogorov-Smirnov statistic comparing observed to a normal distribution.

        Returns KS statistic in [0, 1]. Lower = better fit.
        """
        # Coerced, not cast: `astype(float)` raises on a single non-numeric cell, and
        # `run_evaluation`'s blanket except then threw away fidelity *and* coverage for
        # the entire entity. A non-numeric value in a numeric column is a type_error
        # the validator already reports; it must not also blind the distribution check.
        # This is the `pd.to_numeric(..., errors="coerce")` pattern `coverage` uses.
        values = pd.to_numeric(observed, errors="coerce").dropna()
        if len(values) < 2:
            return 1.0

        sorted_vals = sorted(values)
        n = len(sorted_vals)

        if target_std <= 0:
            # A zero/absent std is a degenerate distribution: all mass at the mean, so
            # its CDF is a step function. The per-point loop below cannot express that
            # — it compares against the *pre-jump* empirical CDF at tied values — and
            # with `z = 0` it previously pinned the theoretical CDF at a constant 0.5,
            # scoring KS 0.5 for data that matched the spec exactly. The distance is
            # simply the fraction of observations that are not at the mean.
            off_mass = sum(1 for v in sorted_vals if v != target_mean)
            return off_mass / n

        max_diff = 0.0
        for i, val in enumerate(sorted_vals):
            empirical_cdf = (i + 1) / n
            z = (val - target_mean) / target_std
            theoretical_cdf = 0.5 * (1 + math.erf(z / math.sqrt(2)))
            diff = abs(empirical_cdf - theoretical_cdf)
            max_diff = max(max_diff, diff)

        return max_diff

    def distribution_distance_jsd(self, observed_counts: dict, expected_weights: dict) -> float:
        """Jensen-Shannon Divergence between observed and expected categorical distributions.

        Returns JSD in [0, 1]. Lower = better fit. 0.0 = identical.
        """
        all_keys = set(observed_counts.keys()) | set(expected_weights.keys())
        if not all_keys:
            return 0.0

        total_observed = sum(observed_counts.values())
        if total_observed == 0:
            return 1.0

        total_expected = sum(expected_weights.values())
        if total_expected == 0:
            return 1.0

        p = {k: observed_counts.get(k, 0) / total_observed for k in all_keys}
        q = {k: expected_weights.get(k, 0) / total_expected for k in all_keys}

        m = {k: (p[k] + q[k]) / 2 for k in all_keys}

        def kl_div(dist_a, dist_b):
            total = 0.0
            for k in all_keys:
                if dist_a[k] > 0 and dist_b[k] > 0:
                    total += dist_a[k] * math.log2(dist_a[k] / dist_b[k])
            return total

        jsd = 0.5 * kl_div(p, m) + 0.5 * kl_div(q, m)
        return min(jsd, 1.0)

    def overall_fidelity_score(self, data: pd.DataFrame, schema: EntitySchema) -> dict:
        """Compute fidelity metrics for an entity's generated data."""
        results = {
            "constraint_violation_rate": 0.0,
            "distribution_distances": {},
            "overall_score": 0.0,
        }

        if data.empty:
            return results

        cvr = self.constraint_violation_rate(data, schema)
        results["constraint_violation_rate"] = cvr

        dist_scores = []
        for field in schema.fields:
            if field.distribution is None or field.name not in data.columns:
                continue

            series = data[field.name]
            if field.distribution.type == DistributionType.NORMAL and field.type in ("integer", "float"):
                # Numeric only: the generator supports NORMAL on date/datetime too
                # (params are day offsets), and running the numeric KS on ISO date
                # strings coerced them all to NaN -> "fewer than 2 values" -> a 1.0
                # distance appended for perfectly correct dates, pinning fidelity at
                # exactly the 0.6 gate threshold. Dates are simply not scored here:
                # unmeasurable is not the same as worst-possible.
                # Read through the *same* helpers the generator uses, so the evaluator
                # scores against the parameters that were actually sampled from. Read
                # raw, a spec of `{"mean": 100, "std": 0}` was generated with
                # `positive_param`'s 1.0 substitution — producing spread data — and then
                # scored here as a degenerate distribution, giving ~1.0 KS distance and
                # dragging fidelity to the threshold for data that was fine.
                mean = scalar_param(field.distribution.params, "mean", 0.0)
                std = positive_param(field.distribution.params, "std", 1.0)
                ks = self.distribution_distance_ks(series, mean, std)
                results["distribution_distances"][field.name] = {"ks_statistic": ks}
                dist_scores.append(1.0 - ks)

            elif field.distribution.type == DistributionType.CATEGORICAL_WEIGHTED:
                weights_list = field.distribution.params.get("weights", [])
                # `and weights_list`: an empty list passes the isinstance check, making
                # `expected` empty, and `distribution_distance_jsd` then returns its
                # `total_expected == 0` sentinel of 1.0 — scoring perfectly balanced
                # data worst-possible because the *schema* omitted its weights.
                if field.enum_values and isinstance(weights_list, list) and weights_list:
                    expected = dict(zip(field.enum_values, weights_list))
                    # str()-normalized: `enum_values` is `list[str]` by model
                    # validator, while `_coerce_enum` emits real ints/floats/bools —
                    # compared raw, a numeric enum matching its weights exactly had
                    # disjoint supports and scored JSD 1.0. The other two consumers
                    # (`coverage.enum_coverage_ratio`, `_violates_constraint`)
                    # already str()-normalize; this was the odd one out.
                    observed_raw = _hashable(series).dropna().value_counts().to_dict()
                    observed: dict = {}
                    for key, count in observed_raw.items():
                        skey = str(key)
                        observed[skey] = observed.get(skey, 0) + count
                    jsd = self.distribution_distance_jsd(observed, expected)
                    results["distribution_distances"][field.name] = {"jsd": jsd}
                    dist_scores.append(1.0 - jsd)

        conformance_score = 1.0 - cvr
        if dist_scores:
            dist_avg = sum(dist_scores) / len(dist_scores)
            results["overall_score"] = 0.6 * conformance_score + 0.4 * dist_avg
        else:
            results["overall_score"] = conformance_score

        return results

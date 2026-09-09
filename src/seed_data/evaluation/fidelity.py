import math
import re

import pandas as pd

from seed_data.schema.models import DistributionType, EntitySchema, FieldDefinition


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
                if pd.isna(value):
                    if field.requires_value:
                        violations += 1
                    continue

                if self._violates_constraint(value, field):
                    violations += 1

        if total_cells == 0:
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
        values = observed.dropna().astype(float)
        if len(values) < 2:
            return 1.0

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        max_diff = 0.0

        for i, val in enumerate(sorted_vals):
            empirical_cdf = (i + 1) / n
            z = (val - target_mean) / target_std if target_std > 0 else 0
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
            if field.distribution.type == DistributionType.NORMAL:
                mean = field.distribution.params.get("mean", 0.0)
                std = field.distribution.params.get("std", 1.0)
                ks = self.distribution_distance_ks(series, float(mean), float(std))
                results["distribution_distances"][field.name] = {"ks_statistic": ks}
                dist_scores.append(1.0 - ks)

            elif field.distribution.type == DistributionType.CATEGORICAL_WEIGHTED:
                weights_list = field.distribution.params.get("weights", [])
                if field.enum_values and isinstance(weights_list, list):
                    expected = dict(zip(field.enum_values, weights_list))
                    observed = series.dropna().value_counts().to_dict()
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

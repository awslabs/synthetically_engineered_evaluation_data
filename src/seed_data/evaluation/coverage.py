from itertools import combinations

import pandas as pd

from seed_data.schema.models import EntitySchema, FieldDefinition


class CoverageMetrics:
    """Measures how well generated data covers the specified value space."""

    def enum_coverage_ratio(self, series: pd.Series, field: FieldDefinition) -> float:
        """Fraction of allowed enum values that appear at least once.

        Returns 1.0 if all enum values are represented, 0.0 if none.
        """
        if not field.enum_values:
            return 1.0
        observed = set(series.dropna().astype(str).unique())
        covered = observed & set(field.enum_values)
        return len(covered) / len(field.enum_values)

    def numeric_range_coverage(self, series: pd.Series, field: FieldDefinition) -> float:
        """Proportion of the specified numeric range actually explored.

        Returns (max_observed - min_observed) / (max_allowed - min_allowed).
        Capped at 1.0.
        """
        if field.min_value is None or field.max_value is None:
            return 1.0

        allowed_range = field.max_value - field.min_value
        if allowed_range <= 0:
            return 1.0

        numeric_vals = pd.to_numeric(series.dropna(), errors="coerce").dropna()
        if len(numeric_vals) < 2:
            return 0.0

        observed_range = numeric_vals.max() - numeric_vals.min()
        return min(observed_range / allowed_range, 1.0)

    def combinatorial_coverage(self, data: pd.DataFrame, columns: list[str], n: int = 2) -> float:
        """Fraction of n-wise value combinations actually observed.

        For n=2 (pairwise), measures what fraction of all possible 2-column
        value pair combinations appear in the data. Capped at analyzing
        columns with <= 20 unique values each to keep computation tractable.
        """
        eligible_cols = [
            col for col in columns if col in data.columns and data[col].nunique() <= 20
        ]

        if len(eligible_cols) < n:
            return 1.0

        coverage_scores = []
        for col_combo in combinations(eligible_cols, n):
            cols = list(col_combo)
            subset = data[cols].dropna()
            if subset.empty:
                coverage_scores.append(0.0)
                continue

            observed_combos = subset.drop_duplicates().shape[0]

            max_possible = 1
            for col in cols:
                max_possible *= data[col].nunique()

            if max_possible == 0:
                coverage_scores.append(1.0)
            else:
                coverage_scores.append(min(observed_combos / max_possible, 1.0))

        if not coverage_scores:
            return 1.0
        return sum(coverage_scores) / len(coverage_scores)

    def overall_coverage_score(self, data: pd.DataFrame, schema: EntitySchema) -> dict:
        """Compute coverage metrics for an entity's generated data."""
        results = {
            "enum_coverage": {},
            "range_coverage": {},
            "combinatorial_2way": 0.0,
            "overall_score": 0.0,
        }

        if data.empty:
            return results

        scores = []

        enum_cols = []
        for field in schema.fields:
            if field.name not in data.columns:
                continue
            series = data[field.name]

            if field.enum_values:
                cov = self.enum_coverage_ratio(series, field)
                results["enum_coverage"][field.name] = cov
                scores.append(cov)
                enum_cols.append(field.name)

            if field.type in ("integer", "float") and field.min_value is not None and field.max_value is not None:
                range_cov = self.numeric_range_coverage(series, field)
                results["range_coverage"][field.name] = range_cov
                scores.append(range_cov)

        if enum_cols and len(enum_cols) >= 2:
            comb_cov = self.combinatorial_coverage(data, enum_cols, n=2)
            results["combinatorial_2way"] = comb_cov
            scores.append(comb_cov)

        results["overall_score"] = sum(scores) / len(scores) if scores else 1.0
        return results

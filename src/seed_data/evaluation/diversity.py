import math

import pandas as pd

from seed_data.schema.models import EntitySchema


def _hashable(series: pd.Series) -> pd.Series:
    """Make a column safe for ``value_counts`` / ``nunique`` / ``drop_duplicates``.

    ``InferredSchema`` fully supports nested ``object`` and ``array`` fields, so a
    cell can legitimately hold a list or a dict. Those are unhashable, and pandas
    raises ``TypeError: unhashable type: 'list'`` — which ``run_evaluation``'s blanket
    ``except`` then recorded as an "evaluation error", dropping diversity, fidelity
    *and* coverage for the whole entity. Valid nested data scored 0.25 overall and
    failed the quality gate.

    Nested values are compared by their JSON form: two structurally identical lists
    are one value, which is the right notion of "distinct" for every caller here.
    """
    if series.map(lambda v: isinstance(v, (list, dict, set))).any():
        import json

        return series.map(
            lambda v: json.dumps(v, sort_keys=True, default=str)
            if isinstance(v, (list, dict, set)) else v
        )
    return series


class DiversityMetrics:
    """Measures value variation and uniqueness across generated data."""

    def per_column_entropy(self, series: pd.Series, n_possible: int | None = None) -> float:
        """Shannon entropy normalized to [0, 1].

        Args:
            series: the column's values.
            n_possible: how many distinct values the column is *allowed* to take
                (an enum's cardinality). When given it is the normalizer, so a column
                using only some of its allowed values scores below 1.0. When None — a
                free-form column with no declared domain — the observed distinct count
                is the only denominator available.

        Returns 1.0 for maximally diverse, 0.0 for all-same.
        """
        counts = _hashable(series).dropna().value_counts()
        if len(counts) <= 1:
            return 0.0
        total = counts.sum()
        probs = counts / total
        entropy = -sum(p * math.log2(p) for p in probs if p > 0)

        # Normalized by the *possible* cardinality when the schema declares one, not
        # by the observed distinct count. Observed-count normalization made the metric
        # blind to what it exists to detect: a status column allowing three values but
        # only ever emitting two, 50/50, scored exactly 1.0 — "maximally diverse" — so
        # mode collapse could not lower the score at all.
        denominator = max(n_possible or 0, len(counts))
        max_entropy = math.log2(denominator)
        if max_entropy == 0:
            return 0.0
        return entropy / max_entropy

    def unique_ratio(self, series: pd.Series) -> float:
        """Fraction of unique values in the column. 1.0 = all unique, 1/n = all same."""
        non_null = _hashable(series).dropna()
        if len(non_null) == 0:
            return 0.0
        return non_null.nunique() / len(non_null)

    def embedding_dispersion(self, data: pd.DataFrame, text_columns: list[str]) -> float:
        """Simple text dispersion metric using character-level Jaccard distance.

        Averages pairwise Jaccard distance across all text column values.
        Returns value in [0, 1] where 1.0 = maximally dispersed.
        """
        if not text_columns or data.empty:
            return 0.0

        dispersions = []
        for col in text_columns:
            if col not in data.columns:
                continue
            values = data[col].dropna().astype(str).tolist()
            if len(values) < 2:
                continue
            char_sets = [set(v.lower()) for v in values]
            distances = []
            for i in range(min(len(char_sets), 50)):
                for j in range(i + 1, min(len(char_sets), 50)):
                    union = char_sets[i] | char_sets[j]
                    if not union:
                        continue
                    intersection = char_sets[i] & char_sets[j]
                    distances.append(1.0 - len(intersection) / len(union))
            if distances:
                dispersions.append(sum(distances) / len(distances))

        if not dispersions:
            return 0.0
        return sum(dispersions) / len(dispersions)

    def overall_diversity_score(self, data: pd.DataFrame, schema: EntitySchema) -> dict:
        """Compute diversity metrics for all columns in an entity."""
        results = {
            "per_column_entropy": {},
            "per_column_unique_ratio": {},
            "text_dispersion": 0.0,
            "overall_score": 0.0,
        }

        if data.empty:
            return results

        entropy_scores = []
        unique_scores = []
        text_columns = []

        for field in schema.fields:
            if field.name not in data.columns:
                continue
            series = data[field.name]

            # The enum's cardinality is the normalizer when the schema declares one:
            # that is what makes a column using 2 of its 3 allowed values score below
            # 1.0 instead of "maximally diverse".
            ent = self.per_column_entropy(
                series, n_possible=len(field.enum_values) if field.enum_values else None
            )
            results["per_column_entropy"][field.name] = ent
            entropy_scores.append(ent)

            uniq = self.unique_ratio(series)
            results["per_column_unique_ratio"][field.name] = uniq
            unique_scores.append(uniq)

            if field.type in ("string", "email", "phone"):
                text_columns.append(field.name)

        if text_columns:
            results["text_dispersion"] = self.embedding_dispersion(data, text_columns)

        scores = entropy_scores + unique_scores
        if text_columns:
            scores.append(results["text_dispersion"])

        results["overall_score"] = sum(scores) / len(scores) if scores else 0.0
        return results

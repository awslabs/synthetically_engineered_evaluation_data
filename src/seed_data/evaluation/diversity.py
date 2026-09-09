import math

import pandas as pd

from seed_data.schema.models import EntitySchema


class DiversityMetrics:
    """Measures value variation and uniqueness across generated data."""

    def per_column_entropy(self, series: pd.Series) -> float:
        """Shannon entropy normalized to [0, 1] by dividing by log(n_unique_possible).

        Returns 1.0 for maximally diverse (uniform), 0.0 for all-same.
        """
        counts = series.dropna().value_counts()
        if len(counts) <= 1:
            return 0.0
        total = counts.sum()
        probs = counts / total
        entropy = -sum(p * math.log2(p) for p in probs if p > 0)
        max_entropy = math.log2(len(counts))
        if max_entropy == 0:
            return 0.0
        return entropy / max_entropy

    def unique_ratio(self, series: pd.Series) -> float:
        """Fraction of unique values in the column. 1.0 = all unique, 1/n = all same."""
        non_null = series.dropna()
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

            ent = self.per_column_entropy(series)
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

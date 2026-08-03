import numpy as np
import pandas as pd
from scipy import stats

from seed_data.schema.models import DistributionSpec, DistributionType, EntitySchema, FieldDefinition


class DistributionAdjuster:
    """Post-hoc statistical adjustment of LLM-generated data to match target distributions.

    Uses rank-based quantile mapping: sort LLM values by rank, then map each rank
    to the corresponding quantile of the target distribution. This preserves
    inter-column correlation structure while achieving the target marginals.
    """

    def adjust_field(self, series: pd.Series, field: FieldDefinition) -> pd.Series:
        """Adjust a single column's distribution to match its target spec."""
        if field.distribution is None:
            return series

        if field.type in ("integer", "float"):
            return self._adjust_numeric(series, field)
        elif field.type == "enum" and field.enum_values:
            return self._adjust_categorical(series, field)
        return series

    def adjust_entity(self, df: pd.DataFrame, schema: EntitySchema) -> pd.DataFrame:
        """Adjust all columns in a DataFrame to match their target distributions."""
        result = df.copy()
        for field in schema.fields:
            if field.distribution is None or field.name not in result.columns:
                continue
            result[field.name] = self.adjust_field(result[field.name], field)
        return result

    def _adjust_numeric(self, series: pd.Series, field: FieldDefinition) -> pd.Series:
        """Rank-based quantile mapping for numeric columns."""
        spec = field.distribution
        non_null_mask = series.notna()
        values = series[non_null_mask].astype(float)

        if len(values) < 2:
            return series

        n = len(values)
        ranks = values.rank(method="average")
        quantiles = (ranks - 0.5) / n

        target_values = self._inverse_cdf(quantiles.values, spec, field)

        result = series.copy().astype(float)
        result[non_null_mask] = target_values

        if field.type == "integer":
            result = result.round().astype(int)

        return result

    def _inverse_cdf(self, quantiles: np.ndarray, spec: DistributionSpec, field: FieldDefinition) -> np.ndarray:
        """Compute inverse CDF (quantile function) for the target distribution."""
        params = spec.params
        min_val = field.min_value if field.min_value is not None else -np.inf
        max_val = field.max_value if field.max_value is not None else np.inf

        quantiles = np.clip(quantiles, 0.001, 0.999)

        if spec.type == DistributionType.NORMAL:
            mean = float(params.get("mean", 0.0))
            std = float(params.get("std", 1.0))
            values = stats.norm.ppf(quantiles, loc=mean, scale=std)

        elif spec.type == DistributionType.UNIFORM:
            low = float(params.get("low", min_val if np.isfinite(min_val) else 0.0))
            high = float(params.get("high", max_val if np.isfinite(max_val) else 1.0))
            values = stats.uniform.ppf(quantiles, loc=low, scale=high - low)

        elif spec.type == DistributionType.EXPONENTIAL:
            lam = float(params.get("lambda", 1.0))
            values = stats.expon.ppf(quantiles, scale=1.0 / lam)

        elif spec.type == DistributionType.LOG_NORMAL:
            mu = float(params.get("mu", 0.0))
            sigma = float(params.get("sigma", 1.0))
            values = stats.lognorm.ppf(quantiles, s=sigma, scale=np.exp(mu))

        elif spec.type == DistributionType.SKEWED_LEFT:
            a = -float(params.get("skewness", 5.0))
            values = stats.skewnorm.ppf(quantiles, a)

        elif spec.type == DistributionType.SKEWED_RIGHT:
            a = float(params.get("skewness", 5.0))
            values = stats.skewnorm.ppf(quantiles, a)

        else:
            values = stats.norm.ppf(quantiles)

        return np.clip(values, min_val, max_val)

    def _adjust_categorical(self, series: pd.Series, field: FieldDefinition) -> pd.Series:
        """Resample categorical values to match target weight distribution."""
        spec = field.distribution
        if not field.enum_values or spec.type != DistributionType.CATEGORICAL_WEIGHTED:
            return series

        weights = spec.params.get("weights", [])
        if not isinstance(weights, list) or len(weights) != len(field.enum_values):
            return series

        total = sum(weights)
        target_probs = [w / total for w in weights]

        non_null_mask = series.notna()
        n = non_null_mask.sum()
        if n == 0:
            return series

        target_counts = [max(1, round(p * n)) for p in target_probs]
        while sum(target_counts) > n:
            max_idx = target_counts.index(max(target_counts))
            target_counts[max_idx] -= 1
        while sum(target_counts) < n:
            min_idx = target_counts.index(min(target_counts))
            target_counts[min_idx] += 1

        new_values = []
        for val, count in zip(field.enum_values, target_counts):
            new_values.extend([val] * count)

        rng = np.random.default_rng(42)
        rng.shuffle(new_values)

        result = series.copy()
        result[non_null_mask] = new_values[:n]
        return result

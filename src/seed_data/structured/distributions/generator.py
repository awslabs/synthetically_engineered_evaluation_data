from datetime import date, timedelta

import numpy as np
from scipy import stats

from seed_data.schema.models import DistributionSpec, DistributionType, FieldDefinition


class DistributionGenerator:
    """Generates column values according to specified statistical distributions."""

    def __init__(self, seed: int | None = None):
        self.rng = np.random.default_rng(seed)

    def generate_field_values(self, field: FieldDefinition, count: int) -> list:
        """Generate values for a field based on its distribution spec and constraints."""
        if field.distribution is None:
            return self._generate_default(field, count)

        if field.type in ("integer", "float"):
            return self.generate_numeric(field, count)
        elif field.enum_values:
            return self.generate_categorical(field, count)
        elif field.type in ("date", "datetime"):
            return self.generate_dates(field, count)
        else:
            return self._generate_default(field, count)

    def generate_numeric(self, field: FieldDefinition, count: int) -> list:
        """Generate numeric values following the specified distribution."""
        spec = field.distribution
        min_val = field.min_value if field.min_value is not None else -1e6
        max_val = field.max_value if field.max_value is not None else 1e6

        if spec.type in (DistributionType.SKEWED_LEFT, DistributionType.SKEWED_RIGHT):
            values = self._sample_skewed(spec, count, min_val, max_val)
        else:
            values = self._sample_distribution(spec, count)
        values = np.clip(values, min_val, max_val)

        if field.type == "integer":
            values = np.round(values).astype(int)
            return values.tolist()
        return [round(float(v), 2) for v in values]

    def _sample_skewed(self, spec: DistributionSpec, count: int, min_val: float, max_val: float) -> np.ndarray:
        """Sample from skewed distribution, scaled to fit [min_val, max_val]."""
        a = float(spec.params.get("skewness", 5.0))
        if spec.type == DistributionType.SKEWED_LEFT:
            a = -a

        # Generate raw skewnorm values
        raw = stats.skewnorm.rvs(a, size=count, random_state=self.rng)

        # Scale to [0, 1] using the distribution's approximate quantiles
        lo = stats.skewnorm.ppf(0.001, a)
        hi = stats.skewnorm.ppf(0.999, a)
        normalized = (raw - lo) / (hi - lo) if hi != lo else np.full(count, 0.5)
        normalized = np.clip(normalized, 0, 1)

        # Map to field range
        return min_val + normalized * (max_val - min_val)

    def generate_categorical(self, field: FieldDefinition, count: int) -> list[str]:
        """Generate categorical values with specified weight distribution."""
        if not field.enum_values:
            return [""] * count

        spec = field.distribution
        if spec and spec.type == DistributionType.CATEGORICAL_WEIGHTED:
            weights = spec.params.get("weights", [])
            if isinstance(weights, list) and len(weights) == len(field.enum_values):
                total = sum(weights)
                probs = [w / total for w in weights]
            else:
                probs = [1.0 / len(field.enum_values)] * len(field.enum_values)
        else:
            probs = [1.0 / len(field.enum_values)] * len(field.enum_values)

        indices = self.rng.choice(len(field.enum_values), size=count, p=probs)
        return [field.enum_values[i] for i in indices]

    def generate_dates(self, field: FieldDefinition, count: int) -> list[str]:
        """Generate date values following the specified distribution within range."""
        spec = field.distribution

        start_date = date(2020, 1, 1)
        end_date = date(2026, 1, 1)
        total_days = (end_date - start_date).days

        if spec and spec.type == DistributionType.NORMAL:
            mean_day = spec.params.get("mean", total_days / 2)
            std_day = spec.params.get("std", total_days / 6)
            offsets = self.rng.normal(float(mean_day), float(std_day), size=count)
        elif spec and spec.type == DistributionType.EXPONENTIAL:
            lam = spec.params.get("lambda", 1.0 / (total_days / 3))
            offsets = self.rng.exponential(1.0 / float(lam), size=count)
        else:
            offsets = self.rng.uniform(0, total_days, size=count)

        offsets = np.clip(offsets, 0, total_days).astype(int)
        dates = [(start_date + timedelta(days=int(d))).isoformat() for d in offsets]

        if field.type == "datetime":
            hours = self.rng.integers(0, 24, size=count)
            minutes = self.rng.integers(0, 60, size=count)
            dates = [f"{d}T{h:02d}:{m:02d}:00Z" for d, h, m in zip(dates, hours, minutes)]

        return dates

    def _sample_distribution(self, spec: DistributionSpec, count: int) -> np.ndarray:
        """Sample from the specified distribution type."""
        params = spec.params

        if spec.type == DistributionType.NORMAL:
            mean = float(params.get("mean", 0.0))
            std = float(params.get("std", 1.0))
            return self.rng.normal(mean, std, size=count)

        elif spec.type == DistributionType.UNIFORM:
            low = float(params.get("low", 0.0))
            high = float(params.get("high", 1.0))
            return self.rng.uniform(low, high, size=count)

        elif spec.type == DistributionType.EXPONENTIAL:
            lam = float(params.get("lambda", 1.0))
            return self.rng.exponential(1.0 / lam, size=count)

        elif spec.type == DistributionType.LOG_NORMAL:
            mu = float(params.get("mu", 0.0))
            sigma = float(params.get("sigma", 1.0))
            return self.rng.lognormal(mu, sigma, size=count)

        elif spec.type == DistributionType.SKEWED_LEFT:
            a = float(params.get("skewness", 5.0))
            return stats.skewnorm.rvs(-a, size=count, random_state=self.rng)

        elif spec.type == DistributionType.SKEWED_RIGHT:
            a = float(params.get("skewness", 5.0))
            return stats.skewnorm.rvs(a, size=count, random_state=self.rng)

        else:
            return self.rng.normal(0, 1, size=count)

    def _generate_default(self, field: FieldDefinition, count: int) -> list:
        """Fallback generation when no distribution is specified."""
        if field.type == "integer":
            low = int(field.min_value) if field.min_value is not None else 1
            high = int(field.max_value) if field.max_value is not None else 1000
            return self.rng.integers(low, high + 1, size=count).tolist()
        elif field.type == "float":
            low = field.min_value if field.min_value is not None else 0.0
            high = field.max_value if field.max_value is not None else 1000.0
            return [round(float(v), 2) for v in self.rng.uniform(low, high, size=count)]
        elif field.enum_values:
            indices = self.rng.integers(0, len(field.enum_values), size=count)
            return [field.enum_values[i] for i in indices]
        elif field.type == "boolean":
            return [bool(v) for v in self.rng.integers(0, 2, size=count)]
        else:
            return [None] * count

import logging
import math
from datetime import date, timedelta

import numpy as np
from scipy import stats

from seed_data.schema.models import DistributionSpec, DistributionType, FieldDefinition

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation for LLM-supplied distribution parameters
#
# `prompts/distribution_inference.j2` asks the model for the numeric parameters of
# each field's distribution — weights, `lambda`, `std`, `sigma` — and whatever comes
# back was fed straight to numpy/scipy. Nothing constrained the values, so a
# plausible-looking response could stop the run outright:
#
#   {"weights": [0, 0, 0]}  → ZeroDivisionError normalizing by the sum
#   a negative weight       → ValueError from rng.choice(p=...)
#   {"lambda": 0}           → ZeroDivisionError computing the 1/lambda scale
#
# These substitute the default the caller would have used had the model omitted the
# parameter. A bad parameter is a modelling mistake, not a user error: falling back
# and saying so beats aborting a generation run that is otherwise fine.
# ---------------------------------------------------------------------------


def normalized_weights(weights, expected: int) -> list[float] | None:
    """Turn model-supplied categorical weights into probabilities.

    Args:
        weights: the raw ``params["weights"]`` value.
        expected: how many categories the field has.

    Returns:
        Probabilities summing to 1.0, or ``None`` when the weights are unusable and
        the caller should fall back to a uniform distribution.
    """
    if not isinstance(weights, list) or len(weights) != expected:
        return None

    # `DistributionSpec.params` is typed `dict[str, float | list[float]]`, so
    # pydantic has already rejected non-numeric elements; what it lets through is
    # zero, negative, and non-finite.
    numeric = [float(w) for w in weights]
    if any(not math.isfinite(w) or w < 0 for w in numeric):
        logger.warning("Categorical weights %s are negative or non-finite — using uniform weights", numeric)
        return None

    total = sum(numeric)
    if total <= 0:
        logger.warning("Categorical weights sum to %s — using uniform weights", total)
        return None
    return [w / total for w in numeric]


def scalar_param(params: dict, name: str, default: float) -> float:
    """Read any numeric distribution parameter, falling back to ``default``.

    The unsigned counterpart of :func:`positive_param`, for the parameters that may
    legitimately be zero or negative (``mean``, ``mu``, ``low``, ``high``,
    ``skewness``). Those went straight into ``float()``, which raises ``TypeError``
    on the list values ``DistributionSpec.params`` is explicitly typed to allow
    (``{"mean": [50.0]}``) — killing the whole generation run, which is the failure
    ``positive_param`` was introduced to prevent for its own subset.
    """
    raw = params.get(name, default)
    if isinstance(raw, (list, tuple)):
        # A scalar arriving as a one-element list is the common LLM shape; take it.
        raw = raw[0] if len(raw) == 1 else default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("Distribution parameter %s=%r is not a number — using %s", name, raw, default)
        return float(default)
    if not math.isfinite(value):
        logger.warning("Distribution parameter %s=%s is not finite — using %s", name, value, default)
        return float(default)
    return value


def positive_param(params: dict, name: str, default: float) -> float:
    """Read a strictly-positive distribution parameter, falling back to ``default``.

    Used for the parameters that are divided by, or that scipy/numpy reject at zero
    or below (``lambda``, ``std``, ``sigma``).
    """
    raw = params.get(name, default)
    if isinstance(raw, (list, tuple)):
        # The same one-element-list unwrap as `scalar_param`: `params` is typed
        # `float | list[float]`, and a response like {"mean":[2000.0],"std":[300.0]}
        # previously had `mean` honoured while `std` silently fell back to 1.0 —
        # producing a near-constant column, which the evaluator (sharing this
        # helper) then scored as conforming.
        raw = raw[0] if len(raw) == 1 else default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("Distribution parameter %s=%r is not a number — using %s", name, raw, default)
        return float(default)
    if not math.isfinite(value) or value <= 0:
        logger.warning("Distribution parameter %s=%s must be > 0 — using %s", name, value, default)
        return float(default)
    return value


class DistributionGenerator:
    """Generates column values according to specified statistical distributions."""

    def __init__(self, seed: int | None = None):
        self.rng = np.random.default_rng(seed)

    def generate_field_values(self, field: FieldDefinition, count: int) -> list:
        """Generate values for a field based on its distribution spec and constraints."""
        if field.distribution is None:
            return self._generate_default(field, count)

        # `enum_values` is tested before the numeric types, not after: an enum field
        # is categorical whatever its underlying JSON type, and
        # `prompts/distribution_inference.j2` asks the model for
        # `categorical_weighted` on every enum field. Numeric-first, an integer enum
        # fell through to `generate_numeric`, whose `_sample_distribution` has no
        # CATEGORICAL_WEIGHTED branch — so it drew from a standard normal and
        # `np.clip` pinned ~92% of rows to `min_value`, ignoring both the allowed
        # values and their weights.
        if field.enum_values:
            return self.generate_categorical(field, count)
        elif field.type in ("integer", "float"):
            return self.generate_numeric(field, count)
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
        a = scalar_param(spec.params, "skewness", 5.0)
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

    @staticmethod
    def _coerce_enum(field: FieldDefinition, value: str):
        """Cast an enum member back to the JSON type the source schema declared.

        ``FieldDefinition.enum_values`` is ``list[str]`` for the extraction model's
        benefit, so a schema's ``enum: [1, 2, 3]`` is stored as ``["1", "2", "3"]``
        and ``enum_base_type`` remembers the real type. Without casting here, an
        integer enum column exports Python strings, which then fail
        ``validator._check_type`` on every row.
        """
        base = field.enum_base_type
        if base is None:
            return value
        try:
            if base == "integer":
                return int(value)
            if base == "number":
                return float(value)
            if base == "boolean":
                return value.strip().lower() in ("true", "1")
        except (TypeError, ValueError):
            # A member that does not parse as its declared type is a schema defect,
            # not a generation one; the string still round-trips to the validator,
            # which reports it against the declared type rather than crashing here.
            return value
        return value

    def generate_categorical(self, field: FieldDefinition, count: int) -> list:
        """Generate categorical values with specified weight distribution."""
        if not field.enum_values:
            return [""] * count

        spec = field.distribution
        uniform = [1.0 / len(field.enum_values)] * len(field.enum_values)
        if spec and spec.type == DistributionType.CATEGORICAL_WEIGHTED:
            # `normalized_weights` rather than `w / sum(weights)`: the weights come
            # from the LLM, and all-zero weights divided by zero while a negative
            # weight was rejected downstream by `rng.choice(p=...)`.
            probs = normalized_weights(spec.params.get("weights", []), len(field.enum_values)) or uniform
        else:
            probs = uniform

        indices = self.rng.choice(len(field.enum_values), size=count, p=probs)
        return [self._coerce_enum(field, field.enum_values[i]) for i in indices]

    def generate_dates(self, field: FieldDefinition, count: int) -> list[str]:
        """Generate date values following the specified distribution within range."""
        spec = field.distribution

        start_date = date(2020, 1, 1)
        end_date = date(2026, 1, 1)
        total_days = (end_date - start_date).days

        if spec and spec.type == DistributionType.NORMAL:
            mean_day = scalar_param(spec.params, "mean", total_days / 2)
            std_day = positive_param(spec.params, "std", total_days / 6)
            offsets = self.rng.normal(mean_day, std_day, size=count)
        elif spec and spec.type == DistributionType.EXPONENTIAL:
            # `lambda` is a divisor and comes from the LLM: at 0 this raised
            # ZeroDivisionError, taking the whole run down.
            lam = positive_param(spec.params, "lambda", 1.0 / (total_days / 3))
            offsets = self.rng.exponential(1.0 / lam, size=count)
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
            mean = scalar_param(params, "mean", 0.0)
            std = positive_param(params, "std", 1.0)
            return self.rng.normal(mean, std, size=count)

        elif spec.type == DistributionType.UNIFORM:
            low = scalar_param(params, "low", 0.0)
            high = scalar_param(params, "high", 1.0)
            # numpy tolerates low > high but returns values outside [low, high];
            # ordering them matches what the schema plainly means.
            return self.rng.uniform(min(low, high), max(low, high), size=count)

        elif spec.type == DistributionType.EXPONENTIAL:
            lam = positive_param(params, "lambda", 1.0)
            return self.rng.exponential(1.0 / lam, size=count)

        elif spec.type == DistributionType.LOG_NORMAL:
            mu = scalar_param(params, "mu", 0.0)
            sigma = positive_param(params, "sigma", 1.0)
            return self.rng.lognormal(mu, sigma, size=count)

        elif spec.type == DistributionType.SKEWED_LEFT:
            a = scalar_param(params, "skewness", 5.0)
            return stats.skewnorm.rvs(-a, size=count, random_state=self.rng)

        elif spec.type == DistributionType.SKEWED_RIGHT:
            a = scalar_param(params, "skewness", 5.0)
            return stats.skewnorm.rvs(a, size=count, random_state=self.rng)

        else:
            return self.rng.normal(0, 1, size=count)

    def _generate_default(self, field: FieldDefinition, count: int) -> list:
        """Fallback generation when no distribution is specified."""
        # Enum first, for the same reason as in `generate_field_values`: an integer
        # enum reaching the numeric branch was drawn from `1..1000`, so every row was
        # an enum_violation that the corrector then rewrote with `random.choice` —
        # putting Python strings into an integer column.
        if field.enum_values:
            indices = self.rng.integers(0, len(field.enum_values), size=count)
            return [self._coerce_enum(field, field.enum_values[i]) for i in indices]
        elif field.type == "integer":
            low = int(field.min_value) if field.min_value is not None else 1
            high = int(field.max_value) if field.max_value is not None else 1000
            return self.rng.integers(low, high + 1, size=count).tolist()
        elif field.type == "float":
            low = field.min_value if field.min_value is not None else 0.0
            high = field.max_value if field.max_value is not None else 1000.0
            return [round(float(v), 2) for v in self.rng.uniform(low, high, size=count)]
        elif field.type == "boolean":
            return [bool(v) for v in self.rng.integers(0, 2, size=count)]
        else:
            return [None] * count

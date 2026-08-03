"""Shared configuration for the structured-generation and ingest engines.

Ported from seed-tabular's ``models/config.py``. The model *registry* (short key
→ model id) lives in :data:`seed_data.MODELS`; this module keeps the
structured-generation defaults (a default model id, token budget, Bedrock client
config, per-agent temperatures, and quality thresholds).

The default model id here is resolved through the shared ``MODELS`` registry so
the two stay in sync; callers that want a different model pass a ``models`` /
``model`` argument down from the ``Generator`` facade.
"""

from botocore.config import Config as BotoConfig

from seed_data import MODELS

# Default model for structured generation / ingest agents. Nova 2 Lite handles
# document + image blocks and is fast/cheap for the tabular pipeline. Resolved
# through the shared MODELS registry so the id stays in one place.
_DEFAULT_MODEL_KEY = "nova2-lite"
MODEL_ID = MODELS[_DEFAULT_MODEL_KEY]["model_id"]
MAX_TOKENS = MODELS[_DEFAULT_MODEL_KEY]["max_tokens"]

# Bedrock client config: long read timeout for large generations + bounded retries.
BEDROCK_READ_TIMEOUT = 300  # seconds
BEDROCK_CLIENT_CONFIG = BotoConfig(
    read_timeout=BEDROCK_READ_TIMEOUT,
    retries={"max_attempts": 3},
)

# Per-agent sampling temperatures.
TEMPERATURE_SCHEMA_INFERENCE = 0.3
TEMPERATURE_ORCHESTRATOR = 0.3
TEMPERATURE_SAMPLE_GENERATION = 0.7
TEMPERATURE_BULK_GENERATION = 0.8
TEMPERATURE_CRITIQUE = 0.3
TEMPERATURE_DISTRIBUTION_INFERENCE = 0.3

# Quality gate thresholds for the structured-generation retry loop.
#
# `completeness` is row count as a fraction of the requested target. Without it
# the gate scored only the *shape* of whatever came back, so a run that delivered
# a quarter of the requested rows still reported "Quality PASSED" — the few rows
# it did produce were perfectly diverse and faithful. Set below 1.0 because the
# LLM routinely returns a few rows under target and an exact-count demand would
# burn every retry on a dataset that is fine; 0.75 is low enough to tolerate that
# drift and high enough to catch a genuine collapse.
#
# Every consumer iterates this dict, so a new dimension here must also be
# computed at each evaluation site (structured/pipeline.py, structured/loop.py) —
# an absent key reads as 0.0 and would fail the gate on every attempt.
QUALITY_THRESHOLDS = {
    "diversity": 0.5,
    "fidelity": 0.6,
    "coverage": 0.4,
    "structural": 0.7,
    "completeness": 0.75,
}
MAX_GENERATION_ATTEMPTS = 3


def completeness_score(row_count: int, target_count: int) -> float:
    """Row count as a fraction of target, clamped to ``[0.0, 1.0]``.

    Lives beside :data:`QUALITY_THRESHOLDS` so the two evaluation sites that gate
    on ``completeness`` score it identically, without either engine module having
    to import the other.

    Clamped above 1.0 so overshooting cannot inflate a mean of the quality
    dimensions and mask a genuinely low score elsewhere. A non-positive target is
    treated as fully complete: there is no shortfall to measure, and scoring it
    0.0 would deadlock the retry loop on a gate that can never be satisfied.
    """
    if target_count <= 0:
        return 1.0
    return min(row_count / target_count, 1.0)

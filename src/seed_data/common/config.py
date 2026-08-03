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
QUALITY_THRESHOLDS = {
    "diversity": 0.5,
    "fidelity": 0.6,
    "coverage": 0.4,
    "structural": 0.7,
}
MAX_GENERATION_ATTEMPTS = 3

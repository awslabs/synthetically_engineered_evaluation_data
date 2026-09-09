"""seed_data — AI-powered synthetic document generation pipeline.

Public API (lazy-loaded): ``Generator``, ``Schema``, ``ModelConfig``,
``GeneratedDoc``, ``BatchResult``. See ``seed_data.api.Generator``.
"""

# Re-exported from a leaf module so internal consumers can import the registry
# without importing the package root. `seed_data.MODELS` stays the public name.
from seed_data.model_registry import MODELS  # noqa: F401

# Public API. Exposed lazily so `import seed_data` stays light — the heavy
# imports (strands, boto3) only load when you touch the API.
__all__ = [
    "Generator",
    "Schema",
    "ModelConfig",
    "GeneratedDoc",
    "BatchResult",
    "StructuredResult",
    "InferredSchema",
    "MODELS",
]


def __getattr__(name):
    if name in ("Generator", "BatchResult", "StructuredResult"):
        from seed_data.api import BatchResult, Generator, StructuredResult
        return {
            "Generator": Generator,
            "BatchResult": BatchResult,
            "StructuredResult": StructuredResult,
        }[name]
    if name == "Schema":
        from seed_data.schema import Schema
        return Schema
    if name == "InferredSchema":
        from seed_data.schema.models import InferredSchema
        return InferredSchema
    if name == "ModelConfig":
        from seed_data.stages.base import ModelConfig
        return ModelConfig
    if name == "GeneratedDoc":
        from seed_data.stages.pipeline import GeneratedDoc
        return GeneratedDoc
    raise AttributeError(f"module 'seed_data' has no attribute {name!r}")

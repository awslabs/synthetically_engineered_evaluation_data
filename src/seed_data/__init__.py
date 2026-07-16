"""seed_data — AI-powered synthetic document generation pipeline.

Public API (lazy-loaded): ``Generator``, ``Schema``, ``ModelConfig``,
``GeneratedDoc``, ``BatchResult``. See ``seed_data.api.Generator``.
"""

MODELS = {
    "haiku": {"model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "max_tokens": 63999},
    "sonnet": {"model_id": "us.anthropic.claude-sonnet-4-6", "max_tokens": 63999},
    "opus": {"model_id": "us.anthropic.claude-opus-4-6-v1", "max_tokens": 63999},
    "nova-pro": {"model_id": "us.amazon.nova-pro-v1:0", "max_tokens": 16383},
    "nova-lite": {"model_id": "us.amazon.nova-lite-v1:0", "max_tokens": 16383},
    "nova2-lite": {"model_id": "us.amazon.nova-2-lite-v1:0", "max_tokens": 63999},
    "nova2-pro": {"model_id": "us.amazon.nova-pro-v2:0", "max_tokens": 63999},
    "nova-premier": {"model_id": "us.amazon.nova-premier-v1:0", "max_tokens": 16383},
    "deepseek-v3": {"model_id": "deepseek.v3.2", "max_tokens": 16384, "streaming": False},
    "qwen3-vl": {"model_id": "qwen.qwen3-vl-235b-a22b", "max_tokens": 32767, "streaming": False},
    "qwen3-coder": {"model_id": "qwen.qwen3-coder-next", "max_tokens": 32767, "streaming": False},
    "qwen3-coder-480b": {"model_id": "qwen.qwen3-coder-480b-a35b-v1:0", "max_tokens": 32767, "streaming": False},
    "qwen3-80b": {"model_id": "qwen.qwen3-next-80b-a3b", "max_tokens": 32767, "streaming": False},
    "gpt-oss": {"model_id": "openai.gpt-oss-120b-1:0", "max_tokens": 16383, "streaming": False},
    "gpt-oss-20b": {"model_id": "openai.gpt-oss-20b-1:0", "max_tokens": 16383, "streaming": False},
    "gpt-oss-sg": {"model_id": "openai.gpt-oss-safeguard-120b", "max_tokens": 16383, "streaming": False},
    "gpt-oss-sg-20b": {"model_id": "openai.gpt-oss-safeguard-20b", "max_tokens": 16383, "streaming": False},
    "nemotron": {"model_id": "nvidia.nemotron-nano-12b-v2", "max_tokens": 16383, "streaming": False},
    "nemotron-super": {"model_id": "nvidia.nemotron-super-3-120b", "max_tokens": 16383, "streaming": False},
    "nemotron-nano-30b": {"model_id": "nvidia.nemotron-nano-3-30b", "max_tokens": 16383, "streaming": False},
}

# Public API. Exposed lazily so `import seed_data` stays light — the heavy
# imports (strands, boto3) only load when you touch the API.
__all__ = [
    "Generator",
    "Schema",
    "ModelConfig",
    "GeneratedDoc",
    "BatchResult",
    "MODELS",
]


def __getattr__(name):
    if name in ("Generator", "BatchResult"):
        from seed_data.api import Generator, BatchResult
        return {"Generator": Generator, "BatchResult": BatchResult}[name]
    if name == "Schema":
        from seed_data.schema import Schema
        return Schema
    if name == "ModelConfig":
        from seed_data.stages.base import ModelConfig
        return ModelConfig
    if name == "GeneratedDoc":
        from seed_data.stages.pipeline import GeneratedDoc
        return GeneratedDoc
    raise AttributeError(f"module 'seed_data' has no attribute {name!r}")

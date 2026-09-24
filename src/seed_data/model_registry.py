"""Bedrock model registry: short key → model id and token budget.

Deliberately a leaf module with no imports of its own — not even from the
``seed_data`` package root. ``seed_data.MODELS`` re-exports this, so the public
name is unchanged, but modules that need the registry (``common.config``,
``utils``, ``cli``) can import it here instead of doing ``from seed_data import
MODELS``. That import reached back into the partially-initialised package root
and only worked because ``MODELS`` happened to be defined before the lazy
``__getattr__`` that pulls in the API surface: add one eager import above it and
``common.config`` breaks with a circular ImportError. Importing the leaf directly
cannot break that way.
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

__all__ = ["MODELS"]

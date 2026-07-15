"""seed_data — Synthetically Engineered Evaluation Data.

AI-powered synthetic document generation pipeline. In addition to the CLI
(``seed-data`` / ``python -m seed_data``), the batch and packet pipelines are
available as a stable programmatic API for embedding in other tools:

    import seed_data

    manifest = seed_data.run_batch(
        schema_dir="src/seed_data/schemas/fcc-invoice",
        count=5,
        brief="Local TV stations in the Pacific Northwest",
        output_dir="./output",
    )

    result = seed_data.generate_packet(config, output_dir="./output")

These names are re-exported lazily (PEP 562 ``__getattr__``): importing
``seed_data`` — or ``from seed_data import MODELS`` — stays lightweight and does
NOT import the Strands/Bedrock stack; that happens only on first access to
``run_batch`` / ``generate_packet``.
"""

from typing import TYPE_CHECKING, Any

__all__ = ["MODELS", "run_batch", "generate_packet"]

if TYPE_CHECKING:  # import-time only for type checkers, not at runtime
    from seed_data.batch import run_batch
    from seed_data.packet import generate_packet


def __getattr__(name: str) -> Any:
    """Lazily resolve the public programmatic API (PEP 562).

    Keeps ``import seed_data`` cheap while exposing the pipeline entry points as
    documented top-level attributes.
    """
    if name == "run_batch":
        from seed_data.batch import run_batch

        return run_batch
    if name == "generate_packet":
        from seed_data.packet import generate_packet

        return generate_packet
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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

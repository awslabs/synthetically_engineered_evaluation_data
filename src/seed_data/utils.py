"""Shared utilities for the orchestrator."""
import glob
import hashlib
import json
import os
import shutil

from strands.models import BedrockModel
from botocore.config import Config

from seed_data import MODELS
from seed_data.session import get_boto_session

# GitHub location of the schema library, for docs and CLI messaging.
SCHEMA_LIBRARY_URL = (
    "https://github.com/awslabs/synthetically_engineered_evaluation_data"
    "/tree/main/src/seed_data/schemas"
)


def bundled_schemas_dir() -> str:
    """Path to the schemas/ directory shipped inside the installed package."""
    return os.path.join(os.path.dirname(__file__), "schemas")


def clone_schema_library(dest: str) -> str:
    """Copy the bundled schema library out to a local, editable directory.

    Users install seed-data from PyPI, so the built-in schemas live inside
    site-packages where they cannot be edited comfortably. This copies the whole
    library to ``dest`` so users can tweak schemas and point --schema-dir at them.

    Returns the path the schemas were copied to. Raises if ``dest`` already exists.
    """
    src = bundled_schemas_dir()
    if not os.path.isdir(src):
        raise FileNotFoundError(f"Bundled schema library not found at {src}")
    if os.path.exists(dest):
        raise FileExistsError(
            f"Destination already exists: {dest}\n"
            f"Choose a different path or remove it first."
        )
    # ignore samples/ (local-only reference PDFs, gitignored) and caches
    shutil.copytree(
        src, dest,
        ignore=shutil.ignore_patterns("samples", "__pycache__", ".DS_Store"),
    )
    return dest

# Shared boto client config for adaptive retries and long timeouts
BOTO_CONFIG = Config(
    retries={"total_max_attempts": 10, "mode": "adaptive"},
    read_timeout=600,
    connect_timeout=10,
)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def make_model(model_key: str, thinking_budget: int = 0, role: str = "",
               session=None) -> BedrockModel:
    """Create a BedrockModel from a MODELS key or raw model ID.

    ``model_key`` may be a key in ``MODELS`` or a raw Bedrock model ID (for region
    portability, e.g. an EU/GovCloud inference profile). ``session`` is an optional
    boto3 Session for in-process use (containers, Lambda, AgentCore); if omitted,
    one is resolved from the environment via ``get_boto_session``.
    """
    import warnings

    entry = MODELS.get(model_key)
    if entry:
        model_id = entry["model_id"]
        max_tokens = entry["max_tokens"]
    else:
        model_id = model_key
        max_tokens = 8192

    # Warn if Anthropic models are used for generation (not critique)
    if "anthropic" in model_id and role in ("data", "doc"):
        warnings.warn(
            f"⚠ Anthropic model '{model_key}' selected for {role} generation. "
            "Ensure your use of this model for synthetic data generation complies "
            "with Anthropic's Acceptable Use Policy and your organization's terms of service.",
            stacklevel=2,
        )

    kwargs = {
        "model_id": model_id,
        "boto_session": session or get_boto_session(),
        "boto_client_config": BOTO_CONFIG,
        "max_tokens": max_tokens,
    }

    # Some models don't support streaming with tool use
    if entry and entry.get("streaming") is False:
        kwargs["streaming"] = False

    if thinking_budget > 0 and "anthropic" in model_id:
        kwargs["additional_request_fields"] = {
            "thinking": {"type": "enabled", "budget_tokens": thinking_budget}
        }
    return BedrockModel(**kwargs)


def load_schema_dir(schema_dir: str) -> tuple[dict, str, list[str]]:
    """Load schema.json, *.md steering docs, and sample PDFs from a directory.

    Returns:
        (schema_dict, steering_text, sample_pdf_paths)
    """
    json_files = glob.glob(os.path.join(schema_dir, "*.json"))
    if len(json_files) != 1:
        raise FileNotFoundError(
            f"Expected exactly 1 JSON schema in {schema_dir}, found {len(json_files)}"
        )
    with open(json_files[0]) as f:
        schema = json.load(f)

    md_files = sorted(glob.glob(os.path.join(schema_dir, "*.md")))
    steering_parts = []
    for md in md_files:
        with open(md) as f:
            steering_parts.append(f.read())

    samples_dir = os.path.join(schema_dir, "samples")
    sample_pdfs = sorted(glob.glob(os.path.join(samples_dir, "*.pdf"))) if os.path.isdir(samples_dir) else []

    return schema, "\n\n---\n\n".join(steering_parts), sample_pdfs

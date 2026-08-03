"""Unified Schema Extraction Agent.

A single agent that handles all input modalities (document, text, schema,
example data, ERD) using tools, and always outputs an InferredSchema.
Replaces the previous separate analysis + inference two-step process.

For document and image inputs, the raw bytes are passed directly in the user
message content (not via tool results) because Nova models do not support
document/image blocks inside toolResult messages.
"""

import logging
import os
from pathlib import Path

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from seed_data.common.config import BEDROCK_CLIENT_CONFIG, MAX_TOKENS, MODEL_ID, TEMPERATURE_SCHEMA_INFERENCE
from seed_data.schema.flat import flat_inferred_schema, to_canonical
from seed_data import prompts
from seed_data.ingest.tools import (
    analyze_example_data,
    apply_schema_overrides,
    parse_erd,
    parse_schema_definition,
    SUPPORTED_DOCUMENT_FORMATS,
)

logger = logging.getLogger(__name__)

SCHEMA_EXTRACTION_PROMPT = prompts.render("schema_extraction")

_SCHEMA_TOOLS = [
    parse_schema_definition,
    analyze_example_data,
    parse_erd,
    apply_schema_overrides,
]


def _build_schema_agent() -> Agent:
    """Create the schema extraction agent with all tools."""
    model = BedrockModel(
        model_id=MODEL_ID,
        temperature=TEMPERATURE_SCHEMA_INFERENCE,
        max_tokens=MAX_TOKENS,
        boto_client_config=BEDROCK_CLIENT_CONFIG,
    )
    return Agent(
        model=model,
        system_prompt=SCHEMA_EXTRACTION_PROMPT,
        tools=_SCHEMA_TOOLS,
        callback_handler=None,
    )


@tool
def schema_extraction_agent(
    file_path: str = "",
    text_description: str = "",
    schema_input: str = "",
    schema_format: str = "",
    erd_input: str = "",
    erd_format: str = "",
    override_instructions: str = "",
) -> str:
    """Extract a complete InferredSchema from any input type.

    Accepts one or more input sources and produces a unified schema.
    The agent uses tools internally to read/parse inputs, then synthesizes
    a final InferredSchema.

    Args:
        file_path: Path to a document or example data file.
        text_description: Free-text description of the desired dataset.
        schema_input: Raw JSON Schema or SQL DDL text.
        schema_format: Format of schema_input: 'json_schema' or 'sql_ddl'.
        erd_input: ERD definition text (DBML, PlantUML, Mermaid) or image path.
        erd_format: ERD format: 'dbml', 'plantuml', 'mermaid', or 'image'.
        override_instructions: Optional modifications to apply to the extracted schema.

    Returns:
        JSON InferredSchema with all entities, fields, and relationships.
    """
    logger.info("Schema extraction agent started")

    # Build the user prompt content. For documents and images, we embed the raw
    # bytes directly in the user message (not via tools) because Nova models
    # reject document/image blocks inside toolResult messages.
    content_blocks: list[dict] = []
    prompt_parts = ["Extract a complete InferredSchema from the following input(s):\n"]

    if file_path:
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        if ext in ("csv", "json"):
            prompt_parts.append(f"- Example data file: {file_path}")
            prompt_parts.append("  → Use the analyze_example_data tool to read and summarize it.")
        elif erd_format == "image" or ext in ("png", "jpg", "jpeg"):
            # Pass image bytes directly in user message
            if os.path.isfile(file_path):
                with open(file_path, "rb") as f:
                    image_bytes = f.read()
                media_format = "png" if ext == "png" else "jpeg"
                prompt_parts.append("- ERD image (attached below):")
                prompt_parts.append("  → Analyze this ERD image to extract entities, fields, and relationships.")
                content_blocks.append({
                    "image": {
                        "format": media_format,
                        "source": {"bytes": image_bytes},
                    }
                })
            else:
                prompt_parts.append(f"- ERD image file not found: {file_path}")
        elif ext in SUPPORTED_DOCUMENT_FORMATS:
            # Pass document bytes directly in user message
            if os.path.isfile(file_path):
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                doc_name = Path(file_path).stem
                prompt_parts.append(f"- Document (attached below, format: {ext}):")
                prompt_parts.append("  → Analyze this document to extract all data entities, fields, relationships, and constraints.")
                content_blocks.append({
                    "document": {
                        "format": ext,
                        "name": doc_name,
                        "source": {"bytes": file_bytes},
                    }
                })
            else:
                prompt_parts.append(f"- Document file not found: {file_path}")
        else:
            prompt_parts.append(f"- Unsupported file format: .{ext}")

    if text_description:
        prompt_parts.append(f"- Free-text description:\n  {text_description}")
        prompt_parts.append("  → Analyze this description to identify entities, fields, and relationships.")

    if schema_input:
        prompt_parts.append(f"- Schema definition ({schema_format or 'json_schema'}):")
        prompt_parts.append(f"  → Use parse_schema_definition with format='{schema_format or 'json_schema'}'")

    if erd_input and erd_format and erd_format != "image":
        prompt_parts.append(f"- ERD definition ({erd_format}):")
        prompt_parts.append(f"  → Use parse_erd with format='{erd_format}'")

    if override_instructions:
        prompt_parts.append(f"- Override instructions: {override_instructions}")
        prompt_parts.append("  → After extracting the base schema, use apply_schema_overrides to modify it.")

    prompt_parts.append("\nUse the appropriate tool(s) for schema/ERD text inputs, then produce the final InferredSchema.")

    # Build the final content: text prompt first, then any document/image blocks
    user_content = [{"text": "\n".join(prompt_parts)}] + content_blocks

    agent = _build_schema_agent()
    # The canonical InferredSchema is self-recursive and cannot be turned into a
    # Bedrock tool spec; the flat variant is an equivalent depth-bounded subclass.
    result = agent(user_content, structured_output_model=flat_inferred_schema())

    output = to_canonical(result.structured_output)
    entity_names = [e.entity_name for e in output.entities] if output.entities else []
    logger.info("Schema extraction agent finished — entities: %s", entity_names)

    return output.model_dump_json(indent=2)

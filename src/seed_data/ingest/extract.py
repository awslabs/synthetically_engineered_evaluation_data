"""Unified Schema Extraction Agent.

A single agent that handles all input modalities (document, text, schema,
example data, ERD) and always outputs an InferredSchema. Replaces the previous
separate analysis + inference two-step process.

Everything the caller supplies goes into the user message, not through a tool.
For documents and images that is forced: Nova models reject document/image blocks
inside toolResult messages. For schema/ERD/revision text it is the only thing that
works at all — tool arguments come from the model, and the model has never seen
text the caller passed. ``analyze_example_data`` is the one real tool, because it
reads a file from a path the prompt names.
"""

import json
import logging
import os
from pathlib import Path

from strands import Agent, tool

from seed_data.common.config import MODEL_KEY, TEMPERATURE_SCHEMA_INFERENCE
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

# The only tool that reads something the model cannot already see. The three
# parse helpers are plain functions now (see `ingest.tools`); registered, the model
# could still call them with the empty string it used to be handed, which is the
# same "invent a schema from nothing" failure by another route.
_SCHEMA_TOOLS = [analyze_example_data]


def _build_schema_agent(model: str | None = None, session=None) -> Agent:
    """Create the schema extraction agent with all tools.

    Built through ``utils.make_model`` rather than ``BedrockModel(...)`` directly:
    that factory is the only place ``boto_session`` is wired, so constructing the
    model here would silently drop a ``Generator(session=...)`` and fall back to
    ambient environment credentials.
    """
    from seed_data.utils import make_model

    return Agent(
        model=make_model(
            model or MODEL_KEY,
            role="data",
            session=session,
            temperature=TEMPERATURE_SCHEMA_INFERENCE,
        ),
        system_prompt=SCHEMA_EXTRACTION_PROMPT,
        tools=_SCHEMA_TOOLS,
        callback_handler=None,
    )


def _inline_payload(
    payload_json: str, text_key: str, default_label: str = ""
) -> tuple[str, str, str]:
    """Unpack a parse helper's payload into (label, raw_text, instructions).

    ``parse_schema_definition`` / ``parse_erd`` / ``apply_schema_overrides`` hand
    the text back with format-specific parsing instructions; rendering the prompt
    from their payload keeps those instructions in one place rather than restating
    them here.
    """
    payload = json.loads(payload_json)
    return (
        payload.get("format_label", default_label),
        payload[text_key],
        payload["instructions"],
    )


def extract_schema(
    file_path: str = "",
    text_description: str = "",
    schema_input: str = "",
    schema_format: str = "",
    erd_input: str = "",
    erd_format: str = "",
    override_instructions: str = "",
    current_schema: str = "",
    *,
    model: str | None = None,
    session=None,
) -> str:
    """Extract a complete InferredSchema from any input type.

    The implementation behind the :func:`schema_extraction_agent` tool. In-process
    callers use this directly so they can pass ``model`` / ``session``, which must
    stay off the tool signature — ``@tool`` turns every parameter into something the
    orchestrating LLM is invited to fill in.

    Args:
        file_path: Path to a document or example data file.
        text_description: Free-text description of the desired dataset.
        schema_input: Raw JSON Schema or SQL DDL text.
        schema_format: Format of schema_input: 'json_schema' or 'sql_ddl'.
        erd_input: ERD definition text (DBML, PlantUML, Mermaid) or image path.
        erd_format: ERD format: 'dbml', 'plantuml', 'mermaid', or 'image'.
        override_instructions: Optional modifications to apply to the extracted schema.
        current_schema: An existing ``InferredSchema`` JSON to revise. Distinct from
            ``schema_input``, which is a *source* definition (JSON Schema / SQL DDL)
            to extract from; this is already-canonical output being amended, and
            labelling it as the former misdescribes it to the model.
        model: model key for the extraction agent (defaults to ``MODEL_KEY``).
        session: optional boto3 Session.

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

    # The schema / ERD text goes inline. It cannot be routed through
    # parse_schema_definition / parse_erd: those take the text as a tool *argument*,
    # and only the model can supply arguments — it has never seen this text. Naming
    # the tool without the text made the model either invent a schema unrelated to
    # the input or call the tool with an empty string.
    if schema_input:
        label, text, instructions = _inline_payload(
            parse_schema_definition(schema_input, schema_format or "json_schema"),
            "schema_text",
        )
        prompt_parts.append(f"- Schema definition ({label}):")
        prompt_parts.append(f"```\n{text}\n```")
        prompt_parts.append(f"  → {instructions}")

    if erd_input and erd_format and erd_format != "image":
        label, text, instructions = _inline_payload(
            parse_erd(erd_input, erd_format), "erd_text",
        )
        prompt_parts.append(f"- ERD definition ({label}):")
        prompt_parts.append(f"```\n{text}\n```")
        prompt_parts.append(f"  → {instructions}")

    if current_schema:
        label, text, instructions = _inline_payload(
            apply_schema_overrides(current_schema, override_instructions),
            "current_schema",
            "Current InferredSchema to revise",
        )
        prompt_parts.append(f"- {label}:")
        prompt_parts.append(f"```json\n{text}\n```")
        prompt_parts.append(f"- Requested changes: {override_instructions}")
        prompt_parts.append(f"  → {instructions}")
    elif override_instructions:
        prompt_parts.append(f"- Override instructions: {override_instructions}")
        prompt_parts.append("  → After extracting the base schema, apply these modifications to it.")

    prompt_parts.append("\nProduce the final InferredSchema from the input(s) above.")

    # Build the final content: text prompt first, then any document/image blocks
    user_content = [{"text": "\n".join(prompt_parts)}] + content_blocks

    agent = _build_schema_agent(model=model, session=session)
    # The canonical InferredSchema is self-recursive and cannot be turned into a
    # Bedrock tool spec; the flat variant is an equivalent depth-bounded subclass.
    result = agent(user_content, structured_output_model=flat_inferred_schema())

    if result.structured_output is None:
        # A guardrail or content-filter refusal yields None here. Left unguarded,
        # `to_canonical(None)` raises an AttributeError from inside the converter,
        # which says nothing about what actually happened.
        raise ValueError(
            "The model returned no structured schema (likely a content-filter or "
            "guardrail refusal on the input). Try a different model or input."
        )

    output = to_canonical(result.structured_output)
    entity_names = [e.entity_name for e in output.entities] if output.entities else []
    logger.info("Schema extraction agent finished — entities: %s", entity_names)

    return output.model_dump_json(indent=2)


@tool
def schema_extraction_agent(
    file_path: str = "",
    text_description: str = "",
    schema_input: str = "",
    schema_format: str = "",
    erd_input: str = "",
    erd_format: str = "",
    override_instructions: str = "",
    current_schema: str = "",
) -> str:
    """Extract a complete InferredSchema from any input type.

    Accepts one or more input sources and produces a unified schema.

    Args:
        file_path: Path to a document or example data file.
        text_description: Free-text description of the desired dataset.
        schema_input: Raw JSON Schema or SQL DDL text.
        schema_format: Format of schema_input: 'json_schema' or 'sql_ddl'.
        erd_input: ERD definition text (DBML, PlantUML, Mermaid) or image path.
        erd_format: ERD format: 'dbml', 'plantuml', 'mermaid', or 'image'.
        override_instructions: Optional modifications to apply to the extracted schema.
        current_schema: An existing InferredSchema JSON to revise rather than extract.

    Returns:
        JSON InferredSchema with all entities, fields, and relationships.
    """
    return extract_schema(
        file_path=file_path,
        text_description=text_description,
        schema_input=schema_input,
        schema_format=schema_format,
        erd_input=erd_input,
        erd_format=erd_format,
        override_instructions=override_instructions,
        current_schema=current_schema,
    )

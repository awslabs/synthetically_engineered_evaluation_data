import logging

from strands import Agent, tool

from seed_data.common.config import MODEL_KEY, TEMPERATURE_SAMPLE_GENERATION
from seed_data.schema.models import GeneratedSamples
from seed_data import prompts

logger = logging.getLogger(__name__)

SAMPLE_GENERATION_PROMPT = prompts.render("sample_generation")


def generate_samples(
    entity_schema_definitions: str, *, model: str | None = None, session=None
) -> str:
    """Generate 3-5 diverse sample records per entity based on schema definitions.

    The implementation behind the :func:`sample_generation_agent` tool; in-process
    callers use this so they can pass ``model`` / ``session``, which must stay off
    the tool signature.

    Args:
        entity_schema_definitions: JSON string of the inferred schema definitions.
        model: model key for the agent (defaults to ``MODEL_KEY``).
        session: optional boto3 Session.

    Returns:
        JSON mapping of entity names to lists of sample records.
    """
    from seed_data.utils import make_model

    logger.info("Sample generation agent started")
    logger.debug("Sample generation input length: %d chars", len(entity_schema_definitions))

    agent = Agent(
        # Via make_model, the only place `boto_session` is wired — a direct
        # BedrockModel(...) here silently ignored `Generator(session=...)`.
        model=make_model(
            model or MODEL_KEY, role="data", session=session,
            temperature=TEMPERATURE_SAMPLE_GENERATION,
        ),
        system_prompt=SAMPLE_GENERATION_PROMPT,
        tools=[],
        callback_handler=None,
    )

    result = agent(
        f"Here are the entity schema definitions:\n\n{entity_schema_definitions}\n\n"
        "Generate 3-5 diverse, realistic sample records for each entity. "
        "Ensure all records conform to the schema constraints.",
        structured_output_model=GeneratedSamples,
    )

    output = result.structured_output
    if output is None:
        # None on a guardrail/content-filter refusal. Unguarded, `output.data`
        # raised an AttributeError naming neither the step nor the cause.
        raise ValueError(
            "Sample generation returned no structured output (likely a "
            "content-filter or guardrail refusal on the schema)."
        )
    record_summary = {entity: len(records) for entity, records in output.data.items()}
    logger.info("Sample generation agent finished — records per entity: %s", record_summary)

    return output.model_dump_json(indent=2)


@tool
def sample_generation_agent(entity_schema_definitions: str) -> str:
    """Generate 3-5 diverse sample records per entity based on schema definitions.

    Args:
        entity_schema_definitions: JSON string of the inferred schema definitions.

    Returns:
        JSON mapping of entity names to lists of sample records.
    """
    return generate_samples(entity_schema_definitions)

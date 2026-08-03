import logging

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from seed_data.common.config import MAX_TOKENS, MODEL_ID, TEMPERATURE_SAMPLE_GENERATION
from seed_data.schema.models import GeneratedSamples
from seed_data import prompts

logger = logging.getLogger(__name__)

SAMPLE_GENERATION_PROMPT = prompts.render("sample_generation")


@tool
def sample_generation_agent(entity_schema_definitions: str) -> str:
    """Generate 3-5 diverse sample records per entity based on schema definitions.

    Args:
        entity_schema_definitions: JSON string of the inferred schema definitions.

    Returns:
        JSON mapping of entity names to lists of sample records.
    """
    logger.info("Sample generation agent started")
    logger.debug("Sample generation input length: %d chars", len(entity_schema_definitions))

    model = BedrockModel(
        model_id=MODEL_ID,
        temperature=TEMPERATURE_SAMPLE_GENERATION,
        max_tokens=MAX_TOKENS,
    )

    agent = Agent(
        model=model,
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
    record_summary = {entity: len(records) for entity, records in output.data.items()}
    logger.info("Sample generation agent finished — records per entity: %s", record_summary)

    return output.model_dump_json(indent=2)

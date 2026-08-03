import logging

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from seed_data.common.config import MAX_TOKENS, MODEL_ID, TEMPERATURE_DISTRIBUTION_INFERENCE
from seed_data.schema.flat import flat_inferred_schema, to_canonical
from seed_data import prompts

logger = logging.getLogger(__name__)

DISTRIBUTION_INFERENCE_PROMPT = prompts.render("distribution_inference")


@tool
def distribution_inference_agent(schema_json: str) -> str:
    """Analyze a schema and suggest realistic statistical distributions for each field.

    Takes an InferredSchema and returns an updated version with distribution
    specifications populated on appropriate fields.

    Args:
        schema_json: JSON string of the InferredSchema to enhance with distributions.

    Returns:
        JSON InferredSchema with distribution field populated on relevant fields.
    """
    logger.info("Distribution inference agent started")

    model = BedrockModel(
        model_id=MODEL_ID,
        temperature=TEMPERATURE_DISTRIBUTION_INFERENCE,
        max_tokens=MAX_TOKENS,
    )

    agent = Agent(
        model=model,
        system_prompt=DISTRIBUTION_INFERENCE_PROMPT,
        tools=[],
        callback_handler=None,
    )

    result = agent(
        f"Here is the schema to enhance with distribution specifications:\n\n```json\n{schema_json}\n```\n\n"
        "Assign a distribution to EVERY numeric field (integer/float) and EVERY enum field. "
        "Use domain knowledge to choose realistic parameters. "
        "A field with distribution: null when it has min_value/max_value or enum_values is INVALID. "
        "Return the complete schema with all distributions populated.",
        # Depth-bounded subclass: the canonical model's self-recursive `children`
        # cannot be flattened into a Bedrock tool spec.
        structured_output_model=flat_inferred_schema(),
    )

    output = to_canonical(result.structured_output)
    dist_count = sum(
        1 for e in output.entities for f in e.fields if f.distribution is not None
    )
    logger.info("Distribution inference agent finished — %d distributions assigned", dist_count)

    return output.model_dump_json(indent=2)

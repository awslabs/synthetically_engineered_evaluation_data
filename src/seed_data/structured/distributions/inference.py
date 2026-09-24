import logging

from strands import Agent, tool

from seed_data.common.config import MODEL_KEY, TEMPERATURE_DISTRIBUTION_INFERENCE
from seed_data.schema.flat import flat_inferred_schema, to_canonical
from seed_data import prompts

logger = logging.getLogger(__name__)

DISTRIBUTION_INFERENCE_PROMPT = prompts.render("distribution_inference")


def infer_distributions(
    schema_input: str, *, model: str | None = None, session=None
) -> str:
    """Analyze a schema and suggest realistic statistical distributions for each field.

    Takes an InferredSchema and returns an updated version with distribution
    specifications populated on appropriate fields.

    The implementation behind the :func:`distribution_inference_agent` tool;
    in-process callers use this so they can pass ``model`` / ``session``, which must
    stay off the tool signature.

    Args:
        schema_input: JSON string of the InferredSchema to enhance with distributions.
        model: model key for the agent (defaults to ``MODEL_KEY``).
        session: optional boto3 Session.

    Returns:
        JSON InferredSchema with distribution field populated on relevant fields.
    """
    from seed_data.utils import make_model

    logger.info("Distribution inference agent started")

    agent = Agent(
        # Via make_model, the only place `boto_session` is wired — a direct
        # BedrockModel(...) here silently ignored `Generator(session=...)`.
        model=make_model(
            model or MODEL_KEY, role="data", session=session,
            temperature=TEMPERATURE_DISTRIBUTION_INFERENCE,
        ),
        system_prompt=DISTRIBUTION_INFERENCE_PROMPT,
        tools=[],
        callback_handler=None,
    )

    result = agent(
        f"Here is the schema to enhance with distribution specifications:\n\n```json\n{schema_input}\n```\n\n"
        "Assign a distribution to EVERY numeric field (integer/float) and EVERY enum field. "
        "Use domain knowledge to choose realistic parameters. "
        "A field with distribution: null when it has min_value/max_value or enum_values is INVALID. "
        "Return the complete schema with all distributions populated.",
        # Depth-bounded subclass: the canonical model's self-recursive `children`
        # cannot be flattened into a Bedrock tool spec.
        structured_output_model=flat_inferred_schema(),
    )

    if result.structured_output is None:
        # None on a guardrail/content-filter refusal. Unguarded, `to_canonical(None)`
        # raised an AttributeError from inside the converter.
        raise ValueError(
            "Distribution inference returned no structured output (likely a "
            "content-filter or guardrail refusal on the schema)."
        )

    output = to_canonical(result.structured_output)
    dist_count = sum(
        1 for e in output.entities for f in e.fields if f.distribution is not None
    )
    logger.info("Distribution inference agent finished — %d distributions assigned", dist_count)

    return output.model_dump_json(indent=2)


@tool
def distribution_inference_agent(schema_input: str) -> str:
    """Analyze a schema and suggest realistic statistical distributions for each field.

    The parameter is deliberately not named ``schema_json``: ``@tool`` builds a
    pydantic model from this signature, and that name shadows the deprecated
    ``BaseModel.schema_json`` attribute, so every import emitted a ``UserWarning``
    at the user. ``schema_input`` also matches the schema-revision agent's
    parameter.

    Args:
        schema_input: JSON string of the InferredSchema to enhance with distributions.

    Returns:
        JSON InferredSchema with distribution field populated on relevant fields.
    """
    return infer_distributions(schema_input)

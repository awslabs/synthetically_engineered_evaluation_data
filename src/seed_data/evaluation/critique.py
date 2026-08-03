"""LLM critique for structured (tabular) data — the cross-modality counterpart
to :mod:`seed_data.critique`.

The quantitative metrics in this package measure what can be counted: enum
coverage, constraint violations, referential integrity. They cannot tell you
that an order was dated before its customer existed, or that every street
address is "123 Main St". That judgement needs a model, which is exactly what
doc-gen's critique loop already does for PDFs. This module points the same
mechanism at tabular data.

Mirrors :func:`seed_data.critique.critique_data`: a Strands ``Agent`` with the
calculator tool and ``structured_output_model``, returning a plain dict so
callers stay decoupled from the pydantic models.
"""
from __future__ import annotations

import json
from typing import List

from pydantic import BaseModel, Field

from seed_data.schema.models import InferredSchema

# How many records per entity to put in front of the model. Critique quality
# plateaus well before the context limit, and a 10k-row dataset would blow it.
_MAX_SAMPLE_ROWS = 25


class StructuredIssue(BaseModel):
    """A single semantic problem found in generated tabular data."""

    entity: str = Field(default="", description="Entity/table the issue was found in")
    field: str = Field(default="", description="Field name, if the issue is field-specific")
    category: str = Field(
        description="One of: consistency, referential, temporal, realism, distribution, completeness"
    )
    severity: str = Field(description="One of: critical, major, minor")
    description: str = Field(description="Specific constructive feedback citing concrete values")
    fix_hint: str = Field(
        default="",
        description="Actionable suggestion, e.g. 'constrain Order.order_date to be >= Customer.created_at'",
    )


class StructuredCritiqueResult(BaseModel):
    """Structured critique of a generated tabular dataset."""

    score: int = Field(description="Quality score 1-10", ge=1, le=10)
    issues: List[StructuredIssue] = Field(default_factory=list, description="Issues found")
    summary: str = Field(description="One sentence overall assessment")


def _sample_records(data: dict[str, list[dict]]) -> tuple[dict[str, list[dict]], dict]:
    """Take a head sample of each entity's records, reporting what was elided.

    A head sample (rather than random) keeps this deterministic, which matters
    for reproducing a critique. Returns ``(sampled_data, stats)``.
    """
    sampled: dict[str, list[dict]] = {}
    total = 0
    shown = 0

    for entity_name, records in data.items():
        if not isinstance(records, list):
            continue
        total += len(records)
        head = records[:_MAX_SAMPLE_ROWS]
        shown += len(head)
        sampled[entity_name] = head

    return sampled, {
        "total_rows": total,
        "shown_rows": shown,
        "truncated": shown < total,
        "sampled": True,
    }


def critique_structured(
    data: dict[str, list[dict]] | str,
    schema: InferredSchema,
    steering: str = "",
    model: str = "haiku",
    threshold: int = 7,
    session=None,
) -> dict:
    """Critique generated structured data for semantic consistency using an LLM.

    Args:
        data: Map of entity name to list of record dicts, or a path to a JSON
            file containing that mapping.
        schema: The ``InferredSchema`` the data was generated from.
        steering: Extra reviewer instructions (domain rules, known pitfalls).
        model: Model alias from ``seed_data.MODELS`` (default ``"haiku"``).
        threshold: Minimum score to count as accepted.
        session: Optional boto3 Session for in-process use (containers, Lambda,
            AgentCore); mirrors ``critique_document`` so both critique entry
            points share one calling convention.

    Returns:
        Dict with ``score``, ``verdict`` (``"accepted"``/``"rejected"``),
        ``issues`` (list of dicts) and ``summary``. On any LLM/transport failure
        the dict carries ``verdict="error"``, ``score=0`` and an ``error`` key —
        callers treat critique as advisory and must not crash a finished
        generation run because the reviewer was unreachable.

    Raises:
        ImportError: If the ``strands`` dependency is unavailable.
        ValueError: If ``schema`` has no entities.
    """
    # Imported lazily: `strands` is a base dependency but this module is reachable
    # from `seed_data.evaluation`, which callers import for pure-pandas metrics.
    try:
        from strands import Agent
    except ImportError as e:  # pragma: no cover - base dep, defensive only
        raise ImportError(
            "critique_structured() needs the 'strands-agents' package. "
            "Install it with: pip install seed-data"
        ) from e

    from seed_data import prompts
    from seed_data.utils import make_model

    if not schema.entities:
        raise ValueError("Cannot critique against a schema with no entities.")

    if isinstance(data, str):
        with open(data) as f:
            data = json.load(f)

    sampled, stats = _sample_records(data)

    relationships = [
        f"{rel.source_entity}.{rel.source_field} -> "
        f"{rel.target_entity}.{rel.target_field} ({rel.cardinality.value})"
        for entity in schema.entities
        for rel in entity.structured_relationships
    ]

    system_prompt = prompts.render(
        "structured_critic",
        schema_json=schema.model_dump_json(indent=2),
        data_json=json.dumps(sampled, indent=2, default=str),
        relationships=relationships,
        steering=steering,
        **stats,
    )

    try:
        from strands_tools.calculator import calculator

        agent = Agent(
            model=make_model(model, session=session),
            system_prompt=system_prompt,
            tools=[calculator],
        )
        result = agent(
            "Review this dataset for semantic consistency. Use the calculator tool to "
            "verify any arithmetic relationship between fields before reporting it.",
            structured_output_model=StructuredCritiqueResult,
        )
        critique = result.structured_output
    except Exception as e:
        return {
            "score": 0,
            "verdict": "error",
            "issues": [],
            "summary": f"Critique unavailable: {e}",
            "error": str(e),
        }

    verdict = "accepted" if critique.score >= threshold else "rejected"

    return {
        "score": critique.score,
        "verdict": verdict,
        "issues": [issue.model_dump() for issue in critique.issues],
        "summary": critique.summary,
    }


__all__ = [
    "StructuredCritiqueResult",
    "StructuredIssue",
    "critique_structured",
]

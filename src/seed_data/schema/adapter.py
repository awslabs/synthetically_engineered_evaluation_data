"""Adapt an :class:`InferredSchema` into the triple the doc-gen pipeline consumes.

The document pipeline accepts ``resolved: tuple[dict, str, list[str]]`` — a JSON
Schema dict, generation-guidance prose, and reference sample PDF paths. That is
exactly what :func:`seed_data.utils.load_schema_dir` returns for an on-disk
schema dir, and what :meth:`seed_data.schema.legacy.Schema.resolve` returns for
an in-code schema.

This module adds the third source: a canonical ``InferredSchema`` (produced by
``ingest``, or lifted from a schema dir). Converting here means the existing
pipeline stays untouched — it never learns about ``InferredSchema`` at all.

Distributions are deliberately dropped: they steer *statistical* generation for
tabular output and have no meaning for document rendering. Everything else
(types, constraints, enums, nullability, nesting) round-trips through
:func:`seed_data.schema.io.to_json_schema`.
"""
from __future__ import annotations

from seed_data.schema.models import EntitySchema, InferredSchema


def _select_entity(schema: InferredSchema, entity_name: str | None) -> EntitySchema:
    """Pick the entity to render as a document type.

    A document type is a single entity, so a multi-entity schema (typical of
    relational/tabular ingest) needs one selected. Defaults to the first, which
    is the primary entity by convention in both the extraction prompt's output
    and the JSON-Schema converter.
    """
    if not schema.entities:
        raise ValueError("InferredSchema has no entities to generate from.")

    if entity_name is None:
        return schema.entities[0]

    for entity in schema.entities:
        if entity.entity_name == entity_name:
            return entity

    available = ", ".join(e.entity_name for e in schema.entities)
    raise KeyError(f"No entity named {entity_name!r} in schema. Available: {available}")


def inferred_to_resolved(
    schema: InferredSchema,
    entity_name: str | None = None,
    sample_pdfs: list[str] | None = None,
) -> tuple[dict, str, list[str]]:
    """Convert an ``InferredSchema`` into ``(json_schema, guidance, sample_pdfs)``.

    The returned triple is accepted directly by the pipeline's ``resolved=``
    parameter, so an ingested schema generates documents through the same code
    path as a bundled schema dir.

    Args:
        schema: the schema to adapt.
        entity_name: which entity to render (defaults to the first).
        sample_pdfs: optional reference PDFs for the doc critic. Not carried on
            ``InferredSchema`` — pass them explicitly when available.

    Returns:
        ``(json_schema_dict, guidance_text, sample_pdf_paths)``.
    """
    from seed_data.schema.io import to_json_schema

    entity = _select_entity(schema, entity_name)
    json_schema = to_json_schema(schema, entity_name=entity.entity_name)
    return json_schema, entity.generation_guidance or "", list(sample_pdfs or [])


def inferred_to_schema(
    schema: InferredSchema,
    entity_name: str | None = None,
    sample_pdfs: list[str] | None = None,
):
    """Adapt an ``InferredSchema`` into a legacy :class:`Schema` object.

    Useful when you want the in-code ``Schema`` surface (e.g. to edit guidance,
    or to hand to something that type-checks against ``Schema``) rather than the
    raw triple :func:`inferred_to_resolved` produces.
    """
    from seed_data.schema.legacy import Schema

    entity = _select_entity(schema, entity_name)
    json_schema, guidance, samples = inferred_to_resolved(
        schema, entity_name=entity.entity_name, sample_pdfs=sample_pdfs
    )
    return Schema(
        name=entity.entity_name,
        json_schema=json_schema,
        generation_guidance=guidance,
        sample_pdfs=samples,
    )


__all__ = ["inferred_to_resolved", "inferred_to_schema"]

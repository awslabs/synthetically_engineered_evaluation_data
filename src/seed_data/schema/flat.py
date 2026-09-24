"""Depth-bounded, non-recursive mirror of :class:`InferredSchema` for LLM output.

:class:`~seed_data.schema.models.FieldDefinition` is self-recursive — ``children``
is a ``list[FieldDefinition]`` — which is what lets one model describe arbitrarily
nested document schemas. Bedrock tool specs cannot express that: Strands flattens
a Pydantic model's JSON Schema by inlining every ``$ref``, so a self-reference
makes ``convert_pydantic_to_tool_spec`` recurse until the interpreter's stack
limit and raise ``RecursionError``. Passing ``structured_output_model=InferredSchema``
therefore fails before a single token is generated.

The fix is to hand the model an equivalent *finite* schema: a chain of distinct
classes where each level's ``children`` points at the next level down, and the
last level has no ``children`` at all. Because every level is a subclass of the
canonical models, instances validate as the real thing, so
:func:`to_canonical` is a plain re-validation rather than a translation.

``MAX_NESTING_DEPTH`` is 5. The deepest bundled document schema nests 3 levels,
so this leaves headroom while keeping the emitted tool spec small — cost grows
with depth, since each level is inlined in full.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, create_model

from seed_data.schema.models import (
    EntitySchema,
    InferredSchema,
    _FieldDefinitionBase,
)

#: How many levels of nested object/array fields the model may return.
MAX_NESTING_DEPTH = 5


@lru_cache(maxsize=1)
def flat_inferred_schema() -> type[InferredSchema]:
    """Return an ``InferredSchema`` subclass safe to use as a structured-output model.

    Cached: the class only needs building once, and Strands caches tool specs by
    model identity, so returning a fresh class per call would defeat that cache.
    """
    # Deepest level: no `children` field at all. Omitting it (rather than typing
    # it `None`) keeps the emitted tool spec free of a degenerate
    # `"type": ["null", "null"]` entry, and the canonical model defaults it to
    # None on the way back.
    level: type[_FieldDefinitionBase] = create_model(
        "FlatFieldDefinitionDepth1", __base__=_FieldDefinitionBase
    )

    for depth in range(2, MAX_NESTING_DEPTH + 1):
        level = create_model(
            f"FlatFieldDefinitionDepth{depth}",
            __base__=_FieldDefinitionBase,
            children=(
                list[level] | None,
                Field(
                    default=None,
                    description=(
                        "Sub-fields for nested object/array types "
                        "(JSON Schema properties/items)"
                    ),
                ),
            ),
        )

    flat_entity = create_model(
        "FlatEntitySchema",
        __base__=EntitySchema,
        fields=(list[level], Field(description="List of field definitions")),
    )
    return create_model(
        "FlatInferredSchema",
        __base__=InferredSchema,
        entities=(
            list[flat_entity],
            Field(description="List of entity schemas with full definitions"),
        ),
    )


def to_canonical(schema: InferredSchema) -> InferredSchema:
    """Re-validate a flat-model instance as a canonical :class:`InferredSchema`.

    The flat classes subclass the canonical ones, so this is a type normalization:
    it converts the depth-specific ``children`` classes into plain
    :class:`FieldDefinition` instances, so downstream code (and equality checks)
    sees exactly the model it declares.
    """
    return InferredSchema.model_validate(schema.model_dump())


__all__ = ["MAX_NESTING_DEPTH", "flat_inferred_schema", "to_canonical"]

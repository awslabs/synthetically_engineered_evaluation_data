"""Tests for the depth-bounded structured-output variant of ``InferredSchema``.

``FieldDefinition.children`` is self-recursive, which Strands cannot turn into a
Bedrock tool spec — it inlines every ``$ref`` and recurses until the stack runs
out. Every agent call that asks for an ``InferredSchema`` therefore has to use
:func:`seed_data.schema.flat.flat_inferred_schema` instead. These tests pin that
down, since the failure mode is a ``RecursionError`` raised before any request is
sent — invisible to anything that does not exercise the real conversion.
"""
import pytest

from seed_data.schema.flat import MAX_NESTING_DEPTH, flat_inferred_schema, to_canonical
from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema

convert = pytest.importorskip(
    "strands.tools.structured_output.structured_output_utils"
).convert_pydantic_to_tool_spec


# --- the actual bug ---------------------------------------------------------

def test_canonical_inferred_schema_cannot_be_a_tool_spec():
    """Documents *why* the flat variant exists.

    If a future Strands release handles recursive models, this test fails and the
    flat indirection can be deleted.
    """
    with pytest.raises(RecursionError):
        convert(InferredSchema)


def test_flat_schema_converts_to_a_tool_spec():
    spec = convert(flat_inferred_schema())
    assert spec["name"]
    assert "json" in spec["inputSchema"]


def test_flat_schema_is_cached():
    """Strands caches tool specs by model identity; a fresh class each call would
    rebuild the spec on every agent invocation."""
    assert flat_inferred_schema() is flat_inferred_schema()


# --- equivalence with the canonical model ----------------------------------

def test_flat_schema_is_an_inferred_schema():
    """Subclassing keeps `isinstance` checks and type hints honest."""
    model = flat_inferred_schema()
    assert issubclass(model, InferredSchema)


def test_flat_schema_carries_every_canonical_field():
    """A field missing here is a field the LLM can never populate."""
    model = flat_inferred_schema()
    top = model.model_fields["entities"].annotation.__args__[0]
    field_model = top.model_fields["fields"].annotation.__args__[0]

    assert set(field_model.model_fields) == set(FieldDefinition.model_fields)
    assert set(top.model_fields) == set(EntitySchema.model_fields)


def test_to_canonical_returns_exact_canonical_types():
    model = flat_inferred_schema()
    instance = model.model_validate({
        "entities": [{
            "entity_name": "Order",
            "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "address", "type": "object", "children": [
                    {"name": "city", "type": "string"},
                ]},
            ],
        }],
    })
    canonical = to_canonical(instance)

    assert type(canonical) is InferredSchema
    assert type(canonical.entities[0]) is EntitySchema
    assert type(canonical.entities[0].fields[0]) is FieldDefinition
    assert type(canonical.entities[0].fields[1].children[0]) is FieldDefinition


def test_flat_schema_supports_documented_nesting_depth():
    """The deepest bundled schema nests 3 levels; the bound must exceed that."""
    assert MAX_NESTING_DEPTH >= 4

    payload = {"name": "leaf", "type": "string"}
    for level in range(MAX_NESTING_DEPTH - 1):
        payload = {"name": f"level{level}", "type": "object", "children": [payload]}

    canonical = to_canonical(flat_inferred_schema().model_validate(
        {"entities": [{"entity_name": "Deep", "fields": [payload]}]}
    ))

    field = canonical.entities[0].fields[0]
    depth = 1
    while field.children:
        field = field.children[0]
        depth += 1
    assert depth == MAX_NESTING_DEPTH
    assert field.name == "leaf"


def test_flat_schema_inherits_validators():
    """`description=None` is common in LLM output and must coerce, not raise."""
    model = flat_inferred_schema()
    instance = model.model_validate({
        "entities": [{"entity_name": "E", "description": None, "fields": [
            {"name": "f", "type": "string", "description": None,
             "enum_values": ["a", None, 3]},
        ]}],
    })
    field = to_canonical(instance).entities[0].fields[0]
    assert field.description == ""
    assert field.enum_values == ["a", "None", "3"]


def test_flat_schema_preserves_doc_gen_extensions():
    """The fields that make an ingested schema render faithfully must survive."""
    instance = flat_inferred_schema().model_validate({
        "entities": [{"entity_name": "E", "fields": [
            {"name": "narrative", "type": "string", "presence_probability": 0.7},
            {"name": "tags", "type": "array", "item_type": "string",
             "min_items": 2, "max_items": 9},
        ]}],
    })
    fields = {f.name: f for f in to_canonical(instance).entities[0].fields}
    assert fields["narrative"].presence_probability == 0.7
    assert fields["tags"].item_type == "string"
    assert (fields["tags"].min_items, fields["tags"].max_items) == (2, 9)


def test_flat_schema_tool_spec_has_no_degenerate_null_type():
    """The deepest level omits `children` rather than typing it `None`.

    Typing it `None` emits `"type": ["null", "null"]`, which is nonsense to hand
    a model even though it parses.
    """
    import json

    spec = json.dumps(convert(flat_inferred_schema()))
    assert '"null","null"' not in spec.replace(" ", "")


@pytest.mark.parametrize("module_path", [
    "ingest/extract.py",
    "structured/distributions/inference.py",
])
def test_agent_call_sites_use_the_flat_model(module_path):
    """The two agents that request an InferredSchema must not pass the recursive one.

    This is the regression that reddened the entire integration suite. Read as
    text rather than imported, because ``structured.distributions`` needs the
    ``[structured]`` extra and this must also hold in the lean base install.
    """
    import pathlib

    import seed_data

    source = (pathlib.Path(seed_data.__file__).parent / module_path).read_text()
    assert "structured_output_model=flat_inferred_schema()" in source
    assert "structured_output_model=InferredSchema" not in source

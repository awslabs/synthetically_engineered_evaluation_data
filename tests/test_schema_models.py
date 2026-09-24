"""Tests for the unified schema models + JSON Schema converters.

Covers seed_data.schema.models (InferredSchema and friends) and
seed_data.schema.io (from_json_schema / to_json_schema / schema-dir round-trip),
plus backward-compat guarantees for the legacy Schema class and the
_InferredSchema -> _InferenceDraft rename in seed_data.infer.
"""
import json
import os

import pytest

from seed_data.schema import (
    DistributionSpec,
    DistributionType,
    EntitySchema,
    FieldDefinition,
    InferredSchema,
    RelationshipDefinition,
    Cardinality,
    Schema,
    from_json_schema,
    from_schema_dir,
    to_json_schema,
    to_schema_dir,
)

SCHEMAS_DIR = os.path.join("src", "seed_data", "schemas")


# --- FieldDefinition / models -----------------------------------------------

def test_field_definition_basic():
    f = FieldDefinition(name="total", type="float", description="amount", min_value=0)
    dumped = f.model_dump()
    assert dumped["name"] == "total"
    assert dumped["type"] == "float"
    assert dumped["min_value"] == 0
    # round-trip through JSON
    reloaded = FieldDefinition.model_validate_json(f.model_dump_json())
    assert reloaded == f


def test_field_definition_nested():
    child = FieldDefinition(name="city", type="string")
    parent = FieldDefinition(name="address", type="object", children=[child])
    reloaded = FieldDefinition.model_validate_json(parent.model_dump_json())
    assert reloaded.children is not None
    assert reloaded.children[0].name == "city"


def test_field_definition_distribution():
    spec = DistributionSpec(type=DistributionType.NORMAL, params={"mean": 50, "std": 10})
    f = FieldDefinition(name="age", type="integer", distribution=spec)
    reloaded = FieldDefinition.model_validate_json(f.model_dump_json())
    assert reloaded.distribution.type == DistributionType.NORMAL
    assert reloaded.distribution.params["mean"] == 50


def test_field_definition_enum_coercion():
    # enum_values with a None entry gets coerced to the string "None"
    f = FieldDefinition(name="status", type="enum", enum_values=["a", None, 3])
    assert f.enum_values == ["a", "None", "3"]


def test_entity_schema_with_relationships():
    rel = RelationshipDefinition(
        source_entity="Order", source_field="customer_id",
        target_entity="Customer", target_field="id",
        cardinality=Cardinality.ONE_TO_MANY,
    )
    e = EntitySchema(
        entity_name="Order",
        fields=[FieldDefinition(name="customer_id", type="integer")],
        structured_relationships=[rel],
    )
    assert e.structured_relationships[0].cardinality == Cardinality.ONE_TO_MANY
    assert e.generation_guidance == ""       # new extension defaults empty
    assert e.reference_samples == []


def test_inferred_schema_multi_entity():
    s = InferredSchema(entities=[
        EntitySchema(entity_name="Customer", fields=[FieldDefinition(name="id", type="integer")]),
        EntitySchema(entity_name="Order", fields=[FieldDefinition(name="id", type="integer")]),
    ])
    names = {e.entity_name for e in s.entities}
    assert names == {"Customer", "Order"}


# --- from_json_schema --------------------------------------------------------

def test_from_json_schema_flat():
    schema_dir = os.path.join(SCHEMAS_DIR, "fcc-invoice")
    if not os.path.isdir(schema_dir):
        pytest.skip("bundled fcc-invoice schema not present")
    with open(os.path.join(schema_dir, "schema.json")) as f:
        raw = json.load(f)

    inferred = from_json_schema(raw)
    assert len(inferred.entities) == 1
    entity = inferred.entities[0]
    assert entity.entity_name == "FCC-Invoice"
    field_names = {f.name for f in entity.fields}
    assert {"Agency", "Advertiser", "Station", "LineItems"}.issubset(field_names)


def test_from_json_schema_required_vs_nullable():
    """`required` (key presence) and `nullable` (value may be null) are distinct.

    Absence from `required` makes a field optional; it does NOT add a null branch
    to its type. Collapsing the two would rewrite `{"type": "string"}` into
    `anyOf: [{"type": "string"}, {"type": "null"}]` on the way back out.
    """
    raw = {
        "title": "T", "type": "object",
        "required": ["a"],
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "string"},
        },
    }
    inferred = from_json_schema(raw)
    fields = {f.name: f for f in inferred.entities[0].fields}
    assert fields["a"].required is True
    assert fields["b"].required is False     # absent from required -> optional
    # neither declares a null branch, so neither is nullable
    assert fields["a"].nullable is False
    assert fields["b"].nullable is False
    # only the required one demands a value
    assert fields["a"].requires_value is True
    assert fields["b"].requires_value is False


def test_from_json_schema_anyof_nullable():
    raw = {
        "title": "T", "type": "object", "required": ["amount"],
        "properties": {
            "amount": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "description": "the amount",
            },
        },
    }
    inferred = from_json_schema(raw)
    field = inferred.entities[0].fields[0]
    # Canonicalized to the semantic vocabulary, not the raw JSON Schema name. This
    # previously asserted "number", which is what the generators, the validator and
    # the range checks all fail to match — so the field was treated as free text and
    # an LLM wrote a string into a numeric column. See `_CANONICAL_TYPES`.
    assert field.type == "float"             # non-null branch type, canonicalized
    assert field.nullable is True            # anyOf null branch
    assert field.description == "the amount"

    # ...and the JSON Schema name comes back on the way out, so the round trip is
    # unchanged for consumers reading the exported schema.
    from seed_data.schema.io import to_json_schema
    out = to_json_schema(inferred)["properties"]["amount"]
    assert out["anyOf"][0]["type"] == "number"


def test_json_schema_number_reaches_the_numeric_generator():
    """A `number` field must be generated programmatically, not sent to the LLM.

    The regression this pins: `from_json_schema` stored the raw `number`, every
    consumer matched on `float`, so all 54 numeric fields across the bundled schemas
    were classified as free text — skipping seeded numeric generation, min/max
    enforcement and type conformance.
    """
    from seed_data.structured.generation import _needs_llm

    inferred = from_json_schema({
        "title": "T", "type": "object", "required": ["amount"],
        "properties": {"amount": {"type": "number", "minimum": 0, "maximum": 100}},
    })
    field = inferred.entities[0].fields[0]
    assert field.type == "float"
    assert field.min_value == 0 and field.max_value == 100
    assert _needs_llm(field, set()) is False


def test_from_json_schema_nested_array_of_objects():
    schema_dir = os.path.join(SCHEMAS_DIR, "fcc-invoice")
    if not os.path.isdir(schema_dir):
        pytest.skip("bundled fcc-invoice schema not present")
    with open(os.path.join(schema_dir, "schema.json")) as f:
        raw = json.load(f)

    inferred = from_json_schema(raw)
    line_items = next(f for f in inferred.entities[0].fields if f.name == "LineItems")
    assert line_items.type == "array"
    assert line_items.children is not None
    child_names = {c.name for c in line_items.children}
    assert "LineItemRate" in child_names


def test_from_json_schema_xprobability():
    """`x-probability` is a published doc-gen feature and must survive a round-trip.

    It drives per-document field-presence variation via the generator's
    `random_roll` tool. Mapping it to `nullable` (the old behaviour) both dropped
    the probability and wrongly added a null branch to the field's type.
    """
    raw = {
        "title": "T", "type": "object", "required": ["narrative"],
        "properties": {
            "narrative": {"type": "string", "x-probability": 0.7},
        },
    }
    inferred = from_json_schema(raw)
    field = inferred.entities[0].fields[0]
    assert field.presence_probability == 0.7
    # "sometimes absent" is not "may be null" — the type gains no null branch
    assert field.nullable is False
    # but a missing value is not a defect either
    assert field.requires_value is False
    # and it round-trips back into the emitted schema
    assert to_json_schema(inferred)["properties"]["narrative"]["x-probability"] == 0.7


# --- to_json_schema round-trip ----------------------------------------------

def test_to_json_schema_roundtrip():
    original = {
        "title": "Widget", "type": "object",
        "required": ["name", "price", "tags"],
        "properties": {
            "name": {"type": "string", "description": "name"},
            "price": {"anyOf": [{"type": "number"}, {"type": "null"}], "description": "price"},
            "tags": {"type": "array", "items": {
                "type": "object",
                "required": ["label"],
                "properties": {"label": {"type": "string"}},
            }},
        },
    }
    inferred = from_json_schema(original)
    rebuilt = to_json_schema(inferred)

    assert rebuilt["title"] == "Widget"
    assert set(rebuilt["properties"]) == {"name", "price", "tags"}
    # `required` (key presence) round-trips independently of nullability: `price`
    # is required *and* nullable — the key is always emitted, its value may be
    # null. Collapsing the two would drop it from `required`.
    assert set(rebuilt["required"]) == {"name", "price", "tags"}
    assert "anyOf" in rebuilt["properties"]["price"]
    assert {"type": "null"} in rebuilt["properties"]["price"]["anyOf"]
    # nested array of objects preserved
    assert rebuilt["properties"]["tags"]["type"] == "array"
    assert "label" in rebuilt["properties"]["tags"]["items"]["properties"]

    # A second pass through from_json_schema yields the same field structure.
    reparsed = from_json_schema(rebuilt)
    assert {f.name for f in reparsed.entities[0].fields} == {"name", "price", "tags"}


def test_from_schema_dir():
    schema_dir = os.path.join(SCHEMAS_DIR, "fcc-invoice")
    if not os.path.isdir(schema_dir):
        pytest.skip("bundled fcc-invoice schema not present")
    inferred = from_schema_dir(schema_dir)
    entity = inferred.entities[0]
    assert len(entity.fields) > 0
    assert isinstance(entity.generation_guidance, str)
    assert len(entity.generation_guidance) > 0    # guidance md loaded


def test_to_schema_dir_roundtrip(tmp_path):
    inferred = InferredSchema(entities=[
        EntitySchema(
            entity_name="mini",
            description="a mini schema",
            fields=[
                FieldDefinition(name="id", type="integer"),
                FieldDefinition(name="note", type="string", nullable=True),
            ],
            generation_guidance="## Guidance\nKeep it small.",
        )
    ])
    dest = str(tmp_path / "mini")
    to_schema_dir(inferred, dest)

    assert os.path.isfile(os.path.join(dest, "schema.json"))
    assert os.path.isfile(os.path.join(dest, "generation_guidance.md"))

    reloaded = from_schema_dir(dest)
    entity = reloaded.entities[0]
    assert entity.entity_name == "mini"
    assert {f.name for f in entity.fields} == {"id", "note"}
    assert "Keep it small." in entity.generation_guidance


@pytest.mark.parametrize("name", sorted(os.listdir(SCHEMAS_DIR)) if os.path.isdir(SCHEMAS_DIR) else [])
def test_all_bundled_schemas_loadable(name):
    """Every bundled schema.json converts to InferredSchema without error."""
    schema_dir = os.path.join(SCHEMAS_DIR, name)
    if not os.path.isfile(os.path.join(schema_dir, "schema.json")):
        pytest.skip(f"{name} has no schema.json")
    inferred = from_schema_dir(schema_dir)
    assert len(inferred.entities) == 1
    assert len(inferred.entities[0].fields) > 0
    # and it re-serializes
    rebuilt = to_json_schema(inferred)
    assert rebuilt["title"] == inferred.entities[0].entity_name


# --- backward compat: legacy Schema -----------------------------------------

def test_legacy_schema_class():
    from seed_data.schema import Schema as SchemaFromPkg
    from seed_data import Schema as SchemaFromTop
    assert SchemaFromPkg is SchemaFromTop


def test_legacy_schema_resolve():
    s = Schema(
        name="wire",
        json_schema={"type": "object", "properties": {"amount": {"type": "number"}}},
        generation_guidance="g",
    )
    schema_dict, guidance, samples = s.resolve()
    assert schema_dict["title"] == "wire"
    assert guidance == "g"
    assert samples == []


# --- backward compat: _InferredSchema -> _InferenceDraft rename --------------

def test_no_inferredschema_name_clash():
    import seed_data.infer as infer_mod
    # old private name is gone; new private name exists
    assert not hasattr(infer_mod, "_InferredSchema")
    assert hasattr(infer_mod, "_InferenceDraft")
    # canonical rich model is the one exported from seed_data.schema
    from seed_data.schema import InferredSchema as RichInferredSchema
    assert RichInferredSchema is InferredSchema


def test_infer_schema_unaffected_by_rename(tmp_path, monkeypatch):
    """After the rename, infer.infer_schema still returns a legacy Schema."""
    import seed_data.infer as infer_mod

    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 minimal")

    def fake_run(docs, *, name, model, session, on_question=None, verbose):
        return ({"type": "object", "properties": {"x": {"type": "number"}}}, "## Guidance\nok")
    monkeypatch.setattr(infer_mod, "_run_inference", fake_run)

    schema = infer_mod.infer_schema(str(tmp_path / "*.pdf"), name="thing", verbose=False)
    assert isinstance(schema, Schema)
    assert schema.name == "thing"


# --- review round 5: crit/high schema defects ---------------------------------

def test_enum_without_explicit_type_keeps_its_value_type():
    """draft-07 allows `{"enum": [1,2,3]}` with no `type`.

    `enum_base_type` was taken from a `raw_jtype` that defaults to "string" there, so
    a numeric enum was recorded as a string one and round-tripped to
    `{"type":"string","enum":["1","2","3"]}` — the exact corruption the field exists
    to prevent. Regression introduced while fixing the `number`/`float` mismatch.
    """
    from seed_data.schema.io import to_json_schema

    inferred = from_json_schema({"title": "T", "type": "object",
                                 "properties": {"rating": {"enum": [1, 2, 3]}}})
    field = inferred.entities[0].fields[0]
    assert field.enum_base_type == "integer"
    assert to_json_schema(inferred)["properties"]["rating"] == {"type": "integer", "enum": [1, 2, 3]}


def test_boolean_enum_round_trips_satisfiably():
    """`{"type":"boolean","enum":[true,false]}` became `enum:["True","False"]`.

    Nothing satisfies that — Draft7Validator rejects `true`, `false` *and* `"True"` —
    and `stages/data` validates every generated document against this schema, so the
    critic could never accept and the run burned every retry.
    """
    import jsonschema
    from seed_data.schema.io import to_json_schema

    inferred = from_json_schema({"title": "T", "type": "object", "required": ["flag"],
                                 "properties": {"flag": {"type": "boolean",
                                                         "enum": [True, False]}}})
    rebuilt = to_json_schema(inferred)
    assert rebuilt["properties"]["flag"] == {"type": "boolean", "enum": [True, False]}
    # And it must actually validate real data.
    jsonschema.Draft7Validator(rebuilt).validate({"flag": True})


def test_semantic_enum_base_types_are_also_coerced():
    """`enum_base_type` can hold the semantic alias, not just the JSON name.

    `_to_json_type` accepts `int`/`float`, so the emitted `type` was coerced while the
    values were left as strings — the same unsatisfiable pairing.
    """
    from seed_data.schema.io import _coerce_enum_values

    assert _coerce_enum_values(["1", "2"], "int") == [1, 2]
    assert _coerce_enum_values(["1.5"], "float") == [1.5]
    assert _coerce_enum_values(["true", "false"], "bool") == [True, False]


def test_sometimes_present_field_is_not_emitted_as_required():
    """A `presence_probability` field must not be in `required`.

    `prompts/data_generator.j2` tells the model to omit the key when the roll fails,
    so emitting it as both `required` and `x-probability` made the schema contradict
    the prompt — the critic rejected ~30% of generations for obeying it.
    """
    from seed_data.schema.io import to_json_schema

    schema = InferredSchema.model_validate({"entities": [{
        "entity_name": "D", "description": "d", "fields": [
            {"name": "always", "type": "string", "required": True},
            {"name": "sometimes", "type": "string", "required": True,
             "presence_probability": 0.7}]}]})
    out = to_json_schema(schema)

    assert out["required"] == ["always"]
    assert out["properties"]["sometimes"]["x-probability"] == 0.7


def test_required_and_nullable_still_round_trips():
    """The exclusion above must not also drop required-and-nullable fields.

    `required` is about key presence, so a field that is required *and* nullable
    belongs in the list — which is why this is not keyed off `requires_value`.
    """
    from seed_data.schema.io import to_json_schema

    inferred = from_json_schema({
        "title": "T", "type": "object", "required": ["price"],
        "properties": {"price": {"anyOf": [{"type": "number"}, {"type": "null"}]}}})
    assert to_json_schema(inferred)["required"] == ["price"]


def test_tuple_form_items_does_not_crash():
    """draft-07's tuple form (`items: [...]`) raised an uncaught AttributeError."""
    inferred = from_json_schema({"title": "T", "type": "object", "properties": {
        "pair": {"type": "array", "items": [{"type": "string"}, {"type": "integer"}]}}})
    field = inferred.entities[0].fields[0]
    assert field.type == "array"
    assert field.item_type == "string"


def test_guidance_is_written_as_utf8(tmp_path, monkeypatch):
    """The guidance .md was written with the locale default encoding.

    LLM-authored guidance reliably contains em dashes, and under a C/POSIX locale the
    write raised UnicodeEncodeError — discarding the whole paid-for inference run.
    """
    from seed_data.schema.io import to_schema_dir

    schema = InferredSchema.model_validate({"entities": [{
        "entity_name": "T", "description": "t",
        "fields": [{"name": "a", "type": "string"}],
        "generation_guidance": "Totals must match — always."}]})
    dest = tmp_path / "out"
    to_schema_dir(schema, str(dest))
    written = (dest / "generation_guidance.md").read_text(encoding="utf-8")
    assert "—" in written


def test_boolean_enum_preserves_its_null_member():
    """`enum_values` records null as the string "None"; the caster ate it.

    The boolean caster was total (`in ("true","1")`), so "None" became `False` — which
    invents a value the source never allowed and drops the null it did. Being total
    also meant `_coerce_enum_values`' bail-out was unreachable.
    """
    from seed_data.schema.io import _coerce_enum_values, to_json_schema

    assert _coerce_enum_values(["True", "False", "None"], "boolean") == [True, False, None]
    # And an unparseable member now reaches the bail-out instead of silently coercing.
    assert _coerce_enum_values(["yes", "no"], "boolean") == ["yes", "no"]

    inferred = from_json_schema({"title": "T", "type": "object",
                                 "properties": {"flag": {"enum": [True, False, None]}}})
    assert to_json_schema(inferred)["properties"]["flag"]["enum"] == [True, False, None]

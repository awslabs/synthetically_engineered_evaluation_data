"""Tests for the InferredSchema -> doc-gen triple adapter (Milestone 3).

The adapter is what lets an ingested schema generate PDFs through the existing
document pipeline: it produces the same ``(json_schema, guidance, sample_pdfs)``
triple that a schema directory yields, so the pipeline needs no changes.
"""
import glob
import os

import pytest

from seed_data.schema.adapter import inferred_to_resolved, inferred_to_schema
from seed_data.schema.io import from_schema_dir
from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema
from seed_data.utils import load_schema_dir

SCHEMAS_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "src", "seed_data", "schemas")


def _bundled_schema_names():
    return sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(SCHEMAS_ROOT, "*"))
        if os.path.isdir(p)
    )


def _entity(fields, name="Order", guidance=""):
    return InferredSchema(entities=[
        EntitySchema(entity_name=name, fields=fields, generation_guidance=guidance)
    ])


# --- flat / basic mapping ---------------------------------------------------

def test_adapter_flat_entity():
    schema = _entity([
        FieldDefinition(name="order_id", type="string"),
        FieldDefinition(name="quantity", type="integer"),
        FieldDefinition(name="total", type="number"),
        FieldDefinition(name="shipped", type="boolean"),
        FieldDefinition(name="notes", type="string", nullable=True),
    ])
    json_schema, guidance, samples = inferred_to_resolved(schema)

    assert json_schema["type"] == "object"
    assert json_schema["title"] == "Order"
    assert set(json_schema["properties"]) == {
        "order_id", "quantity", "total", "shipped", "notes"
    }
    # non-nullable fields land in `required`, the nullable one does not
    assert set(json_schema["required"]) == {"order_id", "quantity", "total", "shipped"}
    assert guidance == ""
    assert samples == []


def test_adapter_returns_triple():
    """The pipeline destructures this — shape matters as much as content."""
    resolved = inferred_to_resolved(_entity([FieldDefinition(name="f", type="string")]))
    assert isinstance(resolved, tuple) and len(resolved) == 3
    schema_dict, guidance, samples = resolved
    assert isinstance(schema_dict, dict)
    assert isinstance(guidance, str)
    assert isinstance(samples, list)


def test_adapter_nested_entity():
    schema = _entity([
        FieldDefinition(name="customer", type="object", children=[
            FieldDefinition(name="name", type="string"),
            FieldDefinition(name="email", type="string"),
        ]),
    ])
    props = inferred_to_resolved(schema)[0]["properties"]
    assert props["customer"]["type"] == "object"
    assert set(props["customer"]["properties"]) == {"name", "email"}


def test_adapter_array_field():
    schema = _entity([
        FieldDefinition(name="line_items", type="array", children=[
            FieldDefinition(name="sku", type="string"),
            FieldDefinition(name="qty", type="integer"),
        ]),
    ])
    prop = inferred_to_resolved(schema)[0]["properties"]["line_items"]
    assert prop["type"] == "array"
    assert set(prop["items"]["properties"]) == {"sku", "qty"}


def test_adapter_nullable_field_uses_anyof_null():
    """doc-gen's nullable idiom is `anyOf: [T, null]` — the converter's contract."""
    schema = _entity([FieldDefinition(name="middle_name", type="string", nullable=True)])
    prop = inferred_to_resolved(schema)[0]["properties"]["middle_name"]
    assert "anyOf" in prop
    assert {"type": "null"} in prop["anyOf"]
    assert "middle_name" not in inferred_to_resolved(schema)[0].get("required", [])


def test_adapter_enum_field():
    schema = _entity([
        FieldDefinition(name="status", type="enum", enum_values=["open", "closed"]),
    ])
    prop = inferred_to_resolved(schema)[0]["properties"]["status"]
    assert prop["enum"] == ["open", "closed"]
    # enum serializes as a string type in JSON Schema
    assert prop["type"] == "string"


def test_adapter_constraints():
    schema = _entity([
        FieldDefinition(name="age", type="integer", min_value=0, max_value=120),
        FieldDefinition(name="code", type="string", min_length=2, max_length=5,
                        pattern=r"^[A-Z]+$"),
    ])
    props = inferred_to_resolved(schema)[0]["properties"]
    assert props["age"]["minimum"] == 0
    assert props["age"]["maximum"] == 120
    assert props["code"]["minLength"] == 2
    assert props["code"]["maxLength"] == 5
    assert props["code"]["pattern"] == r"^[A-Z]+$"


def test_adapter_drops_distribution():
    """Distributions steer tabular generation and are meaningless for rendering."""
    from seed_data.schema.models import DistributionSpec, DistributionType

    schema = _entity([
        FieldDefinition(
            name="amount", type="number",
            distribution=DistributionSpec(type=DistributionType.NORMAL,
                                          params={"mean": 10.0, "std": 2.0}),
        ),
    ])
    prop = inferred_to_resolved(schema)[0]["properties"]["amount"]
    assert "distribution" not in prop
    assert prop["type"] == "number"


def test_adapter_guidance_passthrough():
    schema = _entity([FieldDefinition(name="f", type="string")],
                     guidance="Totals must equal the sum of line items.")
    assert inferred_to_resolved(schema)[1] == "Totals must equal the sum of line items."


def test_adapter_sample_pdfs_passthrough():
    samples = ["/tmp/a.pdf", "/tmp/b.pdf"]
    assert inferred_to_resolved(
        _entity([FieldDefinition(name="f", type="string")]), sample_pdfs=samples,
    )[2] == samples


# --- multi-entity selection -------------------------------------------------

def _multi():
    return InferredSchema(entities=[
        EntitySchema(entity_name="Customer",
                     fields=[FieldDefinition(name="customer_id", type="string")]),
        EntitySchema(entity_name="Order",
                     fields=[FieldDefinition(name="order_id", type="string")]),
        EntitySchema(entity_name="Product",
                     fields=[FieldDefinition(name="sku", type="string")]),
    ])


def test_adapter_multi_entity_select():
    json_schema = inferred_to_resolved(_multi(), entity_name="Order")[0]
    assert json_schema["title"] == "Order"
    assert set(json_schema["properties"]) == {"order_id"}


def test_adapter_multi_entity_default_first():
    json_schema = inferred_to_resolved(_multi())[0]
    assert json_schema["title"] == "Customer"
    assert set(json_schema["properties"]) == {"customer_id"}


def test_adapter_unknown_entity_raises():
    with pytest.raises(KeyError, match="Nope"):
        inferred_to_resolved(_multi(), entity_name="Nope")


def test_adapter_unknown_entity_lists_available():
    """The error should tell you what you could have picked."""
    with pytest.raises(KeyError) as exc:
        inferred_to_resolved(_multi(), entity_name="Nope")
    for name in ("Customer", "Order", "Product"):
        assert name in str(exc.value)


def test_adapter_empty_schema_raises():
    with pytest.raises(ValueError, match="no entities"):
        inferred_to_resolved(InferredSchema(entities=[]))


# --- Schema-object variant --------------------------------------------------

def test_inferred_to_schema_returns_legacy_schema():
    from seed_data.schema import Schema

    schema = inferred_to_schema(
        _entity([FieldDefinition(name="f", type="string")], guidance="G")
    )
    assert isinstance(schema, Schema)
    assert schema.name == "Order"
    assert schema.generation_guidance == "G"
    # and it resolves to the same triple the pipeline wants
    assert schema.resolve()[0]["title"] == "Order"


def test_inferred_to_schema_multi_entity_select():
    assert inferred_to_schema(_multi(), entity_name="Product").name == "Product"


# --- round-trip over every bundled document type ---------------------------

@pytest.mark.parametrize("schema_name", _bundled_schema_names())
def test_roundtrip_builtin_schemas(schema_name):
    """Every bundled schema dir must survive dir -> InferredSchema -> triple.

    Field names and guidance text are the contract the pipeline depends on.
    """
    path = os.path.join(SCHEMAS_ROOT, schema_name)
    original_dict, original_guidance, _ = load_schema_dir(path)

    adapted_dict, adapted_guidance, _ = inferred_to_resolved(from_schema_dir(path))

    assert set(original_dict.get("properties", {})) == set(adapted_dict.get("properties", {}))
    assert adapted_guidance == original_guidance
    assert adapted_dict["type"] == "object"
    assert adapted_dict["title"] == original_dict.get("title", schema_name)


def test_bundled_schema_set_is_discovered():
    """Guard the parametrization above against silently finding nothing."""
    names = _bundled_schema_names()
    assert len(names) >= 17
    assert "fcc-invoice" in names


@pytest.mark.parametrize("schema_name", _bundled_schema_names())
def test_roundtrip_preserves_required_fields(schema_name):
    """Nullability drives `required`, which drives what the generator must emit."""
    path = os.path.join(SCHEMAS_ROOT, schema_name)
    original_dict, _, _ = load_schema_dir(path)
    adapted_dict, _, _ = inferred_to_resolved(from_schema_dir(path))

    assert set(original_dict.get("required", [])) == set(adapted_dict.get("required", []))


def test_from_legacy_schema_dir_matches_from_schema_dir():
    from seed_data.schema.io import from_legacy_schema_dir

    path = os.path.join(SCHEMAS_ROOT, "fcc-invoice")
    assert from_legacy_schema_dir(path) == from_schema_dir(path)


# --- the adapter's output must be a *usable* JSON Schema --------------------
#
# The doc pipeline does not merely pass the emitted schema to a prompt: it runs
# it through `jsonschema.Draft7Validator` as a hard gate in
# `seed_data.stages.data`. A schema that is merely plausible-looking but invalid
# fails every generation attempt, so validity is part of the adapter's contract.

def _semantic_entity():
    """An entity using the type vocabulary `prompts/schema_extraction.j2` asks for."""
    return _entity([
        FieldDefinition(name="id", type="uuid"),
        FieldDefinition(name="contact_email", type="email"),
        FieldDefinition(name="phone_number", type="phone"),
        FieldDefinition(name="issue_date", type="date"),
        FieldDefinition(name="created_at", type="datetime"),
        FieldDefinition(name="total", type="float"),
        FieldDefinition(name="homepage", type="url"),
    ])


def test_adapter_output_is_valid_draft7():
    """Semantic types must be translated, not passed through as JSON Schema types."""
    jsonschema = pytest.importorskip("jsonschema")

    json_schema = inferred_to_resolved(_semantic_entity())[0]
    # Raises SchemaError if any `type` is not a real JSON Schema type.
    jsonschema.Draft7Validator.check_schema(json_schema)


def test_adapter_semantic_types_map_to_json_types_plus_format():
    props = inferred_to_resolved(_semantic_entity())[0]["properties"]

    assert props["id"] == {"type": "string", "format": "uuid"}
    assert props["contact_email"] == {"type": "string", "format": "email"}
    assert props["issue_date"] == {"type": "string", "format": "date"}
    assert props["created_at"] == {"type": "string", "format": "date-time"}
    assert props["homepage"] == {"type": "string", "format": "uri"}
    # `float` is not a JSON Schema type; `number` is.
    assert props["total"] == {"type": "number"}
    # no standard draft-07 format for a phone number — plain string, no `format`
    assert props["phone_number"] == {"type": "string"}


def test_adapter_output_validates_conforming_data():
    """The emitted schema must accept data that genuinely conforms.

    `stages.data` calls `iter_errors`, which raises `UnknownType` on an unknown
    `type` — an exception no retry can recover from.
    """
    jsonschema = pytest.importorskip("jsonschema")

    json_schema = inferred_to_resolved(_semantic_entity())[0]
    record = {
        "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        "contact_email": "a@b.com", "phone_number": "555-0100",
        "issue_date": "2024-01-01", "created_at": "2024-01-01T00:00:00",
        "total": 12.5, "homepage": "https://example.com",
    }
    assert list(jsonschema.Draft7Validator(json_schema).iter_errors(record)) == []


def test_adapter_unknown_type_degrades_to_string():
    """An unrecognized type must not poison the whole schema's validity."""
    jsonschema = pytest.importorskip("jsonschema")

    json_schema = inferred_to_resolved(
        _entity([FieldDefinition(name="mystery", type="quux")])
    )[0]
    jsonschema.Draft7Validator.check_schema(json_schema)
    assert json_schema["properties"]["mystery"]["type"] == "string"


@pytest.mark.parametrize("schema_name", _bundled_schema_names())
def test_bundled_schemas_adapt_to_valid_draft7(schema_name):
    jsonschema = pytest.importorskip("jsonschema")

    path = os.path.join(SCHEMAS_ROOT, schema_name)
    adapted, _, _ = inferred_to_resolved(from_schema_dir(path))
    jsonschema.Draft7Validator.check_schema(adapted)


# --- numeric enums ----------------------------------------------------------

def test_adapter_numeric_enum_keeps_numeric_type():
    """`{"type": "string", "enum": [1, 2, 3]}` is satisfiable by nothing."""
    jsonschema = pytest.importorskip("jsonschema")

    from seed_data.schema.io import from_json_schema

    schema = from_json_schema({
        "title": "T", "type": "object", "required": ["grade", "score"],
        "properties": {
            "grade": {"type": "integer", "enum": [1, 2, 3]},
            "score": {"type": "number", "enum": [0.5, 1.0]},
        },
    })
    props = inferred_to_resolved(schema)[0]["properties"]
    assert props["grade"] == {"type": "integer", "enum": [1, 2, 3]}
    assert props["score"] == {"type": "number", "enum": [0.5, 1.0]}

    validator = jsonschema.Draft7Validator(inferred_to_resolved(schema)[0])
    assert list(validator.iter_errors({"grade": 2, "score": 1.0})) == []
    assert list(validator.iter_errors({"grade": "2", "score": 1.0}))


def test_string_enum_still_serializes_as_string():
    schema = _entity([
        FieldDefinition(name="status", type="enum", enum_values=["open", "closed"]),
    ])
    prop = inferred_to_resolved(schema)[0]["properties"]["status"]
    assert prop == {"type": "string", "enum": ["open", "closed"]}


def test_numeric_enum_does_not_warn_on_serialization():
    """`enum_values` is `list[str]`; storing raw ints there makes pydantic warn."""
    import warnings

    from seed_data.schema.io import from_json_schema

    schema = from_json_schema({
        "title": "T", "type": "object", "required": ["grade"],
        "properties": {"grade": {"type": "integer", "enum": [1, 2, 3]}},
    })
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        schema.model_dump_json()


# --- x-probability (a published doc-gen feature) ----------------------------

def _xprob_count(obj) -> int:
    """Count `x-probability` keys anywhere in a JSON Schema document."""
    if isinstance(obj, dict):
        return ("x-probability" in obj) + sum(_xprob_count(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_xprob_count(v) for v in obj)
    return 0


@pytest.mark.parametrize("schema_name", _bundled_schema_names())
def test_roundtrip_preserves_x_probability(schema_name):
    """`x-probability` drives per-document field variation via `random_roll`.

    Dropping it silently disables a documented feature for every schema that
    reaches generation through the adapter instead of `load_schema_dir`.
    """
    path = os.path.join(SCHEMAS_ROOT, schema_name)
    original_dict, _, _ = load_schema_dir(path)
    adapted_dict, _, _ = inferred_to_resolved(from_schema_dir(path))

    assert _xprob_count(adapted_dict) == _xprob_count(original_dict)


def test_x_probability_is_preserved_somewhere_in_the_bundled_set():
    """Guard the per-schema assertion above against 0 == 0 passing vacuously."""
    total = sum(
        _xprob_count(inferred_to_resolved(from_schema_dir(
            os.path.join(SCHEMAS_ROOT, name)))[0])
        for name in _bundled_schema_names()
    )
    assert total >= 40


def test_x_probability_does_not_add_a_null_branch():
    """"Sometimes absent" is not "may be null" — the type must stay unchanged."""
    from seed_data.schema.io import from_json_schema

    schema = from_json_schema({
        "title": "T", "type": "object", "required": ["narrative"],
        "properties": {"narrative": {"type": "string", "x-probability": 0.7}},
    })
    prop = inferred_to_resolved(schema)[0]["properties"]["narrative"]
    assert prop["type"] == "string"
    assert "anyOf" not in prop
    assert prop["x-probability"] == 0.7


# --- arrays of primitives ---------------------------------------------------

def test_adapter_primitive_array_keeps_items():
    """An array of primitives has no `children`; its element type lives elsewhere.

    Without `item_type` the rebuilt array omits `items` entirely and accepts a
    list of anything.
    """
    schema = _entity([
        FieldDefinition(name="tags", type="array", item_type="string",
                        item_description="Each tag as a string"),
    ])
    prop = inferred_to_resolved(schema)[0]["properties"]["tags"]
    assert prop["items"] == {"type": "string", "description": "Each tag as a string"}


def test_roundtrip_preserves_primitive_array_items():
    """medical-discharge's DischargeDiagnoses is an array of bare strings."""
    path = os.path.join(SCHEMAS_ROOT, "medical-discharge")
    original_dict, _, _ = load_schema_dir(path)
    adapted_dict, _, _ = inferred_to_resolved(from_schema_dir(path))

    original = original_dict["properties"]["DischargeDiagnoses"]
    adapted = adapted_dict["properties"]["DischargeDiagnoses"]
    assert adapted["items"] == original["items"]


def test_roundtrip_preserves_array_item_bounds():
    """minItems/maxItems control how many rows a rendered table has."""
    path = os.path.join(SCHEMAS_ROOT, "bank-statement")
    original_dict, _, _ = load_schema_dir(path)
    adapted_dict, _, _ = inferred_to_resolved(from_schema_dir(path))

    original = original_dict["properties"]["Transactions"]
    adapted = adapted_dict["properties"]["Transactions"]
    assert adapted["minItems"] == original["minItems"]
    assert adapted["maxItems"] == original["maxItems"]


def test_roundtrip_preserves_format_annotations():
    path = os.path.join(SCHEMAS_ROOT, "invoice")
    original_dict, _, _ = load_schema_dir(path)
    adapted_dict, _, _ = inferred_to_resolved(from_schema_dir(path))

    original = original_dict["properties"]["bill_to"]["properties"]["email"]
    adapted = adapted_dict["properties"]["bill_to"]["properties"]["email"]
    assert adapted.get("format") == original.get("format") == "email"


def test_roundtrip_preserves_null_branch_description():
    """fcc-invoice tells the model *when* to emit null on the null branch."""
    path = os.path.join(SCHEMAS_ROOT, "fcc-invoice")
    adapted_dict, _, _ = inferred_to_resolved(from_schema_dir(path))

    branches = adapted_dict["properties"]["GrossTotal"]["anyOf"]
    null_branch = next(b for b in branches if b.get("type") == "null")
    assert null_branch["description"] == "Output null if not shown"


@pytest.mark.parametrize("schema_name", _bundled_schema_names())
def test_roundtrip_is_semantically_lossless(schema_name):
    """The strongest statement of the adapter's contract: nothing is lost.

    Compared after normalizing where an equivalent `description` sits (a
    property-level description and a lone non-null `anyOf` branch description
    mean the same thing) and after sorting `required`, whose order is
    insignificant in JSON Schema.
    """
    path = os.path.join(SCHEMAS_ROOT, schema_name)
    original_dict, guidance, _ = load_schema_dir(path)
    adapted_dict, _, _ = inferred_to_resolved(from_schema_dir(path))

    assert _normalize(original_dict) == _normalize(adapted_dict)


def _normalize(obj):
    """Canonicalize a JSON Schema for comparison (see caller for rationale)."""
    if isinstance(obj, dict):
        out = {k: _normalize(v) for k, v in obj.items()}
        if "required" in out and isinstance(out["required"], list):
            out["required"] = sorted(out["required"])
        # Hoist a description from the sole non-null anyOf branch to the property.
        for branch in out.get("anyOf", []):
            if isinstance(branch, dict) and branch.get("type") != "null" and "description" in branch:
                out.setdefault("description", branch["description"])
                if out["description"] == branch["description"]:
                    branch.pop("description")
        return out
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj

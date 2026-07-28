"""Round-trip converters between JSON Schema and the canonical ``InferredSchema``.

Doc-gen's bundled schemas are draft-07 JSON Schema documents (a single top-level
``object`` with ``properties``). These helpers lift such a document into an
``InferredSchema`` (one ``EntitySchema`` per document) and serialize it back, so
both generation modalities share one canonical model.

Mapping rules (JSON Schema -> InferredSchema):
- Top-level ``object`` -> a single ``EntitySchema`` (``entity_name`` = ``title``).
- Each property -> a ``FieldDefinition``.
- ``anyOf: [{...}, {"type": "null"}]`` (doc-gen's nullable idiom) -> ``nullable=True``
  with the type taken from the non-null branch.
- Fields absent from the object's ``required`` list -> ``nullable=True``.
- ``x-probability`` annotation (doc-gen's "sometimes present" marker) -> ``nullable=True``.
- Nested ``object`` -> ``FieldDefinition(type="object", children=[...])``.
- ``array`` of objects -> ``FieldDefinition(type="array", children=[...])`` (item fields).
- ``enum`` -> ``enum_values`` (and ``type`` recorded as ``"enum"``).
- ``minimum``/``maximum``/``minLength``/``maxLength``/``pattern`` -> the matching constraint.
"""
from __future__ import annotations

import json
import os

from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema

_JSON_SCHEMA_HEADER = "http://json-schema.org/draft-07/schema#"


# --- JSON Schema -> InferredSchema ------------------------------------------

def _unwrap_nullable(prop: dict) -> tuple[dict, bool]:
    """Resolve doc-gen's ``anyOf`` nullable idiom.

    Returns ``(effective_subschema, is_nullable)``. For a plain schema this is
    ``(prop, prop.get("type") == "null")``. For an ``anyOf`` with a null branch it
    returns the first non-null branch merged with any top-level ``description``.
    """
    if "anyOf" not in prop:
        return prop, prop.get("type") == "null"

    branches = prop["anyOf"]
    has_null = any(b.get("type") == "null" for b in branches)
    non_null = [b for b in branches if b.get("type") != "null"]
    sub = dict(non_null[0]) if non_null else {}
    # Prefer a description on the property itself, else keep the branch's.
    if "description" not in sub and "description" in prop:
        sub["description"] = prop["description"]
    return sub, has_null


def _parse_property(name: str, prop: dict, required: set[str]) -> FieldDefinition:
    sub, has_null = _unwrap_nullable(prop)

    nullable = has_null or (name not in required)
    if "x-probability" in prop or "x-probability" in sub:
        nullable = True

    jtype = sub.get("type", "string")
    description = prop.get("description") or sub.get("description") or ""

    field = FieldDefinition(name=name, type=jtype, description=description, nullable=nullable)

    if "minimum" in sub:
        field.min_value = sub["minimum"]
    if "maximum" in sub:
        field.max_value = sub["maximum"]
    if "minLength" in sub:
        field.min_length = sub["minLength"]
    if "maxLength" in sub:
        field.max_length = sub["maxLength"]
    if "pattern" in sub:
        field.pattern = sub["pattern"]
    if "enum" in sub:
        field.enum_values = sub["enum"]
        field.type = "enum"

    if jtype == "object" and "properties" in sub:
        field.children = _parse_properties(sub)
    elif jtype == "array":
        item_sub, _ = _unwrap_nullable(sub.get("items", {}) or {})
        if item_sub.get("type") == "object" and "properties" in item_sub:
            field.children = _parse_properties(item_sub)

    return field


def _parse_properties(obj: dict) -> list[FieldDefinition]:
    props = obj.get("properties", {})
    required = set(obj.get("required", []))
    return [_parse_property(name, prop, required) for name, prop in props.items()]


def from_json_schema(schema_dict: dict, guidance: str = "") -> InferredSchema:
    """Convert a JSON Schema document into an ``InferredSchema``.

    The document is treated as a single entity. ``title`` becomes the entity
    name; ``guidance`` (if given) is stored on the entity's ``generation_guidance``.
    """
    entity_name = str(schema_dict.get("title") or "entity")
    entity = EntitySchema(
        entity_name=entity_name,
        description=schema_dict.get("description", "") or "",
        fields=_parse_properties(schema_dict),
        generation_guidance=guidance,
    )
    return InferredSchema(entities=[entity])


# --- InferredSchema -> JSON Schema ------------------------------------------

def _field_to_prop(field: FieldDefinition) -> dict:
    inner: dict = {"type": "string" if field.type == "enum" else field.type}

    if field.min_value is not None:
        inner["minimum"] = field.min_value
    if field.max_value is not None:
        inner["maximum"] = field.max_value
    if field.min_length is not None:
        inner["minLength"] = field.min_length
    if field.max_length is not None:
        inner["maxLength"] = field.max_length
    if field.pattern is not None:
        inner["pattern"] = field.pattern
    if field.enum_values is not None:
        inner["enum"] = field.enum_values

    if field.type == "object" and field.children:
        sub = _fields_to_object(field.children)
        inner["properties"] = sub["properties"]
        if "required" in sub:
            inner["required"] = sub["required"]
    elif field.type == "array" and field.children:
        inner["items"] = _fields_to_object(field.children)

    if field.nullable:
        prop: dict = {"anyOf": [inner, {"type": "null"}]}
        if field.description:
            prop["description"] = field.description
        return prop

    if field.description:
        inner["description"] = field.description
    return inner


def _fields_to_object(fields: list[FieldDefinition]) -> dict:
    properties = {}
    required = []
    for field in fields:
        properties[field.name] = _field_to_prop(field)
        if not field.nullable:
            required.append(field.name)
    obj: dict = {"type": "object", "properties": properties}
    if required:
        obj["required"] = required
    return obj


def to_json_schema(schema: InferredSchema, entity_name: str | None = None) -> dict:
    """Convert one entity of an ``InferredSchema`` back into a JSON Schema document.

    If ``entity_name`` is given, that entity is serialized; otherwise the first
    entity is used.
    """
    if not schema.entities:
        raise ValueError("InferredSchema has no entities to serialize.")

    if entity_name is None:
        entity = schema.entities[0]
    else:
        matches = [e for e in schema.entities if e.entity_name == entity_name]
        if not matches:
            raise KeyError(f"No entity named {entity_name!r} in schema.")
        entity = matches[0]

    obj = _fields_to_object(entity.fields)
    result: dict = {
        "$schema": _JSON_SCHEMA_HEADER,
        "title": entity.entity_name,
    }
    if entity.description:
        result["description"] = entity.description
    result["type"] = obj["type"]
    result["properties"] = obj["properties"]
    if "required" in obj:
        result["required"] = obj["required"]
    return result


# --- schema-dir round-trip --------------------------------------------------

def from_schema_dir(path: str) -> InferredSchema:
    """Load a bundled schema dir (schema.json + *.md guidance) into ``InferredSchema``."""
    from seed_data.utils import load_schema_dir

    schema_dict, guidance, _samples = load_schema_dir(path)
    return from_json_schema(schema_dict, guidance=guidance)


def to_schema_dir(schema: InferredSchema, path: str, entity_name: str | None = None) -> None:
    """Serialize an ``InferredSchema`` entity to a schema dir (schema.json +
    generation_guidance.md) on disk."""
    os.makedirs(path, exist_ok=True)

    if entity_name is None:
        entity = schema.entities[0]
    else:
        entity = next(e for e in schema.entities if e.entity_name == entity_name)

    with open(os.path.join(path, "schema.json"), "w") as f:
        json.dump(to_json_schema(schema, entity_name=entity.entity_name), f, indent=2)
        f.write("\n")

    if entity.generation_guidance:
        with open(os.path.join(path, "generation_guidance.md"), "w") as f:
            f.write(entity.generation_guidance)
            if not entity.generation_guidance.endswith("\n"):
                f.write("\n")

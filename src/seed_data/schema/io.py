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
- ``x-probability`` (doc-gen's "sometimes present" marker) -> ``presence_probability``,
  round-tripped back out so per-document field variation survives the conversion.
- Membership in ``required`` is recorded separately on ``FieldDefinition.required``.
  A field can be both required (the key is always emitted) and nullable (its value
  may be null) — several bundled schemas rely on exactly that pairing, so the two
  are tracked independently rather than collapsed into one flag.
- Nested ``object`` -> ``FieldDefinition(type="object", children=[...])``.
- ``array`` of objects -> ``FieldDefinition(type="array", children=[...])`` (item fields);
  ``array`` of primitives -> ``item_type``/``item_description`` (no children to hold).
- ``enum`` -> ``enum_values`` (and ``type`` recorded as ``"enum"``); the values' own
  JSON type is kept in ``enum_base_type`` so a numeric enum rebuilds as numeric.
- ``minimum``/``maximum``/``minLength``/``maxLength``/``pattern``/``format``/
  ``minItems``/``maxItems`` -> the matching constraint.

Serializing back out (``to_json_schema``) has one extra job: ``InferredSchema``
uses a *semantic* type vocabulary (``email``, ``date``, ``float``, ``uuid``, ...)
that the schema-extraction prompt asks the model for, and those names are not
JSON Schema types. They are translated into a valid ``type`` plus a ``format``
hint, because the emitted document is fed to a real ``jsonschema`` validator in
:mod:`seed_data.stages.data` — an untranslated ``{"type": "uuid"}`` raises
``UnknownType`` there and fails generation outright.
"""
from __future__ import annotations

import json
import os

from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema

_JSON_SCHEMA_HEADER = "http://json-schema.org/draft-07/schema#"

#: Semantic ``FieldDefinition.type`` -> ``(json_schema_type, format_or_None)``.
#: Keys are the vocabulary ``prompts/schema_extraction.j2`` instructs the model to
#: emit; values are what draft-07 actually accepts. ``format`` is an annotation in
#: draft-07 (not asserted by default), so it guides the generator without making
#: otherwise-valid data fail validation.
_SEMANTIC_TYPES: dict[str, tuple[str, str | None]] = {
    "float": ("number", None),
    "double": ("number", None),
    "decimal": ("number", None),
    "int": ("integer", None),
    "bool": ("boolean", None),
    "str": ("string", None),
    "text": ("string", None),
    "date": ("string", "date"),
    "datetime": ("string", "date-time"),
    "timestamp": ("string", "date-time"),
    "time": ("string", "time"),
    "email": ("string", "email"),
    "uuid": ("string", "uuid"),
    "url": ("string", "uri"),
    "uri": ("string", "uri"),
    "ipv4": ("string", "ipv4"),
    "ipv6": ("string", "ipv6"),
    "hostname": ("string", "hostname"),
    # No standard draft-07 format exists for these; they are plain strings whose
    # shape is conveyed by the description (and `pattern`, when inferred).
    "phone": ("string", None),
    "currency": ("string", None),
    "name": ("string", None),
    "address": ("string", None),
}

#: The types draft-07 itself defines. Anything outside this set and outside
#: ``_SEMANTIC_TYPES`` is an unknown annotation and degrades to ``string``.
_JSON_SCHEMA_TYPES = frozenset(
    {"string", "number", "integer", "boolean", "object", "array", "null"}
)


def _to_json_type(type_name: str) -> tuple[str, str | None]:
    """Translate a ``FieldDefinition.type`` into ``(json_schema_type, format)``.

    Unrecognized names fall back to ``string`` rather than passing through: an
    invalid ``type`` makes the whole schema unusable for validation, while a
    string is always safe and the field's description still steers generation.
    """
    if type_name in _JSON_SCHEMA_TYPES:
        return type_name, None
    lowered = (type_name or "").strip().lower()
    if lowered in _JSON_SCHEMA_TYPES:
        return lowered, None
    if lowered in _SEMANTIC_TYPES:
        return _SEMANTIC_TYPES[lowered]
    return "string", None


# --- JSON Schema -> InferredSchema ------------------------------------------

def _unwrap_nullable(prop: dict) -> tuple[dict, bool, str | None]:
    """Resolve doc-gen's ``anyOf`` nullable idiom.

    Returns ``(effective_subschema, is_nullable, null_branch_description)``. For a
    plain schema this is ``(prop, prop.get("type") == "null", None)``. For an
    ``anyOf`` with a null branch it returns the first non-null branch merged with
    any top-level ``description``, plus the null branch's own description if it
    carries one (several bundled schemas say "Output null if not shown" there).
    """
    if "anyOf" not in prop:
        return prop, prop.get("type") == "null", None

    branches = prop["anyOf"]
    null_branches = [b for b in branches if b.get("type") == "null"]
    non_null = [b for b in branches if b.get("type") != "null"]
    sub = dict(non_null[0]) if non_null else {}
    # Prefer a description on the property itself, else keep the branch's.
    if "description" not in sub and "description" in prop:
        sub["description"] = prop["description"]
    null_description = next(
        (b["description"] for b in null_branches if b.get("description")), None
    )
    return sub, bool(null_branches), null_description


def _parse_property(name: str, prop: dict, required: set[str]) -> FieldDefinition:
    sub, has_null, null_description = _unwrap_nullable(prop)

    # `nullable` tracks only "the value may be null". Absence from `required` is
    # recorded on `required` itself, and "present in only some documents" is
    # `presence_probability` — folding either one into `nullable` would rewrite
    # the schema on the way back out (adding an `anyOf` null branch that the
    # source never had).
    jtype = sub.get("type", "string")
    description = prop.get("description") or sub.get("description") or ""

    # `required` (key presence) is orthogonal to `nullable` (value may be null):
    # doc-gen schemas mark fields as required *and* null-valued when the source
    # document omits them. Record both so the pair survives a round-trip.
    field = FieldDefinition(
        name=name, type=jtype, description=description,
        nullable=has_null, required=name in required,
        null_description=null_description,
    )

    probability = prop.get("x-probability", sub.get("x-probability"))
    if probability is not None:
        field.presence_probability = probability

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
    if "format" in sub:
        field.format = sub["format"]
    if "enum" in sub:
        # `enum_values` is declared `list[str]` for the structured-data consumers,
        # so stringify here (assigning the raw list would bypass the field
        # validator and make `model_dump_json` warn) and remember the values' real
        # JSON type so the enum rebuilds faithfully.
        if any(not isinstance(v, str) for v in sub["enum"] if v is not None):
            field.enum_base_type = jtype
        field.enum_values = [
            str(v) if v is not None else "None" for v in sub["enum"]
        ]
        field.type = "enum"

    if jtype == "object" and "properties" in sub:
        field.children = _parse_properties(sub)
    elif jtype == "array":
        if "minItems" in sub:
            field.min_items = sub["minItems"]
        if "maxItems" in sub:
            field.max_items = sub["maxItems"]
        item_sub, _, _ = _unwrap_nullable(sub.get("items", {}) or {})
        if item_sub.get("type") == "object" and "properties" in item_sub:
            field.children = _parse_properties(item_sub)
        elif item_sub:
            # An array of primitives has no sub-fields for `children` to hold, so
            # its element type would otherwise be lost and the rebuilt array
            # would accept anything.
            field.item_type = item_sub.get("type", "string")
            field.item_description = item_sub.get("description")

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

def _coerce_enum_values(values: list, base_type: str | None) -> list:
    """Restore an enum's original value type for emission.

    ``FieldDefinition.enum_values`` is ``list[str]``, so a numeric enum arrives
    here stringified. Emitting those strings under a numeric ``type`` produces a
    schema nothing can satisfy, so convert back when a base type was recorded.
    """
    if base_type == "integer":
        caster = int
    elif base_type == "number":
        caster = float
    else:
        return values

    coerced = []
    for value in values:
        try:
            coerced.append(caster(value))
        except (TypeError, ValueError):
            # A non-numeric member means the recorded base type no longer
            # describes the values; emit them as-is rather than dropping any.
            return values
    return coerced


def _field_to_prop(field: FieldDefinition) -> dict:
    if field.type == "enum":
        json_type, fmt = _to_json_type(field.enum_base_type or "string")
    else:
        json_type, fmt = _to_json_type(field.type)

    inner: dict = {"type": json_type}
    # An explicit `format` on the field wins over the one implied by a semantic
    # type, since it came from the source schema verbatim.
    if field.format is not None:
        inner["format"] = field.format
    elif fmt is not None:
        inner["format"] = fmt

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
        inner["enum"] = _coerce_enum_values(field.enum_values, field.enum_base_type)

    if json_type == "object" and field.children:
        sub = _fields_to_object(field.children)
        inner["properties"] = sub["properties"]
        if "required" in sub:
            inner["required"] = sub["required"]
    elif json_type == "array":
        if field.min_items is not None:
            inner["minItems"] = field.min_items
        if field.max_items is not None:
            inner["maxItems"] = field.max_items
        if field.children:
            inner["items"] = _fields_to_object(field.children)
        elif field.item_type is not None:
            item_type, item_fmt = _to_json_type(field.item_type)
            items: dict = {"type": item_type}
            if item_fmt is not None:
                items["format"] = item_fmt
            if field.item_description:
                items["description"] = field.item_description
            inner["items"] = items

    if field.nullable:
        null_branch: dict = {"type": "null"}
        if field.null_description:
            null_branch["description"] = field.null_description
        prop: dict = {"anyOf": [inner, null_branch]}
        if field.description:
            prop["description"] = field.description
        if field.presence_probability is not None:
            prop["x-probability"] = field.presence_probability
        return prop

    if field.description:
        inner["description"] = field.description
    if field.presence_probability is not None:
        inner["x-probability"] = field.presence_probability
    return inner


def _fields_to_object(fields: list[FieldDefinition]) -> dict:
    properties = {}
    required = []
    for field in fields:
        properties[field.name] = _field_to_prop(field)
        if field.is_required:
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


def from_legacy_schema_dir(path: str) -> InferredSchema:
    """Load a legacy doc-gen schema dir into an ``InferredSchema``.

    Same mechanics as :func:`from_schema_dir`; this name documents the specific
    use case of lifting one of the bundled document types into the canonical
    model so it can be round-tripped back through
    :func:`seed_data.schema.adapter.inferred_to_resolved` and generate documents.
    """
    return from_schema_dir(path)


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

"""Scrub PII out of a schema planned from real files.

``infer_schema`` / ``plan`` never keep the source documents, but the schema they
return can still *echo* real values: an enum built from a low-cardinality column
of customer names, a ``default`` or ``examples`` lifted from a sample, a naming
note in the generation guidance, few-shot ``reference_samples`` copied from real
rows. Generation then samples those values straight back into "synthetic" output.

:func:`scrub_schema` removes them before the schema is stored or reused:

* **Literal values** — enum members, ``default``/``const``/``examples``,
  ``pattern``, reference-sample cells — are sent to a :class:`PIIDetector`. A
  field with any PII value loses that value; an enum with *any* PII member is
  dropped whole (a detector that caught three names may have missed the fourth)
  and the field is re-typed semantically ("realistic, fictitious name") so the
  generator invents fresh values instead.
* **Free text** — descriptions, generation guidance, relationship notes — has each
  detected span replaced with ``[TYPE]``.
* **Reference samples** containing PII are dropped.

It **fails closed**: any detector error, or a detector that does not answer for
every input, raises :class:`ScrubError` and returns nothing — a half-scrubbed
schema is never handed back.

The :class:`ScrubReport` names *where* things were removed (field paths) and how
many, never the values themselves, so it is safe to store next to the dataset.

SEED stays detector-agnostic: pass anything implementing :class:`PIIDetector`
(e.g. an adapter over Bedrock Guardrails' ``ApplyGuardrail`` or Amazon Comprehend).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Iterator, Protocol, Sequence, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema


@dataclass(frozen=True)
class PIIFinding:
    """One detected PII span: its entity type (e.g. ``"NAME"``) and matched text."""

    type: str
    match: str


class PIIDetector(Protocol):
    """Anything that can find PII in a batch of strings.

    ``detect`` must return exactly one list of findings per input, in input order
    (an empty list for a clean string), and raise on failure. Batching, paging and
    retries are the implementation's business.
    """

    def detect(self, texts: Sequence[str]) -> list[list[PIIFinding]]: ...


class ScrubError(RuntimeError):
    """The schema could not be scrubbed; it must not be stored or used."""


@dataclass
class ScrubReport:
    """What was scrubbed — field paths and counts only, never values."""

    removed: list[str] = field(default_factory=list)
    retyped: list[str] = field(default_factory=list)
    text_redactions: int = 0
    samples_dropped: int = 0
    findings_by_type: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.removed or self.retyped or self.text_redactions or self.samples_dropped)

    def to_dict(self) -> dict:
        return {
            "removed": list(self.removed),
            "retyped": list(self.retyped),
            "text_redactions": self.text_redactions,
            "samples_dropped": self.samples_dropped,
            "findings_by_type": dict(self.findings_by_type),
        }


# PII entity types whose values have a SEED semantic type the generator already
# knows how to synthesize. Anything else stays a string with a descriptive hint.
_SEMANTIC_TYPES = {"EMAIL": "email", "PHONE": "phone", "URL": "url"}

# JSON Schema keys that hold literal values copied from data (vs. structure).
_JSON_VALUE_KEYS = ("default", "const")
_JSON_TEXT_KEYS = ("description", "title")


def scrub_schema(schema, detector: PIIDetector):
    """Return ``(scrubbed_schema, report)`` for a ``Schema`` or ``InferredSchema``.

    The input is not modified.

    Raises:
        ScrubError: if the detector fails or answers incompletely.
        TypeError: for an unsupported schema type.
    """
    from seed_data.schema import Schema
    from seed_data.schema.models import InferredSchema

    if isinstance(schema, InferredSchema):
        scrubber = _Scrubber(detector)
        out = schema.model_copy(deep=True)
        scrubber.prime(_inferred_strings(out))
        for entity in out.entities:
            scrubber.entity(entity)
        return out, scrubber.report
    if isinstance(schema, Schema):
        scrubber = _Scrubber(detector)
        # to_schema_dict covers both the json_schema and pydantic-model forms.
        json_schema = copy.deepcopy(schema.to_schema_dict())
        scrubber.prime([*_json_strings(json_schema), schema.generation_guidance])
        scrubber.json_schema(json_schema)
        guidance = scrubber.text(schema.generation_guidance)
        # sample_pdfs are real documents: never carried into a scrubbed schema.
        out = Schema(name=schema.name, json_schema=json_schema, generation_guidance=guidance)
        return out, scrubber.report
    raise TypeError(f"scrub_schema: unsupported schema type {type(schema).__name__}")


class _Scrubber:
    def __init__(self, detector: PIIDetector):
        self._detector = detector
        self._findings: dict[str, list[PIIFinding]] = {}
        self.report = ScrubReport()

    # -- detection -----------------------------------------------------------

    def prime(self, strings) -> None:
        """Detect over every distinct string once, up front (one batched call)."""
        unique = list(dict.fromkeys(s for s in strings if isinstance(s, str) and s.strip()))
        if not unique:
            return
        try:
            results = self._detector.detect(unique)
        except Exception as e:  # fail closed on *any* detector failure
            raise ScrubError(f"PII detector failed: {type(e).__name__}") from e
        if not isinstance(results, list) or len(results) != len(unique):
            raise ScrubError(
                f"PII detector returned {len(results) if isinstance(results, list) else 'no'} "
                f"result(s) for {len(unique)} input(s)"
            )
        self._findings = dict(zip(unique, results))

    def _hits(self, value) -> list[PIIFinding]:
        text = _as_text(value)
        if text is None or not text.strip():
            return []
        if text not in self._findings:
            # Every string reaching here was collected by prime(); a miss means the
            # collectors and the transform walk disagree — refuse rather than guess.
            raise ScrubError("internal: value was not submitted to the PII detector")
        hits = self._findings[text]
        for h in hits:
            self.report.findings_by_type[h.type] = self.report.findings_by_type.get(h.type, 0) + 1
        return hits

    def is_pii(self, value) -> list[PIIFinding]:
        return self._hits(value)

    def text(self, value: str | None) -> str | None:
        if not value:
            return value
        hits = self._hits(value)
        # Longest first, so a full name is replaced before a substring of it.
        for h in sorted(hits, key=lambda h: len(h.match), reverse=True):
            if h.match and h.match in value:
                value = value.replace(h.match, f"[{h.type}]")
                self.report.text_redactions += 1
        return value

    # -- InferredSchema ------------------------------------------------------

    def entity(self, entity: "EntitySchema") -> None:
        base = f"entities[{entity.entity_name}]"
        entity.description = self.text(entity.description)
        entity.generation_guidance = self.text(entity.generation_guidance)
        entity.relationships = [self.text(r) for r in entity.relationships]
        for f in entity.fields:
            self.field(f, f"{base}.fields[{f.name}]")
        kept = [rec for rec in entity.reference_samples if not self._record_has_pii(rec)]
        dropped = len(entity.reference_samples) - len(kept)
        if dropped:
            self.report.samples_dropped += dropped
            self.report.removed.append(f"{base}.reference_samples")
        entity.reference_samples = kept

    def field(self, f: "FieldDefinition", path: str) -> None:
        f.description = self.text(f.description)
        f.item_description = self.text(f.item_description)
        f.null_description = self.text(f.null_description)
        if f.default is not None and self.is_pii(f.default):
            f.default = None
            self.report.removed.append(f"{path}.default")
        if f.pattern and self.is_pii(f.pattern):
            f.pattern = None
            self.report.removed.append(f"{path}.pattern")
        if f.enum_values:
            hits = [h for v in f.enum_values for h in self.is_pii(v)]
            if hits:
                self._retype_field(f, hits)
                self.report.removed.append(f"{path}.enum_values")
                self.report.retyped.append(path)
        for child in f.children or []:
            self.field(child, f"{path}.children[{child.name}]")

    @staticmethod
    def _retype_field(f: "FieldDefinition", hits: list[PIIFinding]) -> None:
        from seed_data.schema.models import DistributionType

        f.enum_values = None
        if f.type == "enum":
            f.type = f.enum_base_type or "string"
        f.enum_base_type = None
        # A categorical distribution's weights were sized to the dropped enum.
        if f.distribution is not None and f.distribution.type == DistributionType.CATEGORICAL_WEIGHTED:
            f.distribution = None
        semantic = _semantic_type(hits)
        if semantic and f.type in ("string", "enum"):
            f.type = semantic
        f.description = _with_hint(f.description, hits)

    def _record_has_pii(self, record) -> bool:
        return any(self.is_pii(v) for v in _record_values(record))

    # -- JSON Schema (legacy Schema) -----------------------------------------

    def json_schema(self, root: dict) -> None:
        for node, path in list(_schema_nodes(root, "")):
            self._json_node(node, path)

    def _json_node(self, node: dict, path: str) -> None:
        for key in _JSON_TEXT_KEYS:
            if isinstance(node.get(key), str):
                node[key] = self.text(node[key])
        for key in (*_JSON_VALUE_KEYS, "examples"):
            if key in node and any(self.is_pii(v) for v in _record_values(node[key])):
                del node[key]
                self.report.removed.append(_join(path, key))
        if isinstance(node.get("pattern"), str) and self.is_pii(node["pattern"]):
            del node["pattern"]
            self.report.removed.append(_join(path, "pattern"))
        if isinstance(node.get("enum"), list):
            hits = [h for v in node["enum"] for h in self.is_pii(v)]
            if hits:
                del node["enum"]
                node.setdefault("type", "string")
                semantic = _semantic_type(hits)
                if semantic in ("email", "url") and "format" not in node:
                    node["format"] = "uri" if semantic == "url" else semantic
                node["description"] = _with_hint(node.get("description", ""), hits)
                self.report.removed.append(_join(path, "enum"))
                self.report.retyped.append(path or "$")


# -- string collection (must cover everything the transforms inspect) --------

def _inferred_strings(schema: "InferredSchema") -> Iterator[str]:
    for e in schema.entities:
        yield e.description
        yield e.generation_guidance
        yield from e.relationships
        for rec in e.reference_samples:
            yield from _record_values(rec)
        for f in e.fields:
            yield from _field_strings(f)


def _field_strings(f: "FieldDefinition") -> Iterator[str]:
    for v in (f.description, f.item_description, f.null_description, f.default, f.pattern):
        t = _as_text(v)
        if t is not None:
            yield t
    for v in f.enum_values or []:
        t = _as_text(v)
        if t is not None:
            yield t
    for child in f.children or []:
        yield from _field_strings(child)


# Where JSON Schema nests subschemas. Walking only these positions (rather than
# every dict) keeps a *property* named "description" or "default" from being read
# as the keyword, and keeps literal object values (an object ``default``) from
# being walked as if they were schemas.
_SUBSCHEMA_MAPS = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")
_SUBSCHEMA_ONE = ("items", "additionalProperties", "additionalItems", "not", "if", "then",
                  "else", "contains", "propertyNames", "unevaluatedItems", "unevaluatedProperties")
_SUBSCHEMA_LISTS = ("allOf", "anyOf", "oneOf", "prefixItems", "items")


def _schema_nodes(node, path: str) -> Iterator[tuple[dict, str]]:
    """Every schema object in a JSON Schema, with a dotted path to it."""
    if not isinstance(node, dict):
        return
    yield node, path
    for key in _SUBSCHEMA_MAPS:
        if isinstance(node.get(key), dict):
            for name, child in node[key].items():
                yield from _schema_nodes(child, _join(path, f"{key}.{name}"))
    for key in _SUBSCHEMA_ONE:
        if isinstance(node.get(key), dict):
            yield from _schema_nodes(node[key], _join(path, key))
    for key in _SUBSCHEMA_LISTS:
        if isinstance(node.get(key), list):
            for i, child in enumerate(node[key]):
                yield from _schema_nodes(child, _join(path, f"{key}[{i}]"))


def _json_strings(root: dict) -> Iterator[str]:
    for node, _ in _schema_nodes(root, ""):
        for key in _JSON_TEXT_KEYS:
            if isinstance(node.get(key), str):
                yield node[key]
        for key in (*_JSON_VALUE_KEYS, "examples", "enum"):
            if key in node:
                yield from _record_values(node[key])
        if isinstance(node.get("pattern"), str):
            yield node["pattern"]


def _record_values(value) -> Iterator[str]:
    """Every scalar inside a value (record dicts and lists flattened), as text."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _record_values(v)
    elif isinstance(value, list):
        for v in value:
            yield from _record_values(v)
    else:
        t = _as_text(value)
        if t is not None:
            yield t


def _as_text(value) -> str | None:
    # bool before int: True is an int, and is never PII.
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _semantic_type(hits: list[PIIFinding]) -> str | None:
    types = {_SEMANTIC_TYPES.get(h.type) for h in hits}
    return types.pop() if len(types) == 1 else None


def _with_hint(description: str, hits: list[PIIFinding]) -> str:
    labels = sorted({h.type.lower().replace("_", " ") for h in hits})
    hint = (f"Values are synthetic: generate realistic, fictitious {', '.join(labels)} "
            "values; do not reuse real ones.")
    return f"{description.rstrip()} {hint}".strip() if description else hint


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key

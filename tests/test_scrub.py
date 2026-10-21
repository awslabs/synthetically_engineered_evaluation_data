"""Tests for seed_data.scrub — PII scrubbing of schemas planned from real files.

A fake detector stands in for Guardrails/Comprehend: it reports any of a fixed set
of "real" strings found inside an input, with a type. That makes every assertion
about what was removed, kept, or redacted exact.
"""
import json

import pytest

from seed_data.schema import Schema
from seed_data.schema.models import (
    DistributionSpec, DistributionType, EntitySchema, FieldDefinition, InferredSchema,
)
from seed_data.scrub import PIIFinding, ScrubError, scrub_schema

PII = {
    "Jane Doe": "NAME",
    "Jane": "NAME",
    "John Smith": "NAME",
    "jane@example.com": "EMAIL",
    "555-0100": "PHONE",
    "123-45-6789": "US_SOCIAL_SECURITY_NUMBER",
}


class FakeDetector:
    def __init__(self):
        self.calls = []

    def detect(self, texts):
        self.calls.append(list(texts))
        return [[PIIFinding(t, m) for m, t in PII.items() if m in text] for text in texts]


class RaisingDetector:
    def detect(self, texts):
        raise ConnectionError("guardrail unreachable")


class ShortDetector:
    def detect(self, texts):
        return [[] for _ in texts][:-1]


def _field(name, **kw):
    return FieldDefinition(name=name, type=kw.pop("type", "string"), **kw)


def _inferred(**entity_kw):
    entity_kw.setdefault("entity_name", "Customer")
    entity_kw.setdefault("fields", [])
    return InferredSchema(entities=[EntitySchema(**entity_kw)])


def _all_text(obj) -> str:
    return json.dumps(obj, default=str)


# --- InferredSchema ------------------------------------------------------------

def test_enum_with_any_pii_member_is_dropped_and_field_retyped():
    schema = _inferred(fields=[_field(
        "customer_name", type="enum", enum_values=["Jane Doe", "John Smith", "Acme"],
        enum_base_type="string",
        distribution=DistributionSpec(type=DistributionType.CATEGORICAL_WEIGHTED,
                                      params={"weights": [0.5, 0.3, 0.2]}),
        description="Customer full name",
    )])
    out, report = scrub_schema(schema, FakeDetector())

    f = out.entities[0].fields[0]
    assert f.enum_values is None          # whole enum gone, incl. the clean "Acme"
    assert f.type == "string"
    assert f.distribution is None         # weights were sized to the dropped enum
    assert "fictitious name" in f.description
    assert f.description.startswith("Customer full name")
    assert report.removed == ["entities[Customer].fields[customer_name].enum_values"]
    assert report.retyped == ["entities[Customer].fields[customer_name]"]


def test_clean_enum_is_kept():
    schema = _inferred(fields=[_field("status", type="enum", enum_values=["Running", "Idle"])])
    out, report = scrub_schema(schema, FakeDetector())
    assert out.entities[0].fields[0].enum_values == ["Running", "Idle"]
    assert not report.changed


def test_email_enum_is_retyped_semantically():
    schema = _inferred(fields=[_field("contact", type="enum", enum_values=["jane@example.com"])])
    out, _ = scrub_schema(schema, FakeDetector())
    assert out.entities[0].fields[0].type == "email"


def test_pii_default_and_pattern_are_removed():
    schema = _inferred(fields=[_field("phone", default="555-0100", pattern="^555-0100$")])
    out, report = scrub_schema(schema, FakeDetector())
    f = out.entities[0].fields[0]
    assert f.default is None and f.pattern is None
    assert set(report.removed) == {
        "entities[Customer].fields[phone].default",
        "entities[Customer].fields[phone].pattern",
    }


def test_free_text_is_redacted_longest_match_first():
    schema = _inferred(
        description="Accounts like Jane Doe's",
        generation_guidance="Names look like Jane Doe or John Smith; SSN 123-45-6789.",
        relationships=["belongs_to: Jane Doe"],
    )
    out, report = scrub_schema(schema, FakeDetector())
    e = out.entities[0]
    # "Jane Doe" replaced as one NAME, not "[NAME] Doe" from the shorter "Jane".
    assert e.description == "Accounts like [NAME]'s"
    assert e.generation_guidance == (
        "Names look like [NAME] or [NAME]; SSN [US_SOCIAL_SECURITY_NUMBER]."
    )
    assert e.relationships == ["belongs_to: [NAME]"]
    assert report.text_redactions >= 4


def test_reference_samples_with_pii_are_dropped():
    schema = _inferred(reference_samples=[
        {"name": "Jane Doe", "tier": "gold"},
        {"name": "Acme", "tier": "silver"},
        {"contact": {"phones": ["555-0100"]}},     # nested values are checked too
    ])
    out, report = scrub_schema(schema, FakeDetector())
    assert out.entities[0].reference_samples == [{"name": "Acme", "tier": "silver"}]
    assert report.samples_dropped == 2


def test_nested_children_are_scrubbed():
    schema = _inferred(fields=[_field("address", type="object", children=[
        _field("recipient", type="enum", enum_values=["John Smith"]),
    ])])
    out, report = scrub_schema(schema, FakeDetector())
    assert out.entities[0].fields[0].children[0].enum_values is None
    assert report.retyped == ["entities[Customer].fields[address].children[recipient]"]


def test_numeric_pii_values_are_checked():
    """An SSN or phone stored as a number is still PII; booleans never are."""
    class NumericDetector(FakeDetector):
        def detect(self, texts):
            return [[PIIFinding("PHONE", t)] if t == "5550100" else [] for t in texts]

    schema = _inferred(reference_samples=[{"phone": 5550100}, {"active": True}])
    out, _ = scrub_schema(schema, NumericDetector())
    assert out.entities[0].reference_samples == [{"active": True}]


def test_a_field_shared_by_two_entities_is_scrubbed_in_both():
    """`model_copy(deep=True)` keeps aliasing: the shared field was walked twice, and
    the second walk read the first walk's rewritten description and raised."""
    shared = _field("rep", type="enum", enum_values=["Jane Doe"])
    schema = InferredSchema(entities=[EntitySchema(entity_name="A", fields=[shared]),
                                      EntitySchema(entity_name="B", fields=[shared])])
    out, report = scrub_schema(schema, FakeDetector())

    assert [e.fields[0].enum_values for e in out.entities] == [None, None]
    assert report.retyped == ["entities[A].fields[rep]", "entities[B].fields[rep]"]
    assert shared.enum_values == ["Jane Doe"]          # input untouched


# --- legacy Schema (JSON Schema) ----------------------------------------------

def _doc_schema():
    return Schema(
        name="invoice",
        json_schema={
            "type": "object",
            "description": "Invoice for Jane Doe",
            "properties": {
                # A *property* named like a keyword must be walked as a schema.
                "description": {"type": "string", "enum": ["Jane Doe", "Bob"]},
                "default": {"type": "string", "default": "John Smith"},
                "bill_to": {
                    "type": "object",
                    "default": {"name": "Jane Doe"},          # object literal default
                    "properties": {
                        "email": {"type": "string", "examples": ["jane@example.com"]},
                        "status": {"type": "string", "enum": ["paid", "open"]},
                    },
                },
                "lines": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"rep": {"type": "string", "const": "John Smith"}},
                }},
            },
        },
        generation_guidance="Signed by John Smith.",
    )


def test_json_schema_scrub_walks_subschemas_not_keywords():
    out, report = scrub_schema(_doc_schema(), FakeDetector())
    js = out.json_schema
    props = js["properties"]

    assert js["description"] == "Invoice for [NAME]"
    assert "enum" not in props["description"]                       # property named "description"
    assert "fictitious name" in props["description"]["description"]
    assert "default" not in props["default"]                        # property named "default"
    assert "default" not in props["bill_to"]                        # object default with PII
    assert "examples" not in props["bill_to"]["properties"]["email"]
    assert props["bill_to"]["properties"]["status"]["enum"] == ["paid", "open"]
    assert "const" not in props["lines"]["items"]["properties"]["rep"]
    assert out.generation_guidance == "Signed by [NAME]."
    assert "properties.description" in report.retyped
    assert "properties.lines.items.properties.rep.const" in report.removed


def test_json_schema_scrub_does_not_mutate_input_or_carry_samples(tmp_path):
    pdf = tmp_path / "real.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    original = _doc_schema()
    original = Schema(name=original.name, json_schema=original.json_schema,
                      generation_guidance=original.generation_guidance, sample_pdfs=[str(pdf)])
    before = json.dumps(original.json_schema, sort_keys=True)

    out, _ = scrub_schema(original, FakeDetector())

    assert json.dumps(original.json_schema, sort_keys=True) == before
    assert out.sample_pdfs == []          # real documents never ride along


def test_a_sub_schema_shared_by_two_properties_is_scrubbed_at_both():
    """Same aliasing through `copy.deepcopy`, for a dict reused in code."""
    addr = {"type": "object", "properties": {
        "contact": {"type": "string", "enum": ["Jane Doe", "John Smith"]}}}
    schema = Schema(name="invoice", json_schema={
        "type": "object", "properties": {"billing": addr, "shipping": addr}})
    out, report = scrub_schema(schema, FakeDetector())

    for side in ("billing", "shipping"):
        assert "enum" not in out.json_schema["properties"][side]["properties"]["contact"]
    assert report.removed == ["properties.billing.properties.contact.enum",
                              "properties.shipping.properties.contact.enum"]


# --- fail closed, batching, report hygiene --------------------------------------

@pytest.mark.parametrize("detector", [RaisingDetector(), ShortDetector()])
def test_detector_failure_fails_closed(detector):
    with pytest.raises(ScrubError):
        scrub_schema(_doc_schema(), detector)
    with pytest.raises(ScrubError):
        scrub_schema(_inferred(description="Jane Doe"), detector)


def test_detector_error_message_carries_no_values():
    class LeakyDetector:
        def detect(self, texts):
            raise ValueError(f"bad input: {texts[0]}")

    with pytest.raises(ScrubError) as exc:
        scrub_schema(_inferred(description="Jane Doe"), LeakyDetector())
    assert "Jane" not in str(exc.value)


@pytest.mark.parametrize("answer", [
    lambda texts: [None] + [[] for _ in texts[1:]],                   # not a list per input
    lambda texts: [[{"type": "NAME", "match": t}] for t in texts],    # not PIIFinding
], ids=["none-for-an-input", "dict-findings"])
def test_malformed_detector_answers_fail_closed(answer):
    """The length check alone let these through to a `TypeError` mid-walk, which a
    host catching `ScrubError` to block storage would not catch."""
    class Malformed:
        def detect(self, texts):
            return answer(texts)

    schema = _inferred(description="Jane Doe", fields=[_field("a", description="plain")])
    with pytest.raises(ScrubError, match="malformed"):
        scrub_schema(schema, Malformed())


@pytest.mark.parametrize("match", ["jane doe", ""], ids=["not-in-text", "empty"])
def test_a_finding_whose_span_is_not_in_its_input_fails_closed(match):
    """Spans are redacted by literal replacement. One that is not in the text (an
    adapter that normalized case, say) used to be skipped, storing the name."""
    class Normalizing:
        def detect(self, texts):
            return [[PIIFinding("NAME", match)] if "Jane Doe" in t else [] for t in texts]

    with pytest.raises(ScrubError, match="does not occur") as exc:
        scrub_schema(_inferred(description="Accounts like Jane Doe's"), Normalizing())
    assert "jane" not in str(exc.value).lower()


def test_one_batched_detector_call_with_unique_strings():
    det = FakeDetector()
    scrub_schema(_inferred(description="Jane Doe", generation_guidance="Jane Doe",
                           fields=[_field("a", description="Jane Doe")]), det)
    assert len(det.calls) == 1
    assert det.calls[0].count("Jane Doe") == 1


def test_report_never_contains_values():
    _, r1 = scrub_schema(_doc_schema(), FakeDetector())
    _, r2 = scrub_schema(_inferred(
        fields=[_field("n", type="enum", enum_values=["Jane Doe"], default="John Smith")],
        reference_samples=[{"x": "555-0100"}],
    ), FakeDetector())
    for report in (r1, r2):
        dumped = _all_text(report.to_dict())
        for value in PII:
            assert value not in dumped
        assert report.changed


def test_findings_are_counted_once_per_distinct_string():
    """Counted at lookup, a string used as both description and default counted
    twice, and a value after an earlier hit in the same sample never counted."""
    schema = _inferred(
        fields=[_field("owner", description="John Smith", default="John Smith")],
        reference_samples=[{"a": "John Smith", "b": "555-0100"}],
    )
    _, report = scrub_schema(schema, FakeDetector())
    assert report.findings_by_type == {"NAME": 1, "PHONE": 1}


def test_unsupported_type_raises():
    with pytest.raises(TypeError):
        scrub_schema({"type": "object"}, FakeDetector())

"""Structured-generation tests — distribution generator, post-processing
(validate/correct/filter), graph build, and the run_structured facade.

Everything here is deterministic: the distribution generator is seeded, the
post-processing is pure Python, and the graph is only *built* (not executed) so
no Bedrock calls happen. `run_structured`'s LLM path is mocked.
"""
import json
import random
import re

import pytest

pytest.importorskip("numpy", reason="requires the [structured] optional dependencies")
pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")

from seed_data.schema.models import (  # noqa: E402
    Cardinality,
    DistributionSpec,
    DistributionType,
    EntitySchema,
    FieldDefinition,
    InferredSchema,
    RelationshipDefinition,
)
from seed_data.structured.distributions.generator import DistributionGenerator  # noqa: E402
from seed_data.structured.generation import (  # noqa: E402
    _entity_seed,
    _expand_char_class,
    _generate_from_pattern,
    _generate_programmatic,
    _parse_json_lenient,
)
from seed_data.structured.postprocessing.corrector import RecordCorrector  # noqa: E402
from seed_data.structured.postprocessing.pipeline import (  # noqa: E402
    PostProcessingConfig,
    PostProcessingPipeline,
)
from seed_data.structured.postprocessing.validator import RecordValidator  # noqa: E402


# --- DistributionGenerator --------------------------------------------------

def test_numeric_generation_respects_range_and_seed():
    field = FieldDefinition(
        name="age", type="integer", min_value=18, max_value=65,
        distribution=DistributionSpec(type=DistributionType.NORMAL,
                                      params={"mean": 40, "std": 10}),
    )
    gen1 = DistributionGenerator(seed=42)
    gen2 = DistributionGenerator(seed=42)
    values1 = gen1.generate_numeric(field, 100)
    values2 = gen2.generate_numeric(field, 100)

    assert values1 == values2  # deterministic with the same seed
    assert len(values1) == 100
    assert all(18 <= v <= 65 for v in values1)
    assert all(isinstance(v, int) for v in values1)


def test_categorical_generation_only_uses_enum_values():
    field = FieldDefinition(
        name="status", type="enum", enum_values=["a", "b", "c"],
        distribution=DistributionSpec(type=DistributionType.CATEGORICAL_WEIGHTED,
                                      params={"weights": [0.7, 0.2, 0.1]}),
    )
    gen = DistributionGenerator(seed=7)
    values = gen.generate_categorical(field, 200)
    assert set(values) <= {"a", "b", "c"}
    assert len(values) == 200


def test_default_generation_no_distribution():
    field = FieldDefinition(name="score", type="float", min_value=0.0, max_value=1.0)
    gen = DistributionGenerator(seed=1)
    values = gen.generate_field_values(field, 50)
    assert len(values) == 50
    assert all(0.0 <= v <= 1.0 for v in values)


# --- pattern generation -----------------------------------------------------

def test_anchored_pattern_produces_self_matching_values():
    """Regression: `^...$` anchors were emitted as literal characters.

    JSON Schema `pattern` values are conventionally anchored, so this was the
    common case: '^[A-Z]{3}-[0-9]{4}$' produced '^YNL-6770$', which fails its
    own pattern and burns the whole correction budget re-failing.
    """
    pattern = r"^[A-Z]{3}-[0-9]{4}$"
    values = _generate_from_pattern(pattern, 5, set())
    assert len(values) == 5
    for v in values:
        assert re.fullmatch(pattern, v), v


def test_anchored_and_unanchored_patterns_agree():
    anchored = _generate_from_pattern(r"^[A-Z]{2}[0-9]{3}$", 4, set())
    plain = _generate_from_pattern(r"[A-Z]{2}[0-9]{3}", 4, set())
    for v in anchored + plain:
        assert re.fullmatch(r"[A-Z]{2}[0-9]{3}", v), v


def test_corrected_pattern_value_survives_revalidation():
    """The compounding case: _correct_pattern uses the same helper, so an
    anchored field used to be 'corrected' into another invalid value."""
    schema = InferredSchema(entities=[EntitySchema(entity_name="Part", fields=[
        FieldDefinition(name="sku", type="string", pattern=r"^[A-Z]{3}-[0-9]{4}$"),
    ])])
    data = {"Part": [{"sku": "not-a-sku"}]}

    validation = RecordValidator().validate_dataset(data, schema)
    assert any(v.violation_type == "pattern_violation" for v in validation.violations)

    corrected = RecordCorrector().correct_dataset(data, validation.violations, schema)
    revalidation = RecordValidator().validate_dataset(corrected, schema)
    assert not [v for v in revalidation.violations if v.violation_type == "pattern_violation"], (
        f"correction produced another invalid value: {corrected['Part'][0]['sku']!r}"
    )


@pytest.mark.parametrize("pattern", [r"[0-9A-F]{6}", r"[B-D]{4}", r"[a-c0-2]{5}"])
def test_character_class_ranges_only_emit_in_class_characters(pattern):
    """Regression: an unmapped class fell through to its literal characters, so
    '[0-9A-F]' sampled '-' as a value character ('90---A')."""
    for value in _generate_from_pattern(pattern, 5, set()):
        assert re.fullmatch(pattern, value), value


@pytest.mark.parametrize(("char_class", "expected"), [
    ("[a-]", {"a", "-"}),      # trailing '-' is a literal
    ("[-a]", {"-", "a"}),      # leading '-' is a literal
    ("[0-9A-F]", set("0123456789ABCDEF")),
    ("[B-D]", set("BCD")),
])
def test_expand_char_class_handles_literal_dash_and_ranges(char_class, expected):
    assert set(_expand_char_class(char_class)) == expected


def test_exhausted_pattern_space_returns_bounded_values():
    """Regression: the uniqueness fallback suffixed the *previous* value, so
    values grew without bound ('6_10_11_12_13') and stopped matching."""
    values = _generate_from_pattern(r"[0-9]{1}", 14, set())
    assert len(values) == 14
    assert len(set(values)) == 14, "fallback must still yield unique values"
    assert max(len(v) for v in values) <= 4, f"unbounded growth: {values}"


def test_parse_json_lenient_recovers_object_with_trailing_garbage():
    """The old suffix heuristic appended '}' after stripping, over-closing the
    object and returning None for input that raw_decode handles."""
    assert _parse_json_lenient('{"data": {"E": [1]}}]}') == {"data": {"E": [1]}}
    assert _parse_json_lenient('  {"a": 1}  ') == {"a": 1}
    assert _parse_json_lenient("[1, 2]") is None, "a JSON array is not a record dict"
    assert _parse_json_lenient("not json at all") is None


# --- seed reproducibility ---------------------------------------------------

def _seedable_entity() -> EntitySchema:
    return EntitySchema(entity_name="Widget", fields=[
        FieldDefinition(name="sku", type="string", unique=True,
                        pattern=r"^[A-Z]{3}-[0-9]{4}$"),
        FieldDefinition(name="qty", type="integer", min_value=1, max_value=999,
                        distribution=DistributionSpec(type=DistributionType.NORMAL,
                                                      params={"mean": 100, "std": 30})),
        FieldDefinition(name="grade", type="enum", enum_values=["A", "B", "C"]),
    ])


def _gen(seed):
    # defer_llm so no Bedrock call happens — the seedable half is the
    # programmatic one anyway.
    return _generate_programmatic(
        "Widget", _seedable_entity(), 8, [], {}, defer_llm=True, seed=seed,
    )


def test_same_seed_reproduces_programmatic_columns():
    """Regression: DistributionGenerator() was constructed with no seed, so the
    --seed flag existed but structured output was never reproducible."""
    assert _gen(99) == _gen(99)


def test_different_seed_produces_different_data():
    assert _gen(99) != _gen(100)


def test_no_seed_still_varies_between_runs():
    """seed=None must keep the previous non-deterministic behaviour."""
    assert _gen(None) != _gen(None)


def test_pattern_generation_is_seedable():
    seeded = _generate_from_pattern(r"^[A-Z]{4}$", 5, set(), random.Random(3))
    again = _generate_from_pattern(r"^[A-Z]{4}$", 5, set(), random.Random(3))
    assert seeded == again


def test_entity_seeds_are_derived_and_independent():
    """One seed shared across entities would make them draw identical values —
    a correlation the schema never asked for. Derivation must be stable across
    processes, so crc32 rather than the salted builtin hash()."""
    assert _entity_seed(7, "Alpha") != _entity_seed(7, "Beta")
    assert _entity_seed(7, "Alpha") == _entity_seed(7, "Alpha")
    assert _entity_seed(None, "Alpha") is None


def test_seed_reaches_bulk_generation_from_the_pipeline():
    """The wiring itself: build_graph_pipeline must forward its seed to
    bulk_generation_agent, offset per attempt so a retry redraws."""
    from seed_data.structured import pipeline as pipeline_mod

    calls = []

    def _fake_tool(name):
        if name != "bulk_generation_agent":
            return lambda **kwargs: "{}"

        def _bulk(**kwargs):
            calls.append(kwargs.get("seed"))
            return json.dumps({"data": {}})
        return _bulk

    original = pipeline_mod._get_tool_func
    pipeline_mod._get_tool_func = _fake_tool
    try:
        schema = InferredSchema(entities=[EntitySchema(
            entity_name="Widget",
            fields=[FieldDefinition(name="qty", type="integer")],
        )])
        _graph, _ctx, ps = pipeline_mod.build_graph_pipeline(schema, seed=1234)
        # Reach the generation node directly rather than executing the graph,
        # which would need Bedrock for the surrounding nodes.
        node = _graph.nodes["bulk_generation"].executor
        node.func("")
        node.func("")
    finally:
        pipeline_mod._get_tool_func = original

    # Attempt 1 → 1235, attempt 2 → 1236: reproducible overall, but a retry does
    # not redraw the identical values that just failed the gate.
    assert calls == [1235, 1236]
    assert ps.generation_attempts == 2


# --- RecordValidator --------------------------------------------------------

def _schema_with_constraints() -> InferredSchema:
    return InferredSchema(entities=[
        EntitySchema(
            entity_name="Customer",
            fields=[
                FieldDefinition(name="age", type="integer", min_value=18, max_value=90),
                FieldDefinition(name="status", type="enum",
                                enum_values=["active", "inactive"]),
                FieldDefinition(name="email", type="string", nullable=False),
            ],
        )
    ])


def test_validator_flags_range_and_enum_violations():
    data = {"Customer": [
        {"age": 25, "status": "active", "email": "a@x.com"},   # valid
        {"age": 200, "status": "active", "email": "b@x.com"},  # range violation (fixable)
        {"age": 30, "status": "unknown", "email": "c@x.com"},  # enum violation (fixable)
    ]}
    result = RecordValidator().validate_dataset(data, _schema_with_constraints())

    types = {v.violation_type for v in result.violations}
    assert "range_violation" in types
    assert "enum_violation" in types
    assert result.fixable_count >= 2


def test_validator_flags_missing_non_nullable():
    data = {"Customer": [{"age": 25, "status": "active", "email": ""}]}
    result = RecordValidator().validate_dataset(data, _schema_with_constraints())
    assert any(v.violation_type == "nullable_violation" for v in result.violations)


def test_validator_flags_duplicate_unique_values():
    """Regression: uniqueness was never checked, so a table of identical primary
    keys validated as fully valid. StructuralMetrics counts duplicates but its
    penalty is capped too low to ever fail the gate on its own."""
    schema = InferredSchema(entities=[EntitySchema(entity_name="Customer", fields=[
        FieldDefinition(name="id", type="integer", unique=True, nullable=False),
    ])])
    result = RecordValidator().validate_dataset({"Customer": [{"id": 1}] * 3}, schema)

    dupes = [v for v in result.violations if v.violation_type == "uniqueness_violation"]
    # First occurrence is left alone; the two later ones are flagged, so
    # correcting or dropping them leaves the column unique.
    assert [v.record_index for v in dupes] == [1, 2]
    assert all(v.fixable for v in dupes)
    assert result.valid_records == 1


def test_validator_ignores_nulls_when_checking_uniqueness():
    """Repeated nulls are the nullable check's business, not uniqueness'."""
    schema = InferredSchema(entities=[EntitySchema(entity_name="Customer", fields=[
        FieldDefinition(name="ref", type="string", unique=True, nullable=True),
    ])])
    result = RecordValidator().validate_dataset(
        {"Customer": [{"ref": None}, {"ref": None}, {"ref": "a"}]}, schema
    )
    assert not [v for v in result.violations if v.violation_type == "uniqueness_violation"]


def test_corrector_makes_duplicate_unique_values_unique():
    schema = InferredSchema(entities=[EntitySchema(entity_name="Customer", fields=[
        FieldDefinition(name="id", type="integer", unique=True, nullable=False),
        FieldDefinition(name="code", type="string", unique=True, nullable=False,
                        pattern=r"^[A-Z]{3}-[0-9]{4}$"),
    ])])
    data = {"Customer": [{"id": 1, "code": "ABC-1234"}] * 3}

    validation = RecordValidator().validate_dataset(data, schema)
    corrected = RecordCorrector().correct_dataset(data, validation.violations, schema)

    assert len({r["id"] for r in corrected["Customer"]}) == 3
    assert len({r["code"] for r in corrected["Customer"]}) == 3
    for record in corrected["Customer"]:
        assert re.fullmatch(r"[A-Z]{3}-[0-9]{4}", record["code"]), record
    assert not RecordValidator().validate_dataset(corrected, schema).violations


def test_validator_rejects_non_integral_value_in_integer_field():
    """Regression: _check_type called int(value), and int(3.7) truncates
    silently — so a float in an integer column passed and the wrong value was
    exported."""
    schema = InferredSchema(entities=[EntitySchema(entity_name="Customer", fields=[
        FieldDefinition(name="count", type="integer", nullable=False),
    ])])
    result = RecordValidator().validate_dataset(
        {"Customer": [{"count": 3}, {"count": 3.7}, {"count": "4.2"}]}, schema
    )

    flagged = [v.record_index for v in result.violations if v.violation_type == "type_error"]
    assert flagged == [1, 2]
    # 3.0 is integral — a float-typed whole number is still a valid integer.
    ok = RecordValidator().validate_dataset({"Customer": [{"count": 3.0}]}, schema)
    assert not ok.violations


def test_validator_enforces_pattern_on_non_string_types():
    """Regression: the pattern check was gated on type in (string, email, phone,
    enum) — exactly excluding the semantic types _needs_llm routes to the LLM, so
    uuid/url values carried a pattern that was never checked."""
    schema = InferredSchema(entities=[EntitySchema(entity_name="Thing", fields=[
        FieldDefinition(name="uid", type="uuid", nullable=False, pattern=r"^[0-9a-f]{8}$"),
    ])])
    result = RecordValidator().validate_dataset({"Thing": [{"uid": "GARBAGE"}]}, schema)
    assert any(v.violation_type == "pattern_violation" for v in result.violations)


def test_validator_pattern_check_is_fullmatch_not_prefix():
    """Regression: re.match accepted a valid prefix followed by garbage.
    generation._samples_match_pattern already used fullmatch; the two must agree."""
    schema = InferredSchema(entities=[EntitySchema(entity_name="Part", fields=[
        FieldDefinition(name="sku", type="string", pattern=r"^[A-Z]{3}-[0-9]{4}$"),
    ])])
    result = RecordValidator().validate_dataset({"Part": [{"sku": "ABC-1234-GARBAGE"}]}, schema)
    assert any(v.violation_type == "pattern_violation" for v in result.violations)


def test_validator_tolerates_uncompilable_pattern():
    """A malformed pattern from an LLM-inferred schema must not crash validation."""
    schema = InferredSchema(entities=[EntitySchema(entity_name="Part", fields=[
        FieldDefinition(name="sku", type="string", pattern="[unclosed"),
    ])])
    result = RecordValidator().validate_dataset({"Part": [{"sku": "anything"}]}, schema)
    assert not [v for v in result.violations if v.violation_type == "pattern_violation"]


# --- RecordCorrector --------------------------------------------------------

def test_corrector_clips_range_and_fixes_enum():
    schema = _schema_with_constraints()
    data = {"Customer": [
        {"age": 200, "status": "active", "email": "b@x.com"},
        {"age": 30, "status": "Active", "email": "c@x.com"},  # case mismatch enum
    ]}
    validation = RecordValidator().validate_dataset(data, schema)
    corrected = RecordCorrector().correct_dataset(data, validation.violations, schema)

    assert corrected["Customer"][0]["age"] <= 90          # clipped into range
    assert corrected["Customer"][1]["status"] == "active"  # case-corrected to valid enum

    # Re-validating should have no more fixable range/enum violations.
    revalidation = RecordValidator().validate_dataset(corrected, schema)
    revtypes = {v.violation_type for v in revalidation.violations}
    assert "range_violation" not in revtypes
    assert "enum_violation" not in revtypes


def test_corrector_reassigns_broken_fk():
    schema = InferredSchema(entities=[
        EntitySchema(entity_name="Customer",
                     fields=[FieldDefinition(name="id", type="integer", unique=True)]),
        EntitySchema(
            entity_name="Order",
            fields=[FieldDefinition(name="customer_id", type="integer")],
            structured_relationships=[
                RelationshipDefinition(
                    source_entity="Order", source_field="customer_id",
                    target_entity="Customer", target_field="id",
                    cardinality=Cardinality.ONE_TO_MANY,
                )
            ],
        ),
    ])
    data = {
        "Customer": [{"id": 1}, {"id": 2}],
        "Order": [{"customer_id": 999}],  # dangling FK
    }
    validation = RecordValidator().validate_dataset(data, schema)
    assert any(v.violation_type == "fk_violation" for v in validation.violations)

    corrected = RecordCorrector().correct_dataset(data, validation.violations, schema)
    assert corrected["Order"][0]["customer_id"] in {1, 2}


# --- PostProcessingPipeline -------------------------------------------------

def test_postprocessing_pipeline_runs_end_to_end():
    schema = _schema_with_constraints()
    data = {"Customer": [
        {"age": 25, "status": "active", "email": "a@x.com"},
        {"age": 300, "status": "active", "email": "b@x.com"},   # fixable range
        {"age": 40, "status": "active", "email": ""},           # unfixable (nullable)
    ]}
    pipeline = PostProcessingPipeline(schema, PostProcessingConfig())
    result = pipeline.run(data)

    assert result.original_count["Customer"] == 3
    assert result.corrected_count >= 1     # the range violation was corrected
    assert result.filtered_count >= 1      # the empty-email record was filtered
    assert result.validation is not None
    assert result.evaluation is not None


def test_postprocessing_returns_corrected_data():
    """Regression: run() must surface the corrected+filtered data, not just counts.

    The out-of-range age must be clipped into [18, 90] in the returned data, and
    the empty-email record dropped. Previously run() corrected an internal copy
    and returned only counts, so callers exported the un-corrected records.
    """
    schema = _schema_with_constraints()
    data = {"Customer": [
        {"age": 25, "status": "active", "email": "a@x.com"},
        {"age": 300, "status": "active", "email": "b@x.com"},   # fixable range
        {"age": 40, "status": "active", "email": ""},           # unfixable (nullable)
    ]}
    result = PostProcessingPipeline(schema, PostProcessingConfig()).run(data)

    assert result.data, "run() must return the processed dataset"
    ages = [r["age"] for r in result.data["Customer"]]
    assert all(18 <= a <= 90 for a in ages), f"ages not clipped: {ages}"
    assert all(r["email"] for r in result.data["Customer"]), "empty-email row not filtered"
    assert result.final_count["Customer"] == len(result.data["Customer"])


# --- _needs_llm routing of semantic string types ----------------------------

def test_needs_llm_routes_semantic_string_types():
    """Regression: email/phone/uuid must route to the LLM fill path.

    They have no programmatic generator, so if _needs_llm skips them the field is
    never populated and the whole entity gets filtered out as null-violating.
    """
    from seed_data.structured.generation import _needs_llm

    for jtype in ("string", "email", "phone", "uuid", "url", "name", "address"):
        field = FieldDefinition(name="f", type=jtype, nullable=False)
        assert _needs_llm(field, set()) is True, f"{jtype} should need the LLM"


def test_needs_llm_excludes_programmatic_and_container_types():
    from seed_data.structured.generation import _needs_llm

    # programmatically generated → not LLM
    for jtype in ("integer", "float", "boolean", "date", "datetime"):
        assert _needs_llm(FieldDefinition(name="f", type=jtype, nullable=False), set()) is False
    # container types are unsupported in tabular and must not be force-filled
    for jtype in ("object", "array"):
        assert _needs_llm(FieldDefinition(name="f", type=jtype, nullable=False), set()) is False
    # enum / unique / distribution / FK are all programmatic
    assert _needs_llm(FieldDefinition(name="s", type="enum", enum_values=["a"]), set()) is False
    assert _needs_llm(FieldDefinition(name="id", type="string", unique=True), set()) is False
    assert _needs_llm(FieldDefinition(name="fk", type="string"), {"fk"}) is False


# --- dangling foreign keys --------------------------------------------------

def _order_with_customer_fk() -> EntitySchema:
    """An Order whose customer_id references a Customer that may not exist."""
    return EntitySchema(
        entity_name="Order",
        fields=[
            FieldDefinition(name="order_id", type="uuid", unique=True, required=True),
            FieldDefinition(name="customer_id", type="uuid", required=True),
            FieldDefinition(
                name="order_total", type="float", min_value=0.0,
                distribution=DistributionSpec(
                    type=DistributionType.LOG_NORMAL, params={"mean": 4, "sigma": 1}),
            ),
        ],
        structured_relationships=[
            RelationshipDefinition(
                source_entity="Order", source_field="customer_id",
                target_entity="Customer", target_field="id",
                cardinality=Cardinality.ONE_TO_MANY,
            )
        ],
    )


def test_live_fk_values_skips_dangling_relationship():
    """A relationship counts as an FK only when its parent produced values.

    Ingest routinely emits an FK to an entity it never extracted (e.g. an
    ``Order`` with ``customer_id -> Customer.id`` but no ``Customer`` entity).
    Such a dangling FK has no parent values and must be omitted, so the field
    falls through to normal generation instead of being copied-from-nothing.
    """
    from seed_data.structured.generation import _live_fk_values

    entity = _order_with_customer_fk()

    # No Customer generated → dangling → not treated as an FK.
    assert _live_fk_values("Order", entity.structured_relationships, {}) == {}

    # Customer present → live FK, exposes the parent key values.
    parents = {"Customer": [{"id": "C1"}, {"id": "C2"}]}
    live = _live_fk_values("Order", entity.structured_relationships, parents)
    assert live == {"customer_id": ["C1", "C2"]}


def test_dangling_fk_field_is_populated_not_left_null():
    """Regression: a required FK with no parent entity must still get a value.

    Previously the field was registered as an FK (so ``_needs_llm`` skipped it)
    but had no parent values to copy, so the column stayed ``None`` and every
    programmatic row was dropped by the not-null check — a 20-row request
    silently collapsing to just the handful of seed samples.
    """
    from seed_data.structured.generation import _generate_programmatic

    records = _generate_programmatic(
        "Order", _order_with_customer_fk(), count=15,
        existing_records=[], all_data={}, defer_llm=False,
    )
    assert len(records) == 15
    assert all(r.get("customer_id") for r in records), "dangling FK left empty"


def test_live_fk_still_copies_parent_values():
    """The fix must not regress the normal case: a live FK draws from its parent."""
    from seed_data.structured.generation import _generate_programmatic

    parents = {"Customer": [{"id": f"CUST-{i}"} for i in range(3)]}
    records = _generate_programmatic(
        "Order", _order_with_customer_fk(), count=15,
        existing_records=[], all_data=parents, defer_llm=False,
    )
    assert len(records) == 15
    parent_ids = {"CUST-0", "CUST-1", "CUST-2"}
    assert all(r["customer_id"] in parent_ids for r in records)


# --- graph build (no execution → no Bedrock) --------------------------------

def test_build_graph_pipeline_no_execution():
    from seed_data.structured.pipeline import PipelineState, build_graph_pipeline

    schema = _schema_with_constraints()
    graph, task_context, ps = build_graph_pipeline(
        schema, output_dir="./output", export_format="csv", target_count=10,
    )
    assert graph is not None
    assert isinstance(ps, PipelineState)
    assert "Customer" in task_context
    # the state is seeded with the resolved schema, not yet run
    assert json.loads(ps.schema_json)["entities"][0]["entity_name"] == "Customer"
    assert ps.quality_passed is False


def test_pipeline_state_defaults():
    from seed_data.structured.pipeline import PipelineState

    ps = PipelineState()
    assert ps.generation_attempts == 0
    assert ps.schema_revisions == 0
    assert ps.quality_passed is False
    assert ps.export_json == ""


# --- run_structured facade (LLM graph mocked) -------------------------------

def test_run_structured_parses_export_summary(monkeypatch):
    from seed_data import structured as structured_pkg
    from seed_data.structured.pipeline import PipelineState

    schema = _schema_with_constraints()

    def fake_run_graph_pipeline(sch, *, output_dir, export_format, target_count, seed=None):
        ps = PipelineState()
        ps.export_json = json.dumps({
            "format": export_format,
            "files": [f"{output_dir}/customer.csv"],
            "record_counts": {"Customer": 42},
        })
        ps.evaluation_scores = {"diversity": 0.8, "fidelity": 0.9}
        return "summary", ps

    monkeypatch.setattr(
        "seed_data.structured.pipeline.run_graph_pipeline",
        fake_run_graph_pipeline,
    )

    result = structured_pkg.run_structured(
        schema, target_count=42, export_format="csv", output_dir="./out", verbose=False,
    )
    assert result.success is True
    assert result.output_paths == ["./out/customer.csv"]
    assert result.row_counts == {"Customer": 42}
    assert result.evaluation == {"diversity": 0.8, "fidelity": 0.9}


def test_run_structured_handles_pipeline_error(monkeypatch):
    from seed_data import structured as structured_pkg

    schema = _schema_with_constraints()

    def boom(*a, **k):
        raise RuntimeError("bedrock unavailable")

    monkeypatch.setattr("seed_data.structured.pipeline.run_graph_pipeline", boom)

    result = structured_pkg.run_structured(schema, verbose=False)
    assert result.success is False
    assert "bedrock unavailable" in result.error


def test_run_structured_empty_export_has_explanatory_error(monkeypatch):
    """Regression: a run that produces no files must not report `error=None`.

    Otherwise the CLI prints a bare "FAILED: None".
    """
    from seed_data import structured as structured_pkg
    from seed_data.structured.pipeline import PipelineState

    schema = _schema_with_constraints()

    def fake_run_graph_pipeline(sch, *, output_dir, export_format, target_count, seed=None):
        ps = PipelineState()
        ps.export_json = json.dumps({"format": export_format, "files": [], "record_counts": {}})
        ps.evaluation_issues = ["Entity 'Customer' has no records"]
        return "summary", ps

    monkeypatch.setattr(
        "seed_data.structured.pipeline.run_graph_pipeline", fake_run_graph_pipeline
    )

    result = structured_pkg.run_structured(schema, verbose=False)
    assert result.success is False
    assert result.error is not None and result.error != ""
    assert "Customer" in result.error       # surfaced the pipeline's own issue


# --- exporter cleanup is scoped, not a directory wipe -----------------------

def test_export_data_only_removes_its_own_files(tmp_path):
    """Regression: export must not delete unrelated files in a shared output dir."""
    from seed_data.structured.exporter import export_data

    # a pre-existing unrelated file (e.g. from the document pipeline)
    bystander = tmp_path / "invoice.pdf"
    bystander.write_bytes(b"%PDF-1.4 keep me")
    # a stale prior export of the SAME entity, in a different format
    stale = tmp_path / "customer.json"
    stale.write_text("[]")

    data_json = json.dumps({"Customer": [{"id": 1, "name": "Acme"}]})
    # call the undecorated function behind the @tool wrapper
    export_data.__wrapped__(data_json, "csv", str(tmp_path))

    assert bystander.exists(), "unrelated file must survive export"
    assert not stale.exists(), "stale same-entity export should be cleared"
    assert (tmp_path / "customer.csv").exists()


def test_export_data_rejects_bad_format_without_deleting(tmp_path):
    """Regression: a rejected format must leave the previous export intact.

    Cleanup used to run *before* the format was validated, so an unusable format
    emptied the directory it was writing into — the user ended up with neither the
    new export nor the one they already had.
    """
    from seed_data.structured.exporter import export_data

    prior = tmp_path / "customer.csv"
    prior.write_text("id,name\n1,Acme\n")

    data_json = json.dumps({"Customer": [{"id": 2, "name": "Globex"}]})
    result = export_data.__wrapped__(data_json, "tsv", str(tmp_path))

    assert "Unsupported format" in result
    assert prior.read_text() == "id,name\n1,Acme\n", "prior export was destroyed"


def test_export_data_parquet_missing_engine_preserves_prior(tmp_path, monkeypatch):
    """Regression: no parquet engine must fail fast, before touching any file.

    pandas' own error ("Unable to find a usable engine") names neither the package
    nor this project's extra, and it was raised only after cleanup had already
    deleted the previous export.
    """
    from seed_data.structured import exporter

    prior = tmp_path / "customer.csv"
    prior.write_text("id,name\n1,Acme\n")

    # Simulate an environment with neither engine installed.
    monkeypatch.setattr(exporter, "_parquet_engine_error", lambda: "no engine, install pyarrow")

    data_json = json.dumps({"Customer": [{"id": 2, "name": "Globex"}]})
    result = exporter.export_data.__wrapped__(data_json, "parquet", str(tmp_path))

    assert "pyarrow" in result
    assert prior.read_text() == "id,name\n1,Acme\n", "prior export was destroyed"
    assert not (tmp_path / "customer.parquet").exists()


def test_parquet_engine_error_is_none_when_engine_present():
    """With pyarrow installed (it ships in [structured]) the check must not fire."""
    pytest.importorskip("pyarrow", reason="requires the [structured] optional dependencies")

    from seed_data.structured.exporter import _parquet_engine_error

    assert _parquet_engine_error() is None


def test_export_data_parquet_round_trips(tmp_path):
    """The happy path: parquet actually writes and reads back."""
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow", reason="requires the [structured] optional dependencies")

    from seed_data.structured.exporter import export_data

    data_json = json.dumps({"Customer": [{"id": 1, "name": "Acme"}, {"id": 2, "name": "Globex"}]})
    result = json.loads(export_data.__wrapped__(data_json, "parquet", str(tmp_path)))

    assert result["record_counts"] == {"Customer": 2}
    written = tmp_path / "customer.parquet"
    assert written.exists()
    assert pd.read_parquet(written)["name"].tolist() == ["Acme", "Globex"]

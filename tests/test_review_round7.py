"""Regressions for the seventh review pass — each test is the reviewer's own repro.

Kept together because they came from one full-diff review and several interact
(the FK chain in particular had been "fixed" twice before, each time breaking a
downstream consumer the fix's own test never exercised).
"""
import asyncio
import json
import os
import random
import re
import time

import pytest

pd = pytest.importorskip("pandas")

from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema  # noqa: E402


# --- structured/ ---------------------------------------------------------------

def test_char_class_escapes_match_their_own_pattern():
    from seed_data.structured.generation import _expand_char_class, _generate_from_pattern

    for pat in [r"[A-Z0-9\-]{5}", r"[\d]{4}", r"[\w]{6}", r"[A-HJ-NPR-Z0-9]{17}"]:
        vals = _generate_from_pattern(pat, 30, set(), random.Random(1))
        assert all(re.fullmatch(pat, v) for v in vals), (pat, vals[:3])
    # An escaped hyphen is a literal, never a range operator.
    assert _expand_char_class(r"[a\-z]") == "a-z"


def test_pattern_repair_does_not_duplicate_unique_keys():
    from seed_data.structured.postprocessing.corrector import RecordCorrector
    from seed_data.structured.postprocessing.validator import Violation

    schema = InferredSchema.model_validate({"entities": [{
        "entity_name": "Part", "description": "p",
        "fields": [{"name": "code", "type": "string", "unique": True, "pattern": "[0-9]{2}"}]}]})
    data = {"Part": [{"code": f"bad{i}"} for i in range(12)]}
    violations = [Violation(entity="Part", record_index=i, field="code",
                            violation_type="pattern_violation", actual_value=f"bad{i}",
                            constraint="p", fixable=True) for i in range(12)]
    codes = [r["code"] for r in RecordCorrector(seed=7).correct_dataset(data, violations, schema)["Part"]]
    assert len(codes) == len(set(codes)), codes


def test_positive_param_unwraps_one_element_lists():
    import numpy as np
    from seed_data.schema.models import DistributionSpec, DistributionType
    from seed_data.structured.distributions.generator import DistributionGenerator, positive_param

    assert positive_param({"std": [300.0]}, "std", 1.0) == 300.0
    field = FieldDefinition(name="x", type="float", min_value=0, max_value=5000,
                            distribution=DistributionSpec(type=DistributionType.NORMAL,
                                                          params={"mean": [2000.0], "std": [300.0]}))
    vals = DistributionGenerator(seed=1).generate_field_values(field, 500)
    assert np.std(vals) > 150, "std=[300.0] must not silently collapse to 1.0"


def test_required_container_is_filled_and_survives_postprocessing():
    """Bundled pay-stub schema: required `Deductions` array exported ZERO rows."""
    from unittest.mock import patch
    from seed_data.schema.io import from_schema_dir
    from seed_data.schema.models import DistributionSpec, DistributionType
    from seed_data.structured.generation import generate_bulk
    from seed_data.structured.postprocessing.pipeline import PostProcessingConfig, PostProcessingPipeline

    schema = from_schema_dir("src/seed_data/schemas/pay-stub")
    ent = schema.entities[0]
    for f in ent.fields:
        if f.type == "float":
            f.distribution = DistributionSpec(type=DistributionType.NORMAL,
                                              params={"mean": 1000, "std": 100})
    sample = {f.name: ([{"DeductionType": "tax", "DeductionAmount": 10.0}] if f.type == "array"
                       else {"x": 1} if f.type == "object"
                       else 1 if f.type in ("integer", "float") else "s") for f in ent.fields}

    def fake_fill(entity, sch, partial, existing, fields, **kw):
        for r in partial:
            for name in fields:
                r.setdefault(name, existing[0].get(name))
        return partial

    with patch("seed_data.structured.generation._fill_string_fields_with_llm", fake_fill):
        out = json.loads(generate_bulk(schema.model_dump_json(),
                                       json.dumps({"data": {ent.entity_name: [sample]}}), "5", seed=3))
    result = PostProcessingPipeline(schema, PostProcessingConfig(), seed=3).run(out["data"])
    assert result.final_count[ent.entity_name] == 5
    assert result.filtered_count == 0


def test_export_entity_name_cannot_escape_output_dir(tmp_path):
    from seed_data.structured.exporter import export_data

    victim = tmp_path / "victim.csv"
    victim.write_text("precious\n")
    out = tmp_path / "out"
    res = json.loads(export_data(data_json=json.dumps({"../victim": [{"a": 1}]}),
                                 export_format="csv", output_dir=str(out)))
    assert all(os.path.realpath(f).startswith(os.path.realpath(out)) for f in res["files"])
    assert victim.read_text() == "precious\n"


# --- schema/ and inputs ----------------------------------------------------------

def test_list_form_type_is_the_nullable_idiom():
    from seed_data.schema.io import from_json_schema

    s = from_json_schema({"title": "T", "type": "object", "properties": {
        "a": {"type": ["string", "null"]}, "n": {"type": ["number", "null"], "minimum": 0}}})
    a, n = s.entities[0].fields
    assert (a.type, a.nullable) == ("string", True)
    assert (n.type, n.nullable, n.min_value) == ("float", True, 0)


def test_string_enum_null_member_round_trips_as_null():
    from seed_data.schema.io import from_json_schema, to_json_schema

    s = from_json_schema({"title": "T", "type": "object", "properties": {
        "status": {"type": "string", "enum": ["active", "inactive", None]},
        "opt": {"type": "string", "enum": ["None", "Some"]}}})   # literal "None" must survive
    props = to_json_schema(s)["properties"]
    assert props["status"]["enum"] == ["active", "inactive", None]
    assert props["opt"]["enum"] == ["None", "Some"]


def test_resolve_inputs_never_silently_drops_a_spec(tmp_path):
    from seed_data.inputs import resolve_inputs

    (tmp_path / "invoice[1].pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "w2.pdf").write_bytes(b"%PDF-1.4")
    docs, skipped = resolve_inputs([str(tmp_path / "invoice[1].pdf"), str(tmp_path / "w2.pdf")])
    assert sorted(d.name for d in docs) == ["invoice[1].pdf", "w2.pdf"]
    docs, skipped = resolve_inputs([str(tmp_path / "*.tif"), str(tmp_path / "w2.pdf")])
    assert [d.name for d in docs] == ["w2.pdf"]
    assert any("*.tif" in s for s in skipped), "an empty glob must be reported"


# --- evaluation/ ---------------------------------------------------------------

def test_normal_distribution_on_a_date_field_is_not_scored_as_numeric():
    from seed_data.evaluation.fidelity import FidelityMetrics

    schema = EntitySchema.model_validate({"entity_name": "T", "description": "t", "fields": [
        {"name": "d", "type": "date",
         "distribution": {"type": "normal", "params": {"mean": 1000, "std": 200}}}]})
    df = pd.DataFrame([{"d": f"2024-0{m}-15"} for m in range(1, 6)])
    assert FidelityMetrics().overall_fidelity_score(df, schema)["overall_score"] == 1.0


def test_numeric_enum_jsd_compares_like_with_like():
    from seed_data.evaluation.fidelity import FidelityMetrics

    schema = EntitySchema.model_validate({"entity_name": "R", "description": "r", "fields": [
        {"name": "rating", "type": "integer", "enum_values": ["1", "2", "3"], "enum_base_type": "integer",
         "distribution": {"type": "categorical_weighted", "params": {"weights": [0.5, 0.3, 0.2]}}}]})
    df = pd.DataFrame([{"rating": v} for v in [1] * 50 + [2] * 30 + [3] * 20])
    res = FidelityMetrics().overall_fidelity_score(df, schema)
    assert res["distribution_distances"]["rating"]["jsd"] == pytest.approx(0.0, abs=1e-9)


def test_required_nullable_leaves_do_not_reduce_completeness():
    from seed_data.evaluation.metrics import evaluate_document_labels

    schema = InferredSchema.model_validate({"entities": [{"entity_name": "Inv", "description": "i", "fields": [
        {"name": "id", "type": "string", "required": True},
        {"name": "GrossTotal", "type": "float", "required": True, "nullable": True}]}]})
    rep = evaluate_document_labels([{"id": "a", "GrossTotal": None}, "oops"], schema, entity_name="Inv")
    assert rep.completeness_score == 1.0
    assert rep.per_field_presence["id"] == 1.0, "skipped labels must not count as documents"


def test_total_primary_key_duplication_fails_the_gate():
    from seed_data.evaluation.metrics import run_evaluation

    schema = InferredSchema.model_validate({"entities": [{"entity_name": "C", "description": "c", "fields": [
        {"name": "id", "type": "integer", "unique": True}, {"name": "name", "type": "string"},
        {"name": "status", "type": "enum", "enum_values": ["a", "b", "c"]}]}]})
    dup = [{"id": i // 2, "name": f"n{i}", "status": "abc"[i % 3]} for i in range(40)]
    clean = [{"id": i, "name": f"n{i}", "status": "abc"[i % 3]} for i in range(40)]
    bad, good = run_evaluation({"C": dup}, schema), run_evaluation({"C": clean}, schema)
    assert bad.passes_quality_gate is False
    assert any("duplicate" in i for i in bad.issues)
    assert good.passes_quality_gate is True


# --- stages/, ingest/, augment, packet -----------------------------------------

def test_fractional_augraphy_probability_is_not_truncated():
    from seed_data.augment import _build_augmentation, _coerce_to_default_shape

    assert _build_augmentation("InkBleed", {"p": 0.8}).p == 0.8
    assert _coerce_to_default_shape([15.0, 25.0], (3, 10)) == (15, 25)   # integral still coerced


def test_generate_uses_the_caller_timeout_as_the_node_cap(monkeypatch, tmp_path):
    from seed_data.stages import pipeline as pipe

    captured = {}

    def fake_build(ctx, **kw):
        captured.update(kw)
        raise RuntimeError("stop")

    monkeypatch.setattr(pipe, "build_pipeline_graph", fake_build)
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "schema.json").write_text('{"title": "w", "type": "object", "properties": {}}')
    with pytest.raises(RuntimeError):
        pipe.generate(schema_dir=str(tmp_path / "s"), output_dir=str(tmp_path), timeout=7200, verbose=False)
    assert captured["node_timeout"] == 7200


def test_function_nodes_do_not_block_the_event_loop():
    """Blocking critics serialized the batch fan-out and defeated node_timeout."""
    from seed_data.stages.base import FunctionNode, StageContext

    ctx = StageContext(schema_dict={}, output_path="x", data_json_path="x", script_path="x")
    nodes = [FunctionNode(lambda t, c: (time.sleep(0.4), "ok")[1], f"n{i}", ctx) for i in range(4)]

    async def run_all():
        return await asyncio.gather(*(n.invoke_async("t") for n in nodes))

    start = time.monotonic()
    asyncio.run(run_all())
    assert time.monotonic() - start < 1.2, "4 x 0.4s blocking calls must overlap"


def test_xlsx_is_routed_to_the_example_data_tool(tmp_path):
    from unittest.mock import patch
    openpyxl = pytest.importorskip("openpyxl")
    from seed_data.ingest.extract import extract_schema

    path = tmp_path / "sales_data.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b"])
    wb.save(path)
    seen = {}

    class Stop(Exception):
        pass

    class FakeAgent:
        def __call__(self, content, structured_output_model=None):
            seen["content"] = content
            raise Stop

    with patch("seed_data.ingest.extract._build_schema_agent", lambda **k: FakeAgent()):
        with pytest.raises(Stop):
            extract_schema(file_path=str(path))
    assert "analyze_example_data" in seen["content"][0]["text"]
    assert not any("document" in b for b in seen["content"][1:])


def test_document_block_names_are_bedrock_safe(tmp_path):
    from unittest.mock import patch
    from seed_data.ingest.extract import extract_schema

    path = tmp_path / "q1.2024_report.pdf"
    path.write_bytes(b"%PDF-1.4")
    seen = {}

    class Stop(Exception):
        pass

    class FakeAgent:
        def __call__(self, content, structured_output_model=None):
            seen["content"] = content
            raise Stop

    with patch("seed_data.ingest.extract._build_schema_agent", lambda **k: FakeAgent()):
        with pytest.raises(Stop):
            extract_schema(file_path=str(path))
    name = next(b["document"]["name"] for b in seen["content"] if "document" in b)
    assert re.fullmatch(r"[A-Za-z0-9 \-()\[\]]+", name), name


def test_invalid_schema_is_a_terminal_critique_not_a_crash(tmp_path):
    from seed_data.stages import data as data_stage
    from seed_data.stages.base import StageContext

    data_path = tmp_path / "d.json"
    data_path.write_text('{"a": 1}')
    ctx = StageContext(schema_dict={"type": "date"}, output_path=str(tmp_path / "d.pdf"),
                       data_json_path=str(data_path), script_path=str(tmp_path / "d.html"))
    v = data_stage.critique(ctx)
    assert v.accepted is False and v.retryable is False
    assert "invalid" in v.issues[0].description.lower()


def test_generator_session_reaches_every_packet_model():
    from unittest.mock import patch
    from seed_data.api import Generator
    from seed_data.packet import DocumentSpec, PacketConfig

    sentinel, seen = object(), {}

    def fake_resolve(config, extra="", model="x", session=None):
        seen["ctx"] = session
        return {"name": "x"}

    def fake_generate(**kw):
        seen["gen"] = kw.get("session")
        raise RuntimeError("stop")

    with patch("seed_data.packet.resolve_shared_context", fake_resolve), \
         patch("seed_data.stages.pipeline.generate", fake_generate), \
         patch("seed_data.api.Generator._resolve_packet", lambda self, p: "/x"), \
         patch("seed_data.packet.load_packet_config", lambda d: PacketConfig(
             name="t", description="", documents=[DocumentSpec(document_class="w2", schema_dir="/nonexistent")])):
        Generator(session=sentinel).generate_packet("t")
    assert seen["ctx"] is sentinel and seen["gen"] is sentinel

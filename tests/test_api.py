"""Tests for seed_data.api — the Generator facade wiring (no generation)."""
import os

import pytest

from seed_data import Generator, ModelConfig, GeneratedDoc, BatchResult


def test_generator_defaults():
    g = Generator()
    assert g.renderer == "xhtml2pdf"
    assert g.threshold == 7
    assert isinstance(g.models, ModelConfig)
    assert g.augment is False


def test_generator_repr_mentions_config():
    g = Generator(threshold=3, renderer="weasyprint")
    r = repr(g)
    assert "threshold=3" in r and "weasyprint" in r


def test_available_schemas_lists_bundled():
    schemas = Generator.available_schemas()
    assert isinstance(schemas, list) and len(schemas) > 0
    assert "invoice" in schemas


def test_available_packets_returns_list():
    assert isinstance(Generator.available_packets(), list)


def test_resolve_schema_bundled_name():
    g = Generator()
    resolved = g._resolve_schema("invoice")
    assert os.path.isdir(resolved) and resolved.endswith("invoice")


def test_resolve_schema_real_path(tmp_path):
    g = Generator()
    assert g._resolve_schema(str(tmp_path)) == str(tmp_path)


def test_resolve_schema_bad_name_raises():
    g = Generator()
    with pytest.raises(FileNotFoundError) as exc:
        g._resolve_schema("definitely-not-a-schema")
    # error should list the available options
    assert "Available bundled schemas" in str(exc.value)


# --- BatchResult rollup -----------------------------------------------------

def _doc(success, tokens):
    return GeneratedDoc(
        success=success, doc_id="x", doctype="t",
        token_usage={"inputTokens": 0, "outputTokens": 0, "totalTokens": tokens},
    )


def test_batch_result_rollup():
    docs = [_doc(True, 100), _doc(False, 50), _doc(True, 25)]
    br = BatchResult(count_requested=3, count_succeeded=2, count_failed=1, documents=docs)
    assert len(br.succeeded) == 2
    assert all(d.success for d in br.succeeded)
    assert br.total_tokens == 175


# --- inference verbs: facade wiring (inference + generation both mocked) ----

def _stub_schema():
    from seed_data import Schema
    return Schema(name="invoice", json_schema={"type": "object"}, generation_guidance="g")


def test_infer_schema_delegates_with_config(monkeypatch):
    """infer_schema forwards inputs/name/model/max_docs/session/on_question to the
    core, and writes to output_dir when given, always returning the Schema."""
    import seed_data.infer as infer_mod
    captured = {}

    def fake_infer(inputs, *, name, model, max_docs, session, on_question, verbose):
        captured.update(inputs=inputs, name=name, model=model, max_docs=max_docs,
                        on_question=on_question)
        return _stub_schema()

    wrote = {}
    monkeypatch.setattr(infer_mod, "infer_schema", fake_infer)
    monkeypatch.setattr(infer_mod, "write_schema_dir",
                        lambda schema, d: wrote.update(dir=d, schema=schema))

    gen = Generator()
    cb = lambda q: "yes"
    schema = gen.infer_schema("./s/*.pdf", name="invoice", model="haiku",
                              max_docs=3, output_dir="./out/invoice", on_question=cb)

    assert schema.name == "invoice"                 # returns the Schema
    assert captured["inputs"] == "./s/*.pdf"
    assert captured["name"] == "invoice"
    assert captured["model"] == "haiku"
    assert captured["max_docs"] == 3
    assert captured["on_question"] is cb            # dialogue threaded through
    assert wrote["dir"] == "./out/invoice"          # persisted for review


def test_infer_schema_default_model_when_none(monkeypatch):
    import seed_data.infer as infer_mod
    seen = {}
    monkeypatch.setattr(infer_mod, "infer_schema",
                        lambda inputs, *, name, model, **kw: seen.update(model=model) or _stub_schema())
    Generator().infer_schema("x.pdf", name="invoice")   # model omitted
    assert seen["model"] == infer_mod.DEFAULT_INFER_MODEL   # -> "sonnet"


def test_generate_from_samples_infers_then_generates(monkeypatch):
    """generate_from_samples = infer_schema(...) -> generate(Schema, ...)."""
    gen = Generator()
    schema = _stub_schema()
    monkeypatch.setattr(gen, "infer_schema",
                        lambda inputs, **kw: schema)

    calls = {}
    def fake_generate(s, *, scenario, augment, verbose):
        calls.update(schema=s, scenario=scenario)
        return _doc(True, 10)
    monkeypatch.setattr(gen, "generate", fake_generate)

    out = gen.generate_from_samples("x.pdf", name="invoice", scenario="IT consulting")
    assert out.success
    assert calls["schema"] is schema                # the inferred Schema flows into generate
    assert calls["scenario"] == "IT consulting"


def test_generate_batch_from_samples_infers_then_batches(monkeypatch):
    """generate_batch_from_samples = infer_schema(...) -> generate_batch(Schema, ...)."""
    gen = Generator()
    schema = _stub_schema()
    monkeypatch.setattr(gen, "infer_schema", lambda inputs, **kw: schema)

    calls = {}
    def fake_batch(s, *, count, scenario, augment, seed, on_document, verbose):
        calls.update(schema=s, count=count, scenario=scenario, seed=seed)
        return BatchResult(count_requested=count, count_succeeded=count,
                           count_failed=0, documents=[])
    monkeypatch.setattr(gen, "generate_batch", fake_batch)

    out = gen.generate_batch_from_samples("x.pdf", name="invoice", count=7,
                                          scenario="varied", seed=42)
    assert calls["schema"] is schema
    assert calls["count"] == 7 and calls["scenario"] == "varied" and calls["seed"] == 42


def test_infer_packet_delegates(monkeypatch):
    """infer_packet forwards to packet_infer.infer_packet and returns its dir."""
    import seed_data.packet_infer as pkt_mod
    captured = {}

    def fake_infer_packet(inputs, *, name, output_dir, model, boundaries, session, on_question, verbose):
        captured.update(inputs=inputs, name=name, output_dir=output_dir,
                        boundaries=boundaries, on_question=on_question)
        return output_dir

    monkeypatch.setattr(pkt_mod, "infer_packet", fake_infer_packet)

    gen = Generator()
    out = gen.infer_packet("pkg.pdf", name="lending", output_dir="./out/lending",
                           boundaries="1-2,3")
    assert out == "./out/lending"
    assert captured["name"] == "lending"
    assert captured["boundaries"] == "1-2,3"

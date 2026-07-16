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

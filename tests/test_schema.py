"""Tests for seed_data.schema.Schema — in-code document-type definitions."""
import os
import tempfile

import pytest
from pydantic import BaseModel, ValidationError

from seed_data.schema import Schema


class _Invoice(BaseModel):
    invoice_number: str
    total: float


def test_from_pydantic_model_title_is_name():
    s = Schema(name="invoice", model=_Invoice, generation_guidance="g")
    schema_dict, guidance, samples = s.resolve()
    assert schema_dict["title"] == "invoice"          # name wins over class name
    assert set(schema_dict["properties"]) == {"invoice_number", "total"}
    assert guidance == "g"
    assert samples == []


def test_from_json_schema_dict():
    s = Schema(
        name="wire",
        json_schema={"type": "object", "properties": {"amount": {"type": "number"}}},
        generation_guidance="g",
    )
    schema_dict, _, _ = s.resolve()
    assert schema_dict["title"] == "wire"
    assert "amount" in schema_dict["properties"]


def test_requires_exactly_one_source_both():
    with pytest.raises(ValidationError):
        Schema(name="x", model=_Invoice, json_schema={"type": "object"})


def test_requires_exactly_one_source_neither():
    with pytest.raises(ValidationError):
        Schema(name="x")


def test_missing_sample_pdf_raises():
    with pytest.raises((ValidationError, FileNotFoundError)):
        Schema(name="x", model=_Invoice, sample_pdfs=["/does/not/exist.pdf"])


def test_existing_sample_pdf_accepted():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        s = Schema(name="x", model=_Invoice, sample_pdfs=[path])
        assert s.sample_pdfs == [path]
    finally:
        os.unlink(path)


def test_from_dir_roundtrip():
    schema_dir = os.path.join("src", "seed_data", "schemas", "invoice")
    if not os.path.isdir(schema_dir):
        pytest.skip("bundled invoice schema not present")
    s = Schema.from_dir(schema_dir)
    schema_dict, guidance, _ = s.resolve()
    assert isinstance(schema_dict, dict) and "title" in schema_dict
    assert isinstance(guidance, str) and len(guidance) > 0

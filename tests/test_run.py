"""Tests for the end-to-end ``Generator.run()`` verb (Milestone 4).

``run()`` is pure dispatch — ingest, then hand off to the right generate verb.
These tests mock both sides so the wiring is verified without Bedrock: what
matters is that the right verb is called, with the right arguments, and that the
typed result comes back untouched.
"""
from unittest.mock import patch

import pytest

from seed_data.api import BatchResult, Generator, StructuredResult
from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema
from seed_data.stages.pipeline import GeneratedDoc


@pytest.fixture(autouse=True)
def _structured_extra_present(monkeypatch):
    """Report the ``[structured]`` extra as installed for every test here.

    ``run(output="structured")`` guards on the extra before ingesting, so on a lean
    base install these tests would fail on the guard. They mock the generation half
    outright, so no pandas is ever touched and the extra's real presence is beside
    the point — what is under test is dispatch. The guard itself is covered in
    tests/test_deps_guard.py, which asserts it fires (and that ingest is skipped).
    """
    monkeypatch.setattr("seed_data.common.deps.structured_available", lambda: True)


@pytest.fixture
def schema():
    return InferredSchema(entities=[
        EntitySchema(entity_name="Order", fields=[
            FieldDefinition(name="order_id", type="string"),
            FieldDefinition(name="total", type="number"),
        ]),
    ])


@pytest.fixture
def structured_result(schema):
    return StructuredResult(
        success=True, schema=schema, format="csv",
        output_paths=["/tmp/out/Order.csv"], row_counts={"Order": 100},
    )


def _doc(success=True):
    return GeneratedDoc(
        doc_id="abcd1234", doctype="Order", success=success, verdict="ACCEPT",
        score=9, pdf_path="/tmp/out/doc.pdf",
    )


# --- dispatch ---------------------------------------------------------------

def test_generator_run_dispatches_structured(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "ingest", return_value=schema) as ingest, \
         patch.object(Generator, "generate_structured", return_value=structured_result) as gs:
        result = gen.run("Customer orders", output="structured")

    ingest.assert_called_once()
    gs.assert_called_once()
    # the schema ingest produced is what generation receives
    assert gs.call_args.args[0] is schema
    assert result is structured_result


def test_generator_run_dispatches_documents(schema):
    gen = Generator()
    doc = _doc()
    with patch.object(Generator, "ingest", return_value=schema), \
         patch.object(Generator, "generate", return_value=doc) as g, \
         patch.object(Generator, "generate_batch") as gb:
        result = gen.run("FCC invoices", output="documents")

    g.assert_called_once()
    gb.assert_not_called()
    assert result is doc


def test_generator_run_batch_documents(schema):
    gen = Generator()
    batch = BatchResult(count_requested=5, count_succeeded=5, count_failed=0,
                        documents=[_doc() for _ in range(5)])
    with patch.object(Generator, "ingest", return_value=schema), \
         patch.object(Generator, "generate") as g, \
         patch.object(Generator, "generate_batch", return_value=batch) as gb:
        result = gen.run("FCC invoices", output="documents", count=5)

    gb.assert_called_once()
    g.assert_not_called()
    assert gb.call_args.kwargs["count"] == 5
    assert result is batch


def test_generator_run_defaults_to_structured(schema, structured_result):
    """The documented default — omitting `output` generates structured data."""
    gen = Generator()
    with patch.object(Generator, "ingest", return_value=schema), \
         patch.object(Generator, "generate_structured", return_value=structured_result) as gs:
        gen.run("Customer orders")
    gs.assert_called_once()


# --- argument forwarding ----------------------------------------------------

def test_generator_run_passes_rows_and_format(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "ingest", return_value=schema), \
         patch.object(Generator, "generate_structured", return_value=structured_result) as gs:
        gen.run("orders", output="structured", rows=500, format="parquet")

    assert gs.call_args.kwargs["rows"] == 500
    assert gs.call_args.kwargs["format"] == "parquet"


def test_generator_run_passes_count_and_augment(schema):
    gen = Generator()
    batch = BatchResult(count_requested=10, count_succeeded=10, count_failed=0)
    with patch.object(Generator, "ingest", return_value=schema), \
         patch.object(Generator, "generate_batch", return_value=batch) as gb:
        gen.run("invoices", output="documents", count=10, augment=True)

    assert gb.call_args.kwargs["count"] == 10
    assert gb.call_args.kwargs["augment"] is True


def test_generator_run_passes_scenario_and_entity(schema):
    gen = Generator()
    with patch.object(Generator, "ingest", return_value=schema), \
         patch.object(Generator, "generate", return_value=_doc()) as g:
        gen.run("invoices", output="documents", scenario="Midwest", entity="Order")

    assert g.call_args.kwargs["scenario"] == "Midwest"
    assert g.call_args.kwargs["entity"] == "Order"


def test_generator_run_multiple_inputs(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "ingest", return_value=schema) as ingest, \
         patch.object(Generator, "generate_structured", return_value=structured_result):
        gen.run("orders.csv", "constraints.txt", "add a priority field")

    assert ingest.call_args.args == ("orders.csv", "constraints.txt", "add a priority field")


def test_generator_run_passes_name_to_ingest(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "ingest", return_value=schema) as ingest, \
         patch.object(Generator, "generate_structured", return_value=structured_result):
        gen.run("orders", name="retail")
    assert ingest.call_args.kwargs["name"] == "retail"


def test_generator_run_forwards_verbose(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "ingest", return_value=schema) as ingest, \
         patch.object(Generator, "generate_structured", return_value=structured_result) as gs:
        gen.run("orders", verbose=False)
    assert ingest.call_args.kwargs["verbose"] is False
    assert gs.call_args.kwargs["verbose"] is False


# --- validation -------------------------------------------------------------

def test_generator_run_invalid_output_raises():
    gen = Generator()
    with pytest.raises(ValueError, match="structured.*documents"):
        gen.run("text", output="invalid")


def test_generator_run_invalid_output_does_not_ingest():
    """Validate before spending tokens on ingest."""
    gen = Generator()
    with patch.object(Generator, "ingest") as ingest:
        with pytest.raises(ValueError):
            gen.run("text", output="invalid")
    ingest.assert_not_called()


# --- typed returns ----------------------------------------------------------

def test_generator_run_returns_typed_structured(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "ingest", return_value=schema), \
         patch.object(Generator, "generate_structured", return_value=structured_result):
        result = gen.run("orders", output="structured")
    assert isinstance(result, StructuredResult)
    assert not isinstance(result, dict)


def test_generator_run_returns_typed_document(schema):
    gen = Generator()
    with patch.object(Generator, "ingest", return_value=schema), \
         patch.object(Generator, "generate", return_value=_doc()):
        single = gen.run("invoices", output="documents", count=1)
    assert isinstance(single, GeneratedDoc)

    batch = BatchResult(count_requested=3, count_succeeded=3, count_failed=0)
    with patch.object(Generator, "ingest", return_value=schema), \
         patch.object(Generator, "generate_batch", return_value=batch):
        many = gen.run("invoices", output="documents", count=3)
    assert isinstance(many, BatchResult)


# --- generate()/generate_batch() accept InferredSchema ----------------------

def test_generate_accepts_inferred_schema(schema):
    """An InferredSchema must reach the pipeline as `resolved=`, not `schema_dir=`."""
    gen = Generator()
    with patch("seed_data.api._pipeline_generate", return_value=_doc()) as pipeline:
        gen.generate(schema, scenario="x")

    kwargs = pipeline.call_args.kwargs
    assert "resolved" in kwargs
    assert "schema_dir" not in kwargs
    json_schema, guidance, samples = kwargs["resolved"]
    assert json_schema["title"] == "Order"
    assert set(json_schema["properties"]) == {"order_id", "total"}


def test_generate_batch_accepts_inferred_schema(schema):
    gen = Generator()
    with patch("seed_data.stages.batch.generate_batch", return_value=[_doc()]) as batch:
        gen.generate_batch(schema, count=1, scenario="x")

    kwargs = batch.call_args.kwargs
    assert "resolved" in kwargs
    assert "schema_dir" not in kwargs
    assert kwargs["resolved"][0]["title"] == "Order"


def test_generate_selects_entity_from_multi_entity_schema():
    gen = Generator()
    multi = InferredSchema(entities=[
        EntitySchema(entity_name="Customer",
                     fields=[FieldDefinition(name="customer_id", type="string")]),
        EntitySchema(entity_name="Order",
                     fields=[FieldDefinition(name="order_id", type="string")]),
    ])
    with patch("seed_data.api._pipeline_generate", return_value=_doc()) as pipeline:
        gen.generate(multi, entity="Order")

    assert pipeline.call_args.kwargs["resolved"][0]["title"] == "Order"


def test_generate_string_still_uses_schema_dir():
    """Regression guard: the published `generate("name")` path is unchanged."""
    gen = Generator()
    with patch("seed_data.api._pipeline_generate", return_value=_doc()) as pipeline:
        gen.generate("fcc-invoice")

    assert "schema_dir" in pipeline.call_args.kwargs
    assert "resolved" not in pipeline.call_args.kwargs


def test_generate_schema_object_still_resolves():
    """Regression guard: the published `generate(Schema(...))` path is unchanged."""
    from seed_data.schema import Schema

    gen = Generator()
    schema = Schema(name="t", json_schema={"type": "object", "properties": {}},
                    generation_guidance="G")
    with patch("seed_data.api._pipeline_generate", return_value=_doc()) as pipeline:
        gen.generate(schema)

    resolved = pipeline.call_args.kwargs["resolved"]
    assert resolved[0]["title"] == "t"
    assert resolved[1] == "G"

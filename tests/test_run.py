"""Tests for the end-to-end ``Generator.plan_and_generate()`` verb (Milestone 4).

``plan_and_generate()`` is pure dispatch — plan, then hand off to the right
generate verb.
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

    ``plan_and_generate(output="structured")`` guards on the extra before planning,
    so on a lean
    base install these tests would fail on the guard. They mock the generation half
    outright, so no pandas is ever touched and the extra's real presence is beside
    the point — what is under test is dispatch. The guard itself is covered in
    tests/test_deps_guard.py, which asserts it fires (and that planning is skipped).
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

def test_generator_plan_and_generate_dispatches_structured(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema) as plan, \
         patch.object(Generator, "generate_structured", return_value=structured_result) as gs:
        result = gen.plan_and_generate("Customer orders", output="structured")

    plan.assert_called_once()
    gs.assert_called_once()
    # the schema planning produced is what generation receives
    assert gs.call_args.args[0] is schema
    assert result is structured_result


def test_generator_plan_and_generate_dispatches_documents(schema):
    gen = Generator()
    doc = _doc()
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate", return_value=doc) as g, \
         patch.object(Generator, "generate_batch") as gb:
        result = gen.plan_and_generate("FCC invoices", output="documents")

    g.assert_called_once()
    gb.assert_not_called()
    assert result is doc


def test_generator_plan_and_generate_batch_documents(schema):
    gen = Generator()
    batch = BatchResult(count_requested=5, count_succeeded=5, count_failed=0,
                        documents=[_doc() for _ in range(5)])
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate") as g, \
         patch.object(Generator, "generate_batch", return_value=batch) as gb:
        result = gen.plan_and_generate("FCC invoices", output="documents", count=5)

    gb.assert_called_once()
    g.assert_not_called()
    assert gb.call_args.kwargs["count"] == 5
    assert result is batch


def test_generator_plan_and_generate_defaults_to_structured(schema, structured_result):
    """The documented default — omitting `output` generates structured data."""
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate_structured", return_value=structured_result) as gs:
        gen.plan_and_generate("Customer orders")
    gs.assert_called_once()


# --- argument forwarding ----------------------------------------------------

def test_generator_plan_and_generate_passes_rows_and_format(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate_structured", return_value=structured_result) as gs:
        gen.plan_and_generate("orders", output="structured", rows=500, format="parquet")

    assert gs.call_args.kwargs["rows"] == 500
    assert gs.call_args.kwargs["format"] == "parquet"


def test_generator_plan_and_generate_passes_count_and_augment(schema):
    gen = Generator()
    batch = BatchResult(count_requested=10, count_succeeded=10, count_failed=0)
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate_batch", return_value=batch) as gb:
        gen.plan_and_generate("invoices", output="documents", count=10, augment=True)

    assert gb.call_args.kwargs["count"] == 10
    assert gb.call_args.kwargs["augment"] is True


def test_generator_plan_and_generate_passes_scenario_and_entity(schema):
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate", return_value=_doc()) as g:
        gen.plan_and_generate("invoices", output="documents", scenario="Midwest", entity="Order")

    assert g.call_args.kwargs["scenario"] == "Midwest"
    assert g.call_args.kwargs["entity"] == "Order"


def test_generator_plan_and_generate_multiple_inputs(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema) as plan, \
         patch.object(Generator, "generate_structured", return_value=structured_result):
        gen.plan_and_generate("orders.csv", "constraints.txt", "add a priority field")

    assert plan.call_args.args == ("orders.csv", "constraints.txt", "add a priority field")


def test_generator_plan_and_generate_passes_name_to_plan(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema) as plan, \
         patch.object(Generator, "generate_structured", return_value=structured_result):
        gen.plan_and_generate("orders", name="retail")
    assert plan.call_args.kwargs["name"] == "retail"


def test_generator_plan_and_generate_forwards_verbose(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema) as plan, \
         patch.object(Generator, "generate_structured", return_value=structured_result) as gs:
        gen.plan_and_generate("orders", verbose=False)
    assert plan.call_args.kwargs["verbose"] is False
    assert gs.call_args.kwargs["verbose"] is False


# --- validation -------------------------------------------------------------

def test_generator_plan_and_generate_invalid_output_raises():
    gen = Generator()
    with pytest.raises(ValueError, match="structured.*documents"):
        gen.plan_and_generate("text", output="invalid")


def test_generator_plan_and_generate_invalid_output_does_not_plan():
    """Validate before spending tokens on planning."""
    gen = Generator()
    with patch.object(Generator, "plan") as plan:
        with pytest.raises(ValueError):
            gen.plan_and_generate("text", output="invalid")
    plan.assert_not_called()


# --- typed returns ----------------------------------------------------------

def test_generator_plan_and_generate_returns_typed_structured(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate_structured", return_value=structured_result):
        result = gen.plan_and_generate("orders", output="structured")
    assert isinstance(result, StructuredResult)
    assert not isinstance(result, dict)


def test_generator_plan_and_generate_returns_typed_document(schema):
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate", return_value=_doc()):
        single = gen.plan_and_generate("invoices", output="documents", count=1)
    assert isinstance(single, GeneratedDoc)

    batch = BatchResult(count_requested=3, count_succeeded=3, count_failed=0)
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate_batch", return_value=batch):
        many = gen.plan_and_generate("invoices", output="documents", count=3)
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


# --- deprecated aliases -----------------------------------------------------

def test_ingest_alias_delegates_to_plan_and_warns(schema):
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema) as plan:
        with pytest.warns(DeprecationWarning, match="Generator.plan"):
            result = gen.ingest("orders.csv", name="retail", verbose=False)

    assert result is schema
    assert plan.call_args.args == ("orders.csv",)
    assert plan.call_args.kwargs == {"name": "retail", "verbose": False}


def test_run_alias_delegates_to_plan_and_generate_and_warns(schema, structured_result):
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate_structured", return_value=structured_result) as gs:
        with pytest.warns(DeprecationWarning, match="Generator.plan_and_generate"):
            result = gen.run("orders", output="structured", rows=500)

    assert result is structured_result
    assert gs.call_args.kwargs["rows"] == 500


def test_run_alias_forwards_every_keyword(schema, structured_result):
    """The alias takes ``**kwargs``, so a keyword it never names must still arrive.

    This is what stops the two signatures drifting as ``plan_and_generate`` grows.
    """
    gen = Generator()
    with patch.object(Generator, "plan", return_value=schema), \
         patch.object(Generator, "generate_structured", return_value=structured_result) as gs:
        with pytest.warns(DeprecationWarning):
            gen.run("orders", output="structured", format="parquet", seed=7)

    assert gs.call_args.kwargs["format"] == "parquet"
    assert gs.call_args.kwargs["seed"] == 7

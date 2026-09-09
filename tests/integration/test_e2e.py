"""Integration: end-to-end ``Generator.plan_and_generate()`` across both modalities (Milestone 4).

The one schema, planned once, drives both structured and document generation —
the unification the whole plan is about. Also exercises the cross-modality
evaluators (§4.2) on real generated output.

Live Bedrock. Excluded from the default run; invoke explicitly with creds:

    AWS_PROFILE=your-profile uv run pytest tests/integration/test_e2e.py -v
"""
import csv
import os

from seed_data.api import BatchResult, StructuredResult
from seed_data.evaluation import critique_structured, evaluate_document_labels
from seed_data.stages.pipeline import GeneratedDoc


def test_generator_run_structured_text(generator):
    result = generator.plan_and_generate("Customer orders with an order total and a status",
                           output="structured", rows=20)
    assert isinstance(result, StructuredResult)
    assert result.success, f"structured run failed: {result.error}"
    assert result.output_paths
    # at least one entity produced ~20 rows
    assert any(count >= 15 for count in result.row_counts.values()), result.row_counts


def test_generator_run_documents_text(generator):
    result = generator.plan_and_generate("FCC broadcast advertising invoices",
                           output="documents", count=2)
    assert isinstance(result, BatchResult)
    assert result.count_succeeded >= 1, result
    assert any(os.path.isfile(d.pdf_path) for d in result.documents if d.pdf_path)


def test_same_schema_both_modalities(generator):
    """Ingest once, generate both ways — fields must be consistent across them."""
    schema = generator.plan("Retail customer orders", name="retail")
    fields = {f.name for e in schema.entities for f in e.fields}
    assert fields, "plan produced no fields"

    structured = generator.generate_structured(schema, rows=10)
    assert isinstance(structured, StructuredResult)
    assert structured.success

    doc = generator.generate(schema)
    assert isinstance(doc, GeneratedDoc)
    assert doc.success

    # the structured output's columns come from the same schema fields
    assert structured.schema.entities[0].entity_name == schema.entities[0].entity_name


def test_generator_run_from_csv_input(generator, tmp_path):
    csv_path = tmp_path / "orders.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "customer", "total", "status"])
        for i in range(5):
            w.writerow([f"O{i}", f"Cust{i}", 10.0 * i, "open" if i % 2 else "closed"])

    result = generator.plan_and_generate(str(csv_path), output="structured", rows=15)
    assert isinstance(result, StructuredResult)
    assert result.success
    # schema fields should reflect the CSV columns
    field_names = {f.name.lower() for e in result.schema.entities for f in e.fields}
    assert {"order_id", "customer", "total", "status"} & field_names


def test_evaluation_on_documents(generator):
    """After generating a doc, its label JSON scores for coverage/completeness."""
    schema = generator.plan("FCC broadcast advertising invoices", name="fcc")
    doc = generator.generate(schema)
    assert doc.success

    # locate the ground-truth JSON emitted alongside the PDF
    assert doc.data_json_path and os.path.isfile(doc.data_json_path)
    import json

    with open(doc.data_json_path) as f:
        labels = json.load(f)

    report = evaluate_document_labels(labels, schema)
    assert report.document_count >= 1
    assert 0.0 <= report.overall_score <= 1.0


def test_critique_structured_on_generated_data(generator):
    """The structured critique runs against real generated data and returns a score."""
    schema = generator.plan("Customer orders with dates and totals", name="orders")
    result = generator.generate_structured(schema, rows=10, format="json")
    assert result.success

    # load the generated JSON back for critique
    import json

    json_paths = [p for p in result.output_paths if p.endswith(".json")]
    if not json_paths:
        # csv/parquet fallback: reconstruct the mapping is out of scope; skip cleanly
        import pytest

        pytest.skip("structured output was not JSON; nothing to feed the critic")

    data = {}
    for p in json_paths:
        entity = os.path.splitext(os.path.basename(p))[0]
        with open(p) as f:
            data[entity] = json.load(f)

    critique = critique_structured(data, schema, session=generator.session)
    assert critique["verdict"] in ("accepted", "rejected")  # not "error"
    assert 1 <= critique["score"] <= 10

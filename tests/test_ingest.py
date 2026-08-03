"""Ingest tests — input-type detection and the ingest orchestration.

`detect_input_type` is pure (no I/O beyond os.path.isfile) so it's tested
directly. The `run_ingest` orchestration is tested with the schema-extraction
agent and infer_schema mocked out, so nothing here needs Bedrock credentials.
"""
import pytest

from seed_data.ingest import InputType, detect_input_type, run_ingest
from seed_data.ingest import pipeline as ingest_pipeline
from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema


# --- detect_input_type ------------------------------------------------------

@pytest.mark.parametrize("spec,expected", [
    # S3 is always a document, regardless of extension.
    ("s3://bucket/key.pdf", InputType.DOCUMENT),
    ("s3://bucket/some/prefix", InputType.DOCUMENT),
    # Documents/images (delegated to infer_schema).
    ("invoice.pdf", InputType.DOCUMENT),
    ("scan.png", InputType.DOCUMENT),
    ("photo.JPEG", InputType.DOCUMENT),
    # Example data.
    ("customers.csv", InputType.EXAMPLE_DATA),
    ("sales.xlsx", InputType.EXAMPLE_DATA),
    ("legacy.XLS", InputType.EXAMPLE_DATA),
    # Schema definitions.
    ("model.sql", InputType.SCHEMA),
    ("model.ddl", InputType.SCHEMA),
    # ERD text formats.
    ("diagram.dbml", InputType.ERD),
    ("diagram.puml", InputType.ERD),
    ("diagram.plantuml", InputType.ERD),
    ("diagram.mmd", InputType.ERD),
    ("diagram.mermaid", InputType.ERD),
    # Bare free text.
    ("Generate 100 fake customers with names and emails", InputType.FREE_TEXT),
    ("a description that ends in a word", InputType.FREE_TEXT),
])
def test_detect_input_type(spec, expected):
    assert detect_input_type(spec) == expected


def test_detect_json_file_is_schema_when_exists(tmp_path):
    p = tmp_path / "schema.json"
    p.write_text('{"type": "object"}')
    assert detect_input_type(str(p)) == InputType.SCHEMA


def test_detect_json_nonexistent_is_free_text():
    # A .json string that isn't a real file is treated as a bare description.
    assert detect_input_type("something.json") == InputType.FREE_TEXT


def test_detect_case_insensitive_extension():
    assert detect_input_type("REPORT.PDF") == InputType.DOCUMENT
    assert detect_input_type("DATA.CSV") == InputType.EXAMPLE_DATA


# --- run_ingest orchestration (agent + infer_schema mocked) -----------------

def _fake_schema(entity_name: str) -> InferredSchema:
    return InferredSchema(entities=[
        EntitySchema(
            entity_name=entity_name,
            fields=[FieldDefinition(name="id", type="integer")],
        )
    ])


def test_run_ingest_requires_inputs():
    with pytest.raises(ValueError):
        run_ingest()


def test_run_ingest_free_text_calls_extraction_agent(monkeypatch):
    captured = {}

    def fake_extract(**kwargs):
        captured.update(kwargs)
        return _fake_schema("Customer").model_dump_json()

    # Patch the raw tool func the pipeline pulls off the @tool object.
    import seed_data.ingest.extract as extract_mod
    monkeypatch.setattr(extract_mod.schema_extraction_agent, "_tool_func", fake_extract)

    schema = run_ingest("Generate customers with names", name="dataset", verbose=False)

    assert isinstance(schema, InferredSchema)
    assert [e.entity_name for e in schema.entities] == ["Customer"]
    # free text is routed via text_description
    assert captured.get("text_description") == "Generate customers with names"


def test_run_ingest_merges_multiple_inputs(monkeypatch):
    calls = []

    def fake_extract(**kwargs):
        calls.append(kwargs)
        # name the entity after which kwarg was passed so we can assert routing
        if "text_description" in kwargs:
            return _fake_schema("FromText").model_dump_json()
        if "schema_input" in kwargs:
            return _fake_schema("FromSchema").model_dump_json()
        return _fake_schema("Other").model_dump_json()

    import seed_data.ingest.extract as extract_mod
    monkeypatch.setattr(extract_mod.schema_extraction_agent, "_tool_func", fake_extract)

    schema = run_ingest(
        "a free text description",
        "model.sql",
        verbose=False,
    )

    names = sorted(e.entity_name for e in schema.entities)
    assert names == ["FromSchema", "FromText"]
    # SQL DDL routed with schema_format=sql_ddl
    sql_call = next(c for c in calls if "schema_input" in c)
    assert sql_call["schema_format"] == "sql_ddl"


def test_run_ingest_documents_delegated(monkeypatch):
    """Document inputs are routed through _ingest_documents, not the agent."""
    def fake_ingest_documents(specs, **kwargs):
        assert list(specs) == ["invoice.pdf"]
        return _fake_schema("Invoice").entities

    monkeypatch.setattr(ingest_pipeline, "_ingest_documents", fake_ingest_documents)

    schema = run_ingest("invoice.pdf", verbose=False)
    assert [e.entity_name for e in schema.entities] == ["Invoice"]


def test_run_ingest_erd_format_detection(monkeypatch):
    captured = {}

    def fake_extract(**kwargs):
        captured.update(kwargs)
        return _fake_schema("Node").model_dump_json()

    import seed_data.ingest.extract as extract_mod
    monkeypatch.setattr(extract_mod.schema_extraction_agent, "_tool_func", fake_extract)

    run_ingest("diagram.mmd", verbose=False)
    assert captured.get("erd_format") == "mermaid"


# --- _load_data: file readers -----------------------------------------------

def _load(path):
    """Call the loader the way analyze_example_data does."""
    import os

    from seed_data.ingest.tools import _load_data

    return _load_data(str(path), os.path.splitext(str(path))[1].lower())


def test_load_data_csv_names_entity_after_the_file(tmp_path):
    pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")

    csv = tmp_path / "orders.csv"
    csv.write_text("id,total\n1,9.99\n2,19.99\n")

    frames = _load(csv)
    assert list(frames) == ["orders"]
    assert len(frames["orders"]) == 2


def test_load_data_reads_single_sheet_excel(tmp_path):
    """Regression: .xlsx had no reader at all, so every spreadsheet ingest failed.

    detect_input_type classifies .xls/.xlsx as EXAMPLE_DATA and routes them here,
    so the branch has to exist. A lone default-named sheet takes the filename, to
    match how .csv is named.
    """
    pd = pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")
    pytest.importorskip("openpyxl", reason="requires the [structured] optional dependencies")

    xlsx = tmp_path / "orders.xlsx"
    pd.DataFrame({"id": [1, 2], "total": [9.99, 19.99]}).to_excel(
        xlsx, index=False, sheet_name="Sheet1"
    )

    frames = _load(xlsx)
    assert list(frames) == ["orders"], "a default 'Sheet1' carries no meaning; the filename does"
    assert frames["orders"]["total"].tolist() == [9.99, 19.99]


def test_load_data_keeps_meaningful_single_sheet_name(tmp_path):
    pd = pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")
    pytest.importorskip("openpyxl", reason="requires the [structured] optional dependencies")

    xlsx = tmp_path / "export_2026.xlsx"
    pd.DataFrame({"id": [1]}).to_excel(xlsx, index=False, sheet_name="Customer")

    assert list(_load(xlsx)) == ["Customer"]


def test_load_data_treats_each_sheet_as_an_entity(tmp_path):
    """A workbook is the natural way to hand over a multi-table dataset."""
    pd = pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")
    pytest.importorskip("openpyxl", reason="requires the [structured] optional dependencies")

    xlsx = tmp_path / "shop.xlsx"
    with pd.ExcelWriter(xlsx) as writer:
        pd.DataFrame({"id": [1, 2]}).to_excel(writer, index=False, sheet_name="Customer")
        pd.DataFrame({"id": [9], "customer_id": [1]}).to_excel(
            writer, index=False, sheet_name="Order"
        )

    frames = _load(xlsx)
    assert sorted(frames) == ["Customer", "Order"]
    assert len(frames["Customer"]) == 2
    assert len(frames["Order"]) == 1


def test_load_data_skips_empty_sheets(tmp_path):
    """Template workbooks routinely carry blank trailing sheets.

    An empty sheet infers an entity with no fields, which is noise in the schema.
    """
    pd = pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")
    pytest.importorskip("openpyxl", reason="requires the [structured] optional dependencies")

    xlsx = tmp_path / "shop.xlsx"
    with pd.ExcelWriter(xlsx) as writer:
        pd.DataFrame({"id": [1]}).to_excel(writer, index=False, sheet_name="Customer")
        pd.DataFrame().to_excel(writer, index=False, sheet_name="Blank")

    assert list(_load(xlsx)) == ["Customer"]


def test_load_data_rejects_a_workbook_with_no_data(tmp_path):
    pd = pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")
    pytest.importorskip("openpyxl", reason="requires the [structured] optional dependencies")

    xlsx = tmp_path / "empty.xlsx"
    pd.DataFrame().to_excel(xlsx, index=False, sheet_name="Blank")

    with pytest.raises(ValueError, match="No non-empty sheets"):
        _load(xlsx)


def test_load_data_unsupported_extension_names_what_works(tmp_path):
    pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")

    bad = tmp_path / "data.parquet"
    bad.write_bytes(b"not really parquet")

    with pytest.raises(ValueError, match=r"\.csv, \.json, \.xls or \.xlsx"):
        _load(bad)


def test_analyze_example_data_summarizes_a_workbook(tmp_path):
    """The tool wrapper must surface every sheet as an entity."""
    import json

    pd = pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")
    pytest.importorskip("openpyxl", reason="requires the [structured] optional dependencies")

    from seed_data.ingest.tools import analyze_example_data

    xlsx = tmp_path / "shop.xlsx"
    with pd.ExcelWriter(xlsx) as writer:
        pd.DataFrame({"email": ["a@x.com", "b@x.com"]}).to_excel(
            writer, index=False, sheet_name="Customer"
        )
        pd.DataFrame({"total": [1.5]}).to_excel(writer, index=False, sheet_name="Order")

    result = json.loads(analyze_example_data.__wrapped__(str(xlsx)))
    assert sorted(result["entities_found"]) == ["Customer", "Order"]
    assert "Entity: Customer" in result["summary"]
    assert "Entity: Order" in result["summary"]

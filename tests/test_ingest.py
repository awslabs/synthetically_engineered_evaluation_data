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

    # Patch the plain implementation the pipeline calls, not the @tool wrapper —
    # the wrapper's signature deliberately omits model/session.
    monkeypatch.setattr("seed_data.ingest.extract.extract_schema", fake_extract)

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

    monkeypatch.setattr("seed_data.ingest.extract.extract_schema", fake_extract)

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

    monkeypatch.setattr("seed_data.ingest.extract.extract_schema", fake_extract)

    run_ingest("diagram.mmd", verbose=False)
    assert captured.get("erd_format") == "mermaid"


def test_run_ingest_passes_data_model_to_extraction(monkeypatch):
    """Regression: `--data-model` / `ModelConfig.data` was documented on
    `run_ingest` and never read, so the extraction agent always used the
    `common.config` default and the flag was a no-op for ingest."""
    from seed_data.api import ModelConfig

    captured = {}

    def fake_extract(**kwargs):
        captured.update(kwargs)
        return _fake_schema("Customer").model_dump_json()

    monkeypatch.setattr("seed_data.ingest.extract.extract_schema", fake_extract)

    run_ingest("some customers", models=ModelConfig(data="sonnet"), verbose=False)
    assert captured["model"] == "sonnet"


def test_run_ingest_explicit_model_beats_model_config(monkeypatch):
    from seed_data.api import ModelConfig

    captured = {}

    def fake_extract(**kwargs):
        captured.update(kwargs)
        return _fake_schema("Customer").model_dump_json()

    monkeypatch.setattr("seed_data.ingest.extract.extract_schema", fake_extract)

    run_ingest(
        "some customers", models=ModelConfig(data="sonnet"), model="nova2-lite",
        verbose=False,
    )
    assert captured["model"] == "nova2-lite"


def test_run_ingest_forwards_session_to_extraction(monkeypatch):
    """Regression: `Generator(session=...)` was silently dropped on the ingest
    path, so an in-process host's explicit profile/region fell back to ambient
    environment credentials."""
    captured = {}
    sentinel = object()

    def fake_extract(**kwargs):
        captured.update(kwargs)
        return _fake_schema("Customer").model_dump_json()

    monkeypatch.setattr("seed_data.ingest.extract.extract_schema", fake_extract)

    run_ingest("some customers", session=sentinel, verbose=False)
    assert captured["session"] is sentinel


# --- extract_schema prompt assembly -----------------------------------------

class _StubAgent:
    """Captures the user content and returns a fixed InferredSchema."""

    def __init__(self, entity_name="Captured"):
        self.calls = []
        self._entity_name = entity_name

    def __call__(self, user_content, **kwargs):
        self.calls.append(user_content)
        from seed_data.schema.flat import flat_inferred_schema

        flat = flat_inferred_schema()
        return type("R", (), {
            "structured_output": flat.model_validate({
                "entities": [{
                    "entity_name": self._entity_name,
                    "fields": [{"name": "id", "type": "integer"}],
                }],
            })
        })()

    @property
    def prompt_text(self) -> str:
        return "\n".join(
            block["text"] for block in self.calls[0] if "text" in block
        )


@pytest.fixture
def stub_agent(monkeypatch):
    agent = _StubAgent()
    monkeypatch.setattr(
        "seed_data.ingest.extract._build_schema_agent",
        lambda model=None, session=None: agent,
    )
    return agent


def test_schema_input_text_reaches_the_model(stub_agent):
    """Regression (blocking): the prompt named the format and pointed at
    `parse_schema_definition` — a tool whose text argument only the model can
    supply, and it had never seen the DDL. The model got a label and no schema,
    so it invented one unrelated to the input."""
    from seed_data.ingest.extract import extract_schema

    ddl = "CREATE TABLE orders (id INT PRIMARY KEY, total DECIMAL(10,2));"
    extract_schema(schema_input=ddl, schema_format="sql_ddl")

    assert ddl in stub_agent.prompt_text
    assert "SQL DDL" in stub_agent.prompt_text


def test_erd_input_text_reaches_the_model(stub_agent):
    from seed_data.ingest.extract import extract_schema

    dbml = "Table users {\n  id int [pk]\n}"
    extract_schema(erd_input=dbml, erd_format="dbml")

    assert dbml in stub_agent.prompt_text
    assert "DBML" in stub_agent.prompt_text


def test_current_schema_reaches_the_model_for_revision(stub_agent):
    """Regression (blocking): schema revision sent the schema as `schema_input`,
    which was both dropped from the prompt and the wrong label — an
    InferredSchema dump is not a source JSON Schema."""
    from seed_data.ingest.extract import extract_schema

    current = _fake_schema("Widget").model_dump_json()
    extract_schema(current_schema=current, override_instructions="loosen ranges")

    prompt = stub_agent.prompt_text
    assert "Widget" in prompt
    assert "loosen ranges" in prompt


def test_extract_schema_raises_on_refusal(monkeypatch):
    """A guardrail refusal returns structured_output=None; `to_canonical(None)`
    raised an opaque AttributeError from inside the converter."""
    from seed_data.ingest.extract import extract_schema

    class _RefusingAgent:
        def __call__(self, user_content, **kwargs):
            return type("R", (), {"structured_output": None})()

    monkeypatch.setattr(
        "seed_data.ingest.extract._build_schema_agent",
        lambda model=None, session=None: _RefusingAgent(),
    )

    with pytest.raises(ValueError, match="no structured schema"):
        extract_schema(text_description="anything")


def test_extract_schema_builds_model_through_make_model(monkeypatch):
    """The session only reaches Bedrock via `utils.make_model`; a direct
    `BedrockModel(...)` here ignored it."""
    from seed_data.ingest import extract as extract_mod

    captured = {}
    sentinel = object()

    def fake_make_model(model_key, **kwargs):
        captured["model_key"] = model_key
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("seed_data.utils.make_model", fake_make_model)
    monkeypatch.setattr(extract_mod, "Agent", lambda **kwargs: object())

    extract_mod._build_schema_agent(model="sonnet", session=sentinel)

    assert captured["model_key"] == "sonnet"
    assert captured["session"] is sentinel


def test_only_the_reading_tool_is_registered():
    """The parse helpers echo their text argument back, and that text is inlined
    now — registered, the model could call them with the empty string it used to be
    handed, which is blocker 1's failure by another route. The system prompt must
    name exactly what is registered: it previously advertised `read_document` and
    `read_erd_image`, neither of which was ever available (both are now deleted)."""
    from seed_data.ingest.extract import SCHEMA_EXTRACTION_PROMPT, _SCHEMA_TOOLS

    names = {getattr(t, "tool_name", getattr(t, "__name__", "")) for t in _SCHEMA_TOOLS}
    assert names == {"analyze_example_data"}
    for absent in ("read_document", "read_erd_image", "parse_schema_definition",
                   "parse_erd", "apply_schema_overrides"):
        assert absent not in SCHEMA_EXTRACTION_PROMPT


def test_parse_schema_definition_does_not_mislabel_unknown_formats():
    """`json_schema else "SQL DDL"` told the model an unrecognized format was
    SQL DDL."""
    import json

    from seed_data.ingest.tools import parse_schema_definition

    payload = json.loads(parse_schema_definition("whatever", "protobuf"))
    assert "SQL DDL" not in payload["format_label"]
    assert "protobuf" in payload["format_label"]


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

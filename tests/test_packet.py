"""Unit tests for packet generation module.

No LLM calls — tests config loading, schema resolution, document planning,
PDF merging, label emission, JSON parsing, and shared context formatting.

Usage:
  uv run pytest tests/test_packet.py -v
  # or directly:
  uv run python tests/test_packet.py
"""
import json
import os
import tempfile


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def test_load_packet_config():
    from seed_data.packet import load_packet_config
    config = load_packet_config("src/seed_data/packets/insurance-claim-packet")
    assert config.name == "insurance-claim-packet"
    assert len(config.documents) == 3
    assert config.documents[0].document_class == "Insurance Claim"
    assert config.documents[1].min_instances == 1
    assert config.documents[1].max_instances == 2
    assert config.shared_context is not None
    assert "claimant_name" in config.shared_context
    print("✓ load_packet_config")


def test_load_packet_config_missing():
    from seed_data.packet import load_packet_config
    try:
        load_packet_config("/nonexistent/path")
        assert False, "Should have raised"
    except (FileNotFoundError, OSError):
        pass
    print("✓ load_packet_config raises on missing dir")


# ---------------------------------------------------------------------------
# Schema resolution
# ---------------------------------------------------------------------------

def test_resolve_schema_dir():
    from seed_data.packet import _resolve_schema_dir
    resolved = _resolve_schema_dir("insurance-claim")
    assert os.path.isdir(resolved)
    assert resolved.endswith("schemas/insurance-claim")
    print("✓ _resolve_schema_dir relative name")


def test_resolve_schema_dir_absolute():
    from seed_data.packet import _resolve_schema_dir
    abs_path = os.path.abspath("src/seed_data/schemas/invoice")
    resolved = _resolve_schema_dir(abs_path)
    assert resolved == abs_path
    print("✓ _resolve_schema_dir absolute path")


def test_resolve_schema_dir_missing():
    from seed_data.packet import _resolve_schema_dir
    try:
        _resolve_schema_dir("nonexistent-schema")
        assert False, "Should have raised"
    except FileNotFoundError as e:
        assert "nonexistent-schema" in str(e)
    print("✓ _resolve_schema_dir raises on missing schema")


def test_all_schemas_resolve():
    from seed_data.packet import load_packet_config
    config = load_packet_config("src/seed_data/packets/insurance-claim-packet")
    for doc in config.documents:
        assert os.path.isdir(doc.schema_dir), f"{doc.document_class}: {doc.schema_dir} not found"
        assert os.path.exists(os.path.join(doc.schema_dir, "schema.json"))
    print("✓ all packet schemas resolve to real directories")


# ---------------------------------------------------------------------------
# Document plan
# ---------------------------------------------------------------------------

def test_build_document_plan_fixed_counts():
    from seed_data.packet import _build_document_plan, PacketConfig, DocumentSpec
    config = PacketConfig(
        name="test", description="",
        documents=[
            DocumentSpec(document_class="A", schema_dir=tempfile.gettempdir(), min_instances=2, max_instances=2),
            DocumentSpec(document_class="B", schema_dir=tempfile.gettempdir(), min_instances=1, max_instances=1),
        ],
    )
    plan = _build_document_plan(config, {})
    classes = [p.document_class for p in plan]
    assert classes.count("A") == 2
    assert classes.count("B") == 1
    assert plan[0].instance_index == 0
    assert plan[1].instance_index == 1
    print("✓ _build_document_plan fixed counts")


def test_build_document_plan_range():
    from seed_data.packet import _build_document_plan, PacketConfig, DocumentSpec
    config = PacketConfig(
        name="test", description="",
        documents=[
            DocumentSpec(document_class="X", schema_dir=tempfile.gettempdir(), min_instances=1, max_instances=5),
        ],
    )
    # Run multiple times to verify range is respected
    counts = set()
    for _ in range(50):
        plan = _build_document_plan(config, {})
        count = len(plan)
        assert 1 <= count <= 5
        counts.add(count)
    # With 50 trials over range [1,5], we should see at least 2 different counts
    assert len(counts) >= 2, f"Expected variation, got {counts}"
    print("✓ _build_document_plan respects min/max range")


def test_build_document_plan_optional_skip():
    from seed_data.packet import _build_document_plan, PacketConfig, DocumentSpec
    config = PacketConfig(
        name="test", description="",
        documents=[
            DocumentSpec(document_class="Required", schema_dir=tempfile.gettempdir(), required=True),
            DocumentSpec(document_class="Optional", schema_dir=tempfile.gettempdir(), required=False),
        ],
    )
    # Run many times — optional should be skipped sometimes
    skip_count = 0
    for _ in range(100):
        plan = _build_document_plan(config, {})
        classes = [p.document_class for p in plan]
        assert "Required" in classes  # always present
        if "Optional" not in classes:
            skip_count += 1
    assert skip_count > 0, "Optional doc was never skipped in 100 trials"
    assert skip_count < 100, "Optional doc was always skipped"
    print("✓ _build_document_plan skips optional docs sometimes")


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def test_parse_json_plain():
    from seed_data.packet import _parse_json_from_response
    assert _parse_json_from_response('{"a": 1}') == {"a": 1}
    print("✓ _parse_json_from_response plain JSON")


def test_parse_json_markdown_fences():
    from seed_data.packet import _parse_json_from_response
    text = '```json\n{"a": 1}\n```'
    assert _parse_json_from_response(text) == {"a": 1}
    print("✓ _parse_json_from_response markdown fences")


def test_parse_json_surrounded_by_text():
    from seed_data.packet import _parse_json_from_response
    text = 'Here is the result: {"name": "Jane"} as requested.'
    assert _parse_json_from_response(text) == {"name": "Jane"}
    print("✓ _parse_json_from_response surrounded by text")


def test_parse_json_garbage():
    from seed_data.packet import _parse_json_from_response
    assert _parse_json_from_response("no json here at all") == {}
    print("✓ _parse_json_from_response returns {} on garbage")


# ---------------------------------------------------------------------------
# Shared context formatting
# ---------------------------------------------------------------------------

def test_format_shared_context_instructions():
    from seed_data.packet import _format_shared_context_instructions
    ctx = {"applicant_name": "Jane Doe", "address": "123 Oak St"}
    text = _format_shared_context_instructions(ctx, "Invoice")
    assert "Jane Doe" in text
    assert "123 Oak St" in text
    assert "SHARED CONTEXT" in text
    print("✓ _format_shared_context_instructions")


def test_format_shared_context_empty():
    from seed_data.packet import _format_shared_context_instructions
    assert _format_shared_context_instructions({}, "Invoice") == ""
    print("✓ _format_shared_context_instructions empty")


# ---------------------------------------------------------------------------
# PDF merging
# ---------------------------------------------------------------------------

def _make_test_pdf(path: str, text: str = "test", pages: int = 1):
    """Create a minimal PDF with N blank pages using pypdf.

    The packet tests only exercise merging and page counting, so the page
    content is irrelevant; blank Letter-size pages are sufficient.
    """
    import pypdf
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with open(path, "wb") as f:
        writer.write(f)
    writer.close()


def test_merge_pdfs():
    from seed_data.packet import _merge_pdfs, _count_pdf_pages
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf1 = os.path.join(tmpdir, "a.pdf")
        pdf2 = os.path.join(tmpdir, "b.pdf")
        merged = os.path.join(tmpdir, "merged.pdf")
        _make_test_pdf(pdf1, "doc A", pages=2)
        _make_test_pdf(pdf2, "doc B", pages=3)
        _merge_pdfs([pdf1, pdf2], merged)
        assert os.path.exists(merged)
        assert _count_pdf_pages(merged) == 5
    print("✓ _merge_pdfs")


def test_count_pdf_pages():
    from seed_data.packet import _count_pdf_pages
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.pdf")
        _make_test_pdf(path, pages=4)
        assert _count_pdf_pages(path) == 4
    print("✓ _count_pdf_pages")


# ---------------------------------------------------------------------------
# Label emission
# ---------------------------------------------------------------------------

def test_emit_baseline_labels():
    from seed_data.packet import _emit_baseline_labels, SectionResult
    with tempfile.TemporaryDirectory() as tmpdir:
        sections = [
            SectionResult(
                document_class="Invoice",
                page_indices=[0, 1],
                inference_result={"total": 100},
            ),
            SectionResult(
                document_class="Bank Statement",
                page_indices=[2],
                inference_result={"balance": 5000},
            ),
        ]
        _emit_baseline_labels(sections, "packet_001.pdf", tmpdir)

        # Check section 1
        r1_path = os.path.join(tmpdir, "baseline", "packet_001.pdf", "sections", "1", "result.json")
        assert os.path.exists(r1_path)
        with open(r1_path) as f:
            r1 = json.load(f)
        assert r1["document_class"]["type"] == "Invoice"
        assert r1["split_document"]["page_indices"] == [0, 1]
        assert r1["inference_result"]["total"] == 100

        # Check section 2
        r2_path = os.path.join(tmpdir, "baseline", "packet_001.pdf", "sections", "2", "result.json")
        with open(r2_path) as f:
            r2 = json.load(f)
        assert r2["document_class"]["type"] == "Bank Statement"
        assert r2["split_document"]["page_indices"] == [2]
    print("✓ _emit_baseline_labels")


def test_emit_classes_yaml():
    from seed_data.packet import emit_classes_yaml, PacketConfig, DocumentSpec
    config = PacketConfig(
        name="test", description="",
        documents=[
            DocumentSpec(document_class="Invoice", schema_dir=tempfile.gettempdir()),
            DocumentSpec(document_class="Bank Statement", schema_dir=tempfile.gettempdir()),
            DocumentSpec(document_class="Invoice", schema_dir=tempfile.gettempdir()),  # duplicate
        ],
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = emit_classes_yaml(config, tmpdir)
        assert os.path.exists(path)
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["classes"] == ["Bank Statement", "Invoice"]  # sorted, deduplicated
    print("✓ emit_classes_yaml")


# ---------------------------------------------------------------------------
# Inference result loading
# ---------------------------------------------------------------------------

def test_load_inference_result():
    from seed_data.packet import _load_inference_result
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "data.json")
        with open(path, "w") as f:
            json.dump({"name": "test", "amount": 42.5}, f)
        result = _load_inference_result(path)
        assert result == {"name": "test", "amount": 42.5}
    print("✓ _load_inference_result")


def test_load_inference_result_missing():
    from seed_data.packet import _load_inference_result
    assert _load_inference_result(None) == {}
    assert _load_inference_result("/nonexistent/file.json") == {}
    print("✓ _load_inference_result handles missing files")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def test_write_packet_manifest():
    from seed_data.packet import write_packet_manifest, PacketConfig, DocumentSpec, PacketResult, SectionResult
    config = PacketConfig(
        name="test-packet", description="Test",
        documents=[DocumentSpec(document_class="Invoice", schema_dir=tempfile.gettempdir())],
    )
    results = [
        PacketResult(
            packet_id="p001", merged_pdf=os.path.join(tempfile.gettempdir(), "p001.pdf"), success=True,
            shared_context={"name": "Jane"},
            sections=[SectionResult(
                document_class="Invoice", page_indices=[0], inference_result={},
                doc_id="abc123", success=True,
            )],
        ),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = write_packet_manifest(results, config, tmpdir, elapsed_s=10.5)
        assert os.path.exists(path)
        with open(path) as f:
            manifest = json.load(f)
        assert manifest["packet_type"] == "test-packet"
        assert manifest["count_requested"] == 1
        assert manifest["count_succeeded"] == 1
        assert manifest["elapsed_s"] == 10.5
        assert manifest["packets"][0]["packet_id"] == "p001"
        assert manifest["packets"][0]["shared_context"]["name"] == "Jane"
    print("✓ write_packet_manifest")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_load_packet_config()
    test_load_packet_config_missing()
    test_resolve_schema_dir()
    test_resolve_schema_dir_absolute()
    test_resolve_schema_dir_missing()
    test_all_schemas_resolve()
    test_build_document_plan_fixed_counts()
    test_build_document_plan_range()
    test_build_document_plan_optional_skip()
    test_parse_json_plain()
    test_parse_json_markdown_fences()
    test_parse_json_surrounded_by_text()
    test_parse_json_garbage()
    test_format_shared_context_instructions()
    test_format_shared_context_empty()
    test_merge_pdfs()
    test_count_pdf_pages()
    test_emit_baseline_labels()
    test_emit_classes_yaml()
    test_load_inference_result()
    test_load_inference_result_missing()
    test_write_packet_manifest()
    print(f"\nAll packet tests passed.")

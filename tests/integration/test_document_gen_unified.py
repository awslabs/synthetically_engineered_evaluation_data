"""Integration: document generation through the unified schema path (Milestone 3).

Verifies that an ingested / round-tripped ``InferredSchema`` drives the existing
document pipeline unchanged — the whole point of the M3 adapter — and that the
published ``--schema-dir`` path still works.

Live Bedrock. Excluded from the default run; invoke explicitly with creds:

    AWS_PROFILE=your-profile uv run pytest tests/integration/test_document_gen_unified.py -v
"""
import os
import subprocess
import sys

from seed_data.schema.io import from_schema_dir, to_schema_dir
from seed_data.stages.pipeline import GeneratedDoc


def _bundled_schema_dir(name="fcc-invoice") -> str:
    here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(here, "src", "seed_data", "schemas", name)


def test_ingest_then_generate_doc(generator):
    """ingest(free text) -> InferredSchema -> generate() -> a PDF on disk."""
    schema = generator.ingest("FCC broadcast advertising invoices", name="fcc")
    assert schema.entities, "ingest produced an empty schema"

    doc = generator.generate(schema, scenario="A regional TV station in the Midwest")
    assert isinstance(doc, GeneratedDoc)
    assert doc.success, f"generation failed: {doc}"
    assert doc.pdf_path and os.path.isfile(doc.pdf_path)
    assert os.path.getsize(doc.pdf_path) > 0


def test_inferred_schema_file_to_pdf(generator, tmp_path):
    """A round-tripped InferredSchema JSON file drives generate() to a PDF.

    Exercises the M3 contract directly: bundled dir -> InferredSchema -> adapter
    -> pipeline triple, with no schema-dir in the loop.
    """
    inferred = from_schema_dir(_bundled_schema_dir("fcc-invoice"))
    doc = generator.generate(inferred)
    assert isinstance(doc, GeneratedDoc)
    assert doc.success, f"generation failed: {doc}"
    assert doc.pdf_path and os.path.isfile(doc.pdf_path)


def test_generate_documents_cli_from_schema_json(aws_credentials, tmp_path):
    """`seed-data generate-documents <schema.json>` renders a PDF end to end."""
    inferred = from_schema_dir(_bundled_schema_dir("fcc-invoice"))
    schema_json = tmp_path / "schema.json"
    to_schema_dir(inferred, str(tmp_path / "schemadir"))
    # generate-documents takes the schema.json file path, not the dir
    schema_json = tmp_path / "schemadir" / "schema.json"
    assert schema_json.is_file()

    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "seed_data", "generate-documents", str(schema_json),
         "--count", "1", "--output", str(out_dir),
         "--doc-model", "sonnet", "--critic-model", "haiku", "--quiet"],
        capture_output=True, text=True, timeout=1800,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    pdfs = list(out_dir.rglob("*.pdf"))
    assert pdfs, f"no PDF produced under {out_dir}"


def test_legacy_schema_dir_unchanged(aws_credentials, tmp_path):
    """The published entry point (`--schema-dir <name>`) still produces a PDF."""
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "seed_data", "--schema-dir", "fcc-invoice",
         "--count", "1", "--output", str(out_dir),
         "--doc-model", "sonnet", "--critic-model", "haiku"],
        capture_output=True, text=True, timeout=1800,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert list(out_dir.rglob("*.pdf")), f"no PDF produced under {out_dir}"

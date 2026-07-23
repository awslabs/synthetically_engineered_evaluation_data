# Milestone 4: End-to-End Integration & `seed-data run`

**Goal:** Full pipeline works end-to-end with a unified `seed-data run` command that dispatches ingest → schema → generate (structured or documents). Evaluation metrics are shared across modalities. Cross-modality generation (same schema → both outputs) is verified.

**Duration:** ~1 week

**Depends on:** Milestones 1, 2, 3

---

## What Changes

| File / Dir | Action |
|---|---|
| `src/seed_data/cli.py` | **MODIFIED** — add `run` subcommand |
| `src/seed_data/run.py` | **NEW** — dispatch orchestrator |
| `src/seed_data/evaluation/critique.py` | **NEW** — LLM critique loops (ported from doc-gen) available to structured |
| `src/seed_data/evaluation/__init__.py` | **MODIFIED** — expose critique alongside metrics |
| `tests/integration/test_e2e.py` | **NEW** — cross-modality integration tests |
| `tests/test_run.py` | **NEW** — unit tests for dispatch logic |

---

## Implementation Steps

### 4.1 Implement `seed-data run` dispatch

The `run` command combines ingest + generate in one shot:

```bash
# Structured output
seed-data run "Generate realistic customer orders" --output structured --rows 500 --format csv

# Document output
seed-data run "Generate FCC broadcast invoices" --output documents --count 10 --augment

# From files
seed-data run ./spec.pdf --output structured --rows 200
seed-data run ./example.csv ./constraints.txt --output structured --rows 1000
```

Implementation in `src/seed_data/run.py`:

```python
from enum import Enum

class OutputModality(str, Enum):
    STRUCTURED = "structured"
    DOCUMENTS = "documents"

def run(
    *inputs: str,
    output: OutputModality = OutputModality.STRUCTURED,
    # Structured-specific
    rows: int = 100,
    format: str = "csv",
    # Document-specific
    count: int = 1,
    augment: bool = False,
    renderer: str = "xhtml2pdf",
    # Common
    output_dir: str = "./output",
    models: dict | None = None,
    threshold: int = 7,
) -> dict:
    """End-to-end: ingest inputs → generate output.

    Returns a result dict with paths to generated files + metadata.
    """
    from seed_data.ingest import ingest
    schema = ingest(*inputs)

    if output == OutputModality.STRUCTURED:
        from seed_data.structured import generate_structured
        return generate_structured(schema, target_count=rows, export_format=format, output_dir=output_dir)
    elif output == OutputModality.DOCUMENTS:
        from seed_data.schema.adapter import inferred_to_resolved
        from seed_data.stages.pipeline import generate
        resolved = inferred_to_resolved(schema)
        # Dispatch to existing doc-gen pipeline
        if count == 1:
            result = generate(resolved=resolved, output_dir=output_dir, augment=augment, renderer=renderer, threshold=threshold)
            return {"result": result, "schema": schema}
        else:
            from seed_data.stages.batch import generate_batch
            result = generate_batch(resolved=resolved, output_dir=output_dir, count=count, augment=augment, renderer=renderer, threshold=threshold)
            return {"result": result, "schema": schema}
```

### 4.2 Cross-modality evaluation

Make doc-gen's LLM critique loops available for structured data (quality assessment via LLM), and make tabular's quantitative metrics available for document generation:

**Structured → LLM critique (new):**
- After generating structured data, optionally run an LLM critique that checks semantic consistency (e.g., "does the address match the state?", "are order dates after customer creation dates?").
- Implemented as `seed_data.evaluation.critique.critique_structured()`.

**Documents → quantitative metrics (new):**
- After generating document ground-truth JSON, compute basic coverage/completeness metrics on the label data.
- Implemented as `seed_data.evaluation.metrics.evaluate_document_labels()`.

```python
# src/seed_data/evaluation/__init__.py
from seed_data.evaluation.metrics import run_evaluation, evaluate_document_labels
from seed_data.evaluation.critique import critique_structured
```

### 4.3 CLI wiring

Add to `cli.py`:

```python
@app.command("run")
def run_cmd(
    inputs: list[str],
    output: str = "structured",  # "structured" or "documents"
    rows: int = 100,
    format: str = "csv",
    count: int = 1,
    augment: bool = False,
    output_dir: str = "./output",
    # ... other flags
):
    """End-to-end: ingest inputs → generate output in one command."""
    from seed_data.run import run, OutputModality
    result = run(
        *inputs,
        output=OutputModality(output),
        rows=rows, format=format, count=count,
        augment=augment, output_dir=output_dir,
    )
    # Print summary
```

### 4.4 Extend Python API

```python
# src/seed_data/__init__.py — add to __getattr__
if name == "run":
    from seed_data.run import run
    return run
```

Usage:
```python
from seed_data import run

# Structured
result = run("Customer orders with priority field", output="structured", rows=500)

# Documents
result = run("FCC broadcast invoices", output="documents", count=10, augment=True)
```

---

## Testing Plan

### Unit Tests (`tests/test_run.py`)

| Test | What it verifies |
|---|---|
| `test_run_dispatches_structured` | Mock ingest + generate_structured, verify `run(..., output="structured")` calls both |
| `test_run_dispatches_documents` | Mock ingest + generate (doc), verify `run(..., output="documents")` calls both |
| `test_run_passes_rows` | `rows=500` forwarded to generate_structured |
| `test_run_passes_count_augment` | `count=10, augment=True` forwarded to doc gen |
| `test_run_multiple_inputs` | Multiple strings/paths forwarded to `ingest()` |
| `test_output_modality_enum` | Invalid modality raises ValueError |
| `test_run_structured_returns_schema` | Result includes the inferred schema for inspection |
| `test_run_documents_returns_schema` | Same for documents |

### Unit Tests — Cross-modality Evaluation (`tests/test_evaluation_cross.py`)

| Test | What it verifies |
|---|---|
| `test_critique_structured_mock` | Mock LLM, feed generated data → get critique items back |
| `test_evaluate_document_labels_coverage` | Feed doc labels (JSON) → coverage score computed |
| `test_evaluate_document_labels_completeness` | Missing fields → low completeness score |

### CLI Smoke Tests

| Test | What it verifies |
|---|---|
| `test_run_help` | `seed-data run --help` exits 0 |
| `test_run_invalid_output` | `seed-data run "text" --output invalid` exits with error |
| `test_all_subcommands_listed` | `seed-data --help` shows all subcommands (ingest, generate-structured, generate-documents, run, packet) |

### Integration Tests (`tests/integration/test_e2e.py`)

```bash
uv run pytest tests/integration/test_e2e.py -v
```

| Test | What it verifies |
|---|---|
| `test_run_structured_text` | `run("Customer orders", output="structured", rows=20)` → CSV with 20 rows |
| `test_run_documents_text` | `run("FCC invoices", output="documents", count=2)` → 2 PDFs |
| `test_same_schema_both_modalities` | Ingest once → generate structured AND documents from same schema → consistent fields |
| `test_run_from_csv_input` | `run("sample.csv", output="structured", rows=50)` → schema matches CSV, data generated |
| `test_run_from_schema_file` | `run("schema.json", output="documents", count=1)` → PDF |
| `test_evaluation_on_structured` | After structured generation, metrics above thresholds |
| `test_evaluation_on_documents` | After doc generation, label coverage computed |

### Cross-Modality Consistency Test

```python
def test_cross_modality_consistency():
    """Same schema produces consistent outputs across modalities."""
    from seed_data import ingest, generate_structured
    from seed_data.schema.adapter import inferred_to_resolved
    from seed_data.stages.pipeline import generate

    schema = ingest("Simple 3-field invoice: number, date, total")

    # Structured output
    structured_result = generate_structured(schema, target_count=5)

    # Document output
    resolved = inferred_to_resolved(schema)
    doc_result = generate(resolved=resolved)

    # Both should have the same fields
    struct_fields = set(structured_result["data"]["Invoice"][0].keys())
    doc_fields = set(doc_result.data.keys()) if doc_result.data else set()

    # At minimum, the schema fields should appear in both
    schema_fields = {f.name for f in schema.entities[0].fields}
    assert schema_fields.issubset(struct_fields)
    assert schema_fields.issubset(doc_fields)
```

---

## Acceptance Criteria

- [ ] `seed-data run "description" --output structured` works end-to-end
- [ ] `seed-data run "description" --output documents` works end-to-end
- [ ] `seed-data run file.csv file.pdf "add priority" --output structured` handles mixed inputs
- [ ] Same schema produces outputs in both modalities with consistent fields
- [ ] LLM critique is available for structured data (optional quality check)
- [ ] Quantitative metrics are available for document labels
- [ ] All existing commands (`--schema-dir`, `packet`) still work
- [ ] All previous milestone tests still pass
- [ ] Python API: `from seed_data import run` works

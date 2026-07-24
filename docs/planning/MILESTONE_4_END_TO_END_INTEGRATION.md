# Milestone 4: End-to-End Integration & `seed-data run`

**Goal:** Full pipeline works end-to-end with a unified `seed-data run` command that dispatches ingest → schema → generate (structured or documents). Evaluation metrics are shared across modalities. Cross-modality generation (same schema → both outputs) is verified.

**Duration:** ~1 week

**Depends on:** Milestones 1, 2, 3

---

## What Changes

| File / Dir | Action |
|---|---|
| `src/seed_data/api.py` | **MODIFIED** — add `Generator.run()` verb (dispatch via existing verbs) |
| `src/seed_data/cli.py` | **MODIFIED** — add `run` subcommand |
| `src/seed_data/evaluation/critique.py` | **NEW** — LLM critique loops (ported from doc-gen) available to structured |
| `src/seed_data/evaluation/__init__.py` | **MODIFIED** — expose critique alongside metrics |
| `tests/integration/test_e2e.py` | **NEW** — cross-modality integration tests |
| `tests/test_run.py` | **NEW** — unit tests for `Generator.run()` dispatch logic |

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

Implementation — a new verb on the existing `Generator` facade (consistent with
how the Python offering works today):

```python
# In seed_data/api.py — new method on Generator

class Generator:
    # ... existing generate / generate_batch / generate_packet / ingest / generate_structured ...

    def run(
        self,
        *inputs: str,
        output: str = "structured",    # "structured" or "documents"
        # Structured-specific
        rows: int = 100,
        format: str = "csv",
        # Document-specific
        count: int = 1,
        scenario: str = "",
        augment: bool | None = None,
    ) -> "GeneratedDoc | BatchResult | StructuredResult":
        """End-to-end: ingest inputs → generate output in one call.

        Dispatches to self.ingest() → self.generate_structured() or
        self.generate() / self.generate_batch() based on `output`.

        Returns a typed result — StructuredResult for "structured",
        GeneratedDoc (count==1) or BatchResult (count>1) for "documents".
        """
        schema = self.ingest(*inputs)

        if output == "structured":
            return self.generate_structured(schema, rows=rows, format=format)
        elif output == "documents":
            if count == 1:
                return self.generate(schema, scenario=scenario, augment=augment)
            else:
                return self.generate_batch(schema, count=count, scenario=scenario, augment=augment)
        else:
            raise ValueError(f"output must be 'structured' or 'documents', got {output!r}")
```

Notes:
- `run()` is just a convenience verb that chains `ingest()` + the appropriate
  `generate*()` verb. Configuration lives on the `Generator` instance as always.
- Return type is a typed model (GeneratedDoc / BatchResult / StructuredResult) — no
  raw dicts. Consistent with the existing offering.
- The `schema` argument on `generate()`/`generate_batch()` now also accepts
  `InferredSchema` (adapted internally via `schema/adapter.py`), extending the
  existing `str | Schema` union.

The underlying dispatch logic is implemented in `src/seed_data/_dispatch.py`
(internal engine — not exposed in `__init__.py` or documented as public API).

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

Add to `cli.py`. The CLI constructs a `Generator` and calls its `run()` verb —
same pattern as how the existing CLI builds model configs and calls the pipeline:

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
    # ... model flags, threshold, etc. (same as existing CLI)
):
    """End-to-end: ingest inputs → generate output in one command."""
    from seed_data import Generator
    gen = Generator(output_dir=output_dir, models=models, threshold=threshold, ...)
    result = gen.run(*inputs, output=output, rows=rows, format=format, count=count, augment=augment)
    # Print typed result summary (result.success, result.output_paths, etc.)
```

### 4.4 Python API — stays on `Generator`

No new top-level functions. The Python offering is:

```python
from seed_data import Generator, ModelConfig, StructuredResult

gen = Generator(models=ModelConfig(data="gpt-oss", critic="sonnet"), output_dir="./out")

# End-to-end structured (one call)
result = gen.run("Customer orders with priority field", output="structured", rows=500)
assert isinstance(result, StructuredResult)
print(result.row_counts, result.output_paths)

# End-to-end documents (one call)
doc = gen.run("FCC broadcast invoices", output="documents", count=1)
print(doc.pdf_path)

# Or step by step (more control):
schema = gen.ingest("Customer orders", "./constraints.pdf")
structured = gen.generate_structured(schema, rows=500, format="parquet")
document   = gen.generate(schema, scenario="Midwest food distributor")  # InferredSchema now accepted
```

`__init__.py` re-exports `StructuredResult` and `InferredSchema` lazily (same
pattern as existing `GeneratedDoc`, `BatchResult`).

---

## Testing Plan

### Unit Tests (`tests/test_run.py`)

| Test | What it verifies |
|---|---|
| `test_generator_run_dispatches_structured` | Mock `Generator.ingest` + `Generator.generate_structured`, verify `gen.run(..., output="structured")` chains both |
| `test_generator_run_dispatches_documents` | Mock `Generator.ingest` + `Generator.generate`, verify `gen.run(..., output="documents")` chains both |
| `test_generator_run_batch_documents` | `gen.run(..., output="documents", count=5)` dispatches to `generate_batch` |
| `test_generator_run_passes_rows` | `rows=500` forwarded to `generate_structured` |
| `test_generator_run_passes_count_augment` | `count=10, augment=True` forwarded to doc gen |
| `test_generator_run_multiple_inputs` | Multiple strings/paths forwarded to `ingest()` |
| `test_generator_run_invalid_output` | `gen.run(..., output="invalid")` raises ValueError |
| `test_generator_run_returns_typed_structured` | Returns `StructuredResult`, not a dict |
| `test_generator_run_returns_typed_document` | Returns `GeneratedDoc` (count=1) or `BatchResult` (count>1) |
| `test_generator_generate_accepts_inferred_schema` | `gen.generate(inferred_schema, ...)` works (adapter called internally) |

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
| `test_generator_run_structured_text` | `gen.run("Customer orders", output="structured", rows=20)` → `StructuredResult` with 20 rows |
| `test_generator_run_documents_text` | `gen.run("FCC invoices", output="documents", count=2)` → `BatchResult` with 2 docs |
| `test_same_schema_both_modalities` | `gen.ingest()` once → `gen.generate_structured()` AND `gen.generate()` → consistent fields |
| `test_generator_run_from_csv_input` | `gen.run("sample.csv", output="structured", rows=50)` → schema matches CSV columns |
| `test_generator_run_from_schema_file` | `gen.run("schema.json", output="documents", count=1)` → `GeneratedDoc` with PDF |
| `test_evaluation_on_structured` | After `gen.generate_structured()`, `result.evaluation` scores above thresholds |
| `test_evaluation_on_documents` | After `gen.generate()`, label coverage computed |

### Cross-Modality Consistency Test

```python
def test_cross_modality_consistency():
    """Same schema produces consistent outputs across modalities."""
    from seed_data import Generator

    gen = Generator(output_dir="/tmp/test_cross")

    # Step 1: ingest (shared schema)
    schema = gen.ingest("Simple 3-field invoice: number, date, total")

    # Step 2: generate in both modalities from same schema
    structured_result = gen.generate_structured(schema, rows=5, format="csv")
    doc_result = gen.generate(schema, scenario="test invoice")

    # Both should have the same fields
    struct_fields = set(structured_result.row_counts.keys())  # entity names
    doc_fields = set(doc_result.data.keys()) if doc_result.data else set()

    # At minimum, the schema fields should appear in doc labels
    schema_fields = {f.name for f in schema.entities[0].fields}
    assert schema_fields.issubset(doc_fields)
```

---

## Acceptance Criteria

- [ ] `seed-data run "description" --output structured` works end-to-end (CLI)
- [ ] `seed-data run "description" --output documents` works end-to-end (CLI)
- [ ] `seed-data run file.csv file.pdf "add priority" --output structured` handles mixed inputs
- [ ] Same schema produces outputs in both modalities with consistent fields
- [ ] LLM critique is available for structured data (optional quality check)
- [ ] Quantitative metrics are available for document labels
- [ ] All existing commands (`--schema-dir`, `packet`) still work
- [ ] All previous milestone tests still pass
- [ ] Python API: `gen.run(...)` works on `Generator` (no bare top-level functions)
- [ ] `gen.generate(inferred_schema, ...)` works (InferredSchema accepted alongside str/Schema)
- [ ] All results are typed Pydantic models (StructuredResult, GeneratedDoc, BatchResult) — no raw dicts

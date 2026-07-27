# Milestone 2: Ingest + Structured Data Generation

**Goal:** Add `seed_data.ingest` and `seed_data.structured` subpackages ported from `seed-tabular` (branch `hp/agentic-redesign`). After this milestone, a new CLI subcommand `seed-data ingest` and `seed-data generate-structured` work end-to-end: text/file/schema → `InferredSchema` → CSV/Parquet/Excel.

**Duration:** ~2 weeks

**Depends on:** Milestone 1 (unified schema layer)

### Relationship to v0.0.6's existing inference

v0.0.6 already ships `Generator.infer_schema` + `seed_data/infer.py`, which turns **documents** (PDF/PNG/JPEG, local + `s3://`) into a `Schema` via a vision model, and `seed_data/inputs.py` which resolves those inputs. This milestone does **not** replace that — it adds the **non-document** input paths (free-text, CSV, JSON-Schema, SQL-DDL, ERD) and the tabular output engine.

Concretely:
- **Reuse** `seed_data/inputs.py`'s input-resolution (paths/globs/dirs/`s3://`, `Document` type) wherever possible instead of re-implementing file loading.
- `infer_schema` remains the vision/document path → returns `Schema`.
- New `ingest` handles non-document inputs → returns the richer `InferredSchema` (typed fields/distributions/relationships from Milestone 1).
- Where a document input carries tabular structure, `ingest` may delegate to `infer_schema` and then enrich the result into an `InferredSchema`.
- The two converge on the same canonical model so downstream (`generate_structured`, `generate`) treats them uniformly.

---

## What Changes

| File / Dir | Action |
|---|---|
| `src/seed_data/ingest/` | **NEW** — schema extraction agent pipeline |
| `src/seed_data/structured/` | **NEW** — structured data generation engine |
| `src/seed_data/structured/distributions/` | **NEW** — distribution-aware generation |
| `src/seed_data/structured/postprocessing/` | **NEW** — validate/correct/filter pipeline |
| `src/seed_data/evaluation/` | **NEW** — quality metrics (diversity, fidelity, coverage, structural) |
| `src/seed_data/common/` | **NEW** — shared model config, prompts |
| `src/seed_data/prompts/schema_extraction.j2` | **NEW** — Jinja2 prompt for schema extraction |
| `src/seed_data/prompts/bulk_generation.j2` | **NEW** — Jinja2 prompt for generation |
| `src/seed_data/prompts/...` | **NEW** — remaining tabular prompts |
| `src/seed_data/cli.py` | **MODIFIED** — add `ingest` and `generate-structured` subcommands |
| `pyproject.toml` | **MODIFIED** — add optional dependency group `[structured]` |
| `tests/test_ingest.py` | **NEW** |
| `tests/test_structured.py` | **NEW** |
| `tests/test_evaluation.py` | **NEW** |

Existing files are not modified except `cli.py` (additive subcommands) and `pyproject.toml` (additive deps). The `_InferredSchema` → `_InferenceDraft` rename in `infer.py` is handled in Milestone 1; `seed_data/inputs.py` is imported (reused), not modified.

---

## Implementation Steps

### 2.1 Add optional dependency group

In `pyproject.toml`:

```toml
[project.optional-dependencies]
structured = [
    "pandas>=2.0",
    "numpy>=1.26",
    "scipy>=1.12",
    "openpyxl>=3.1",
]
dev = [
    # existing...
    "pandas>=2.0",  # needed for structured tests
    "numpy>=1.26",
    "scipy>=1.12",
    "openpyxl>=3.1",
]
```

### 2.2 Port shared config (`src/seed_data/common/`)

From `seed-tabular/models/config.py`:

```
src/seed_data/common/__init__.py
src/seed_data/common/config.py      # Model IDs, temperatures, thresholds — merged with existing MODELS dict
src/seed_data/common/prompts.py     # Jinja2 prompt loader utility
```

Key decisions:
- **Model registry:** Merge tabular's `MODEL_ID` / `BEDROCK_CLIENT_CONFIG` with the existing `MODELS` dict in `__init__.py`. The existing dict wins on conflicts (it's more complete).
- **Quality thresholds** (`QUALITY_THRESHOLDS`): move from tabular's config.py → `common/config.py`. These are structured-generation-specific but could later apply to doc generation too.
- **Temperature settings**: tabular has separate orchestrator/inference temps. Port as structured-specific config.

### 2.3 Port ingest pipeline (`src/seed_data/ingest/`)

Source files from `seed-tabular`:
- `agents/schema_extraction.py` — the unified schema extraction agent
- `tools/schema_extraction.py` — tool functions for the agent

Target layout:
```
src/seed_data/ingest/
├── __init__.py           # re-export: ingest()
├── extract.py            # schema_extraction_agent tool function (ported)
├── pipeline.py           # ingest() entry point: detect input types, call extraction
└── detect.py             # Input type auto-detection logic
```

Key changes during port:
- Replace `from models.schemas import InferredSchema, PipelineInput` → `from seed_data.schema import InferredSchema`
- Replace `from models.config import ...` → `from seed_data.common.config import ...`
- Simplify `PipelineInput` — the ingest function auto-detects inputs (strings → free-text, `.pdf`→ document, `.sql`/`.json`→ schema, `.csv`/`.xlsx`→ example data). Expose a simple `ingest(*inputs) → InferredSchema` API.
- **Reuse v0.0.6 input resolution:** `detect.py` should build on `seed_data.inputs` (the `Document` type, `resolve_inputs`, `SUPPORTED_EXTS`, and `s3://` handling already exist there). Only add detection for the non-document types tabular introduces (`.csv`/`.xlsx` example data, `.sql` DDL, `.json` schema, ERD formats, and bare-string free-text). Do NOT re-implement PDF/image/S3 loading.
- **Delegate documents to `infer_schema`:** when an input resolves to a document, `ingest` calls the existing `seed_data.infer.infer_schema` rather than duplicating vision extraction, then enriches its `Schema` into an `InferredSchema`.

### 2.4 Port structured generation (`src/seed_data/structured/`)

Source files from `seed-tabular`:
- `agents/graph_pipeline.py` → `structured/pipeline.py`
- `agents/distribution_inference.py` → `structured/distributions/inference.py`
- `agents/sample_generation.py` → `structured/sampling.py`
- `agents/bulk_generation.py` → `structured/generation.py`
- `generation/distribution_generator.py` → `structured/distributions/generator.py`
- `generation/distribution_adjustment.py` → `structured/distributions/adjustment.py`

Target layout:
```
src/seed_data/structured/
├── __init__.py               # re-export: generate_structured()
├── pipeline.py               # Graph pipeline (from graph_pipeline.py) — entry point
├── sampling.py               # Sample generation agent
├── generation.py             # Bulk generation agent
├── distributions/
│   ├── __init__.py
│   ├── inference.py          # Distribution inference agent
│   ├── generator.py          # Distribution-aware data generators
│   └── adjustment.py         # Post-hoc distribution adjustment
└── postprocessing/
    ├── __init__.py
    ├── pipeline.py           # PostProcessingPipeline (from postprocessing/)
    ├── validator.py          # Schema validation
    └── corrector.py          # Auto-correction
```

Key changes during port:
- All imports rewritten to `seed_data.*` paths
- `FunctionNode` wrapper (from graph_pipeline.py) → keep in pipeline.py or move to a shared utils
- Pipeline uses `FULLY_AUTONOMOUS` mode by default for CLI (no human-in-the-loop)
- Remove Streamlit-specific code (interactive pipeline, `streamlit_app.py` references)

### 2.5 Port evaluation metrics (`src/seed_data/evaluation/`)

Source files from `seed-tabular/evaluation/`:
- `metrics.py` — `run_evaluation()` orchestrator
- `diversity.py` — diversity score
- `fidelity.py` — distribution fidelity
- `coverage.py` — field coverage
- `structural.py` — structural integrity

Target layout:
```
src/seed_data/evaluation/
├── __init__.py             # re-export: run_evaluation(), EvaluationReport
├── metrics.py              # Orchestrator (from evaluation/metrics.py)
├── diversity.py
├── fidelity.py
├── coverage.py
└── structural.py
```

Minimal changes: mostly import path rewrites.

### 2.6 Port prompts

From `seed-tabular/prompts/`:
- `schema_extraction.j2`
- `bulk_generation.j2`
- `sample_generation.j2`
- `distribution_inference.j2`
- `critique.j2`
- `string_field_fill.j2`

Target: `src/seed_data/prompts/` (already exists for doc-gen prompts — add alongside).

Update `pyproject.toml` package-data to include `prompts/*.j2` (already there).

### 2.7 Wire CLI subcommands

Add to `src/seed_data/cli.py`:

```python
# New subcommands (additive — existing single-doc / batch / packet unchanged)

@app.command("ingest")
def ingest_cmd(inputs: list[str], output: str = "./schema.json"):
    """Ingest inputs → produce an InferredSchema JSON file."""
    from seed_data.ingest import ingest
    from seed_data.schema import to_json_schema
    schema = ingest(*inputs)
    # Write to output path
    ...

@app.command("generate-structured")
def generate_structured_cmd(schema_path: str, rows: int = 100, format: str = "csv", output: str = "./output"):
    """Generate structured data from an InferredSchema."""
    from seed_data.structured import generate_structured
    generate_structured(schema_path, target_count=rows, export_format=format, output_dir=output)
```

The existing CLI uses `argparse` via `__main__.py` and `cli.py`. We'll add these as sub-parsers to maintain the pattern.

### 2.8 Public Python API — extend the `Generator` facade (do NOT add bare functions)

**The supported Python surface is the `Generator` class** (`seed_data.api`), which
follows a "configure once, call typed verbs, get typed results" contract — its
docstring states plainly: *"The engines are internal; this facade is the supported
surface."* The structured extension must be delivered through this same offering,
not as module-level `ingest()` / `generate_structured()` functions returning dicts.
That keeps one blessed entry point and one mental model for users.

Two additions to `Generator`, mirroring the existing `generate*` verbs:

```python
class Generator:
    # ... existing generate / generate_batch / generate_packet unchanged ...

    def ingest(self, *inputs: str) -> InferredSchema:
        """Ingest any inputs (text, CSV, PDF, JSON Schema, SQL DDL, ERD) into a
        unified InferredSchema. Auto-detects each input's type.

        Returns a typed InferredSchema (not a dict), consistent with the other verbs.
        """
        from seed_data.ingest import run_ingest
        return run_ingest(*inputs, models=self.models, session=self.session)

    def generate_structured(
        self,
        schema: "str | InferredSchema",
        *,
        rows: int = 100,
        format: str = "csv",
        verbose: bool = True,
    ) -> "StructuredResult":
        """Generate structured data (CSV/Parquet/Excel) from a schema.

        `schema` accepts a bundled name, a path to an InferredSchema JSON file, or
        an InferredSchema object. Returns a typed StructuredResult — consistent
        with GeneratedDoc / BatchResult / PacketResult.
        """
        from seed_data.structured import run_structured
        resolved = self._resolve_inferred(schema)
        return run_structured(
            resolved, target_count=rows, export_format=format,
            output_dir=self.output_dir, models=self.models,
            threshold=self.threshold, session=self.session, verbose=verbose,
        )
```

Notes:
- Configuration (`models`, `threshold`, `output_dir`, `session`) is read from the
  `Generator` instance — exactly like the existing verbs. Per-call args describe
  only *what* to make.
- `StructuredResult` is a new typed Pydantic model (see 2.9), NOT a dict. It sits
  alongside `GeneratedDoc` / `BatchResult` / `PacketResult`.
- The underlying `seed_data.ingest.run_ingest` and `seed_data.structured.run_structured`
  functions are **internal engines**, not part of the public API — same as
  `stages.pipeline.generate` is internal today.
- Add `Generator.available_input_types()` discovery helper alongside the existing
  `available_schemas()` / `available_packets()`.

### 2.9 Typed result model

Add to `seed_data/api.py` (alongside `BatchResult`), keeping the "no stringly-typed
dicts" contract:

```python
class StructuredResult(BaseModel):
    """Typed result of a structured-data generation run."""
    success: bool
    schema: InferredSchema
    output_paths: list[str] = Field(default_factory=list)   # written files
    format: str                                             # csv | parquet | xlsx
    row_counts: dict[str, int] = Field(default_factory=dict)  # per-entity row count
    evaluation: dict[str, float] = Field(default_factory=dict) # metric scores
    token_usage: dict = Field(default_factory=lambda: {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0})
    error: str | None = None
```

Usage — one consistent offering across modalities:

```python
from seed_data import Generator, ModelConfig

gen = Generator(models=ModelConfig(data="gpt-oss", critic="sonnet"), output_dir="./out")

# Document generation (existing)
doc     = gen.generate("invoice", scenario="Midwest food distributors")

# Structured generation (new — same facade, same shape)
schema  = gen.ingest("Generate realistic customer orders with varying statuses")
result  = gen.generate_structured(schema, rows=500, format="parquet")
print(result.row_counts, result.evaluation)
```

`StructuredResult` and `InferredSchema` are re-exported lazily from
`seed_data.__init__` (via `__getattr__`) so they can be type-imported, matching how
`GeneratedDoc` / `BatchResult` are exposed today. No bare `ingest` / `generate_structured`
functions are added to the top-level namespace.

---

## Testing Plan

### Unit Tests — Ingest (`tests/test_ingest.py`)

| Test | What it verifies |
|---|---|
| `test_detect_input_text` | `detect_input_type("Generate invoices")` → `InputType.FREE_TEXT` |
| `test_detect_input_csv` | `detect_input_type("data.csv")` → `InputType.EXAMPLE_DATA` |
| `test_detect_input_json_schema` | `detect_input_type("schema.json")` → `InputType.SCHEMA` |
| `test_detect_input_sql` | `detect_input_type("create_table.sql")` → `InputType.SCHEMA` |
| `test_detect_input_pdf` | `detect_input_type("requirements.pdf")` → `InputType.DOCUMENT` (delegates to `seed_data.inputs`) |
| `test_detect_input_s3` | `detect_input_type("s3://bucket/doc.pdf")` → `InputType.DOCUMENT` (reuses `inputs.py` S3 handling) |
| `test_detect_input_mixed` | Multiple inputs detected correctly |
| `test_detect_reuses_inputs_module` | Document/image/S3 classification defers to `seed_data.inputs`, not a reimplementation |
| `test_schema_extraction_mock` | Mock the LLM call, verify `InferredSchema` output from a text description |
| `test_schema_extraction_from_csv_mock` | Mock LLM, feed CSV header → valid schema with correct fields |
| `test_ingest_delegates_document_to_infer_schema` | Mock `infer.infer_schema`; a `.pdf` input routes through it, result enriched to `InferredSchema` |
| `test_ingest_entrypoint_mock` | Full `ingest()` call with mocked agents → returns `InferredSchema` |

### Unit Tests — Structured (`tests/test_structured.py`)

| Test | What it verifies |
|---|---|
| `test_pipeline_state_init` | `PipelineState()` initializes correctly |
| `test_function_node_basic` | `FunctionNode` wraps a function and returns `MultiAgentResult` |
| `test_distribution_spec_normal` | Normal distribution generates values within expected range |
| `test_distribution_spec_categorical` | Categorical weighted distribution respects weights |
| `test_distribution_generator_numeric` | Generate 100 numeric values → stats match spec |
| `test_distribution_generator_string` | Pattern-based string generation |
| `test_postprocessing_validator` | Validator catches type errors, constraint violations |
| `test_postprocessing_corrector` | Corrector fixes nullable field issues |
| `test_postprocessing_pipeline` | Full pipeline: validate → correct → filter |
| `test_graph_pipeline_build` | `build_graph_pipeline()` constructs valid graph (no execution) |

### Unit Tests — Evaluation (`tests/test_evaluation.py`)

| Test | What it verifies |
|---|---|
| `test_diversity_score_uniform` | Uniform data → high diversity score |
| `test_diversity_score_constant` | Constant column → low diversity score |
| `test_fidelity_score_matching` | Data matching distribution spec → high fidelity |
| `test_fidelity_score_mismatch` | Data deviating from spec → low fidelity |
| `test_coverage_all_fields` | All fields populated → coverage 1.0 |
| `test_coverage_sparse` | Many nulls → low coverage |
| `test_structural_valid` | Valid FK refs → high structural score |
| `test_structural_broken_fk` | Broken FK → low structural score |
| `test_run_evaluation_full` | End-to-end `run_evaluation()` returns `EvaluationReport` |

### CLI Smoke Tests (`tests/test_cli_smoke.py` — extend existing)

| Test | What it verifies |
|---|---|
| `test_ingest_help` | `seed-data ingest --help` exits 0 |
| `test_generate_structured_help` | `seed-data generate-structured --help` exits 0 |
| `test_existing_commands_unchanged` | Existing `--schema-dir`, `packet` commands still parse correctly |

### Integration Tests (`tests/integration/test_structured_e2e.py`)

Require Bedrock credentials — run explicitly:

```bash
uv run pytest tests/integration/test_structured_e2e.py -v
```

| Test | What it verifies |
|---|---|
| `test_ingest_text_to_schema` | `seed-data ingest "Customer orders"` → produces valid schema.json |
| `test_ingest_csv_to_schema` | `seed-data ingest sample.csv` → schema matches CSV columns |
| `test_generate_structured_csv` | `seed-data generate-structured schema.json --rows 10 --format csv` → valid CSV |
| `test_generate_structured_parquet` | Same with parquet output |
| `test_end_to_end_text` | `gen.ingest("order data") → gen.generate_structured(schema, rows=50)` → 50 rows |
| `test_quality_loop` | Generation with quality thresholds → `result.evaluation` scores pass |

---

## Acceptance Criteria

- [ ] `pip install -e ".[structured]"` installs pandas/numpy/scipy
- [ ] `pip install -e .` (without extras) still works — structured is optional at install time
- [ ] `seed-data ingest "Customer orders with priority field" --output schema.json` produces valid schema (CLI)
- [ ] `seed-data generate-structured schema.json --rows 100 --format csv --output ./out` produces CSV (CLI)
- [ ] Existing `seed-data --schema-dir fcc-invoice` still works (no regression)
- [ ] All new unit tests pass without Bedrock credentials
- [ ] Integration tests pass with Bedrock credentials
- [ ] Python API: `gen.ingest(...)` returns `InferredSchema`, `gen.generate_structured(...)` returns `StructuredResult` (on `Generator`)
- [ ] No new bare functions added to `seed_data.__init__` — extension is via `Generator` verbs
- [ ] `StructuredResult` and `InferredSchema` are type-importable from `seed_data`
- [ ] Quality metrics (diversity, fidelity, coverage, structural) compute and log correctly
- [ ] Post-processing pipeline catches and fixes common issues

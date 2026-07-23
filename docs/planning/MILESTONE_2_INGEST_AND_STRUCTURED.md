# Milestone 2: Ingest + Structured Data Generation

**Goal:** Add `seed_data.ingest` and `seed_data.structured` subpackages ported from `seed-tabular` (branch `hp/agentic-redesign`). After this milestone, a new CLI subcommand `seed-data ingest` and `seed-data generate-structured` work end-to-end: text/file/schema → `InferredSchema` → CSV/Parquet/Excel.

**Duration:** ~2 weeks

**Depends on:** Milestone 1 (unified schema layer)

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

Existing files are not modified except `cli.py` (additive subcommands) and `pyproject.toml` (additive deps).

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

### 2.8 Public Python API

Add to `src/seed_data/__init__.py`:

```python
# In __getattr__:
if name == "ingest":
    from seed_data.ingest import ingest
    return ingest
if name == "generate_structured":
    from seed_data.structured import generate_structured
    return generate_structured
```

Usage:
```python
from seed_data import ingest, generate_structured
schema = ingest("Generate realistic customer orders with varying statuses")
result = generate_structured(schema, target_count=500, export_format="parquet")
```

---

## Testing Plan

### Unit Tests — Ingest (`tests/test_ingest.py`)

| Test | What it verifies |
|---|---|
| `test_detect_input_text` | `detect_input_type("Generate invoices")` → `InputType.FREE_TEXT` |
| `test_detect_input_csv` | `detect_input_type("data.csv")` → `InputType.EXAMPLE_DATA` |
| `test_detect_input_json_schema` | `detect_input_type("schema.json")` → `InputType.SCHEMA` |
| `test_detect_input_sql` | `detect_input_type("create_table.sql")` → `InputType.SCHEMA` |
| `test_detect_input_pdf` | `detect_input_type("requirements.pdf")` → `InputType.DOCUMENT` |
| `test_detect_input_mixed` | Multiple inputs detected correctly |
| `test_schema_extraction_mock` | Mock the LLM call, verify `InferredSchema` output from a text description |
| `test_schema_extraction_from_csv_mock` | Mock LLM, feed CSV header → valid schema with correct fields |
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
| `test_end_to_end_text` | `ingest("order data") → generate_structured(schema, 50)` → 50 rows |
| `test_quality_loop` | Generation with quality thresholds → evaluation passes |

---

## Acceptance Criteria

- [ ] `pip install -e ".[structured]"` installs pandas/numpy/scipy
- [ ] `pip install -e .` (without extras) still works — structured is optional at install time
- [ ] `seed-data ingest "Customer orders with priority field" --output schema.json` produces valid schema
- [ ] `seed-data generate-structured schema.json --rows 100 --format csv --output ./out` produces CSV
- [ ] Existing `seed-data --schema-dir fcc-invoice` still works (no regression)
- [ ] All new unit tests pass without Bedrock credentials
- [ ] Integration tests pass with Bedrock credentials
- [ ] `from seed_data import ingest, generate_structured` works
- [ ] Quality metrics (diversity, fidelity, coverage, structural) compute and log correctly
- [ ] Post-processing pipeline catches and fixes common issues

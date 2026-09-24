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
| `src/seed_data/__main__.py` | **MODIFIED** — add `ingest` and `generate-structured` subcommands (see note below) |
| `pyproject.toml` | **MODIFIED** — add optional dependency group `[structured]` |
| `tests/test_ingest.py` | **NEW** |
| `tests/test_structured.py` | **NEW** |
| `tests/test_evaluation.py` | **NEW** |

> **Correction (as shipped):** this row originally named `src/seed_data/cli.py`. The whole CLI actually lives in `src/seed_data/__main__.py`, which holds a module-level `SUBCOMMANDS = {name: handler}` table; each handler builds its own `argparse` parser and `main()` dispatches on `sys.argv[1]`. `src/seed_data/cli.py` still exists but is only a legacy `base_parser()` helper for old scripts — it was **not** modified and is not where subcommands live.

Existing files are not modified except `__main__.py` (additive subcommands) and `pyproject.toml` (additive deps). The `_InferredSchema` → `_InferenceDraft` rename in `infer.py` is handled in Milestone 1; `seed_data/inputs.py` is imported (reused), not modified.

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

> **Correction (as shipped):** `src/seed_data/common/prompts.py` was never created. `src/seed_data/prompts/__init__.py` already exposed a `render(template_name, **kwargs)` Jinja2 loader for the doc-gen prompts, so the ported tabular prompts reuse it rather than adding a second loader. `src/seed_data/common/` contains only `__init__.py` and `config.py`.

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

> **Correction (as shipped):** the subcommands were added to `src/seed_data/__main__.py`, not `cli.py`, and the sketch above (a Typer-style `@app.command`) does not match the shipped shape. `__main__.py` carries a module-level `SUBCOMMANDS` table — `{"clone-schema-library", "packet", "infer-schema", "ingest", "generate-structured", "generate-documents", "run"}` — mapping each name to a handler (`_ingest`, `_generate_structured`, …) that builds its own `argparse.ArgumentParser` and calls the matching `Generator` verb. `main()` dispatches `sys.argv[1]` through that table and falls through to the untouched default generate flow otherwise. The shipped `generate-structured` flags are `schema` (positional), `--rows`, `--format {csv,parquet,excel,json}`, `--output`, `--quiet`. `cli.py` was left alone.

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

Nine tests as shipped. The per-type detection cases the plan listed as separate
tests (`test_detect_input_text` / `_csv` / `_json_schema` / `_sql` / `_pdf` / `_s3` /
`_mixed`) collapsed into one parametrized `test_detect_input_type` covering 17
specs, so the coverage is a superset of the plan under a single name.

| Test | What it verifies |
|---|---|
| `test_detect_input_type` | Parametrized over 17 specs: `s3://` (any extension/prefix) → `DOCUMENT`; `.pdf`/`.png`/`.JPEG` → `DOCUMENT`; `.csv`/`.xlsx`/`.XLS` → `EXAMPLE_DATA`; `.sql`/`.ddl` → `SCHEMA`; `.dbml`/`.puml`/`.plantuml`/`.mmd`/`.mermaid` → `ERD`; bare prose → `FREE_TEXT`. Replaces the plan's seven separate `test_detect_input_*` rows |
| `test_detect_json_file_is_schema_when_exists` | A `.json` path that exists on disk → `InputType.SCHEMA` |
| `test_detect_json_nonexistent_is_free_text` | A `.json`-looking string that is *not* a real file → `FREE_TEXT` (so prose is never mis-read as a schema path) |
| `test_detect_case_insensitive_extension` | `REPORT.PDF` → `DOCUMENT`, `DATA.CSV` → `EXAMPLE_DATA` — extension matching is case-insensitive |
| `test_run_ingest_requires_inputs` | `run_ingest()` with no inputs raises `ValueError` |
| `test_run_ingest_free_text_calls_extraction_agent` | With the extraction tool's `_tool_func` monkeypatched, free text is routed via the `text_description` kwarg and the result is a typed `InferredSchema` |
| `test_run_ingest_merges_multiple_inputs` | Free text + `model.sql` produce a single schema with both entities; SQL routes as `schema_input` with `schema_format="sql_ddl"` |
| `test_run_ingest_documents_delegated` | A `.pdf` input goes through `_ingest_documents` (which wraps `infer_schema`), not the extraction agent. Covers the plan's `test_ingest_delegates_document_to_infer_schema` |
| `test_run_ingest_erd_format_detection` | `diagram.mmd` routes with `erd_format="mermaid"` |

Planned but not implemented as separate tests:
- `test_detect_reuses_inputs_module` — not implemented; reuse of `seed_data.inputs` is
  covered indirectly by the `s3://` and document cases in `test_detect_input_type`
  plus `test_run_ingest_documents_delegated`.
- `test_schema_extraction_from_csv_mock` — not implemented; CSV example-data ingest is
  covered end-to-end by `tests/integration/test_e2e.py::test_generator_run_from_csv_input`
  instead of at unit level.
- `test_ingest_entrypoint_mock` — covered by
  `test_run_ingest_free_text_calls_extraction_agent`, which is the mocked full
  `run_ingest()` call the plan meant.

### Unit Tests — Structured (`tests/test_structured.py`)

Seventeen tests as shipped. The file guards itself with
`pytest.importorskip("numpy")` / `("pandas")` so it skips cleanly on a base
install rather than erroring.

| Test | What it verifies |
|---|---|
| `test_numeric_generation_respects_range_and_seed` | Normal-distribution ints stay inside `[min_value, max_value]` and two generators with the same seed produce identical output. Covers the plan's `test_distribution_spec_normal` + `test_distribution_generator_numeric` |
| `test_categorical_generation_only_uses_enum_values` | Weighted categorical generation only ever emits declared `enum_values`, at the requested count. Covers `test_distribution_spec_categorical` |
| `test_default_generation_no_distribution` | A field with no `DistributionSpec` still generates in-range values via the default path |
| `test_validator_flags_range_and_enum_violations` | `RecordValidator` reports `range_violation` / `enum_violation` and counts them as fixable |
| `test_validator_flags_missing_non_nullable` | Empty value in a `nullable=False` field → `nullable_violation`. Covers `test_postprocessing_validator` together with the row above |
| `test_corrector_clips_range_and_fixes_enum` | `RecordCorrector` clips out-of-range values and case-corrects enum values; re-validation shows no remaining range/enum violations |
| `test_corrector_reassigns_broken_fk` | A dangling FK is detected as `fk_violation` and reassigned to an existing parent key. Covers `test_postprocessing_corrector` |
| `test_postprocessing_pipeline_runs_end_to_end` | Full validate → correct → filter run: original/corrected/filtered counts, plus `validation` and `evaluation` populated. Covers `test_postprocessing_pipeline` |
| `test_postprocessing_returns_corrected_data` | **Regression (bug 2):** `run()` surfaces the corrected+filtered dataset in `result.data`, not just counts |
| `test_needs_llm_routes_semantic_string_types` | **Regression (bug 3):** `string`/`email`/`phone`/`uuid`/`url`/`name`/`address` all route to the LLM fill path |
| `test_needs_llm_excludes_programmatic_and_container_types` | `integer`/`float`/`boolean`/`date`/`datetime`, `object`/`array`, and enum/unique/FK fields do **not** route to the LLM |
| `test_build_graph_pipeline_no_execution` | `build_graph_pipeline()` builds a graph + task context + seeded `PipelineState` with no Bedrock call. Covers `test_graph_pipeline_build` |
| `test_pipeline_state_defaults` | `PipelineState()` defaults: zero attempts/revisions, `quality_passed=False`, empty `export_json`. Covers `test_pipeline_state_init` |
| `test_run_structured_parses_export_summary` | With the graph mocked, `run_structured` parses the export JSON into `output_paths`, `row_counts` and `evaluation` on a successful `StructuredResult` |
| `test_run_structured_handles_pipeline_error` | A raising pipeline yields `success=False` with the underlying message in `error`, not an exception |
| `test_run_structured_empty_export_has_explanatory_error` | **Regression (bug 6):** a run that writes no files sets an explanatory `error` (surfacing the pipeline's own issue) instead of `error=None` |
| `test_export_data_only_removes_its_own_files` | **Regression (bug 1):** export clears only `<entity>.{json,csv,xlsx,parquet}` and leaves unrelated files in a shared output dir intact |

Planned but not implemented:
- `test_function_node_basic` — not implemented; the `FunctionNode` wrapper is exercised
  through `test_build_graph_pipeline_no_execution`, which builds the real graph.
- `test_distribution_generator_string` — not implemented; pattern-based string fields
  route to the LLM fill path instead of a programmatic generator, so the behaviour under
  test is `_needs_llm` routing (two rows above) rather than a string generator.

### Unit Tests — Evaluation (`tests/test_evaluation.py`)

Seven tests as shipped, also guarded by `pytest.importorskip("pandas")` /
`("numpy")`. The plan's per-scorer tests were consolidated: the four scorers are
exercised through `run_evaluation`, which is the only supported entry point, plus
one direct diversity comparison.

| Test | What it verifies |
|---|---|
| `test_run_evaluation_returns_report` | `run_evaluation()` returns an `EvaluationReport` with per-entity record counts and all five overall scores in `[0, 1]`. Covers the plan's `test_run_evaluation_full` |
| `test_run_evaluation_empty_entity_flagged` | An entity with zero records is flagged in `report.issues` with `record_count == 0` |
| `test_run_evaluation_quality_gate` | `passes_quality_gate` is a bool and consistent with `overall_quality_score >= quality_threshold` |
| `test_run_evaluation_missing_entity_key` | A schema entity absent from the data dict is reported as zero records rather than raising |
| `test_run_evaluation_detects_broken_fk` | Dangling FK drops `structural["referential_integrity"]` below 1.0 and adds an issue. Covers `test_structural_broken_fk` |
| `test_run_evaluation_intact_fk` | All FKs resolvable → `referential_integrity == 1.0`. Covers `test_structural_valid` |
| `test_diversity_metric_more_diverse_scores_higher` | `DiversityMetrics.overall_diversity_score` ranks a varied frame at or above a constant-column frame. Covers `test_diversity_score_uniform` + `test_diversity_score_constant` |

Planned but not implemented:
- `test_fidelity_score_matching` / `test_fidelity_score_mismatch` — not implemented as
  direct scorer tests; fidelity is asserted in-range via
  `test_run_evaluation_returns_report`. A targeted spec-match/spec-deviation pair remains
  a coverage gap.
- `test_coverage_all_fields` / `test_coverage_sparse` — not implemented against
  `CoverageMetrics` directly. Equivalent completeness/coverage behaviour is covered for
  the document modality in M4 by
  `tests/test_evaluation_cross.py::test_evaluate_document_labels_coverage` and
  `..._completeness_penalizes_missing_required`.

### CLI Smoke Tests (`tests/test_cli_smoke.py` — extend existing)

| Test | What it verifies |
|---|---|
| `test_ingest_help_exits_clean` | `seed-data ingest --help` exits 0 and advertises `--name`, `--output`, `--quiet` |
| `test_ingest_requires_inputs` | `seed-data ingest` with no positional inputs exits 2 (argparse usage error) |
| `test_generate_structured_help_exits_clean` | `seed-data generate-structured --help` exits 0 and advertises `--rows`, `--format`, `--output`, `--quiet` |
| `test_generate_structured_requires_schema` | Missing positional `schema` exits 2 |
| `test_generate_structured_bad_format_errors` | `--format not-a-format` exits 2 with "invalid choice" |
| `test_all_subcommands_listed` | Every key in the `SUBCOMMANDS` table (including `ingest` / `generate-structured`) is discoverable from top-level `--help` |

`test_existing_commands_unchanged` was not written as a single test; the
no-regression check is the pre-existing smoke tests, which were left unmodified and
still pass: `test_help_exits_clean`, `test_missing_schema_dir_errors`,
`test_bad_model_choice_errors`, `test_packet_subcommand_help`,
`test_clone_schema_library_help`. (`test_generate_documents_*`, `test_run_*` and
`test_base_import_isolation_without_structured_deps` in the same file belong to
Milestones 3-5.)

### Integration Tests (`tests/integration/test_structured_e2e.py`)

> **Correction (as shipped):** `tests/integration/test_structured_e2e.py` was never
> created. The structured integration coverage landed in
> **`tests/integration/test_e2e.py`** (written in Milestone 4, so that one file covers
> both modalities through the `Generator.run()` dispatcher rather than splitting
> integration coverage per subpackage). `tests/integration` is excluded from the default
> `pytest` run via `addopts`; `tests/integration/conftest.py` makes one cheap STS
> `GetCallerIdentity` call so absent/expired credentials become a clean skip.

Require Bedrock credentials — run explicitly:

```bash
uv run pytest tests/integration/test_e2e.py -v
```

| Test | What it verifies |
|---|---|
| `test_generator_run_structured_text` | Free text → ingest → structured generation, end to end. Covers the plan's `test_ingest_text_to_schema` + `test_generate_structured_csv` + `test_end_to_end_text` |
| `test_generator_run_from_csv_input` | A CSV input is ingested and generated from. Covers the plan's `test_ingest_csv_to_schema` |
| `test_critique_structured_on_generated_data` | LLM critique of generated structured data returns a usable score/verdict — the M4 replacement for the plan's `test_quality_loop` |
| `test_generator_run_documents_text`, `test_same_schema_both_modalities`, `test_evaluation_on_documents` | M4 cross-modality coverage in the same file — see the Milestone 4 plan |

Planned but not implemented:
- `test_generate_structured_parquet` — not implemented. `--format parquet` currently
  fails at runtime for want of a parquet engine (see Acceptance Criteria below), so
  there is nothing green to assert yet.
- `test_quality_loop` — not implemented as written. `result.evaluation` scores are
  asserted in-range by the unit test `test_run_evaluation_returns_report`; the
  LLM-judged quality check is `test_critique_structured_on_generated_data`.

### M2 defects found and fixed during Milestones 3-5

M2 did not ship clean. Wiring the same engines through `Generator.run()` (M3/M4) and
enforcing the optional-dependency boundary in CI (M5) surfaced six real defects in the
ported code. Each was verified against source before changing, and each carries a
regression test.

| # | Defect | Fix | Regression test |
|---|---|---|---|
| 1 | `structured/exporter.py` unlinked **every** file in `output_dir` — which defaults to `./output`, shared with the document pipeline. Data loss. | Cleanup scoped to `<entity>.{json,csv,xlsx,parquet}` | `test_export_data_only_removes_its_own_files` |
| 2 | `structured/postprocessing/pipeline.py` discarded its own corrections: callers re-derived data from `result.validation`, which is the *post*-correction re-validation (`fixable_count` already 0), so un-corrected records got exported | `PostProcessingResult` now carries a `data` field; callers consume it | `test_postprocessing_returns_corrected_data` |
| 3 | `structured/generation.py::_needs_llm` returned `field.type == "string"`, dropping `email`/`phone`/`uuid`/`url`/`name`/`address`. Neither the programmatic nor the LLM path generated them, so whole entities filtered down to empty | Excludes only `object`/`array` container types | `test_needs_llm_routes_semantic_string_types`, `test_needs_llm_excludes_programmatic_and_container_types` |
| 4 | `ingest/tools.py` imported pandas at module level, breaking `Generator.ingest` on a base install (the extra is meant to be optional) | Deferred in-function import + `TYPE_CHECKING` guard | CI `test-base` job (clean venv, no extras, fails if `import pandas` succeeds) |
| 5 | `evaluation/structural.py` had `return isinstance(value, str) or True` — a tautology silently inflating the structural score | Split into real branches (`string` → `isinstance`; `phone`/`enum` → deliberately tolerant, with the reason documented in-line) | Covered by `test_run_evaluation_returns_report` score bounds; the tautology is documented at the fix site |
| 6 | `structured/__init__.py` returned an empty export list with `error=None`, so the CLI printed a bare `FAILED: None` | Sets an explanatory `error` that surfaces the pipeline's own evaluation issues | `test_run_structured_empty_export_has_explanatory_error` |

Also noted: `structured/loop.py::generation_loop` is dead code — referenced nowhere in
`src/` or `tests/`. It was fixed alongside the rest rather than deleted; deleting it is
recorded as an open question rather than done.

---

## Acceptance Criteria

- [x] `pip install -e ".[structured]"` installs pandas/numpy/scipy (plus openpyxl; `[all]` added as a superset target)
- [x] `pip install -e .` (without extras) still works — structured is optional at install time (enforced by the CI `test-base` job: base wheel in a clean venv, build fails if `import pandas` succeeds; 322 passed, 2 skipped)
- [x] `seed-data ingest "Customer orders with priority field" --output schema.json` produces valid schema (CLI) (`__main__.py` `_ingest` handler; parse-level smoke tests `test_ingest_help_exits_clean` / `test_ingest_requires_inputs`, live path via `tests/integration/test_e2e.py::test_generator_run_structured_text`)
- [x] `seed-data generate-structured schema.json --rows 100 --format csv --output ./out` produces CSV (CLI) (CSV/JSON/Excel all work; **parquet does not** — see the unticked item below)
- [x] Existing `seed-data --schema-dir fcc-invoice` still works (no regression) (default generate flow untouched; `cli.py` unmodified; `tests/integration/test_document_gen_unified.py::test_legacy_schema_dir_unchanged`)
- [x] All new unit tests pass without Bedrock credentials (`uv run pytest` → 347 passed, 13 warnings; `tests/integration` excluded by default via `addopts`)
- [ ] Integration tests pass with Bedrock credentials — **partially outstanding.** The suite exists (`tests/integration/test_e2e.py`, 6 tests; `conftest.py` turns absent/expired credentials into a clean skip) but it is excluded from the default `pytest` run and from CI, so there is no recorded green run to cite here. The two structured integration cases the plan asked for that were never written are listed above.
- [x] Python API: `gen.ingest(...)` returns `InferredSchema`, `gen.generate_structured(...)` returns `StructuredResult` (on `Generator`) (`Generator.ingest(*inputs, name="dataset", verbose=True)`, `Generator.generate_structured(schema, *, rows=100, format="csv", verbose=True)`)
- [x] No new bare functions added to `seed_data.__init__` — extension is via `Generator` verbs (`__all__` == `BatchResult, GeneratedDoc, Generator, InferredSchema, MODELS, ModelConfig, Schema, StructuredResult` — types only)
- [x] `StructuredResult` and `InferredSchema` are type-importable from `seed_data` (lazy `__getattr__` re-export)
- [x] Quality metrics (diversity, fidelity, coverage, structural) compute and log correctly (`run_evaluation` aggregates all four; `tests/test_evaluation.py`, 7 tests. Note defect 5 above: `structural.py` was silently inflating its score until M3-M5)
- [x] Post-processing pipeline catches and fixes common issues (validate → correct → filter; range clipping, enum case correction, FK reassignment, null filtering — `tests/test_structured.py`. Note defect 2 above: the corrected data was not reaching callers until M3-M5)
- [ ] `--format parquet` produces a readable parquet file — **outstanding.** `pandas.DataFrame.to_parquet` raises `ImportError: Unable to find a usable engine; tried using: 'pyarrow', 'fastparquet'` because neither engine is in the `[structured]` extra. The CLI accepts `--format parquet` and the exporter has a parquet branch, so the fix is adding `pyarrow` to the extra (or rejecting the choice until then). CSV / JSON / Excel are unaffected.

### Known open items carried out of M2

Recorded here so they are not mistaken for shipped behaviour:

- `--format parquet` fails at runtime (see the unticked criterion above); no `pyarrow` /
  `fastparquet` in the `[structured]` extra.
- `run_structured(models=..., session=...)` and `run_ingest(models=...)` are accepted but
  unused — model/session selection does not thread through to the structured pipeline
  agents, which build their own from `common.config`. The `Generator`-level configuration
  contract described in 2.8 therefore holds for the document verbs but not yet for
  `generate_structured`.
- `ingest/detect.py` classifies a directory path as `FREE_TEXT`.
- `structured/loop.py::generation_loop` is dead code (see the defect table above).

# Milestone 4: End-to-End Integration & `seed-data run`

**Goal:** Full pipeline works end-to-end with a unified `seed-data run` command that dispatches ingest → schema → generate (structured or documents). Evaluation metrics are shared across modalities. Cross-modality generation (same schema → both outputs) is verified.

**Duration:** ~1 week

**Depends on:** Milestones 1, 2, 3

---

## What Changes

| File / Dir | Action |
|---|---|
| `src/seed_data/api.py` | **MODIFIED** — add `Generator.run()` verb (dispatch via existing verbs) |
| ~~`src/seed_data/cli.py`~~ → `src/seed_data/__main__.py` | **MODIFIED** — add `run` subcommand. **Shipped in `__main__.py`**, which is where the whole subcommand CLI lives: a `_run(argv)` handler building its own `argparse` parser, plus a `"run"` entry in the module-level `SUBCOMMANDS` dict. `cli.py` still exists but is only a legacy `base_parser()` helper for old scripts — it was **not** modified. |
| `src/seed_data/evaluation/critique.py` | **NEW** — LLM critique loops (ported from doc-gen) available to structured |
| `src/seed_data/evaluation/__init__.py` | **MODIFIED** — expose critique alongside metrics |
| `src/seed_data/evaluation/metrics.py` | **MODIFIED** (not in the original plan) — `evaluate_document_labels()` + `DocumentLabelReport` added alongside `run_evaluation` |
| `src/seed_data/prompts/structured_critic.j2` | **NEW** (not in the original plan) — the M2-ported `critique.j2` has zero template variables and no data slot, so the structured critic needed its own prompt |
| `tests/integration/test_e2e.py` | **NEW** — cross-modality integration tests |
| `tests/integration/conftest.py` | **NEW** (not in the original plan) — `aws_credentials` / `generator` fixtures; STS pre-check so absent or expired credentials skip cleanly |
| `tests/test_run.py` | **NEW** — unit tests for `Generator.run()` dispatch logic |
| `tests/test_evaluation_cross.py` | **NEW** — unit tests for the two cross-modality evaluators (§4.2) |

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
        name: str = "dataset",         # forwarded to ingest()
        # Structured-specific
        rows: int = 100,
        format: str = "csv",
        # Document-specific
        count: int = 1,
        scenario: str = "",
        entity: str | None = None,     # which entity of a multi-entity schema to render
        augment: bool | None = None,
        verbose: bool = True,
    ) -> "GeneratedDoc | BatchResult | StructuredResult":
        """End-to-end: ingest inputs → generate output in one call.

        Dispatches to self.ingest() → self.generate_structured() or
        self.generate() / self.generate_batch() based on `output`.

        Returns a typed result — StructuredResult for "structured",
        GeneratedDoc (count==1) or BatchResult (count>1) for "documents".
        """
        # Validated up front, before ingest spends any tokens.
        if output not in ("structured", "documents"):
            raise ValueError(f"output must be 'structured' or 'documents', got {output!r}")

        schema = self.ingest(*inputs, name=name, verbose=verbose)

        if output == "structured":
            return self.generate_structured(schema, rows=rows, format=format, verbose=verbose)

        if count == 1:
            return self.generate(schema, scenario=scenario, augment=augment,
                                 entity=entity, verbose=verbose)
        return self.generate_batch(schema, count=count, scenario=scenario,
                                   augment=augment, entity=entity, verbose=verbose)
```

Signature reconciled with what shipped (`src/seed_data/api.py`): the original
sketch omitted `name` (forwarded to `ingest`), `entity` (multi-entity document
render selection) and `verbose`. The shipped verb also validates `output` *before*
calling `ingest`, so a typo'd modality costs nothing — guarded by
`test_generator_run_invalid_output_does_not_ingest`.

Notes:
- `run()` is just a convenience verb that chains `ingest()` + the appropriate
  `generate*()` verb. Configuration lives on the `Generator` instance as always.
- Return type is a typed model (GeneratedDoc / BatchResult / StructuredResult) — no
  raw dicts. Consistent with the existing offering.
- The `schema` argument on `generate()`/`generate_batch()` now also accepts
  `InferredSchema` (adapted internally via `schema/adapter.py`), extending the
  existing `str | Schema` union.

~~The underlying dispatch logic is implemented in `src/seed_data/_dispatch.py`
(internal engine — not exposed in `__init__.py` or documented as public API).~~

**Actual:** no `_dispatch.py` was created — there is nothing to put in it.
`Generator.run()` chains `self.ingest()` and the existing generate verbs directly
in `api.py`; the whole body is a modality check plus four call sites. A separate
internal engine module would have been indirection with no logic in it.

**Deliberate decision — `run()` is pure dispatch.** It does *not* auto-invoke
critique (see §4.2, where the plan says critique is "optionally run"). Auto-running
the structured critic on every `run()` would add an LLM call, and cost, to every
invocation of the headline verb. `critique_structured()` stays an explicit opt-in
call the caller makes against generated data.

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

**What actually shipped** — more than the sketch above, and split along the
optional-dependency boundary rather than imported in one line:

```python
# src/seed_data/evaluation/__init__.py (as shipped)
# Eager: base-install-safe (pure Python / Strands-only).
from .critique import StructuredCritiqueResult, StructuredIssue, critique_structured
from .metrics import (
    DocumentLabelReport, EntityEvaluationReport, EvaluationReport,
    evaluate_document_labels,
)

# Lazy via module __getattr__: needs the [structured] extra (pandas/numpy/scipy).
_LAZY = {"CoverageMetrics": ..., "DiversityMetrics": ..., "FidelityMetrics": ...,
         "StructuralMetrics": ..., "run_evaluation": ...}
```

`run_evaluation` is **not** eagerly imported the way the sketch shows: a bare
`import seed_data.evaluation` must work on a base install, so the pandas-backed
scorers resolve on first attribute access instead. The missing dependency then
surfaces when a scorer is actually touched, with a clear message — guarded by
`test_document_evaluation_works_without_structured_extra` and
`test_run_evaluation_import_error_is_clear_without_pandas`.

`evaluate_document_labels(labels, schema, entity_name=None) -> DocumentLabelReport`
(in `evaluation/metrics.py`) is **standalone pure Python**, not a wrapper over
`run_evaluation`. `DocumentLabelReport` carries `document_count`, `field_count`,
`completeness_score`, `coverage_score`, `overall_score` (`0.5 * completeness +
0.5 * coverage`), `per_field_presence` and `issues`.

**Divergence, and the empirical reason for it.** The plan implies the document
metrics reuse the tabular scorer. Building on `run_evaluation` was tried and
rejected on evidence:

1. It **crashes** on document labels — nested label objects hit
   `unhashable type: dict` inside `DiversityMetrics.per_column_entropy`.
2. Its enum/range coverage is **vacuous** for this modality. Across the 17
   bundled schemas there are 389 leaf fields, of which 0 declare an enum and 1
   declares both a min and a max — so "coverage" would score nothing.

Completeness-and-coverage over schema leaf fields is what is actually measurable
for one-at-a-time document generation, so that is what it computes. Being pure
Python is the second payoff: document users never installed `[structured]`, and
now do not have to in order to score their labels.

`critique_structured(data, schema, steering="", model="haiku", threshold=7,
session=None) -> dict` (in `evaluation/critique.py`) needs only Strands, no
pandas. It returns `{score, verdict, issues, summary}`. Two shipped behaviours
worth recording:

- **It contains its own errors.** Any LLM/transport failure returns
  `verdict="error"`, `score=0` and an `error` key rather than raising — critique
  is advisory and must not crash a generation run that already succeeded because
  the reviewer was unreachable (`test_critique_structured_llm_error_is_advisory`).
- **It samples.** Only the first 25 records per entity go into the prompt
  (`_MAX_SAMPLE_ROWS`), with the full counts reported alongside, so critiquing a
  1000-row dataset does not blow the context window
  (`test_critique_structured_samples_large_datasets`).

It uses a **new prompt, `src/seed_data/prompts/structured_critic.j2`**. The
`critique.j2` ported in M2 could not be reused: it has zero template variables,
so there is no slot to put the data or schema in. `structured_critic.j2` takes
`schema_json`, `data_json` (the sampled records), `relationships`, `steering`, and
the `shown_rows` / `total_rows` sampling stats so the critic knows it is looking at
a head sample rather than the whole dataset.

### 4.3 CLI wiring

~~Add to `cli.py`.~~ Added to `__main__.py`, where the subcommand CLI lives. The
CLI constructs a `Generator` and drives it — same pattern as how the existing CLI
builds model configs and calls the pipeline. There is no Typer in this codebase;
the sketch below was written in Typer style but the shipped CLI is `argparse`,
one parser per subcommand handler:

```python
# ~~@app.command("run")~~ — as shipped, in src/seed_data/__main__.py

def _run(argv):
    """Handle the `run` subcommand — end-to-end ingest + generate in one shot."""
    load_dotenv()
    from seed_data import MODELS, Generator, ModelConfig

    parser = argparse.ArgumentParser(prog="seed-data run", description="...")
    parser.add_argument("inputs", nargs="+")
    # THE FLAG SPLIT: --output is the MODALITY, --output-dir is the PATH.
    parser.add_argument("--output", default="structured",
                        choices=["structured", "documents"])
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--name", default="dataset")
    parser.add_argument("--save-schema", default=None)
    parser.add_argument("--rows", type=int, default=100)          # structured only
    parser.add_argument("--format", default="csv",
                        choices=["csv", "parquet", "excel", "json"])  # structured only
    parser.add_argument("--count", type=int, default=1)           # documents only
    parser.add_argument("--scenario", default="")                 # documents only
    parser.add_argument("--entity", default=None)                 # documents only
    parser.add_argument("--augment", action="store_true")         # documents only
    # ... model flags, --renderer, --threshold, --timeout, --quiet (same as existing CLI)
    args = parser.parse_args(argv)

    gen = Generator(models=ModelConfig(...), threshold=args.threshold,
                    renderer=args.renderer, output_dir=args.output_dir,
                    timeout=args.timeout, augment=args.augment)
    # Then ingest + dispatch, printing a typed result summary and exiting
    # non-zero on failure.

SUBCOMMANDS = {..., "run": _run}
```

**The flag split is the important detail, and the plan's sketch conflated it.**
On `run`, `--output` selects the *modality* (`structured` | `documents`) and
`--output-dir` selects the *path*. The plan's sketch had `output` as the modality
and `output_dir` as the path in the Python signature but did not spell out that
both become user-facing flags on the same command — where `--output` reads like a
path. `test_run_help_exits_clean` asserts both flags appear in `run --help` for
exactly this reason. Note this is `run`-specific: the *default* (no-subcommand)
parser and `generate-documents` still use `--output` as the directory, which is
why `test_legacy_schema_dir_unchanged` passes `--output`.

`_run` also ingests *before* dispatching so `--save-schema` can persist the
schema even when generation subsequently fails — i.e. the CLI handler does not
call `Generator.run()`, it inlines the same two steps in order to get a hook
between them. `--save-schema` was not in the plan.

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

19 tests shipped against the 10 planned. The extra 9 cover the default modality,
`name`/`verbose` forwarding, the "don't ingest on a bad modality" guard, and
regression guards that the published `str` / `Schema` inputs still resolve the old
way.

| Test | What it verifies |
|---|---|
| `test_generator_run_dispatches_structured` | Mock `Generator.ingest` + `Generator.generate_structured`, verify `gen.run(..., output="structured")` chains both — and that the *same* schema object ingest produced is what generation receives |
| `test_generator_run_dispatches_documents` | Mock `Generator.ingest` + `Generator.generate`, verify `gen.run(..., output="documents")` chains both and `generate_batch` is not called |
| `test_generator_run_batch_documents` | `gen.run(..., output="documents", count=5)` dispatches to `generate_batch`, not `generate` |
| `test_generator_run_defaults_to_structured` | **New** — omitting `output` entirely generates structured data (the documented default) |
| `test_generator_run_passes_rows_and_format` | (planned as `test_generator_run_passes_rows`) `rows=500` **and** `format="parquet"` forwarded to `generate_structured` |
| `test_generator_run_passes_count_and_augment` | (planned as `test_generator_run_passes_count_augment`) `count=10, augment=True` forwarded to doc gen |
| `test_generator_run_passes_scenario_and_entity` | **New** — `scenario=` and `entity=` reach `generate()`; `entity` was missing from the planned signature |
| `test_generator_run_multiple_inputs` | Multiple strings/paths forwarded to `ingest()` positionally, in order |
| `test_generator_run_passes_name_to_ingest` | **New** — `name="retail"` reaches `ingest()`; `name` was missing from the planned signature |
| `test_generator_run_forwards_verbose` | **New** — `verbose=False` propagates to *both* `ingest` and the generate verb |
| `test_generator_run_invalid_output_raises` | (planned as `test_generator_run_invalid_output`) `gen.run(..., output="invalid")` raises `ValueError` naming both valid values |
| `test_generator_run_invalid_output_does_not_ingest` | **New** — the modality is validated *before* `ingest` is called, so a typo costs no tokens |
| `test_generator_run_returns_typed_structured` | Returns `StructuredResult`, not a dict |
| `test_generator_run_returns_typed_document` | Returns `GeneratedDoc` (count=1) or `BatchResult` (count>1) |
| `test_generate_accepts_inferred_schema` | (planned as `test_generator_generate_accepts_inferred_schema`) `gen.generate(inferred_schema, ...)` reaches the pipeline as `resolved=`, never `schema_dir=` |
| `test_generate_batch_accepts_inferred_schema` | **New** — same guarantee for `generate_batch` |
| `test_generate_selects_entity_from_multi_entity_schema` | **New** — `entity="Order"` picks that entity out of a multi-entity `InferredSchema` |
| `test_generate_string_still_uses_schema_dir` | **New** (regression guard) — the published `generate("fcc-invoice")` path still resolves via `schema_dir=`, unchanged |
| `test_generate_schema_object_still_resolves` | **New** (regression guard) — the published `generate(Schema(...))` path still resolves to the schema triple, unchanged |

### Unit Tests — Cross-modality Evaluation (`tests/test_evaluation_cross.py`)

18 tests shipped against the 3 planned — the two evaluators grew more surface than
the sketch anticipated (see §4.2), and each behaviour got a guard.

| Test | What it verifies |
|---|---|
| `test_critique_structured_mock` | Mock LLM, feed generated data → get critique items back |
| `test_critique_structured_rejects_below_threshold` | **New** — a score under `threshold` yields `verdict="rejected"` |
| `test_critique_structured_accepts_json_path` | **New** — `data` may be a path to a JSON file, not just an in-memory mapping |
| `test_critique_structured_includes_relationships_in_prompt` | **New** — declared FK relationships are rendered into `structured_critic.j2` so the critic can check referential semantics |
| `test_critique_structured_llm_error_is_advisory` | **New** — an LLM/transport failure returns `verdict="error"`, `score=0` and an `error` key instead of raising |
| `test_critique_structured_empty_schema_raises` | **New** — a schema with no entities is a caller error, `ValueError` |
| `test_critique_structured_samples_large_datasets` | **New** — only the first 25 records per entity reach the prompt; full counts still reported |
| `test_evaluate_document_labels_coverage` | Feed doc labels (JSON) → coverage score computed |
| `test_evaluate_document_labels_completeness_penalizes_missing_required` | (planned as `test_evaluate_document_labels_completeness`) missing *required* fields → low completeness score |
| `test_evaluate_document_labels_flags_never_populated_fields` | **New** — a schema field absent from every label gets `per_field_presence == 0.0` and is named in `issues` |
| `test_evaluate_document_labels_single_dict` | **New** — a bare label dict is accepted as well as a list |
| `test_evaluate_document_labels_nested_fields` | **New** — nested objects are flattened to dotted leaf paths and scored |
| `test_evaluate_document_labels_empty_input` | **New** — no labels → zeroed report with an explanatory issue, not a crash |
| `test_evaluate_document_labels_multi_entity_select` | **New** — `entity_name=` picks which entity of a multi-entity schema to score against |
| `test_evaluate_document_labels_unknown_entity_raises` | **New** — an `entity_name` not in the schema raises `KeyError` naming the entity asked for |
| `test_evaluate_document_labels_treats_empty_string_as_absent` | **New** — `""` counts as not populated, so completeness is not inflated by blank fields |
| `test_document_evaluation_works_without_structured_extra` | **New** — the document evaluator imports and runs with pandas/numpy/scipy blocked (the base-install guarantee for §4.2) |
| `test_run_evaluation_import_error_is_clear_without_pandas` | **New** — touching the lazily-exported tabular scorer without the extra gives an actionable message, not an obscure `AttributeError` |

### CLI Smoke Tests

Landed in `tests/test_cli_smoke.py` (which now holds 25 tests total across M2–M5).

| Test | What it verifies |
|---|---|
| `test_run_help_exits_clean` | (planned as `test_run_help`) `seed-data run --help` exits 0 **and** lists `--output`, `--output-dir`, `--rows`, `--count`, `--name` — pinning the modality-vs-path flag split |
| `test_run_invalid_output_errors` | (planned as `test_run_invalid_output`) `seed-data run "text" --output invalid` exits 2 with argparse's "invalid choice" |
| `test_run_requires_inputs` | **New** — `seed-data run` with no inputs is an argparse usage error |
| `test_all_subcommands_listed` | `seed-data --help` shows all subcommands — the shipped assertion covers all seven: ingest, generate-structured, generate-documents, run, packet, infer-schema, clone-schema-library |

### Integration Tests (`tests/integration/test_e2e.py`)

```bash
AWS_PROFILE=your-profile uv run pytest tests/integration/test_e2e.py -v
```

`tests/integration/` is excluded from the default run (`addopts =
"--ignore=tests/integration"` in `pyproject.toml`) because it hits live Bedrock.

6 of the 7 planned tests landed in some form; 5 kept their planned names.

| Test | What it verifies |
|---|---|
| `test_generator_run_structured_text` | `gen.run("Customer orders...", output="structured", rows=20)` → successful `StructuredResult`; at least one entity produced ≥15 of the 20 requested rows (LLM row counts are not exact, so the assertion is a floor, not equality) |
| `test_generator_run_documents_text` | `gen.run("FCC invoices", output="documents", count=2)` → `BatchResult` with ≥1 succeeded and a PDF on disk |
| `test_same_schema_both_modalities` | `gen.ingest()` once → `gen.generate_structured()` AND `gen.generate()` → both succeed off the one schema, entity name consistent |
| `test_generator_run_from_csv_input` | `gen.run("orders.csv", output="structured", rows=15)` → inferred schema fields intersect the CSV's columns |
| ~~`test_generator_run_from_schema_file`~~ | **NOT IMPLEMENTED.** The schema-file → documents path is covered without live Bedrock by `tests/integration/test_document_gen_unified.py::test_inferred_schema_file_to_pdf` and `::test_generate_documents_cli_from_schema_json` (M3), so a duplicate here earned nothing |
| ~~`test_evaluation_on_structured`~~ | **NOT IMPLEMENTED.** "Scores above thresholds" is not a stable assertion against a live model — `result.evaluation` is populated per-run and gating on it makes the test flaky. `tests/test_structured.py::test_run_structured_parses_export_summary` covers that the field is populated; `test_critique_structured_on_generated_data` covers live scoring without asserting a floor |
| `test_evaluation_on_documents` | After `gen.generate()`, the label JSON is loaded from `doc.data_json_path` and `evaluate_document_labels()` returns a report with `document_count >= 1` and `0.0 <= overall_score <= 1.0` |
| `test_critique_structured_on_generated_data` | **New** — generates with `format="json"`, reads the entity JSON back, and runs `critique_structured()` against real data for a real score (skips cleanly if the output was not JSON) |

`tests/integration/conftest.py` is also new (not planned). It provides the
`aws_credentials` and `generator` fixtures, and makes one cheap STS
`GetCallerIdentity` call before yielding: a `get_credentials()` object exists even
when the token is expired, so without that call an expired profile fails deep
inside the model client. With it, absent or expired credentials become a clean
skip with a clear reason.

### Cross-Modality Consistency Test

`doc_result.data` in the original snippet is valid: `GeneratedDoc.data` is a
`@property` that lazily loads and returns the ground-truth label JSON from
`data_json_path` (or `None` if the file is missing). Its stored fields are
`success`, `doc_id`, `doctype`, `pdf_path`, `data_json_path`, `augmented_path`,
`verdict`, `score`, `sha256`, `size_bytes`, `execution_order`, `token_usage`,
`error`. The shipped integration tests read `data_json_path` explicitly instead,
because they assert on the file's existence on disk as well as its contents —
either form works:

```python
def test_cross_modality_consistency():
    """Same schema produces consistent outputs across modalities."""
    import json

    from seed_data import Generator

    gen = Generator(output_dir="/tmp/test_cross")

    # Step 1: ingest (shared schema)
    schema = gen.ingest("Simple 3-field invoice: number, date, total")

    # Step 2: generate in both modalities from same schema
    structured_result = gen.generate_structured(schema, rows=5, format="csv")
    doc_result = gen.generate(schema, scenario="test invoice")

    # Both should have the same fields
    struct_fields = set(structured_result.row_counts.keys())  # entity names

    # GeneratedDoc carries no `.data`; the ground-truth labels are on disk.
    with open(doc_result.data_json_path) as f:
        labels = json.load(f)
    doc_fields = set(labels.keys()) if isinstance(labels, dict) else set()

    # At minimum, the schema fields should appear in doc labels
    schema_fields = {f.name for f in schema.entities[0].fields}
    assert schema_fields.issubset(doc_fields)
```

---

## Acceptance Criteria

- [x] `seed-data run "description" --output structured` works end-to-end (CLI) (`_run` in `__main__.py`; parser + flag split pinned by `test_run_help_exits_clean`, live generation asserted through the identical call chain by `tests/integration/test_e2e.py::test_generator_run_structured_text`. There is no CLI-driven *live* `run` test — the live assertion is at the Python-verb level)
- [x] `seed-data run "description" --output documents` works end-to-end (CLI) (same `_run` handler, documents branch; live coverage via `test_generator_run_documents_text`, and the CLI-subprocess-to-PDF path via M3's `test_generate_documents_cli_from_schema_json`)
- [x] `seed-data run file.csv file.pdf "add priority" --output structured` handles mixed inputs (`nargs="+"` inputs forwarded positionally — `test_generator_run_multiple_inputs`; merging across inputs covered by M2's `test_run_ingest_merges_multiple_inputs`; live single-CSV run by `test_generator_run_from_csv_input`. A live doc+text mixed run is not automated)
- [x] Same schema produces outputs in both modalities with consistent fields (`test_same_schema_both_modalities` — one `ingest()` drives both verbs and the entity name carries through. The assertion is entity-level, not field-set equality: the document label JSON is LLM-shaped, so requiring an exact key match would be a flaky assertion about the model, not about the wiring)
- [x] LLM critique is available for structured data (optional quality check) (`evaluation.critique.critique_structured()` + new `prompts/structured_critic.j2`; 7 unit tests plus live `test_critique_structured_on_generated_data`. Opt-in by design — `Generator.run()` does not auto-invoke it, see §4.1)
- [x] Quantitative metrics are available for document labels (`evaluation.metrics.evaluate_document_labels()` → `DocumentLabelReport`; 9 unit tests plus live `test_evaluation_on_documents`. Pure Python, so it works on a base install without `[structured]`)
- [x] All existing commands (`--schema-dir`, `packet`) still work (`tests/test_cli_smoke.py` — `test_missing_schema_dir_errors`, `test_bad_model_choice_errors`, `test_packet_subcommand_help`, `test_console_script_installed`; plus M3's `test_legacy_schema_dir_unchanged`. `cli.py` and the default parser were not touched by this milestone)
- [x] All previous milestone tests still pass (`uv run pytest` → 347 passed, 13 warnings; `uv run ruff check .` → All checks passed)
- [x] Python API: `gen.run(...)` works on `Generator` (no bare top-level functions) (19 tests in `tests/test_run.py`; `seed_data.__all__` gained no module-level function — it is `[BatchResult, GeneratedDoc, Generator, InferredSchema, MODELS, ModelConfig, Schema, StructuredResult]`)
- [x] `gen.generate(inferred_schema, ...)` works (InferredSchema accepted alongside str/Schema) (`test_generate_accepts_inferred_schema`, `test_generate_batch_accepts_inferred_schema`, `test_generate_selects_entity_from_multi_entity_schema`; the `str` and `Schema` paths regression-guarded unchanged by `test_generate_string_still_uses_schema_dir` and `test_generate_schema_object_still_resolves`)
- [x] All results are typed Pydantic models (StructuredResult, GeneratedDoc, BatchResult) — no raw dicts (`test_generator_run_returns_typed_structured`, `test_generator_run_returns_typed_document`. One exception, deliberate: `critique_structured()` returns a plain dict. The LLM response *is* schema-bound — `StructuredCritiqueResult` / `StructuredIssue` are the `structured_output_model` — but the return value is flattened to a dict so the failure branch can carry an `error` key and a `verdict="error"` the model does not model. Critique is advisory; it must return something rather than raise)

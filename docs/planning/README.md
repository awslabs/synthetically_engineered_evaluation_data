# SEED Unification — Execution Plan

Merge `seed-synthetically-engineered-evaluation-data-from-discovery` (branch `hp/agentic-redesign`) into this repo, expanding `seed-data` to support **structured data generation** (CSV/Parquet/Excel) alongside the existing **document generation** (PDFs).

## Non-Negotiable: Preserve the published `seed-data` offering

The live [PyPI `seed-data` package](https://pypi.org/project/seed-data/) (v0.0.6, maintainer: @sromoam) must keep working exactly as published. This is a hard constraint on every milestone — the extension **adds to** this offering, it never changes it:

| Published surface | Guarantee |
|---|---|
| `pip install seed-data` | Unchanged — same project name, still installs the same way |
| Import name `seed_data` | Unchanged — `from seed_data import Generator, ModelConfig` keeps working |
| CLI `seed-data` | Unchanged — existing flags (`--schema-dir`, `packet`, …) behave identically |
| `Generator` API (`generate` / `generate_batch` / `generate_packet`) | Unchanged — same signatures, same typed returns |
| Base install deps | Unchanged — structured deps are opt-in via the `[structured]` extra |

Everything new (structured generation, ingest) is delivered as **additive `Generator` verbs and additive CLI subcommands**. A user on today's `pip install seed-data` sees no difference until they choose to install `[structured]` and call the new verbs.

## Baseline: build on v0.0.6, not v0.0.5

This branch is rebased onto `main` (tag `v0.0.6`, commit `0dd05ae`). **v0.0.6 already shipped a document-based schema-inference front-half** that overlaps with what this plan calls "ingest". We build on it rather than duplicate it:

| Already in v0.0.6 (published, @sromoam) | This plan adds |
|---|---|
| `Generator.infer_schema(inputs, name=...)` — reads PDF/PNG/JPEG (local + `s3://`) via a vision model → `Schema` | Non-document inputs: free-text, CSV, JSON-Schema, SQL-DDL, ERD → schema |
| `Generator.infer_packet(...)` — split a concatenated PDF → packet.json + per-segment schemas | (reused as-is) |
| `Generator.generate_from_samples` / `generate_batch_from_samples` — one-shot infer→generate | `generate_structured` one-shot analog for tabular output |
| `seed_data/infer.py`, `inputs.py`, `packet_infer.py` | `seed_data/ingest/` (non-doc extractors), `seed_data/structured/` |
| CLI `seed-data infer-schema` | CLI `seed-data ingest`, `generate-structured`, `run` |
| Private `_InferredSchema` (json_schema + guidance) in `infer.py` | Public `InferredSchema` (typed fields, distributions, relationships) — **naming reconciled**, see below |

**Naming reconciliation:** v0.0.6 has a private `_InferredSchema` in `infer.py` that is a thin (json_schema + guidance) structured-output holder — NOT the same as seed-tabular's rich `InferredSchema` (typed `FieldDefinition`s, distributions, relationships). To avoid confusion, the ported tabular model keeps the name `InferredSchema` (it is the richer, canonical one) and the existing private holder was renamed `_InferredSchema` → `_InferenceDraft` (internal-only, non-breaking) in Milestone 1.

**Unified extraction:** rather than a parallel `ingest` surface, the non-document extractors extend the same inference concept. `infer_schema` stays the document/vision path; the new `ingest` verb handles the non-document inputs and both converge on the canonical `InferredSchema`. Milestone 2 wires them so `Generator` exposes one coherent "give me a schema from whatever I have" story.

## Key Decisions (divergences from original plan)

| Original Plan | Actual Decision | Why |
|---|---|---|
| Rename package `doc_gen_agent` → `seed` | Keep `seed_data` package + `seed-data` CLI unchanged | Package was already renamed; `seed-data` is on PyPI. Renaming breaks users. |
| `src/seed/documents/`, `src/seed/structured/` | `src/seed_data/structured/`, `src/seed_data/ingest/`, `src/seed_data/evaluation/` | Additive subpackages under existing `seed_data`, no renames |
| Single breaking commit (Phase 1) | No breaking commits — every milestone is backward-compatible | "Don't break what's already available" constraint |
| New top-level functions (`ingest()`, `run()`) | New verbs on existing `Generator` class | Python offering shape is `Generator` — configure once, call typed verbs, get typed results. No bare module-level functions. |
| Build ingest from scratch | Build on v0.0.6's `infer_schema` / `infer.py` inference surface | v0.0.6 already ships doc-based schema inference; the plan adds the non-document input types on top instead of duplicating |
| `InferredSchema` as the only such name | Reconcile with existing private `_InferredSchema` in `infer.py` | Two different models with a near-identical name; Milestone 1 disambiguates |
| Drop Streamlit UI | Same (still dropped) | Doc-gen's vanilla HTML/JS pattern is the UI story |

## Architecture (after unification)

```
seed-data (PyPI package: seed_data)
├── Existing (unchanged)
│   ├── seed_data.stages.*         — document generation pipeline (internal engines)
│   ├── seed_data.critique         — LLM critique loops
│   ├── seed_data.augment          — augraphy augmentation
│   ├── seed_data.packet           — multi-document packets
│   ├── seed_data.api              — Generator class (THE public Python API)
│   ├── seed_data.schemas/         — 17 built-in document types
│   ├── seed_data.prompts/         — Jinja2 templates + render() loader; loader
│   │                                reused as-is, new .j2 templates added
│   ├── seed_data.__main__         — THE CLI (seed-data): default --schema-dir flow
│   │                                + SUBCOMMANDS dispatch table
│   └── seed_data.cli              — legacy base_parser() helper only, not the CLI
│
├── New (from seed-tabular — internal engines exposed via Generator verbs)
│   ├── seed_data.schema/          — unified schema models (Milestone 1)
│   │   ├── models.py              — InferredSchema, EntitySchema, FieldDefinition, etc.
│   │   ├── io.py                  — JSON Schema ↔ InferredSchema converters
│   │   ├── adapter.py             — InferredSchema → doc-gen triple (Milestone 3)
│   │   └── legacy.py              — existing Schema class (moved, re-exported)
│   ├── seed_data.ingest/          — schema extraction engine (Milestone 2)
│   ├── seed_data.structured/      — structured data generation engine (Milestone 2)
│   │   ├── pipeline.py            — graph pipeline
│   │   ├── distributions/         — distribution-aware generation
│   │   └── postprocessing/        — validate/correct/filter
│   ├── seed_data.evaluation/      — quality metrics (Milestone 2)
│   └── seed_data.common/          — shared config (Milestone 2); config.py only —
│                                    prompts reuse seed_data.prompts.render()
│
├── Public Python API (Generator — configure once, call typed verbs)
│   ├── gen.generate()             — existing: schema → GeneratedDoc (PDF)
│   ├── gen.generate_batch()       — existing: schema → BatchResult
│   ├── gen.generate_packet()      — existing: packet → PacketResult
│   ├── gen.ingest()               — NEW: any inputs → InferredSchema
│   ├── gen.generate_structured()  — NEW: schema → StructuredResult (CSV/Parquet/Excel)
│   └── gen.run()                  — NEW: inputs → dispatch → typed result
│
└── CLI (additive subcommands)
    ├── seed-data ingest            — any input → InferredSchema JSON
    ├── seed-data generate-structured — schema → CSV/Parquet/Excel
    ├── seed-data generate-documents  — schema → PDFs
    └── seed-data run               — end-to-end (ingest + generate)
```

### Python API Offering (preserved and extended)

The package offering is the `Generator` facade. No bare module-level functions are
added to `__init__.py`. New capabilities are new *verbs* on the same class:

```python
from seed_data import Generator, ModelConfig

gen = Generator(models=ModelConfig(data="gpt-oss", critic="sonnet"), output_dir="./out")

# Existing (unchanged)
doc     = gen.generate("invoice", scenario="Midwest food distributors")
batch   = gen.generate_batch("invoice", count=10, scenario="...")
packets = gen.generate_packet("lending-package", count=3)   # list when count > 1

# New verbs (same pattern: configure once, per-call args describe *what* to make)
schema  = gen.ingest("Customer orders with priority field", "./constraints.pdf", name="orders")
struct  = gen.generate_structured(schema, rows=500, format="csv")
result  = gen.run("FCC invoices", output="documents", name="fcc-invoice", count=5)
```

As shipped, `run()` also takes `name=` (passed through to `ingest`) and `entity=`
(which entity of a multi-entity schema to render), which this sketch omitted.
`format="parquet"` is accepted but not yet usable — `pyarrow` is missing from the
`[structured]` extra (open item, tracked in Milestone 5).

Typed results: `GeneratedDoc`, `BatchResult`, `PacketResult` (existing),
`InferredSchema`, `StructuredResult` (new) — typed objects, never raw dicts.
`GeneratedDoc`, `BatchResult`, `InferredSchema` and `StructuredResult` are
Pydantic models; `PacketResult` (pre-existing, untouched) is a dataclass.

## Milestones

| # | Milestone | Duration | Key Deliverable |
|---|---|---|---|
| 1 | [Unified Schema Layer](MILESTONE_1_UNIFIED_SCHEMA.md) | ~1 week | `InferredSchema` model + JSON Schema converter |
| 2 | [Ingest + Structured Generation](MILESTONE_2_INGEST_AND_STRUCTURED.md) | ~2 weeks | `seed-data ingest` + `seed-data generate-structured` |
| 3 | [Document Generation Wiring](MILESTONE_3_DOCUMENT_GENERATION_WIRING.md) | ~1 week | `seed-data generate-documents` via unified schema |
| 4 | [End-to-End Integration](MILESTONE_4_END_TO_END_INTEGRATION.md) | ~1 week | `seed-data run` + cross-modality evaluation |
| 5 | [Polish & Release](MILESTONE_5_POLISH_AND_RELEASE.md) | ~1 week | CI, docs, audit, fresh-clone verification |

**Total:** ~6 weeks (original estimate, kept as the historical record)

## Status

All five milestones are implemented. `uv run pytest` — 347 passed (`tests/integration`
excluded by default via `addopts`); base install with no `[structured]` extra —
322 passed, 2 skipped (`test_structured.py` / `test_evaluation.py` skip themselves
via `pytest.importorskip`); `uv run ruff check .` — clean. Open items and deliberate
divergences are recorded in the individual milestone documents.

## Dependency Graph

```
M1 (schema) ─┬─→ M2 (ingest + structured)
              │
              └─→ M3 (doc-gen wiring)
                    │
M2 + M3 ──────────→ M4 (end-to-end)
                         │
                         └─→ M5 (polish)
```

M2 and M3 can proceed in parallel once M1 is done.

## Risk Mitigations

| Risk | Mitigation |
|---|---|
| Breaking existing users | Every milestone has "all existing tests pass" as acceptance criteria |
| Structured deps bloat core install | Optional dep group `[structured]` — base install stays lean |
| Nested JSON Schema ↔ flat FieldDefinition mismatch | `FieldDefinition.children` field handles nesting; roundtrip tests on all 17 schemas |
| Tabular's `PipelineInput`/`InputMode` complexity | Simplified to auto-detection in `ingest()` — single entry point |
| Import errors when structured deps missing | Deferred imports (`evaluation/__init__.py` `__getattr__` lazy map; in-function imports in `ingest/tools.py` and `metrics.run_evaluation`) so the pandas dependency surfaces on use, not on import — enforced by the CI `test-base` job, which installs the base wheel in a pandas-free venv and fails if `import pandas` succeeds |

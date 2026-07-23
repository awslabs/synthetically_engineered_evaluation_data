# SEED Unification — Execution Plan

Merge `seed-synthetically-engineered-evaluation-data-from-discovery` (branch `hp/agentic-redesign`) into this repo, expanding `seed-data` to support **structured data generation** (CSV/Parquet/Excel) alongside the existing **document generation** (PDFs).

## Key Decisions (divergences from original plan)

| Original Plan | Actual Decision | Why |
|---|---|---|
| Rename package `doc_gen_agent` → `seed` | Keep `seed_data` package + `seed-data` CLI unchanged | Package was already renamed; `seed-data` is on PyPI. Renaming breaks users. |
| `src/seed/documents/`, `src/seed/structured/` | `src/seed_data/structured/`, `src/seed_data/ingest/`, `src/seed_data/evaluation/` | Additive subpackages under existing `seed_data`, no renames |
| Single breaking commit (Phase 1) | No breaking commits — every milestone is backward-compatible | "Don't break what's already available" constraint |
| Drop Streamlit UI | Same (still dropped) | Doc-gen's vanilla HTML/JS pattern is the UI story |

## Architecture (after unification)

```
seed-data (PyPI package: seed_data)
├── Existing (unchanged)
│   ├── seed_data.stages.*         — document generation pipeline
│   ├── seed_data.critique         — LLM critique loops
│   ├── seed_data.augment          — augraphy augmentation
│   ├── seed_data.packet           — multi-document packets
│   ├── seed_data.api              — Generator class
│   ├── seed_data.schemas/         — 17 built-in document types
│   └── seed_data.cli              — existing CLI (--schema-dir, packet)
│
├── New (from seed-tabular)
│   ├── seed_data.schema/          — unified schema models (Milestone 1)
│   │   ├── models.py              — InferredSchema, EntitySchema, FieldDefinition, etc.
│   │   ├── io.py                  — JSON Schema ↔ InferredSchema converters
│   │   ├── adapter.py             — InferredSchema → doc-gen triple (Milestone 3)
│   │   └── legacy.py              — existing Schema class (moved, re-exported)
│   ├── seed_data.ingest/          — schema extraction from any input (Milestone 2)
│   ├── seed_data.structured/      — structured data generation (Milestone 2)
│   │   ├── pipeline.py            — graph pipeline
│   │   ├── distributions/         — distribution-aware generation
│   │   └── postprocessing/        — validate/correct/filter
│   ├── seed_data.evaluation/      — quality metrics (Milestone 2)
│   ├── seed_data.common/          — shared config, prompts (Milestone 2)
│   └── seed_data.run              — unified dispatch (Milestone 4)
│
└── CLI (additive subcommands)
    ├── seed-data ingest            — any input → InferredSchema
    ├── seed-data generate-structured — schema → CSV/Parquet/Excel
    ├── seed-data generate-documents  — schema → PDFs
    └── seed-data run               — end-to-end (ingest + generate)
```

## Milestones

| # | Milestone | Duration | Key Deliverable |
|---|---|---|---|
| 1 | [Unified Schema Layer](MILESTONE_1_UNIFIED_SCHEMA.md) | ~1 week | `InferredSchema` model + JSON Schema converter |
| 2 | [Ingest + Structured Generation](MILESTONE_2_INGEST_AND_STRUCTURED.md) | ~2 weeks | `seed-data ingest` + `seed-data generate-structured` |
| 3 | [Document Generation Wiring](MILESTONE_3_DOCUMENT_GENERATION_WIRING.md) | ~1 week | `seed-data generate-documents` via unified schema |
| 4 | [End-to-End Integration](MILESTONE_4_END_TO_END_INTEGRATION.md) | ~1 week | `seed-data run` + cross-modality evaluation |
| 5 | [Polish & Release](MILESTONE_5_POLISH_AND_RELEASE.md) | ~1 week | CI, docs, audit, fresh-clone verification |

**Total:** ~6 weeks

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
| Import errors when structured deps missing | Lazy imports behind `try/except` with clear error messages |

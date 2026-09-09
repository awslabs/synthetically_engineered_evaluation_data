# Milestone 3: Wire Document Generation to Unified Schema

**Goal:** Make the existing document generation pipeline consumable via the unified `InferredSchema`. After this milestone, `seed-data generate-documents schema.json` works (where `schema.json` is the unified InferredSchema format), and existing schema dirs still work unchanged.

**Duration:** ~1 week

**Depends on:** Milestone 1 (unified schema layer)

---

## What Changes

| File / Dir | Action |
|---|---|
| `src/seed_data/schema/adapter.py` | **NEW** — converts `InferredSchema` → legacy `(schema_dict, guidance, samples)` tuple. *Shipped with two entry points:* `inferred_to_resolved()` (the triple) and a companion `inferred_to_schema()` that returns a legacy `Schema` object |
| ~~`src/seed_data/cli.py`~~ `src/seed_data/__main__.py` | **MODIFIED** — add `generate-documents` subcommand. *Corrected:* the whole CLI (subcommand table + every handler) lives in `__main__.py`. `src/seed_data/cli.py` is only a legacy `base_parser()` helper for old standalone scripts; it was **not** modified |
| `src/seed_data/schema/io.py` | **MODIFIED** — add `load_legacy_schema_dir()` to load existing schema dirs into `InferredSchema`. *Shipped as* `from_legacy_schema_dir(path)` (the name used in §3.2, not the table's `load_legacy_schema_dir`): a documenting alias that delegates to M1's `from_schema_dir()`, guarded by `test_from_legacy_schema_dir_matches_from_schema_dir` |
| `src/seed_data/api.py` | **MODIFIED (not planned)** — `Generator.generate` / `generate_batch` now accept an `InferredSchema` and an `entity=` kwarg; a new `_resolve_for_documents()` calls the adapter for an `InferredSchema`, `Schema.resolve()` for a `Schema`, and returns `None` for a plain string so the published `schema_dir=` path is byte-identical. A second helper `_resolve_inferred()` turns a *path* (InferredSchema dump or bare JSON-Schema doc) or bundled name into an `InferredSchema` — that is what the CLI handler calls. Putting the conversion here rather than in the CLI means the Python API gains the same capability and there is one code path |
| `tests/test_schema_adapter.py` | **NEW** |
| `tests/integration/test_document_gen_unified.py` | **NEW** (specified in the testing plan below, not in this table) |

Existing pipeline code (`stages/`, `nodes.py`, `critique.py`, etc.) is **untouched** — the adapter produces the exact triple that `build_context(resolved=...)` already accepts.

---

## Implementation Steps

### 3.1 Schema Adapter (`src/seed_data/schema/adapter.py`)

The existing pipeline accepts `resolved: tuple[dict, str, list[str]]` — a JSON Schema dict, guidance text, and sample PDF paths. The adapter converts an `InferredSchema` into this triple.

```python
def inferred_to_resolved(
    schema: InferredSchema,
    entity_name: str | None = None,
    sample_pdfs: list[str] | None = None,
) -> tuple[dict, str, list[str]]:
    """Convert InferredSchema → (json_schema_dict, guidance_text, sample_paths).

    If the schema has multiple entities, select by entity_name (defaults to first).
    generation_guidance from the entity is used as the guidance text.
    """
    from seed_data.schema.io import to_json_schema
    entity = _select_entity(schema, entity_name)
    json_schema = to_json_schema(schema, entity_name=entity.entity_name)
    guidance = entity.generation_guidance or ""
    samples = sample_pdfs or []
    return json_schema, guidance, samples
```

Key mapping rules:
- ~~`FieldDefinition.nullable=True` → JSON Schema `"x-probability": 0.5` (or respect stored prob)~~
  **Divergence (as shipped):** `nullable=True` → `{"anyOf": [<inner>, {"type": "null"}]}`, and the
  field is omitted from the object's `required` list. `x-probability` is *read* on the way in
  (`from_json_schema` treats it as a "sometimes present" marker → `nullable=True`) but is never
  *written* on the way out. Reason: `anyOf`-with-null is what the bundled draft-07 schemas already
  use, so emitting it is what lets all 17 round-trip with matching property *and* `required` sets;
  inventing a `0.5` probability would have fabricated information the source never carried. Verified by
  `test_adapter_nullable_field_uses_anyof_null`. Note also that `nullable` and `required` are
  tracked **independently** (M1's `FieldDefinition.required`) because several bundled schemas mark a
  field required *and* null-valued.
- `FieldDefinition.enum_values` → JSON Schema `"enum": [...]` (with `"type": "string"`, since
  `type="enum"` is not a JSON Schema type)
- `FieldDefinition.min_value/max_value` → `"minimum"/"maximum"` (plus `min_length`/`max_length` →
  `"minLength"/"maxLength"`)
- `FieldDefinition.pattern` → `"pattern"`
- `FieldDefinition.children` → nested `"properties"` or `"items"`
- `FieldDefinition.distribution` → ignored by doc-gen (structured-only; doesn't affect rendering)

All of the above land in `schema/io.py::to_json_schema` (M1); the adapter's own job is only entity
selection + guidance/sample passthrough.

### 3.2 Bidirectional loading of legacy schema dirs

`schema/io.py` already has `from_schema_dir()` (Milestone 1). Verify it handles all 17 built-in schemas correctly. Add:

```python
def from_legacy_schema_dir(path: str) -> InferredSchema:
    """Load one of the built-in schema dirs (schema.json + generation_guidance.md).

    This is the same as from_schema_dir but explicitly documents the legacy use case
    and ensures round-trip fidelity (can generate documents from the result).
    """
```

**Shipped as written** — `from_legacy_schema_dir` is a one-line delegation to `from_schema_dir`; it
carries the docstring that explains the legacy use case and nothing else. `to_schema_dir()` (the
inverse, writing `schema.json` + `generation_guidance.md`) was also added, which is what lets the
integration test materialize an `InferredSchema` as a file the CLI can consume.

### 3.3 Wire `generate-documents` CLI subcommand

**Corrected:** the sketch below was written in Typer syntax (`@app.command(...)`), but this project's
CLI is plain `argparse` — `src/seed_data/__main__.py` holds a module-level `SUBCOMMANDS` dict mapping
a subcommand name to a handler that builds its own `ArgumentParser` from `argv`. The shipped shape:

```python
def _generate_documents(argv):
    """Handle the `generate-documents` subcommand — schema -> PDFs."""
    load_dotenv()
    from seed_data import MODELS, Generator, ModelConfig

    parser = argparse.ArgumentParser(prog="seed-data generate-documents", ...)
    parser.add_argument("schema",
                        help="InferredSchema JSON path, schema directory, or bundled name")
    parser.add_argument("--entity", default=None)   # multi-entity InferredSchema
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--scenario", default="")
    parser.add_argument("--output", default="./output")
    parser.add_argument("--augment", action="store_true")
    # ... plus the existing doc-gen flags: --data/doc/critic/batch/aug-model,
    #     --renderer, --no-critic-samples, --threshold, --max-attempts,
    #     --timeout, --seed, --quiet
    args = parser.parse_args(argv)

    gen = Generator(models=ModelConfig(...), output_dir=args.output, ...)

    # A directory (or bundled name) keeps the legacy path; a *file* is an
    # InferredSchema JSON (or a bare JSON-Schema doc) that gets resolved.
    schema_arg = args.schema
    if os.path.isfile(schema_arg):
        schema_arg = gen._resolve_inferred(schema_arg)

    if args.count > 1:
        gen.generate_batch(schema_arg, count=args.count, entity=args.entity, ...)
    else:
        gen.generate(schema_arg, scenario=args.scenario, entity=args.entity, ...)

SUBCOMMANDS = {
    ..., "generate-documents": _generate_documents, ...
}   # main() dispatches on sys.argv[1]; unknown -> the untouched default flow
```

Two decisions worth recording:

- **The adapter call moved out of the CLI.** The sketch had the CLI import
  `inferred_to_resolved` directly. As shipped, the handler loads the file into an `InferredSchema`
  and hands *that* to `Generator.generate(...)`, which calls the adapter internally via
  `_resolve_for_documents()`. The Python API therefore gains the same capability for free, and the
  CLI holds no schema-conversion logic.
- **File-vs-dir, not dir-vs-else.** The sketch branched on `os.path.isdir()`. The shipped handler
  branches on `os.path.isfile()` so that a bare bundled *name* (`invoice`) — which is neither an
  existing file nor an existing dir — falls through to the legacy resolution path rather than being
  mistaken for an `InferredSchema` JSON.

### 3.4 Preserve existing entry points

The existing `seed-data --schema-dir fcc-invoice` keeps working. The new `generate-documents` is an **additional** path for when users have an InferredSchema (e.g., produced by `seed-data ingest`).

Long term, the original flags (`--schema-dir`) could dispatch through the adapter too, but that's optional polish — not required for this milestone.

**As shipped, that polish was deliberately skipped:** `--schema-dir` still resolves to a `schema_dir=`
kwarg and never touches the adapter, so the published path executes exactly the code it did in v0.0.6.
`test_generate_string_still_uses_schema_dir` asserts that (`"schema_dir" in kwargs`, `"resolved" not in
kwargs`) as a regression guard, which means routing `--schema-dir` through the adapter later would be a
visible, tested change rather than a silent one.

---

## Testing Plan

### Unit Tests (`tests/test_schema_adapter.py`)

21 tests as written (53 collected cases — two of them are parametrized across all 17 bundled schemas):

| Test | What it verifies |
|---|---|
| `test_adapter_flat_entity` | Simple entity (5 string/int/number/bool fields) → valid JSON Schema dict; non-nullable fields land in `required`, the nullable one does not |
| `test_adapter_returns_triple` | **NEW** — the return is a 3-tuple of `(dict, str, list)`; the pipeline destructures it, so shape is part of the contract |
| `test_adapter_nested_entity` | Entity with `children` → nested `properties` in JSON Schema |
| `test_adapter_array_field` | `type="array"` + children → `items: {properties: ...}` |
| ~~`test_adapter_nullable_field`~~ `test_adapter_nullable_field_uses_anyof_null` | **RENAMED + retargeted** — `nullable=True` → `anyOf: [T, {"type":"null"}]` and absent from `required`. The planned assertion (`x-probability` present) was wrong; see the §3.1 divergence |
| `test_adapter_enum_field` | `enum_values=["a","b"]` → `"enum": ["a","b"]` in schema, serialized with `"type": "string"` |
| `test_adapter_constraints` | min/max/minLength/maxLength/pattern → JSON Schema constraints |
| `test_adapter_drops_distribution` | **NEW** — a `DistributionSpec` on a field leaves no trace in the emitted JSON Schema (documents the §3.1 "distributions are structured-only" rule as an assertion) |
| `test_adapter_guidance_passthrough` | `entity.generation_guidance` appears as guidance text |
| `test_adapter_sample_pdfs_passthrough` | **NEW** — `sample_pdfs=[...]` arrives as element 3 of the triple (it is not carried on `InferredSchema`, so passthrough is the only mechanism) |
| `test_adapter_multi_entity_select` | 3-entity schema + entity_name="Order" → only Order fields |
| `test_adapter_multi_entity_default_first` | No entity_name → first entity selected |
| `test_adapter_unknown_entity_raises` | **NEW** — an unknown `entity_name` raises `KeyError` rather than silently defaulting to the first entity |
| `test_adapter_unknown_entity_lists_available` | **NEW** — that error names every available entity, so the message is actionable |
| `test_adapter_empty_schema_raises` | **NEW** — `InferredSchema(entities=[])` raises `ValueError("no entities")` instead of an `IndexError` |
| `test_inferred_to_schema_returns_legacy_schema` | **NEW** — the `inferred_to_schema()` companion returns a real legacy `Schema` whose `.resolve()` yields the same triple |
| `test_inferred_to_schema_multi_entity_select` | **NEW** — `inferred_to_schema()` honours `entity_name` too |
| `test_roundtrip_builtin_schemas` | For each of the 17 built-in schemas (parametrized over the discovered dirs): load → `InferredSchema` → adapter → compare property-name set, guidance text, `type`, and `title` with the original schema_dict |
| `test_bundled_schema_set_is_discovered` | **NEW** — guards the two parametrizations against silently collecting zero cases: asserts `>= 17` discovered dirs and that `fcc-invoice` is among them |
| `test_roundtrip_preserves_required_fields` | **NEW** — parametrized over the same 17: the `required` set survives the round-trip. This is the assertion that would break if nullability were mapped via `x-probability` instead of `anyOf`-null |
| `test_from_legacy_schema_dir_matches_from_schema_dir` | **NEW** — §3.2's `from_legacy_schema_dir()` is equal-by-value to `from_schema_dir()`, so the alias can never drift |
| ~~`test_generate_with_adapted_schema`~~ | **MOVED** — "mock pipeline, assert it receives `resolved=` from the adapter" belongs with the `Generator` wiring, so it lives in `tests/test_run.py` as `test_generate_accepts_inferred_schema` / `test_generate_batch_accepts_inferred_schema` / `test_generate_selects_entity_from_multi_entity_schema`, alongside the regression guards `test_generate_string_still_uses_schema_dir` and `test_generate_schema_object_still_resolves` |

### Roundtrip Verification (parametrized)

**Reconciled:** the planned snippet hardcoded the 17 schema names in the `parametrize` list. The
shipped `test_roundtrip_builtin_schemas` (and its sibling `test_roundtrip_preserves_required_fields`)
instead **discovers** the dirs off disk, so adding an 18th bundled schema is covered automatically
and a typo can't silently drop one. The cost of discovery is that an empty glob would collect zero
cases and still report green — which is exactly why `test_bundled_schema_set_is_discovered` exists
as a separate non-parametrized guard. The planned body is otherwise unchanged; the `title` and
`type` assertions were added:

```python
def _bundled_schema_names():
    return sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(SCHEMAS_ROOT, "*"))
        if os.path.isdir(p)
    )


@pytest.mark.parametrize("schema_name", _bundled_schema_names())
def test_roundtrip_builtin_schemas(schema_name):
    """Load schema dir → InferredSchema → adapter → compare with original."""
    path = os.path.join(SCHEMAS_ROOT, schema_name)
    original_dict, original_guidance, _ = load_schema_dir(path)
    adapted_dict, adapted_guidance, _ = inferred_to_resolved(from_schema_dir(path))

    # Compare: all property names preserved
    assert set(original_dict.get("properties", {})) == set(adapted_dict.get("properties", {}))
    # Guidance text preserved
    assert adapted_guidance == original_guidance
    assert adapted_dict["type"] == "object"
    assert adapted_dict["title"] == original_dict.get("title", schema_name)


def test_bundled_schema_set_is_discovered():
    """Guard the parametrization above against silently finding nothing."""
    names = _bundled_schema_names()
    assert len(names) >= 17
    assert "fcc-invoice" in names
```

### CLI Smoke Tests

In `tests/test_cli_smoke.py`, alongside the pre-existing smoke tests. These must not need Bedrock, so
the two planned tests that would have *generated* a document moved to the integration file below and
were replaced by argparse-level checks:

| Test | What it verifies |
|---|---|
| ~~`test_generate_documents_help`~~ `test_generate_documents_help_exits_clean` | **RENAMED** (matches the file's existing `*_exits_clean` convention) — `seed-data generate-documents --help` exits 0 and lists `--entity`, `--count`, `--scenario`, `--output`, `--quiet` |
| `test_generate_documents_requires_schema` | **NEW** — the positional `schema` arg is mandatory: bare invocation exits 2 |
| `test_generate_documents_bad_model_choice_errors` | **NEW** — `--doc-model not-a-real-model` exits 2 with "invalid choice", i.e. the subcommand shares the top-level `MODELS` choice list |
| `test_all_subcommands_listed` | **NEW** — `generate-documents` (with the other six subcommands) is discoverable from `seed-data --help` |
| ~~`test_generate_documents_legacy_dir`~~ | **NOT WRITTEN** — running a legacy dir *through the new subcommand* needs live Bedrock, and no integration test covers that exact combination either. `test_generate_documents_bad_model_choice_errors` does pass a bundled name (`invoice`) through the subcommand, so the argument is accepted, but the dir/bundled-name branch of `_generate_documents` has no end-to-end assertion — see the Acceptance Criteria |
| ~~`test_existing_schema_dir_flag`~~ | **ALREADY COVERED** — the pre-existing `test_missing_schema_dir_errors` / `test_bad_model_choice_errors` cover the default parser's argument surface without Bedrock; end-to-end coverage is `test_legacy_schema_dir_unchanged` below |

### Integration Tests (`tests/integration/test_document_gen_unified.py`)

```bash
uv run pytest tests/integration/test_document_gen_unified.py -v
```

4 tests as written (one more than planned). All hit live Bedrock; `tests/integration` is excluded from
the default run via `addopts`, and a new `tests/integration/conftest.py` provides `aws_credentials`
(one cheap STS `GetCallerIdentity`, so expired/absent creds become a clean skip) and a `generator`
fixture pinned to public models.

| Test | What it verifies |
|---|---|
| `test_ingest_then_generate_doc` | `ingest("FCC broadcast advertising invoices") → InferredSchema → generator.generate(schema) →` a non-empty PDF on disk |
| `test_inferred_schema_file_to_pdf` | **Retargeted** — exercises the M3 contract via the Python API (bundled dir → `InferredSchema` → adapter → pipeline, no schema-dir in the loop). The planned "via the CLI" half became its own test, below |
| `test_generate_documents_cli_from_schema_json` | **NEW** — `to_schema_dir()` writes a `schema.json`, then a `python -m seed_data generate-documents <schema.json>` subprocess is asserted to exit 0 and leave a PDF. This is the acceptance criterion for the subcommand itself |
| ~~`test_legacy_dir_unchanged`~~ `test_legacy_schema_dir_unchanged` | **RENAMED** — `seed-data --schema-dir fcc-invoice` subprocess exits 0 and produces a PDF. Uses `--output` (not `--output-dir`) because it drives the default parser, where `--output` is the directory |

---

## Acceptance Criteria

- [ ] `seed-data generate-documents schema.json` produces PDFs (from InferredSchema file) — subcommand is wired and parses (`test_generate_documents_help_exits_clean`, `test_generate_documents_requires_schema`, `test_generate_documents_bad_model_choice_errors`), and the adapter reaches the pipeline as `resolved=` (`test_generate_accepts_inferred_schema`). **Outstanding:** the live-Bedrock end-to-end assertion is written (`test_generate_documents_cli_from_schema_json`) but has not been run green in this environment — `tests/integration` is excluded from the default run and the available AWS credentials are expired, so it currently skips
- [ ] `seed-data generate-documents src/seed_data/schemas/fcc-invoice/` still works (legacy dir) — the dir/bundled-name branch is implemented (`os.path.isfile()` is false, so the arg falls through to `Generator._resolve_schema`, the same call the published `--schema-dir` flow makes). **Outstanding:** this branch has *no* end-to-end test at all — `test_legacy_schema_dir_unchanged` covers `--schema-dir`, not `generate-documents <dir>`. Adding a fourth integration case for it is the smallest remaining gap in M3
- [x] All 17 built-in schemas round-trip through `InferredSchema → adapter → JSON Schema` preserving all fields (17/17 via `test_roundtrip_builtin_schemas`, plus `test_roundtrip_preserves_required_fields` on the same 17; `tests/test_schema_adapter.py` = 21 tests / 53 collected cases, all passing)
- [x] `generation_guidance` text passes through the adapter correctly (`test_adapter_guidance_passthrough`, and asserted byte-equal against the on-disk guidance for all 17 in `test_roundtrip_builtin_schemas`)
- [x] Existing `seed-data --schema-dir ...` / `seed-data packet ...` commands work unchanged (the `_packet` / `_infer_schema` / `_clone_schema_library` handlers and the whole default-flow parser body are untouched; the only edits to existing code are behaviour-preserving — the hand-rolled `if sys.argv[1] == ...` chain became the `SUBCOMMANDS` table lookup, and the top-level `description`/`epilog` gained the new subcommand listing. Every pre-existing test in `tests/test_cli_smoke.py` is unmodified and green, and `test_generate_string_still_uses_schema_dir` / `test_generate_schema_object_still_resolves` guard the `Generator` side against the new `InferredSchema` branch)
- [x] All existing tests pass (347 passed, 13 warnings; `uv run ruff check .` clean)
- [x] New adapter tests cover flat, nested, array, enum, nullable, and multi-entity cases (plus, beyond the plan: the returned-triple shape, distribution-dropping, sample-PDF passthrough, unknown-entity and empty-schema errors, `required`-set preservation, the `inferred_to_schema` companion, and the `from_legacy_schema_dir` alias)

# Milestone 3: Wire Document Generation to Unified Schema

**Goal:** Make the existing document generation pipeline consumable via the unified `InferredSchema`. After this milestone, `seed-data generate-documents schema.json` works (where `schema.json` is the unified InferredSchema format), and existing schema dirs still work unchanged.

**Duration:** ~1 week

**Depends on:** Milestone 1 (unified schema layer)

---

## What Changes

| File / Dir | Action |
|---|---|
| `src/seed_data/schema/adapter.py` | **NEW** — converts `InferredSchema` → legacy `(schema_dict, guidance, samples)` tuple |
| `src/seed_data/cli.py` | **MODIFIED** — add `generate-documents` subcommand |
| `src/seed_data/schema/io.py` | **MODIFIED** — add `load_legacy_schema_dir()` to load existing schema dirs into `InferredSchema` |
| `tests/test_schema_adapter.py` | **NEW** |

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
- `FieldDefinition.nullable=True` → JSON Schema `"x-probability": 0.5` (or respect stored prob)
- `FieldDefinition.enum_values` → JSON Schema `"enum": [...]`
- `FieldDefinition.min_value/max_value` → `"minimum"/"maximum"`
- `FieldDefinition.pattern` → `"pattern"`
- `FieldDefinition.children` → nested `"properties"` or `"items"`
- `FieldDefinition.distribution` → ignored by doc-gen (structured-only; doesn't affect rendering)

### 3.2 Bidirectional loading of legacy schema dirs

`schema/io.py` already has `from_schema_dir()` (Milestone 1). Verify it handles all 17 built-in schemas correctly. Add:

```python
def from_legacy_schema_dir(path: str) -> InferredSchema:
    """Load one of the built-in schema dirs (schema.json + generation_guidance.md).

    This is the same as from_schema_dir but explicitly documents the legacy use case
    and ensures round-trip fidelity (can generate documents from the result).
    """
```

### 3.3 Wire `generate-documents` CLI subcommand

```python
@app.command("generate-documents")
def generate_documents_cmd(
    schema_path: str,           # InferredSchema JSON file OR legacy schema dir
    entity: str | None = None,  # entity name (if multi-entity schema)
    count: int = 1,
    output: str = "./output",
    augment: bool = False,
    # ... pass through existing doc-gen flags
):
    """Generate PDF documents from a schema (InferredSchema or legacy schema dir)."""
    if os.path.isdir(schema_path):
        # Legacy schema dir path — use existing flow directly
        ...
    else:
        # InferredSchema JSON — convert via adapter
        from seed_data.schema import InferredSchema
        from seed_data.schema.adapter import inferred_to_resolved
        schema = InferredSchema.model_validate_json(Path(schema_path).read_text())
        resolved = inferred_to_resolved(schema, entity_name=entity)
        # Call existing generate() with resolved=...
```

### 3.4 Preserve existing entry points

The existing `seed-data --schema-dir fcc-invoice` keeps working. The new `generate-documents` is an **additional** path for when users have an InferredSchema (e.g., produced by `seed-data ingest`).

Long term, the original flags (`--schema-dir`) could dispatch through the adapter too, but that's optional polish — not required for this milestone.

---

## Testing Plan

### Unit Tests (`tests/test_schema_adapter.py`)

| Test | What it verifies |
|---|---|
| `test_adapter_flat_entity` | Simple entity (5 string/int fields) → valid JSON Schema dict |
| `test_adapter_nested_entity` | Entity with `children` → nested `properties` in JSON Schema |
| `test_adapter_array_field` | `type="array"` + children → `items: {properties: ...}` |
| `test_adapter_nullable_field` | `nullable=True` → `x-probability` annotation present |
| `test_adapter_enum_field` | `enum_values=["a","b"]` → `"enum": ["a","b"]` in schema |
| `test_adapter_constraints` | min/max/pattern → JSON Schema constraints |
| `test_adapter_guidance_passthrough` | `entity.generation_guidance` appears as guidance text |
| `test_adapter_multi_entity_select` | 3-entity schema + entity_name="Order" → only Order fields |
| `test_adapter_multi_entity_default_first` | No entity_name → first entity selected |
| `test_roundtrip_builtin_schemas` | For each of 17 built-in schemas: load → `InferredSchema` → adapter → compare with original schema_dict (field-level match) |
| `test_generate_with_adapted_schema` | Mock pipeline, pass `resolved` from adapter → pipeline builds context correctly |

### Roundtrip Verification (parametrized)

```python
@pytest.mark.parametrize("schema_name", [
    "fcc-invoice", "bank-statement", "w2", "insurance-claim", "pay-stub",
    "credit-report", "invoice", "loan-application", "commercial-lease",
    "cable-bill", "employment-verification-letter", "homeowners-insurance-declaration",
    "medical-discharge", "police-report", "property-appraisal",
    "statement-of-work", "title-report",
])
def test_roundtrip(schema_name):
    """Load schema dir → InferredSchema → adapter → compare with original."""
    from seed_data.schema.io import from_schema_dir
    from seed_data.schema.adapter import inferred_to_resolved
    from seed_data.utils import load_schema_dir

    original_dict, original_guidance, _ = load_schema_dir(f"src/seed_data/schemas/{schema_name}")
    inferred = from_schema_dir(f"src/seed_data/schemas/{schema_name}")
    adapted_dict, adapted_guidance, _ = inferred_to_resolved(inferred)

    # Compare: all property names preserved
    assert set(original_dict.get("properties", {}).keys()) == set(adapted_dict.get("properties", {}).keys())
    # Guidance text preserved
    assert adapted_guidance == original_guidance
```

### CLI Smoke Tests

| Test | What it verifies |
|---|---|
| `test_generate_documents_help` | `seed-data generate-documents --help` exits 0 |
| `test_generate_documents_legacy_dir` | `seed-data generate-documents src/seed_data/schemas/fcc-invoice` still works (path mode) |
| `test_existing_schema_dir_flag` | `seed-data --schema-dir fcc-invoice` unchanged |

### Integration Tests (`tests/integration/test_document_gen_unified.py`)

```bash
uv run pytest tests/integration/test_document_gen_unified.py -v
```

| Test | What it verifies |
|---|---|
| `test_ingest_then_generate_doc` | `ingest("FCC broadcast invoices") → schema → generate-documents → PDF exists` |
| `test_inferred_schema_file_to_pdf` | Write InferredSchema to JSON → `seed-data generate-documents schema.json` → PDF |
| `test_legacy_dir_unchanged` | Existing `seed-data --schema-dir fcc-invoice` still produces valid output |

---

## Acceptance Criteria

- [ ] `seed-data generate-documents schema.json` produces PDFs (from InferredSchema file)
- [ ] `seed-data generate-documents src/seed_data/schemas/fcc-invoice/` still works (legacy dir)
- [ ] All 17 built-in schemas round-trip through `InferredSchema → adapter → JSON Schema` preserving all fields
- [ ] `generation_guidance` text passes through the adapter correctly
- [ ] Existing `seed-data --schema-dir ...` / `seed-data packet ...` commands work unchanged
- [ ] All existing tests pass
- [ ] New adapter tests cover flat, nested, array, enum, nullable, and multi-entity cases

# Milestone 1: Unified Schema Layer

**Goal:** Add `seed_data.schema` subpackage with canonical data models ported from seed-tabular's `InferredSchema`, without modifying any existing code paths. After this milestone, `pip install seed-data` still works identically, all existing tests pass, and a new `InferredSchema` model can be imported and round-tripped to/from JSON.

**Duration:** ~1 week

---

## What Changes

| File / Dir | Action |
|---|---|
| `src/seed_data/schema/` | **NEW** — subpackage with unified schema models |
| `src/seed_data/schema/__init__.py` | Re-exports: `InferredSchema`, `EntitySchema`, `FieldDefinition`, `DistributionSpec`, `RelationshipDefinition` |
| `src/seed_data/schema/models.py` | Port + extend models from `seed-tabular/models/schemas.py` |
| `src/seed_data/schema/io.py` | Converters: `InferredSchema ↔ JSON Schema dict`, `from_schema_dir()`, `to_schema_dir()` |
| `pyproject.toml` | Add `pydantic` to deps (already transitive via strands, but make explicit) |
| `tests/test_schema_models.py` | Unit tests for the new models + IO |

Nothing is renamed. The existing `seed_data.schema` module (which defines the doc-gen `Schema` class) is at `src/seed_data/schema.py`. It must be **moved to** `src/seed_data/schema/legacy.py` and re-exported unchanged from `src/seed_data/schema/__init__.py` so the public `from seed_data import Schema` still works.

---

## Implementation Steps

### 1.1 Convert `schema.py` → `schema/` subpackage (no behavior change)

```
src/seed_data/schema.py          → src/seed_data/schema/__init__.py (with re-exports)
                                   + src/seed_data/schema/legacy.py (original Schema class, verbatim)
```

- `__init__.py` re-exports everything from `legacy.py` so `from seed_data.schema import Schema` is unchanged.
- `from seed_data import Schema` works because `__init__.py.__getattr__` calls `from seed_data.schema import Schema` which resolves to the package `__init__`.

**Verify:** All existing tests pass, `from seed_data import Schema` works.

### 1.2 Port `InferredSchema` models into `schema/models.py`

From `seed-tabular/models/schemas.py`, port:
- `DistributionType` (enum)
- `DistributionSpec` (BaseModel)
- `Cardinality` (enum)
- `RelationshipDefinition` (BaseModel)
- `FieldDefinition` (BaseModel) — add an optional `children: list[FieldDefinition] | None = None` field for nested objects (doc-gen schemas use nested JSON Schema)
- `EntitySchema` (BaseModel) — add `generation_guidance: str = ""` and `reference_samples: list[dict] = Field(default_factory=list)`
- `InferredSchema` (BaseModel)

Changes from tabular's version:
- `FieldDefinition.children` for nested object support (doc-gen schemas have objects/arrays of objects)
- `EntitySchema.generation_guidance` — free-text rendering/realism rules
- `EntitySchema.reference_samples` — example records for few-shot generation
- Remove `DocumentAnalysis`, `GeneratedSamples`, `StepCritique`, `CritiqueItem` for now (belong in generation/evaluation stages, added later)

### 1.3 Implement `schema/io.py` — round-trip converters

```python
def from_json_schema(schema_dict: dict, guidance: str = "") -> InferredSchema:
    """Convert a JSON Schema (like the existing schema.json files) into InferredSchema."""

def to_json_schema(schema: InferredSchema, entity_name: str | None = None) -> dict:
    """Convert an InferredSchema entity back to a JSON Schema dict."""

def from_schema_dir(path: str) -> InferredSchema:
    """Load a bundled schema dir (schema.json + generation_guidance.md) into InferredSchema."""

def to_schema_dir(schema: InferredSchema, path: str) -> None:
    """Serialize InferredSchema back to a schema dir on disk."""
```

The key challenge is mapping JSON Schema's nested `properties` / `items` / `$ref` into the flat-ish `FieldDefinition` list. Doc-gen's schemas use:
- Top-level `properties` → simple fields
- Nested `object` types (e.g., address with street/city/state) → `FieldDefinition(type="object", children=[...])`
- Arrays of objects (e.g., line items) → `FieldDefinition(type="array", children=[...])`
- `x-probability` → `nullable=True` + store probability in a custom field or extension

### 1.4 Wire up `__init__.py` re-exports

```python
# src/seed_data/schema/__init__.py
from seed_data.schema.legacy import Schema  # backward compat
from seed_data.schema.models import (
    InferredSchema, EntitySchema, FieldDefinition,
    DistributionSpec, DistributionType,
    RelationshipDefinition, Cardinality,
)
from seed_data.schema.io import from_json_schema, to_json_schema, from_schema_dir, to_schema_dir
```

---

## Testing Plan

### Unit Tests (`tests/test_schema_models.py`)

| Test | What it verifies |
|---|---|
| `test_field_definition_basic` | Construct a `FieldDefinition` with all field types (string, int, float, date, enum), verify serialization |
| `test_field_definition_nested` | Create nested object `FieldDefinition` with `children`, verify JSON round-trip |
| `test_field_definition_distribution` | Attach `DistributionSpec` to a field, verify params serialize correctly |
| `test_entity_schema_with_relationships` | Build `EntitySchema` with FK relationships, verify `structured_relationships` |
| `test_inferred_schema_multi_entity` | Multi-entity schema (e.g., Customer + Order), verify entity linking |
| `test_from_json_schema_flat` | Convert the existing `fcc-invoice` schema.json → `InferredSchema`, verify field count + types |
| `test_from_json_schema_nested` | Convert a schema with nested objects (address, line items) → verify `children` populated |
| `test_from_json_schema_xprobability` | Handle `x-probability` annotation → maps to nullable/optional |
| `test_to_json_schema_roundtrip` | `from_json_schema(to_json_schema(schema))` ≈ original (modulo ordering) |
| `test_from_schema_dir` | Load `schemas/fcc-invoice/` → `InferredSchema` with `generation_guidance` populated |
| `test_to_schema_dir` | Write → reload → compare (full round-trip on disk) |
| `test_legacy_schema_class` | `from seed_data.schema import Schema` still works (backward compat) |
| `test_legacy_schema_resolve` | Existing `Schema(name=..., json_schema=...).resolve()` unchanged |

### Regression (`tests/test_pipeline_wiring.py` existing)

- Runs the pipeline wiring (no LLM) — must still pass unchanged after `schema.py` → `schema/` refactor.

### Integration (manual, documented)

```bash
# Verify package installs cleanly
pip install -e .
python -c "from seed_data import Schema, Generator; print('OK')"
python -c "from seed_data.schema import InferredSchema, from_schema_dir; s = from_schema_dir('src/seed_data/schemas/fcc-invoice'); print(f'{len(s.entities[0].fields)} fields')"

# Verify existing CLI
seed-data --help
seed-data --schema-dir fcc-invoice --count 1  # (requires Bedrock creds)
```

---

## Acceptance Criteria

- [ ] `from seed_data import Schema` works (legacy API preserved)
- [ ] `from seed_data.schema import InferredSchema, from_schema_dir` works
- [ ] Every existing schema.json in `schemas/` can be loaded via `from_schema_dir()`
- [ ] `to_json_schema(from_json_schema(schema_dict))` preserves field names, types, constraints
- [ ] All existing unit tests pass without modification
- [ ] New tests cover all converters + edge cases (nested, arrays, x-probability)
- [ ] `pip install -e .` works, `seed-data --help` works

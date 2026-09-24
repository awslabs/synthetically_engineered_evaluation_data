"""Unified schema layer.

Two families of models live here:

- :class:`Schema` (from :mod:`seed_data.schema.legacy`) — the original in-code
  document-type definition. Re-exported unchanged so ``from seed_data.schema
  import Schema`` and ``from seed_data import Schema`` keep working exactly as
  before.
- :class:`InferredSchema` and friends (from :mod:`seed_data.schema.models`) — the
  richer canonical model shared across structured + document generation.

:mod:`seed_data.schema.io` provides round-trip converters between JSON Schema
documents (the bundled ``schema.json`` files) and ``InferredSchema``.

:mod:`seed_data.schema.flat` provides the depth-bounded ``InferredSchema`` variant
required when asking an LLM for one as structured output.
"""
from seed_data.schema.legacy import Schema
from seed_data.schema.models import (
    Cardinality,
    DistributionSpec,
    DistributionType,
    EntitySchema,
    FieldDefinition,
    GeneratedSamples,
    InferredSchema,
    RelationshipDefinition,
)
from seed_data.schema.io import (
    from_json_schema,
    from_legacy_schema_dir,
    from_schema_dir,
    to_json_schema,
    to_schema_dir,
)
from seed_data.schema.adapter import inferred_to_resolved, inferred_to_schema
from seed_data.schema.flat import flat_inferred_schema, to_canonical

__all__ = [
    "Schema",
    "InferredSchema",
    "EntitySchema",
    "FieldDefinition",
    "GeneratedSamples",
    "DistributionSpec",
    "DistributionType",
    "RelationshipDefinition",
    "Cardinality",
    "from_json_schema",
    "to_json_schema",
    "from_schema_dir",
    "from_legacy_schema_dir",
    "to_schema_dir",
    "inferred_to_resolved",
    "inferred_to_schema",
    "flat_inferred_schema",
    "to_canonical",
]

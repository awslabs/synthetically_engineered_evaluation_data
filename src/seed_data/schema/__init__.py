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
"""
from seed_data.schema.legacy import Schema
from seed_data.schema.models import (
    Cardinality,
    DistributionSpec,
    DistributionType,
    EntitySchema,
    FieldDefinition,
    InferredSchema,
    RelationshipDefinition,
)
from seed_data.schema.io import (
    from_json_schema,
    from_schema_dir,
    to_json_schema,
    to_schema_dir,
)

__all__ = [
    "Schema",
    "InferredSchema",
    "EntitySchema",
    "FieldDefinition",
    "DistributionSpec",
    "DistributionType",
    "RelationshipDefinition",
    "Cardinality",
    "from_json_schema",
    "to_json_schema",
    "from_schema_dir",
    "to_schema_dir",
]

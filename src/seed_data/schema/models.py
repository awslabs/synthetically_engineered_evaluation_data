"""Canonical unified schema models.

These are the richer, canonical schema models shared across both generation
modalities (structured tabular data + documents). Ported from seed-tabular's
``models/schemas.py`` and extended for document generation (nested fields,
per-entity generation guidance, reference samples).

This ``InferredSchema`` is distinct from — and richer than — the private
``_InferenceDraft`` structured-output holder in :mod:`seed_data.infer`. It is the
single canonical model that both ``ingest`` and ``infer_schema`` converge on so
downstream generation treats every input uniformly.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Cardinality(str, Enum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_MANY = "many_to_many"


class RelationshipDefinition(BaseModel):
    source_entity: str = Field(description="Entity containing the foreign key")
    source_field: str = Field(description="Field name of the foreign key")
    target_entity: str = Field(description="Entity being referenced")
    target_field: str = Field(description="Field being referenced (usually the primary key)")
    cardinality: Cardinality = Field(description="Relationship cardinality")


class DistributionType(str, Enum):
    UNIFORM = "uniform"
    NORMAL = "normal"
    EXPONENTIAL = "exponential"
    LOG_NORMAL = "log_normal"
    CATEGORICAL_WEIGHTED = "categorical_weighted"
    SKEWED_LEFT = "skewed_left"
    SKEWED_RIGHT = "skewed_right"


class DistributionSpec(BaseModel):
    type: DistributionType = Field(description="Type of statistical distribution")
    params: dict[str, float | list[float]] = Field(
        default_factory=dict,
        description=(
            "Distribution parameters (e.g., {'mean': 50, 'std': 10} for normal, "
            "{'weights': [0.5, 0.3, 0.2]} for categorical_weighted)"
        ),
    )


class FieldDefinition(BaseModel):
    name: str = Field(description="Field/column name")
    type: str = Field(description="Data type (string, integer, float, boolean, date, datetime, email, phone, enum, object, array, etc.)")
    description: str = Field(default="", description="Human-readable description of the field")
    nullable: bool = Field(default=False, description="Whether the field can be null")
    unique: bool = Field(default=False, description="Whether values must be unique")
    min_value: float | None = Field(default=None, description="Minimum numeric value")
    max_value: float | None = Field(default=None, description="Maximum numeric value")
    min_length: int | None = Field(default=None, description="Minimum string length")
    max_length: int | None = Field(default=None, description="Maximum string length")
    pattern: str | None = Field(default=None, description="Regex pattern for validation")
    enum_values: list[str] | None = Field(default=None, description="Allowed values for enum types")
    default: str | None = Field(default=None, description="Default value")
    distribution: DistributionSpec | None = Field(default=None, description="Statistical distribution for generation")
    # Extension for document schemas: nested object/array fields carry their own
    # sub-fields here (e.g. an address object, or line-item array-of-objects).
    children: list["FieldDefinition"] | None = Field(
        default=None,
        description="Sub-fields for nested object/array types (JSON Schema properties/items)",
    )

    @field_validator("description", mode="before")
    @classmethod
    def coerce_description(cls, v):
        if v is None:
            return ""
        return v

    @field_validator("enum_values", mode="before")
    @classmethod
    def coerce_enum_values(cls, v):
        if v is None:
            return v
        return [str(item) if item is not None else "None" for item in v]


class EntitySchema(BaseModel):
    entity_name: str = Field(description="Name of the entity/table")
    description: str = Field(default="", description="Description of what this entity represents")
    fields: list[FieldDefinition] = Field(description="List of field definitions")
    relationships: list[str] = Field(default_factory=list, description="Relationships to other entities (e.g., 'belongs_to: Customer')")
    structured_relationships: list[RelationshipDefinition] = Field(default_factory=list, description="Structured FK relationship definitions")
    # Extensions for document generation:
    generation_guidance: str = Field(default="", description="Free-text rendering/realism rules for this entity")
    reference_samples: list[dict] = Field(default_factory=list, description="Example records for few-shot generation")

    @field_validator("description", mode="before")
    @classmethod
    def coerce_description(cls, v):
        if v is None:
            return ""
        return v


class InferredSchema(BaseModel):
    entities: list[EntitySchema] = Field(description="List of entity schemas with full definitions")

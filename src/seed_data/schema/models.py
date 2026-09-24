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


class _FieldDefinitionBase(BaseModel):
    """Every :class:`FieldDefinition` attribute except the self-recursive ``children``.

    Split out so :mod:`seed_data.schema.flat` can build a depth-bounded,
    non-recursive variant of the model tree for LLM structured output — a
    self-referencing model cannot be flattened into a Bedrock tool spec. Nothing
    should use this class directly; use :class:`FieldDefinition`.
    """

    name: str = Field(description="Field/column name")
    type: str = Field(description="Data type (string, integer, float, boolean, date, datetime, email, phone, enum, object, array, etc.)")
    description: str = Field(default="", description="Human-readable description of the field")
    # `nullable` means strictly "the value may be null" — JSON Schema's
    # `anyOf: [T, {"type": "null"}]`. It is NOT "the key may be absent": that is
    # `required`, and it is NOT "the key appears in some documents": that is
    # `presence_probability`. Conflating the three loses information that changes
    # what the generator emits, so all three are tracked independently.
    nullable: bool = Field(default=False, description="Whether the value may be null")
    # None means "infer from nullable", which keeps schemas written before this
    # field existed behaving as they did.
    required: bool | None = Field(
        default=None,
        description="Whether the key must be present (independent of whether its value may be null)",
    )
    # Doc-gen's `x-probability`: the field is included in only a fraction of
    # generated documents, rolled independently per document. Preserved so a
    # schema that round-trips through this model keeps its per-document variation.
    presence_probability: float | None = Field(
        default=None,
        description="Probability (0-1) that this optional field is present in any one generated record",
    )
    unique: bool = Field(default=False, description="Whether values must be unique")
    min_value: float | None = Field(default=None, description="Minimum numeric value")
    max_value: float | None = Field(default=None, description="Maximum numeric value")
    min_length: int | None = Field(default=None, description="Minimum string length")
    max_length: int | None = Field(default=None, description="Maximum string length")
    pattern: str | None = Field(default=None, description="Regex pattern for validation")
    format: str | None = Field(default=None, description="JSON Schema semantic format hint (email, date, uri, ...)")
    enum_values: list[str] | None = Field(default=None, description="Allowed values for enum types")
    # `enum_values` is declared `list[str]` because every structured-data consumer
    # compares it against `str(value)`. A JSON Schema enum may hold numbers, so the
    # underlying JSON type is recorded here to rebuild `{"type": "integer", "enum":
    # [1, 2, 3]}` rather than the unsatisfiable `{"type": "string", "enum": [1, 2, 3]}`.
    enum_base_type: str | None = Field(
        default=None, description="JSON type of the enum's values when they are not strings"
    )
    default: str | None = Field(default=None, description="Default value")
    # Array-specific constraints. Arrays *of objects* describe their element
    # fields in `children`; arrays of primitives have no sub-fields, so their
    # element type and description live here instead.
    min_items: int | None = Field(default=None, description="Minimum number of array elements")
    max_items: int | None = Field(default=None, description="Maximum number of array elements")
    item_type: str | None = Field(default=None, description="Element type for an array of primitives")
    item_description: str | None = Field(default=None, description="Element description for an array of primitives")
    # JSON Schema allows the null branch of an `anyOf` to carry its own
    # description — doc-gen schemas use it to tell the model *when* to emit null.
    null_description: str | None = Field(
        default=None, description="Guidance attached to the null branch of a nullable field"
    )
    distribution: DistributionSpec | None = Field(default=None, description="Statistical distribution for generation")

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

    @property
    def is_required(self) -> bool:
        """Whether the key must be present in generated output.

        Falls back to ``not nullable`` when ``required`` was never set, which is
        the behaviour every caller assumed before ``required`` existed.
        """
        if self.required is None:
            return not self.nullable
        return self.required

    @property
    def requires_value(self) -> bool:
        """Whether a record must carry a non-empty value for this field.

        False when the key may be absent (optional, or only sometimes present)
        *or* when its value may legitimately be null. Use this rather than
        ``not nullable`` when deciding whether a missing value is a defect:
        ``nullable`` alone describes only the null branch, so a plain optional
        field would otherwise be reported as a violation.
        """
        return self.is_required and not self.nullable and self.presence_probability is None


class FieldDefinition(_FieldDefinitionBase):
    # Extension for document schemas: nested object/array fields carry their own
    # sub-fields here (e.g. an address object, or line-item array-of-objects).
    children: list["FieldDefinition"] | None = Field(
        default=None,
        description="Sub-fields for nested object/array types (JSON Schema properties/items)",
    )


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


class GeneratedSamples(BaseModel):
    data: dict[str, list[dict]] = Field(
        description="Map of entity name to list of sample records"
    )

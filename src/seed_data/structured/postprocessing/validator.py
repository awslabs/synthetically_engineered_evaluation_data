import re

from pydantic import BaseModel, Field

from seed_data.schema.models import EntitySchema, FieldDefinition, InferredSchema, RelationshipDefinition


class Violation(BaseModel):
    entity: str
    record_index: int
    field: str
    violation_type: str
    actual_value: str | None = None
    constraint: str = ""
    fixable: bool = False


class ValidationResult(BaseModel):
    violations: list[Violation] = Field(default_factory=list)
    total_records: int = 0
    valid_records: int = 0
    fixable_count: int = 0
    unfixable_count: int = 0


class RecordValidator:
    """Validates generated records against schema constraints."""

    def validate_dataset(
        self,
        data: dict[str, list[dict]],
        schema: InferredSchema,
    ) -> ValidationResult:
        """Validate all entities in the dataset."""
        violations = []
        total_records = 0

        entity_map = {e.entity_name: e for e in schema.entities}

        for entity_name, records in data.items():
            entity_schema = entity_map.get(entity_name)
            if entity_schema is None:
                continue

            total_records += len(records)
            for idx, record in enumerate(records):
                record_violations = self._validate_record(record, idx, entity_name, entity_schema)
                violations.extend(record_violations)

        all_relationships = []
        for entity in schema.entities:
            all_relationships.extend(entity.structured_relationships)

        if all_relationships:
            fk_violations = self._validate_referential_integrity(data, all_relationships)
            violations.extend(fk_violations)

        records_with_violations = set()
        for v in violations:
            records_with_violations.add((v.entity, v.record_index))

        fixable = sum(1 for v in violations if v.fixable)
        unfixable = sum(1 for v in violations if not v.fixable)

        return ValidationResult(
            violations=violations,
            total_records=total_records,
            valid_records=total_records - len(records_with_violations),
            fixable_count=fixable,
            unfixable_count=unfixable,
        )

    def _validate_record(
        self, record: dict, idx: int, entity_name: str, schema: EntitySchema
    ) -> list[Violation]:
        """Validate a single record against its entity schema."""
        violations = []

        for field in schema.fields:
            value = record.get(field.name)

            if value is None or (isinstance(value, str) and value == ""):
                if field.requires_value:
                    violations.append(
                        Violation(
                            entity=entity_name,
                            record_index=idx,
                            field=field.name,
                            violation_type="nullable_violation",
                            actual_value=None,
                            constraint=f"Field '{field.name}' is not nullable",
                            fixable=False,
                        )
                    )
                continue

            type_violation = self._check_type(value, field, entity_name, idx)
            if type_violation:
                violations.append(type_violation)
                continue

            constraint_violations = self._check_constraints(value, field, entity_name, idx)
            violations.extend(constraint_violations)

        return violations

    def _check_type(self, value, field: FieldDefinition, entity: str, idx: int) -> Violation | None:
        """Check type conformance."""
        try:
            if field.type == "integer":
                int(value)
            elif field.type == "float":
                float(value)
            elif field.type == "boolean":
                if str(value).lower() not in ("true", "false", "0", "1"):
                    raise ValueError
        except (ValueError, TypeError):
            return Violation(
                entity=entity,
                record_index=idx,
                field=field.name,
                violation_type="type_error",
                actual_value=str(value),
                constraint=f"Expected type '{field.type}'",
                fixable=field.type in ("integer", "float"),
            )
        return None

    def _check_constraints(self, value, field: FieldDefinition, entity: str, idx: int) -> list[Violation]:
        """Check value constraints (range, enum, pattern, length)."""
        violations = []

        if field.type in ("integer", "float"):
            num_val = float(value)
            if field.min_value is not None and num_val < field.min_value:
                violations.append(
                    Violation(
                        entity=entity,
                        record_index=idx,
                        field=field.name,
                        violation_type="range_violation",
                        actual_value=str(value),
                        constraint=f"min_value={field.min_value}",
                        fixable=True,
                    )
                )
            if field.max_value is not None and num_val > field.max_value:
                violations.append(
                    Violation(
                        entity=entity,
                        record_index=idx,
                        field=field.name,
                        violation_type="range_violation",
                        actual_value=str(value),
                        constraint=f"max_value={field.max_value}",
                        fixable=True,
                    )
                )

        if field.enum_values and str(value) not in field.enum_values:
            violations.append(
                Violation(
                    entity=entity,
                    record_index=idx,
                    field=field.name,
                    violation_type="enum_violation",
                    actual_value=str(value),
                    constraint=f"allowed={field.enum_values}",
                    fixable=True,
                )
            )

        if field.pattern and field.type in ("string", "email", "phone", "enum"):
            try:
                if not re.match(field.pattern, str(value)):
                    violations.append(
                        Violation(
                            entity=entity,
                            record_index=idx,
                            field=field.name,
                            violation_type="pattern_violation",
                            actual_value=str(value),
                            constraint=f"pattern={field.pattern}",
                            fixable=True,
                        )
                    )
            except re.error:
                pass

        str_val = str(value)
        if field.min_length is not None and len(str_val) < field.min_length:
            violations.append(
                Violation(
                    entity=entity,
                    record_index=idx,
                    field=field.name,
                    violation_type="length_violation",
                    actual_value=str_val,
                    constraint=f"min_length={field.min_length}",
                    fixable=False,
                )
            )
        if field.max_length is not None and len(str_val) > field.max_length:
            violations.append(
                Violation(
                    entity=entity,
                    record_index=idx,
                    field=field.name,
                    violation_type="length_violation",
                    actual_value=str_val,
                    constraint=f"max_length={field.max_length}",
                    fixable=True,
                )
            )

        return violations

    def _validate_referential_integrity(
        self, data: dict[str, list[dict]], relationships: list[RelationshipDefinition]
    ) -> list[Violation]:
        """Check that all FK values reference existing parent records."""
        violations = []

        for rel in relationships:
            source_records = data.get(rel.source_entity, [])
            target_records = data.get(rel.target_entity, [])

            if not source_records or not target_records:
                continue

            valid_pks = {str(r.get(rel.target_field)) for r in target_records if r.get(rel.target_field) is not None}

            for idx, record in enumerate(source_records):
                fk_value = record.get(rel.source_field)
                if fk_value is None:
                    continue
                if str(fk_value) not in valid_pks:
                    violations.append(
                        Violation(
                            entity=rel.source_entity,
                            record_index=idx,
                            field=rel.source_field,
                            violation_type="fk_violation",
                            actual_value=str(fk_value),
                            constraint=f"FK to {rel.target_entity}.{rel.target_field}",
                            fixable=True,
                        )
                    )

        return violations

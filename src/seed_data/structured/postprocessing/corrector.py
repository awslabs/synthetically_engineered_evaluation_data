import random

from seed_data.schema.models import FieldDefinition, InferredSchema

from .validator import Violation


class RecordCorrector:
    """Corrects fixable constraint violations in generated records."""

    def correct_dataset(
        self,
        data: dict[str, list[dict]],
        violations: list[Violation],
        schema: InferredSchema,
    ) -> dict[str, list[dict]]:
        """Apply corrections to all fixable violations in the dataset."""
        entity_map = {e.entity_name: e for e in schema.entities}
        field_maps = {
            name: {f.name: f for f in entity.fields}
            for name, entity in entity_map.items()
        }

        result = {name: [dict(r) for r in records] for name, records in data.items()}

        for violation in violations:
            if not violation.fixable:
                continue

            records = result.get(violation.entity)
            if records is None or violation.record_index >= len(records):
                continue

            field_map = field_maps.get(violation.entity, {})
            field = field_map.get(violation.field)
            if field is None:
                continue

            record = records[violation.record_index]
            corrected_value = self._correct_violation(record, violation, field, result)
            if corrected_value is not None:
                record[violation.field] = corrected_value

        return result

    def _correct_violation(
        self,
        record: dict,
        violation: Violation,
        field: FieldDefinition,
        all_data: dict[str, list[dict]],
    ):
        """Determine the corrected value for a single violation."""
        if violation.violation_type == "range_violation":
            return self._correct_range(record.get(violation.field), field)
        elif violation.violation_type == "type_error":
            return self._correct_type(record.get(violation.field), field)
        elif violation.violation_type == "enum_violation":
            return self._correct_enum(record.get(violation.field), field)
        elif violation.violation_type == "fk_violation":
            return self._correct_fk(violation, all_data)
        elif violation.violation_type == "length_violation":
            return self._correct_length(record.get(violation.field), field)
        elif violation.violation_type == "pattern_violation":
            return self._correct_pattern(record.get(violation.field), field)
        return None

    def _correct_range(self, value, field: FieldDefinition):
        """Clip numeric value to [min_value, max_value]."""
        try:
            num = float(value)
            if field.min_value is not None:
                num = max(num, field.min_value)
            if field.max_value is not None:
                num = min(num, field.max_value)
            return int(num) if field.type == "integer" else round(num, 2)
        except (ValueError, TypeError):
            return field.min_value if field.min_value is not None else 0

    def _correct_type(self, value, field: FieldDefinition):
        """Attempt type coercion."""
        try:
            if field.type == "integer":
                return int(float(str(value)))
            elif field.type == "float":
                return float(str(value))
        except (ValueError, TypeError):
            return field.min_value if field.min_value is not None else 0
        return value

    def _correct_enum(self, value, field: FieldDefinition):
        """Replace invalid enum with closest match or random valid value."""
        if not field.enum_values:
            return value

        str_val = str(value).lower()
        for ev in field.enum_values:
            if ev.lower() == str_val:
                return ev

        for ev in field.enum_values:
            if str_val in ev.lower() or ev.lower() in str_val:
                return ev

        return random.choice(field.enum_values)

    def _correct_fk(self, violation: Violation, all_data: dict[str, list[dict]]):
        """Reassign FK to a random valid parent ID."""
        constraint = violation.constraint
        if "FK to " not in constraint:
            return None

        target_ref = constraint.replace("FK to ", "")
        parts = target_ref.split(".")
        if len(parts) != 2:
            return None

        target_entity, target_field = parts
        target_records = all_data.get(target_entity, [])
        if not target_records:
            return None

        valid_ids = [r.get(target_field) for r in target_records if r.get(target_field) is not None]
        if not valid_ids:
            return None

        return random.choice(valid_ids)

    def _correct_length(self, value, field: FieldDefinition):
        """Truncate string to max_length."""
        str_val = str(value)
        if field.max_length is not None and len(str_val) > field.max_length:
            return str_val[: field.max_length]
        return value

    def _correct_pattern(self, value, field: FieldDefinition):
        """Generate a new value matching the field's regex pattern."""
        if not field.pattern:
            return value
        from seed_data.structured.generation import _generate_from_pattern
        values = _generate_from_pattern(field.pattern, 1, set())
        return values[0] if values else value

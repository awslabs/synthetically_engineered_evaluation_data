import re
from datetime import date, datetime

import pandas as pd

from seed_data.schema.models import EntitySchema, InferredSchema, RelationshipDefinition


class StructuralMetrics:
    """Measures structural validity: referential integrity, type conformance, uniqueness."""

    def referential_integrity_score(
        self,
        all_data: dict[str, pd.DataFrame],
        relationships: list[RelationshipDefinition],
    ) -> float:
        """Fraction of FK references that resolve to an existing parent record.

        Returns 1.0 if all FK values exist in the target entity, 0.0 if none do.
        """
        if not relationships:
            return 1.0

        total_refs = 0
        valid_refs = 0

        for rel in relationships:
            source_df = all_data.get(rel.source_entity)
            target_df = all_data.get(rel.target_entity)

            if source_df is None or source_df.empty:
                continue
            if rel.source_field not in source_df.columns:
                continue

            fk_values = source_df[rel.source_field].dropna()
            if fk_values.empty:
                continue

            # An unresolvable target counts the references as *invalid* rather than
            # skipping the relationship. Skipped, a declared FK whose parent entity
            # produced no rows (or lacks the key column) left `total_refs == 0`, and
            # the `return 1.0` below then reported perfect referential integrity for
            # a dataset whose foreign keys were 100% dangling — which passed the
            # quality gate. Every value here points at a row that does not exist,
            # which is exactly what this metric is for.
            if target_df is None or target_df.empty or rel.target_field not in target_df.columns:
                total_refs += len(fk_values)
                continue

            pk_values = set(target_df[rel.target_field].dropna().astype(str))

            for val in fk_values:
                total_refs += 1
                if str(val) in pk_values:
                    valid_refs += 1

        # Still 1.0 when nothing was *referenced* — no FK values at all is a vacuous
        # truth, unlike FK values with no reachable parent.
        if total_refs == 0:
            return 1.0
        return valid_refs / total_refs

    def type_conformance_rate(self, data: pd.DataFrame, schema: EntitySchema) -> float:
        """Fraction of non-null values that match their declared type.

        Returns 1.0 for perfect type conformance.
        """
        if data.empty:
            return 1.0

        total = 0
        conforming = 0

        for field in schema.fields:
            if field.name not in data.columns:
                continue

            for value in data[field.name].dropna():
                total += 1
                if self._conforms_to_type(value, field.type):
                    conforming += 1

        if total == 0:
            return 1.0
        return conforming / total

    def _conforms_to_type(self, value, declared_type: str) -> bool:
        """Check if a value conforms to the declared type."""
        try:
            if declared_type == "integer":
                # `int(value)` alone truncates (int(3.7) == 3) and accepts bools, so
                # the metric was blind to exactly the violation it exists to catch.
                if isinstance(value, bool):
                    return False
                return float(value).is_integer()
            elif declared_type == "float":
                float(value)
                return True
            elif declared_type == "boolean":
                return str(value).lower() in ("true", "false", "0", "1")
            elif declared_type == "date":
                if isinstance(value, (date, datetime)):
                    return True
                return bool(re.match(r"\d{4}-\d{2}-\d{2}$", str(value)))
            elif declared_type == "datetime":
                if isinstance(value, datetime):
                    return True
                return bool(re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", str(value)))
            elif declared_type == "email":
                return bool(re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(value)))
            elif declared_type == "uuid":
                return bool(
                    re.match(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str(value).lower())
                )
            elif declared_type == "string":
                return isinstance(value, str)
            elif declared_type in ("phone", "enum"):
                # Tolerant on purpose: a phone may be stored as an int and an enum
                # value may be numeric, so any scalar conforms. (Was written as
                # `isinstance(value, str) or True`, an always-true tautology that
                # silently inflated the structural score.)
                return True
            else:
                return True
        except (ValueError, TypeError):
            return False

    def uniqueness_violation_count(self, data: pd.DataFrame, schema: EntitySchema) -> int:
        """Count of duplicate values in fields marked as unique."""
        violations = 0
        for field in schema.fields:
            if not field.unique or field.name not in data.columns:
                continue
            series = data[field.name].dropna()
            duplicates = series.duplicated().sum()
            violations += duplicates
        return violations

    def overall_structural_score(
        self,
        all_data: dict[str, pd.DataFrame],
        schema: InferredSchema,
    ) -> dict:
        """Compute structural validity metrics across all entities."""
        results = {
            "referential_integrity": 1.0,
            "type_conformance": {},
            "uniqueness_violations": {},
            "overall_score": 0.0,
        }

        all_relationships = []
        for entity in schema.entities:
            all_relationships.extend(entity.structured_relationships)

        results["referential_integrity"] = self.referential_integrity_score(all_data, all_relationships)

        type_scores = []
        for entity in schema.entities:
            df = all_data.get(entity.entity_name)
            if df is None or df.empty:
                continue
            tc = self.type_conformance_rate(df, entity)
            results["type_conformance"][entity.entity_name] = tc
            type_scores.append(tc)

            uv = self.uniqueness_violation_count(df, entity)
            results["uniqueness_violations"][entity.entity_name] = uv

        # `0.0` when there were entities to score but none produced a measurable
        # conformance rate (every frame empty): defaulting to 1.0 reported perfect
        # structural health for a dataset with no rows at all.
        avg_type = (
            sum(type_scores) / len(type_scores) if type_scores
            else (1.0 if not schema.entities else 0.0)
        )
        total_unique_violations = sum(results["uniqueness_violations"].values())
        uniqueness_penalty = min(total_unique_violations * 0.05, 0.5)

        results["overall_score"] = (
            0.4 * results["referential_integrity"] + 0.4 * avg_type + 0.2 * (1.0 - uniqueness_penalty)
        )
        return results

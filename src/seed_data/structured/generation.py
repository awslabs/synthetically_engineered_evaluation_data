import json
import logging
import random
import re
import string
import zlib

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from seed_data.structured.distributions.generator import DistributionGenerator
from seed_data.common.config import BEDROCK_CLIENT_CONFIG, MAX_TOKENS, MODEL_ID, TEMPERATURE_BULK_GENERATION
from seed_data.schema.models import EntitySchema, FieldDefinition, GeneratedSamples, InferredSchema
from seed_data import prompts

logger = logging.getLogger(__name__)

BULK_GENERATION_PROMPT = prompts.render("bulk_generation")


BATCH_SIZE = 15
DEFAULT_TARGET = 40


def _parse_json_lenient(s: str) -> dict | None:
    """Parse a JSON string, tolerating trailing garbage the LLM appends.

    ``raw_decode`` stops at the end of the first complete value, so trailing
    junk after a valid object is simply ignored — which is the whole of the
    tolerance this needs. (A previous suffix-stripping heuristic here did not
    work on its own examples: it appended ``}`` after stripping a closer, which
    over-closed and still failed to parse.)

    Returns ``None`` for anything that isn't a JSON object. Callers immediately
    do ``.get()`` or ``model_validate`` on the result, so handing back a list
    would raise past their ``except (KeyError, TypeError)`` guards.
    """
    try:
        parsed, _ = json.JSONDecoder().raw_decode(s.lstrip())
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_tool_input(
    entity_schema_definitions: str,
    sample_records_json: str,
    target_count: str,
) -> tuple[dict[str, list[dict]], str, int]:
    """Extract clean (samples_dict, schema_json, target) from possibly-mangled inputs.

    The orchestrator LLM sometimes merges all arguments into sample_records_json,
    or appends trailing JSON garbage. This function normalizes all known patterns.
    """
    schema_json = entity_schema_definitions or ""
    target = DEFAULT_TARGET

    # Try to parse target_count from the explicit argument first
    try:
        target = int(target_count)
    except (ValueError, TypeError):
        pass

    # Case 1: sample_records_json contains merged fields (target_count / entity_schema_definitions inside)
    parsed = _parse_json_lenient(sample_records_json)
    if parsed and isinstance(parsed, dict):
        if "target_count" in parsed:
            try:
                target = int(parsed["target_count"])
            except (ValueError, TypeError):
                pass
        if "entity_schema_definitions" in parsed:
            esd = parsed["entity_schema_definitions"]
            schema_json = json.dumps(esd) if isinstance(esd, dict) else esd
        if "data" in parsed and ("target_count" in parsed or "entity_schema_definitions" in parsed):
            inner = parsed["data"]
            samples = inner if isinstance(inner, dict) else {}
            samples = {k: v for k, v in samples.items() if isinstance(v, list)}
            return samples, schema_json, target
        # Simple {"data": {...}} wrapper without extra keys
        if "data" in parsed and isinstance(parsed["data"], dict):
            samples = {k: v for k, v in parsed["data"].items() if isinstance(v, list)}
            return samples, schema_json, target
        # Direct entity dict (no wrapper)
        samples = {k: v for k, v in parsed.items() if isinstance(v, list)}
        if samples:
            return samples, schema_json, target

    # Case 2: target_count is embedded in an unparseable blob — extract via regex
    if not schema_json and '"target_count"' in sample_records_json:
        tc_match = re.search(r'"target_count"\s*:\s*"?(\d+)"?', sample_records_json)
        if tc_match:
            target = int(tc_match.group(1))
        # Take everything before "target_count" as the data portion
        tc_idx = sample_records_json.find('"target_count"')
        data_portion = sample_records_json[:tc_idx].rstrip().rstrip(",").rstrip()
        data_obj = _parse_json_lenient(data_portion)
        if data_obj and isinstance(data_obj, dict):
            inner = data_obj.get("data", data_obj)
            samples = {k: v for k, v in inner.items() if isinstance(v, list)}
            if samples:
                logger.info("Extracted sample data from merged blob via regex fallback")
                return samples, schema_json, target

    # Case 3: sample_records_json is just malformed but contains entity data directly
    if parsed is None:
        parsed = _parse_json_lenient(sample_records_json)
    if parsed and isinstance(parsed, dict):
        inner = parsed.get("data", parsed)
        samples = {k: v for k, v in inner.items() if isinstance(v, list)}
        if samples:
            return samples, schema_json, target

    logger.error("Could not parse sample_records_json into entity data")
    return {}, schema_json, target


def _find_unique_fields(entity_name: str, schema_json: str) -> list[str]:
    """Find the unique/PK field names for an entity from the schema JSON."""
    try:
        schema = _parse_json_lenient(schema_json)
        if not schema:
            return ["id"]
        for entity in schema.get("entities", []):
            if entity.get("entity_name") == entity_name:
                return [f["name"] for f in entity.get("fields", []) if f.get("unique")]
    except (KeyError, TypeError):
        pass
    return ["id"]


def _get_entity_schema(entity_name: str, schema_json: str) -> EntitySchema | None:
    """Parse schema JSON and return the EntitySchema for a given entity."""
    parsed = _parse_json_lenient(schema_json)
    if not parsed:
        return None
    try:
        schema = InferredSchema.model_validate(parsed)
        for entity in schema.entities:
            if entity.entity_name == entity_name:
                return entity
    except Exception:
        pass
    return None


def _has_distributions(entity_schema: EntitySchema) -> bool:
    """Check if an entity has any fields with distribution specs."""
    return any(f.distribution is not None for f in entity_schema.fields)


def _expand_char_class(char_class: str) -> str:
    """Expand a regex character class into the literal characters it matches.

    Handles range spans (``a-z``, ``0-9``, ``A-HJ-NPR-Z``), explicit character
    sets (``[89ab]``), and the two positions where ``-`` is itself a literal
    rather than a range operator (first and last inside the brackets).

    A leading ``^`` negates the class; the complement is taken over the
    printable ASCII set generation actually draws from, since the true
    complement is unbounded and mostly unusable in generated values.

    Args:
        char_class: the class including its brackets, e.g. ``"[0-9A-F]"``.

    Returns:
        The expanded character pool. Empty only if the class itself is empty.
    """
    inner = char_class[1:-1]

    negated = inner.startswith("^")
    if negated:
        inner = inner[1:]

    chars: list[str] = []
    i = 0
    while i < len(inner):
        # A '-' is a range operator only between two characters; at either end
        # of the class it is a literal hyphen.
        is_range = (
            inner[i] == "-"
            and i > 0
            and i + 1 < len(inner)
        )
        if is_range:
            # Already consumed the low end on the previous iteration.
            low, high = inner[i - 1], inner[i + 1]
            if ord(low) <= ord(high):
                chars.extend(chr(c) for c in range(ord(low) + 1, ord(high) + 1))
            i += 2
            continue
        chars.append(inner[i])
        i += 1

    pool = "".join(dict.fromkeys(chars))  # de-duplicate, preserve order

    if negated:
        allowed = string.ascii_letters + string.digits
        pool = "".join(c for c in allowed if c not in pool)

    return pool


def _entity_seed(seed: int | None, entity_name: str) -> int | None:
    """Derive a per-entity seed from the run seed.

    Handing every entity the same seed would make them draw the *same* numbers:
    two entities with an integer column in the same range would come out with
    identical values, which reads as a correlation that isn't in the schema.
    Mixing in a stable hash of the name keeps entities independent while staying
    reproducible — ``zlib.crc32`` rather than ``hash()``, which is salted per
    process and would break reproducibility across runs.
    """
    if seed is None:
        return None
    return (seed + zlib.crc32(entity_name.encode())) % (2**32)


def _generate_from_pattern(
    pattern: str, count: int, existing: set[str], rng: random.Random | None = None
) -> list[str]:
    """Generate unique string values matching a simplified regex pattern.

    Supports patterns like:
      - "[A-Z]{3}-[0-9]{4}"  → "ABC-1234"
      - "[A-HJ-NPR-Z0-9]{17}" → realistic VIN-like strings
      - "QI-[0-9]{6}" → "QI-012345"
      - Literal characters are kept as-is

    Anchors are stripped before parsing. JSON Schema ``pattern`` values are
    conventionally anchored, and this generates a whole value (so the match is
    implicitly a fullmatch) — left in place, ``^`` and ``$`` would be emitted as
    literal characters and every value would fail to match its own pattern.

    Args:
        rng: source of randomness. Pass a seeded ``random.Random`` to make the
            output reproducible; defaults to the ``random`` module's shared
            state, which is not.
    """
    picker = rng if rng is not None else random
    # Strip anchors: they constrain matching, not the character content.
    if pattern.startswith("^"):
        pattern = pattern[1:]
    if pattern.endswith("$") and not pattern.endswith(r"\$"):
        pattern = pattern[:-1]

    # Parse pattern into segments: (chars_to_pick_from, repeat_count) or (literal, 1)
    segments: list[tuple[str, int]] = []
    i = 0
    while i < len(pattern):
        if pattern[i] == "[":
            # Find the closing bracket
            end = pattern.index("]", i)
            char_class = pattern[i:end + 1]
            i = end + 1
            # Check for quantifier {n}
            repeat = 1
            if i < len(pattern) and pattern[i] == "{":
                q_end = pattern.index("}", i)
                repeat = int(pattern[i + 1:q_end])
                i = q_end + 1
            chars = _expand_char_class(char_class)
            if not chars:
                # Degenerate class (e.g. "[]") — nothing to draw from.
                continue
            segments.append((chars, repeat))
        elif pattern[i] == "\\":
            # Escaped char like \d
            i += 1
            if i < len(pattern) and pattern[i] == "d":
                repeat = 1
                i += 1
                if i < len(pattern) and pattern[i] == "{":
                    q_end = pattern.index("}", i)
                    repeat = int(pattern[i + 1:q_end])
                    i = q_end + 1
                segments.append((string.digits, repeat))
            else:
                segments.append((pattern[i], 1))
                i += 1
        else:
            # Literal character
            segments.append((pattern[i], 1))
            i += 1

    values: list[str] = []
    attempts = 0
    max_attempts = count * 20
    while len(values) < count and attempts < max_attempts:
        attempts += 1
        val = ""
        for chars, repeat in segments:
            if len(chars) == 1:
                val += chars * repeat
            else:
                val += "".join(picker.choices(chars, k=repeat))
        if val not in existing:
            existing.add(val)
            values.append(val)

    # The pattern space is exhausted (or too dense to sample from) before we hit
    # `count`. Suffix a STABLE base with a counter rather than the previously
    # generated value: chaining off values[-1] compounds, growing each value by
    # the whole of the last one ("5_10", "5_10_11", "5_10_11_12", ...) until the
    # strings are unbounded and no longer pattern-shaped.
    if len(values) < count:
        base = values[0] if values else "ID"
        logger.warning(
            "Pattern %r exhausted after %d unique values (wanted %d) — "
            "suffixing %r to fill the remainder",
            pattern, len(values), count, base,
        )
        suffix = 0
        while len(values) < count:
            candidate = f"{base}_{suffix}"
            suffix += 1
            if candidate in existing:
                continue
            existing.add(candidate)
            values.append(candidate)

    return values


def _samples_match_pattern(sample_vals: list, pattern: str) -> bool:
    """Check if existing sample values match the schema's regex pattern."""
    try:
        return all(re.fullmatch(pattern, str(v)) for v in sample_vals)
    except re.error:
        return False


def _live_fk_values(
    entity_name: str, relationships: list, all_data: dict[str, list[dict]]
) -> dict[str, list]:
    """Map each *live* foreign-key field to the parent values it can draw from.

    A relationship contributes only when its target entity actually produced
    records. A *dangling* FK — one whose parent entity was never generated, e.g.
    ``Order.customer_id -> Customer.id`` when the ingested schema has only an
    ``Order`` entity — has no parent values to copy and is omitted here. The
    field then falls through to normal type-based / LLM generation instead of
    being treated as an FK (which suppresses both the FK copy *and* the LLM
    fill), which would otherwise leave the column empty and get every
    programmatic row filtered out by the not-null check.

    Parent values preserve their original type so FK columns match the parent
    key exactly.
    """
    fk_values: dict[str, list] = {}
    for rel in relationships:
        if rel.source_entity != entity_name:
            continue
        parent_records = all_data.get(rel.target_entity, [])
        parent_vals = [
            r[rel.target_field]
            for r in parent_records
            if r.get(rel.target_field) is not None
        ]
        if parent_vals:
            fk_values[rel.source_field] = parent_vals
    return fk_values


def _needs_llm(field: FieldDefinition, fk_fields: set[str]) -> bool:
    """Determine if a field requires LLM generation (free-text strings)."""
    if field.name in fk_fields:
        return False
    if field.unique:
        return False
    if field.distribution is not None:
        return False
    if field.enum_values:
        return False
    if field.type in ("integer", "float", "boolean", "date", "datetime"):
        return False
    # A field that may be omitted or null needs no LLM call — it is filled with
    # None below. `requires_value` (not `nullable`) is the right test: `nullable`
    # covers only the null branch, so a plain optional field would otherwise be
    # sent to the LLM.
    if not field.requires_value:
        return False
    # Anything left is a textual/semantic type with no programmatic generator —
    # string, but also email, phone, uuid, url, name, address, etc. All need the
    # LLM. Restricting this to type == "string" (the old behaviour) left those
    # semantic types unfilled: the programmatic path never emits them, so every
    # record failed a non-null check and the whole entity was filtered to empty.
    # Container types (object/array) are not supported in tabular generation and
    # must NOT be force-filled as strings, so exclude them explicitly.
    return field.type not in ("object", "array")


def _generate_programmatic(
    entity_name: str,
    entity_schema: EntitySchema,
    count: int,
    existing_records: list[dict],
    all_data: dict[str, list[dict]],
    defer_llm: bool = False,
    seed: int | None = None,
) -> list[dict]:
    """Generate records using hybrid approach: numpy/scipy for structured fields, LLM for free-text.

    1. Generate all programmatic fields (numeric, enum, date, ID, FK, boolean)
    2. Identify free-text string fields that need LLM
    3. Call LLM with partial records to fill in those fields (unless defer_llm=True)

    When defer_llm=True, returns partial records with string fields unfilled
    (marked as None). The caller is responsible for filling them later.

    ``seed`` makes the programmatic half of the output reproducible: it seeds both
    the numpy RNG behind ``DistributionGenerator`` and the stdlib RNG used for
    pattern-based values. The LLM fill pass is not reproducible either way, so a
    seeded run pins the numeric/enum/date/ID columns, not free-text ones.
    """
    generator = DistributionGenerator(seed=seed)
    # Derived from `seed` rather than shared with the numpy RNG: the two draw
    # different value kinds, and coupling them would make a change in one column's
    # count shift the other's values.
    pattern_rng = random.Random(seed) if seed is not None else None

    # Collect existing unique values to avoid duplicates
    existing_uniques: dict[str, set] = {}
    for field in entity_schema.fields:
        if field.unique:
            existing_uniques[field.name] = {
                str(r.get(field.name)) for r in existing_records if r.get(field.name) is not None
            }

    # Collect valid FK values from parent entities (preserve original type).
    # Only *live* FKs — those with a generated parent — count; a dangling FK
    # falls through to normal generation (see `_live_fk_values`).
    fk_values = _live_fk_values(entity_name, entity_schema.structured_relationships, all_data)
    fk_fields = set(fk_values)

    # Identify which fields need LLM
    llm_fields = [f.name for f in entity_schema.fields if _needs_llm(f, fk_fields)]

    # Generate programmatic column values
    column_values: dict[str, list] = {}
    for field in entity_schema.fields:
        if field.name in llm_fields:
            continue  # Will be filled by LLM
        if field.name in fk_values and fk_values[field.name]:
            rng = generator.rng
            parent_vals = fk_values[field.name]
            selected = [parent_vals[i] for i in rng.integers(0, len(parent_vals), size=count)]
            if field.type == "integer":
                selected = [int(v) if str(v).isdigit() else v for v in selected]
            elif field.type == "float":
                selected = [float(v) for v in selected]
            column_values[field.name] = selected
        elif field.unique:
            existing = existing_uniques.get(field.name, set())
            values = []
            # Determine format from existing sample values
            sample_vals = [r.get(field.name) for r in existing_records if r.get(field.name) is not None]
            all_numeric = sample_vals and all(str(v).isdigit() for v in sample_vals)

            if all_numeric:
                # Samples are numeric — generate random unique IDs in a similar magnitude
                int_vals = sorted(int(v) for v in sample_vals)
                # Infer the ID range from samples (e.g., 101-105 → generate in 100-999)
                min_sample = int_vals[0]
                magnitude = 10 ** len(str(min_sample))
                range_low = min_sample
                range_high = max(magnitude - 1, range_low + count * 10)
                rng = generator.rng
                for _ in range(count * 20):  # attempts
                    if len(values) >= count:
                        break
                    val = int(rng.integers(range_low, range_high + 1))
                    if str(val) not in existing:
                        existing.add(str(val))
                        values.append(val if field.type == "integer" else str(val))
                # Fallback if not enough unique values found
                counter = range_high + 1
                while len(values) < count:
                    if str(counter) not in existing:
                        existing.add(str(counter))
                        values.append(counter if field.type == "integer" else str(counter))
                    counter += 1
            elif field.pattern and (not sample_vals or _samples_match_pattern(sample_vals, field.pattern)):
                # Schema has a pattern AND samples match it (or no samples) — use pattern
                values = _generate_from_pattern(field.pattern, count, existing, pattern_rng)
            elif field.type == "integer":
                max_id = 0
                for v in existing:
                    try:
                        max_id = max(max_id, int(v))
                    except (ValueError, TypeError):
                        pass
                counter = max_id + 1
                for _ in range(count):
                    while str(counter) in existing:
                        counter += 1
                    existing.add(str(counter))
                    values.append(counter)
                    counter += 1
            elif field.pattern:
                values = _generate_from_pattern(field.pattern, count, existing, pattern_rng)
            else:
                prefix = entity_name[:3].upper()
                counter = len(existing) + 1
                for _ in range(count):
                    while True:
                        val = f"{prefix}-{counter:04d}"
                        if val not in existing:
                            existing.add(val)
                            values.append(val)
                            counter += 1
                            break
                        counter += 1
            column_values[field.name] = values
        elif field.distribution is not None or field.type in ("integer", "float", "boolean"):
            column_values[field.name] = generator.generate_field_values(field, count)
        elif field.enum_values:
            column_values[field.name] = generator.generate_categorical(field, count)
        elif field.type in ("date", "datetime"):
            column_values[field.name] = generator.generate_dates(field, count)
        elif not field.requires_value:
            # Optional or null-valued: no programmatic generator applies, and the
            # LLM pass skips it too (see `_needs_llm`), so it stays empty.
            column_values[field.name] = [None] * count

    # Assemble partial records
    records: list[dict] = []
    for i in range(count):
        record = {}
        for field in entity_schema.fields:
            if field.name in column_values:
                record[field.name] = column_values[field.name][i]
        records.append(record)

    # Fill free-text string fields via LLM if needed
    # When called with defer_llm=True (from parallel path), skip LLM here
    if llm_fields and not defer_llm:
        records = _fill_string_fields_with_llm(
            entity_name, entity_schema, records, existing_records, llm_fields
        )

    return records


def _fill_string_fields_with_llm(
    entity_name: str,
    entity_schema: EntitySchema,
    partial_records: list[dict],
    existing_records: list[dict],
    fields_to_fill: list[str],
) -> list[dict]:
    """Call LLM to generate contextually-appropriate string values.

    Passes the partial records (with programmatic fields already filled) so
    the LLM can generate string values that make sense in context — e.g.,
    a line with capacity=25 gets named "Prototype Line" not "High-Volume Assembly".
    """
    from strands import Agent
    from strands.models.bedrock import BedrockModel

    model = BedrockModel(
        model_id=MODEL_ID,
        temperature=TEMPERATURE_BULK_GENERATION,
        max_tokens=MAX_TOKENS,
        boto_client_config=BEDROCK_CLIENT_CONFIG,
    )

    agent = Agent(
        model=model,
        system_prompt=prompts.render("string_field_fill"),
        tools=[],
        callback_handler=None,
    )

    # Gather example complete records from samples
    example_records = existing_records[-5:] if existing_records else []

    total_count = len(partial_records)
    batch_size = 15  # Smaller batches since we're sending full record context
    filled_idx = 0

    for batch_start in range(0, total_count, batch_size):
        batch = partial_records[batch_start:batch_start + batch_size]

        # Show only the fields that are filled (for context) + mark which are missing
        batch_for_prompt = []
        for record in batch:
            row = {k: v for k, v in record.items() if k not in fields_to_fill}
            batch_for_prompt.append(row)

        prompt = (
            f"Entity: '{entity_name}'\n"
            f"Fields to fill: {fields_to_fill}\n\n"
            f"Example complete records (showing what good values look like):\n"
            f"{json.dumps(example_records[:3], default=str)}\n\n"
            f"Partial records (fill in {fields_to_fill} for each based on the other field values):\n"
            f"{json.dumps(batch_for_prompt, default=str)}\n\n"
            f"Return a JSON list of {len(batch)} objects, each with ONLY: {fields_to_fill}\n"
            f"Each value should make sense given that record's other fields."
        )

        try:
            result = agent(prompt)
            response_text = str(result)
            # Extract JSON list from response
            json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
            if json_match:
                llm_values = json.loads(json_match.group())
                for i, record in enumerate(batch):
                    if i < len(llm_values) and isinstance(llm_values[i], dict):
                        for fname in fields_to_fill:
                            if fname in llm_values[i]:
                                record[fname] = llm_values[i][fname]
                filled_idx = batch_start + len(batch)
                logger.info("LLM string batch: filled %d records for %s (total: %d/%d)",
                            len(batch), entity_name, filled_idx, total_count)
            else:
                logger.warning("LLM string batch returned no JSON list for %s", entity_name)
                break
        except Exception as e:
            logger.warning("LLM string batch failed for %s: %s", entity_name, e)
            break

    # Fallback for any unfilled records
    example_values = {fname: [r.get(fname) for r in existing_records if r.get(fname)] for fname in fields_to_fill}
    for i, record in enumerate(partial_records):
        for fname in fields_to_fill:
            if fname not in record or record[fname] is None:
                examples = example_values.get(fname, [])
                if examples:
                    record[fname] = examples[i % len(examples)]
                else:
                    record[fname] = f"{fname}_{i + 1}"

    logger.info("LLM filled string fields for %s: %d/%d records completed by LLM",
                entity_name, filled_idx, total_count)

    return partial_records


@tool
def bulk_generation_agent(
    entity_schema_definitions: str,
    sample_records_json: str,
    target_count: str = "40",
    seed: int | None = None,
) -> str:
    """Generate bulk synthetic data (30-50 records per entity) based on schema and sample records.

    Args:
        entity_schema_definitions: JSON string of the inferred schema definitions.
        sample_records_json: JSON string of the approved sample records.
        target_count: Target number of records per entity (e.g., "40").
        seed: optional RNG seed making the programmatic columns reproducible.

    Returns:
        JSON mapping of entity names to lists of generated records (including original samples).
    """
    samples, schema_json, target = _parse_tool_input(
        entity_schema_definitions, sample_records_json, target_count
    )

    if not samples:
        logger.error("No sample data to generate from — returning empty result")
        return json.dumps({"data": {}})

    logger.info("Bulk generation agent started — target: %d records per entity, %d entities",
                target, len(samples))

    all_data: dict[str, list[dict]] = {}

    # First pass: generate entities that don't depend on others (no FK to ungenerated entities)
    # This ensures FK parent data is available for child entities
    entity_order = _resolve_generation_order(samples, schema_json)

    # Phase 1: Programmatic generation (sequential — respects FK order, instant)
    entities_needing_llm: list[tuple[str, EntitySchema, list[dict], list[dict]]] = []

    for entity_name in entity_order:
        sample_records = samples.get(entity_name, [])
        all_records = list(sample_records)
        remaining = target - len(all_records)

        if remaining <= 0:
            all_data[entity_name] = all_records[:target]
            continue

        entity_schema = _get_entity_schema(entity_name, schema_json)

        logger.info("Bulk generation — entity '%s': starting with %d samples, need %d more",
                    entity_name, len(all_records), remaining)

        # Use programmatic generation when schema has distributions
        if entity_schema and _has_distributions(entity_schema):
            logger.info("Bulk generation — entity '%s': using programmatic (numpy/scipy) generation",
                        entity_name)
            new_records = _generate_programmatic(
                entity_name, entity_schema, remaining, all_records, all_data,
                defer_llm=True, seed=_entity_seed(seed, entity_name),
            )
            all_records.extend(new_records)
            logger.info("Bulk generation — entity '%s': programmatic generation produced %d records",
                        entity_name, len(new_records))

            # Check if LLM string filling is needed. Use live FKs only, so a
            # dangling FK is still routed to the LLM instead of left empty.
            fk_fields = set(_live_fk_values(entity_name, entity_schema.structured_relationships, all_data))
            llm_fields = [f.name for f in entity_schema.fields if _needs_llm(f, fk_fields)]
            if llm_fields:
                entities_needing_llm.append((entity_name, entity_schema, all_records, sample_records))
        else:
            # Fall back to LLM-based batch generation
            logger.info("Bulk generation — entity '%s': using LLM-based generation (no distributions)",
                        entity_name)
            model = BedrockModel(
                model_id=MODEL_ID,
                temperature=TEMPERATURE_BULK_GENERATION,
                max_tokens=MAX_TOKENS,
            )
            agent = Agent(
                model=model,
                system_prompt=BULK_GENERATION_PROMPT,
                tools=[],
                callback_handler=None,
            )
            unique_fields = _find_unique_fields(entity_name, schema_json)

            batch_num = 0
            while remaining > 0:
                batch_num += 1
                batch_size = min(BATCH_SIZE, remaining)
                logger.info("Bulk generation — entity '%s': LLM batch %d (requesting %d records)",
                            entity_name, batch_num, batch_size)

                example_records = all_records[-5:]
                existing_ids = []
                for field in unique_fields:
                    existing_ids.extend(
                        str(r[field]) for r in all_records if r.get(field) is not None
                    )

                try:
                    result = agent(
                        f"Schema definitions:\n{schema_json}\n\n"
                        f"Example existing records for entity '{entity_name}' "
                        f"(showing last {len(example_records)} of {len(all_records)} total):\n"
                        f"{json.dumps(example_records)}\n\n"
                        f"Unique field(s): {unique_fields}\n"
                        f"Values already used for unique fields: {existing_ids}\n\n"
                        f"Generate exactly {batch_size} NEW records for the '{entity_name}' entity. "
                        f"Do not repeat any existing records or reuse unique field values.",
                        structured_output_model=GeneratedSamples,
                    )
                except Exception as e:
                    logger.error("Bulk generation — entity '%s': LLM batch %d failed: %s",
                                 entity_name, batch_num, e)
                    break

                if not result.structured_output:
                    logger.warning("Bulk generation — entity '%s': LLM batch %d no structured output",
                                   entity_name, batch_num)
                    break

                new_data = result.structured_output.model_dump()
                new_records = new_data["data"].get(entity_name, [])

                if not new_records:
                    for entity_records in new_data["data"].values():
                        if entity_records:
                            new_records = entity_records
                            break

                if not new_records:
                    logger.warning("Bulk generation — entity '%s': LLM batch %d returned no records",
                                   entity_name, batch_num)
                    break

                all_records.extend(new_records)
                remaining = target - len(all_records)
                logger.info("Bulk generation — entity '%s': LLM batch %d produced %d (total: %d/%d)",
                            entity_name, batch_num, len(new_records), len(all_records), target)

        all_data[entity_name] = all_records[:target]

    # Phase 2: Fill string fields via LLM in parallel across entities
    if entities_needing_llm:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _fill_entity(args):
            ent_name, ent_schema, records, samples = args
            # Match Phase 1's live-FK set exactly, so the fields filled here are
            # precisely the ones left unfilled there (dangling FKs included).
            fk_fields = set(_live_fk_values(ent_name, ent_schema.structured_relationships, all_data))
            llm_fields = [f.name for f in ent_schema.fields if _needs_llm(f, fk_fields)]
            # Only pass records that need filling (the new ones, not the original samples)
            new_records = records[len(samples):]
            filled = _fill_string_fields_with_llm(ent_name, ent_schema, new_records, samples, llm_fields)
            return ent_name, samples + filled

        logger.info("Bulk generation — Phase 2: filling string fields in parallel for %d entities",
                    len(entities_needing_llm))

        max_workers = min(len(entities_needing_llm), 4)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_fill_entity, args): args[0] for args in entities_needing_llm}
            for future in as_completed(futures):
                entity_name = futures[future]
                try:
                    ent_name, filled_records = future.result()
                    all_data[ent_name] = filled_records[:target]
                    logger.info("Bulk generation — entity '%s': LLM string fill complete", ent_name)
                except Exception as e:
                    logger.error("Bulk generation — entity '%s': parallel LLM fill failed: %s", entity_name, e)

    total_records = sum(len(records) for records in all_data.values())
    logger.info("Bulk generation agent finished — %d entities, %d total records",
                len(all_data), total_records)

    result_obj = GeneratedSamples(data=all_data)
    return result_obj.model_dump_json(indent=2)


def _resolve_generation_order(samples: dict[str, list], schema_json: str) -> list[str]:
    """Order entities so parents are generated before children (FK dependencies)."""
    parsed = _parse_json_lenient(schema_json)
    if not parsed:
        return list(samples.keys())

    # Build dependency graph: child -> set of parents
    deps: dict[str, set[str]] = {name: set() for name in samples}
    for entity in parsed.get("entities", []):
        name = entity.get("entity_name", "")
        if name not in deps:
            continue
        for rel in entity.get("structured_relationships", []):
            if rel.get("source_entity") == name:
                parent = rel.get("target_entity", "")
                if parent in deps:
                    deps[name].add(parent)

    # Topological sort (Kahn's algorithm)
    ordered = []
    no_deps = [n for n, d in deps.items() if not d]
    while no_deps:
        node = no_deps.pop(0)
        ordered.append(node)
        for name, d in deps.items():
            d.discard(node)
            if not d and name not in ordered and name not in no_deps:
                no_deps.append(name)

    # Add any remaining (circular deps) at the end
    for name in samples:
        if name not in ordered:
            ordered.append(name)

    return ordered

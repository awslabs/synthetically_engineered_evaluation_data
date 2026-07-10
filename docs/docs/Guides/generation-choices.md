---
title: Generation Choices
---

# Generation Choices

Document diversity comes from two sources of per-run variation, both declared per document type:

1. **Optional fields with `x-probability`**: vary which fields appear in the data.
2. **Table presentation variations**: vary how data is rendered visually.

This guide covers what the mechanism is, how it works, and how to add it to a new document type.

## Why It Exists

Real-world documents of the same type vary across instances. A bank statement might include a deposit-pattern narrative on one issue and skip it the next. A pay stub may or may not include a per-medication instruction column. Generating documents that all look structurally identical produces poor training data for downstream models.

The `x-probability` mechanism produces honest, per-document variation without writing custom orchestration code per schema. The schema declares which fields are optional and at what rate; the pipeline does the rest.

## Optional Fields with `x-probability`

Any field in a schema (top-level, nested, or inside array item definitions) can carry an `x-probability` annotation, a decimal between 0 and 1, marking it as optional with an associated inclusion rate.

### Conventions

- The field must NOT appear in any `required` array.
- `x-probability` is a JSON Schema extension. The `x-` prefix is the standard opt-in vocabulary convention, so generic JSON Schema validators ignore it.
- Works for any field type: strings, numbers, booleans, objects, arrays.
- Works at any nesting level: top-level properties, properties inside nested objects, and properties inside array `items`.

### Behavior

- At generation time, each field with `x-probability` is independently included or omitted based on its probability.
- When included, the field is populated with realistic content per its `description`.
- When omitted, the field is absent from the output JSON entirely (not null, not an empty string, just absent).

### Example: Top-Level Field

```json
"AccountSummaryNarrative": {
  "type": "string",
  "description": "Optional 1-2 sentence narrative summarizing account activity.",
  "x-probability": 0.7
}
```

About 70% of generated documents will include this field with a 1-2 sentence narrative. The other 30% will omit it.

### Example: Nested Field

```json
"customer": {
  "type": "object",
  "properties": {
    "shippingAddress": {
      "type": "string",
      "description": "Delivery address if different from billing.",
      "x-probability": 0.6
    }
  }
}
```

About 60% of generated documents will include `customer.shippingAddress`.

### Example: Field Inside an Array's Items

```json
"DischargeMedications": {
  "type": "array",
  "items": {
    "type": "object",
    "required": ["MedicationName", "Dosage", "Frequency"],
    "properties": {
      "MedicationName": { "type": "string" },
      "Dosage":         { "type": "string" },
      "Frequency":      { "type": "string" },
      "Instructions": {
        "type": "string",
        "description": "Patient-facing instructions, e.g., 'Take with food'.",
        "x-probability": 0.6
      }
    }
  }
}
```

For each medication in the list, the `Instructions` field has roughly a 60% chance of being present. Some medications will have instructions, others will not.

## Table Presentation Variations

Some sections can render either as HTML/PDF tables or as inline labeled fields and lists. These variations live in `generation_guidance.md` only, not in the schema, because they are rendering choices, not data.

### Convention

Each schema's `generation_guidance.md` has a `## Layout Variations` section listing table presentation options with a stated probability (typically 50/50). The renderer decides independently per section.

### Example

```markdown
Table presentation variations. Either format is valid for a realistic bank statement;
~50/50 mix:
- Transactions: full table with date/description/debit/credit/balance columns,
  or simplified list
- Account summary block: summary table, or labeled fields
```

## Adding Generation Choices to a New Document Type

1. **In `schema.json`**: add optional fields with `"x-probability": 0.7` (or whatever rate you want). Keep them out of `required`. Give them a clear `description`. These can be at any nesting level and of any type.
2. **In `generation_guidance.md`**: add a `## Layout Variations` section listing optional fields with their descriptions and inclusion frequency, plus table presentation variations with their alternatives and probability.
3. **Keep the guidance declarative**: describe the document and its variations, not the pipeline or the agents.

### Example `## Layout Variations` Section

```markdown
## Layout Variations

Optional fields, include when context supports them, omit otherwise:
- `AccountSummaryNarrative` (~70%): summarizes account activity and balance trend
- `DepositPatternNarrative` (~70%): describes the deposit pattern
- `customer.shippingAddress` (~60%): delivery address when different from billing

Table presentation variations. Either format is valid for a realistic bank statement;
~50/50 mix:
- Transactions: full table with date/description/debit/credit/balance columns,
  or simplified list
- Account summary block: summary table, or labeled fields
```

## Implementation Notes

The data generator agent reads the schema and calls a `random_roll` tool per `x-probability` field for honest RNG decisions. When a roll fails, the field is omitted from the saved JSON. The doc generator agent calls `random_roll` per table presentation variation listed in the guidance, then renders accordingly.

Roll decisions are captured in the agent's tool-use trace, which makes the per-document variation auditable and debuggable.

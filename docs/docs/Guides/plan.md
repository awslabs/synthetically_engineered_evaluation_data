---
title: Plan
---

# Plan

Planning is the **one front door** into SEED. The `plan` verb takes any description
of a dataset — a sentence of prose, a CSV of real rows, a JSON Schema, a SQL
`CREATE TABLE`, a scanned PDF, an ERD diagram — and turns it into a single canonical
`InferredSchema`. That one schema then drives either output modality, so you
describe your data once and choose the shape it comes out in afterwards.

Two things you can do with the result:

- **Structured** — feed the schema to `generate-structured` for tabular
  CSV/Parquet/Excel/JSON. See [Structured Data](structured-data.md).
- **Documents** — feed the *same* schema to `generate-documents` for rendered
  PDFs with paired ground-truth labels.

!!! note "A planned schema is a draft for review"
    Planning infers structure and constraints from whatever you gave it. A wrong
    `required` field, a too-narrow numeric range, or a missed relationship would
    skew every record and every document you later generate, so `seed-data
    plan` **writes the schema and stops** for you to review. Read
    `schema.json`, fix anything off, then generate.

Every input is classified automatically — you never declare what you are handing
over. Detection is by URI scheme and file extension, and anything without a
recognized extension is treated as a free-text description. The five
classifications are listed by `Generator.available_input_types()`:

```python
from seed_data import Generator

Generator.available_input_types()
# ['free_text', 'example_data', 'schema', 'document', 'erd']
```

## Free text

The lowest-friction input: describe the dataset in prose. Nothing needs to exist
on disk.

### CLI

```bash
seed-data plan "Retail bank customers with credit scores and account tiers, plus the orders each customer placed" \
  --name banking --output ./schema.json
```

`plan` writes one `InferredSchema` JSON file and prints what it found:

```text
============================================================
Wrote InferredSchema to: ./schema.json
Entities: Customer, Order
Generate structured data with:
  seed-data generate-structured ./schema.json --rows 100 --format csv
```

| Flag | Default | Description |
|------|---------|-------------|
| `inputs` | required | One or more free-text description(s), file paths/globs, and/or `s3://` URIs |
| `--name` | `dataset` | Logical dataset name |
| `--output` | `./schema.json` | Path to write the `InferredSchema` JSON |
| `--quiet` | off | Suppress progress output |

### Python

`Generator.plan(...)` returns a typed `InferredSchema` — not a dict — so it
drops straight into the generation verbs:

```python
from seed_data import Generator

gen = Generator()
schema = gen.plan(
    "Retail bank customers with credit scores and account tiers",
    name="banking",
)
print([e.entity_name for e in schema.entities])
```

## Example data

Point `plan` at real rows and it reads them, summarizes each column (types,
cardinality, null counts, ranges, sample values), and infers semantic types
(email, phone, date, enum) and constraints from what it sees. `.csv`, `.json`,
`.xls`, and `.xlsx` are recognized.

### CLI

```bash
# a CSV of real rows -> a schema shaped like that data
seed-data plan ./samples/customers.csv --name customers --output ./schema.json

# a spreadsheet works the same way
seed-data plan ./samples/sales.xlsx --name sales --output ./schema.json
```

### Python

```python
schema = gen.plan("./samples/customers.csv", name="customers")
```

Real rows are the strongest signal available for value distributions: a column of
observed credit scores yields a far better range and shape than the phrase
"credit score" does.

## Formal schema

If the structure is already written down, hand it over directly. Both **JSON
Schema** (`.json`) and **SQL DDL** (`.sql`, `.ddl`) are recognized, and the
format is chosen from the extension.

### CLI

```bash
# a JSON Schema document
seed-data plan ./contracts/customer.schema.json --name customer --output ./schema.json

# SQL DDL — CREATE TABLE statements, including foreign keys
seed-data plan ./db/schema.sql --name warehouse --output ./schema.json
```

A `.json` path only counts as a formal schema when the file **exists on disk**; a
description that happens to end in `.json` is treated as free text instead.

### Python

```python
schema = gen.plan("./db/schema.sql", name="warehouse")
```

## Documents

Documents and images are read with a **vision model**, reusing the same inference
path as [Schema from Documents](schema-from-documents.md). Inputs may be **PDF,
PNG, or JPEG**, from local paths, globs, directories, or `s3://` URIs — an
`s3://` URI is always classified as a document.

### CLI

```bash
# one real invoice -> a schema of the fields it contains
seed-data plan ./samples/invoice.pdf --name invoice --output ./schema.json

# globs and s3:// both work
seed-data plan './samples/*.pdf' --name invoice --output ./schema.json
seed-data plan s3://my-bucket/invoices/ --name invoice --output ./schema.json
```

### Python

```python
schema = gen.plan("./samples/invoice.pdf", name="invoice")
```

`--name` matters most for this input kind: it becomes the document-type name the
vision inference works against.

## ERD diagrams

An entity-relationship diagram already states the entities, their fields, and the
foreign keys between them. `plan` parses **DBML** (`.dbml`), **PlantUML**
(`.puml`, `.plantuml`), and **Mermaid** (`.mmd`, `.mermaid`).

### CLI

```bash
seed-data plan ./design/warehouse.dbml --name warehouse --output ./schema.json
```

### Python

```python
schema = gen.plan("./design/warehouse.dbml", name="warehouse")
```

An ERD is the best input for **multi-entity** datasets, because the relationships
are explicit rather than inferred.

## Combining inputs

`plan` accepts several inputs of **different kinds in one call**. Each is
classified and routed independently, and the resulting entities are merged into
one `InferredSchema`.

### CLI

```bash
seed-data plan \
  ./design/warehouse.dbml \
  ./samples/customers.csv \
  "Orders skew heavily toward Q4; about 8% are refunded" \
  --name warehouse --output ./schema.json
```

### Python

```python
schema = gen.plan(
    "./design/warehouse.dbml",              # entities + relationships
    "./samples/customers.csv",              # observed value distributions
    "Orders skew heavily toward Q4",         # the domain rule no file states
    name="warehouse",
)
```

Combining sharpens the result because the input kinds are good at different
things. The ERD or DDL fixes the **structure** and the foreign keys; the example
data fixes the **value distributions**; the free text supplies the **domain rules
that live nowhere in either** — seasonality, plausible ratios, business
constraints. Planning from all of them together gets you all three in one schema instead of
one of the three plus guesswork.

## The InferredSchema

The output is one `InferredSchema`: a list of **entities**, each with a name, a
description, its **fields**, and its relationships. It is the same model both
modalities consume, importable from `seed_data`:

```json
{
  "entities": [
    {
      "entity_name": "Customer",
      "description": "A retail banking customer",
      "fields": [
        {
          "name": "customer_id",
          "type": "string",
          "description": "Primary key, format CUST-000000",
          "required": true,
          "nullable": false,
          "unique": true,
          "pattern": "^CUST-[0-9]{6}$"
        },
        {
          "name": "credit_score",
          "type": "integer",
          "description": "FICO score at signup",
          "required": true,
          "nullable": true,
          "min_value": 300,
          "max_value": 850,
          "distribution": {
            "type": "normal",
            "params": {"mean": 690, "std": 70}
          }
        },
        {
          "name": "tier",
          "type": "enum",
          "description": "Account tier",
          "required": true,
          "nullable": false,
          "enum_values": ["basic", "plus", "premier"],
          "distribution": {
            "type": "categorical_weighted",
            "params": {"weights": [0.6, 0.3, 0.1]}
          }
        }
      ],
      "relationships": [],
      "structured_relationships": [],
      "generation_guidance": "US retail bank; signup dates within the last 5 years."
    },
    {
      "entity_name": "Order",
      "description": "One purchase made by a customer",
      "fields": [
        {"name": "order_id", "type": "string", "description": "Primary key", "required": true, "unique": true},
        {"name": "customer_id", "type": "string", "description": "FK to Customer", "required": true}
      ],
      "relationships": ["belongs_to: Customer"],
      "structured_relationships": [
        {
          "source_entity": "Order",
          "source_field": "customer_id",
          "target_entity": "Customer",
          "target_field": "customer_id",
          "cardinality": "one_to_many"
        }
      ]
    }
  ]
}
```

The parts worth understanding before you edit it:

- **`required` and `nullable` are independent.** `required` says the *key must be
  present*; `nullable` says the *value may be null*. A required-and-nullable
  field is normal and common — the key always appears, and its value is null when
  the source has nothing to put there. Do not conflate the two: marking a field
  non-nullable when reality includes nulls forces invented values into every row.
- **`distribution`** shapes generated values: `uniform`, `normal`,
  `exponential`, `log_normal`, `categorical_weighted`, `skewed_left`, or
  `skewed_right`, each with its own `params`. Absent a distribution, values are
  drawn without a target shape.
- **Relationships** come in two forms. `relationships` is free text
  (`"belongs_to: Customer"`) for the generator to read; `structured_relationships`
  is the machine-checkable form — source entity/field, target entity/field, and a
  cardinality of `one_to_one`, `one_to_many`, or `many_to_many`. The structured
  form is what referential-integrity enforcement and scoring use, so it is the
  one to add if a foreign key was missed.
- **`generation_guidance`** is per-entity free text: realism rules, value
  conventions, layout notes for the document pipeline.
- Other field constraints: `unique`, `min_value` / `max_value`, `min_length` /
  `max_length`, `pattern`, `enum_values`, `default`, and `children` for nested
  object and array fields.

### Relationship to JSON Schema

`InferredSchema` is **not a competing format**. JSON Schema is the interchange
format, and `InferredSchema` is a deliberate superset of it: everything JSON
Schema can say about a field, it says the same way (`pattern`, `minimum` /
`maximum`, `minLength` / `maxLength`, `enum`, `required`, nested `properties`,
array `items`), plus the generation metadata JSON Schema has no vocabulary for.

Both directions ship in `seed_data.schema.io`:

```python
import json
from seed_data.schema.io import from_json_schema, to_json_schema

with open("customer.schema.json") as f:
    schema = from_json_schema(json.load(f))       # standard -> canonical

document = to_json_schema(schema, entity_name="Customer")  # canonical -> standard
```

`from_schema_dir` is the directory-level form of the same import, for a folder of
per-entity JSON Schema files.

Handing `seed-data plan` a `.json` file that exists on disk routes through
`from_json_schema` — that is what the [Formal schema](#formal-schema) path above
does, so **you never have to convert anything by hand**.

#### What the superset adds, and why it can't be JSON Schema

JSON Schema answers "is this one document valid?". Generation needs to answer
"how do I synthesize a correlated multi-entity dataset?" — a different question,
and these four fields are what carry the difference:

| `InferredSchema` field | What it holds | Why JSON Schema can't express it |
|---|---|---|
| `distribution` | `DistributionSpec` — `normal`, `log_normal`, `categorical_weighted`, … with `params` | JSON Schema constrains the *range* a value may fall in, never the *shape* of a population. `{"minimum": 300, "maximum": 850}` accepts a column of all 300s. |
| `structured_relationships` | `RelationshipDefinition` — source/target entity + field, cardinality | Cross-document foreign keys are outside JSON Schema's scope; `$ref` composes schemas, it does not declare that one instance's field must equal another instance's. |
| `generation_guidance` | Per-entity free text steering realism | Instructions to a generator, not constraints on a value. |
| `reference_samples` | Real example rows to imitate | A validator has no use for examples; `examples` is annotation-only and carries no generation semantics. |

Two structural differences also matter:

- **Multi-entity.** One `InferredSchema` holds many entities; a JSON Schema
  document describes one object. `to_json_schema` therefore serializes **one
  entity at a time** (`entity_name=` picks which; the first by default).
- **The round trip is lossy in one direction.** Starting from a JSON Schema
  document, `from_json_schema` → `to_json_schema` returns what you gave it —
  types, `required`, `pattern`, bounds, lengths, `enum`, and `x-probability` all
  come back unchanged. Starting from an `InferredSchema`, exporting and reimporting
  **loses** the four superset fields above and three more that `to_json_schema`
  does not emit: `unique`, `default`, and `structured_relationships`.

    So export to JSON Schema for interop with external validators, but keep the
    `InferredSchema` JSON as your source of truth — don't use a round trip through
    JSON Schema as a way to store or edit a schema.

#### Custom extensions

Where a JSON Schema extension is genuinely needed, SEED uses the standard `x-`
prefix convention. Currently one such key is read and written:
`x-probability`, which maps to `FieldDefinition.presence_probability` and lets a
field be *sometimes present* across generated documents. It survives the round
trip in both directions. If the superset fields above ever need to travel inside
a JSON Schema document rather than beside it, the same `x-` convention is the
route, and distribution metadata could be aligned with an external vocabulary
should a standard one emerge.

### CLI

The file `--output` wrote is plain JSON. Read it, edit it in any editor, and pass
it back to either generation command:

```bash
seed-data plan "..." --name banking --output ./schema.json
# review and edit ./schema.json, then:
seed-data generate-structured ./schema.json --rows 500 --format csv
seed-data generate-documents ./schema.json --entity Customer --count 5
```

### Python

`InferredSchema` is a pydantic model, so reading, editing, saving, and reloading
all use its standard methods:

```python
from seed_data import Generator, InferredSchema

gen = Generator()
schema = gen.plan("Retail bank customers and their orders", name="banking")

# read
for entity in schema.entities:
    print(entity.entity_name, len(entity.fields), "fields")
    for f in entity.fields:
        print(f"  {f.name:16} {f.type:10} required={f.is_required} nullable={f.nullable}")

# edit in place — the model is mutable
customer = schema.entities[0]
customer.generation_guidance = "US retail bank, signup dates within the last 5 years."
customer.fields[1].min_value = 300
customer.fields[1].max_value = 850

# save for review or reuse
with open("./schema.json", "w") as f:
    f.write(schema.model_dump_json(indent=2))

# reload later
with open("./schema.json") as f:
    schema = InferredSchema.model_validate_json(f.read())

result = gen.generate_structured(schema, rows=500)
```

`generate_structured` also accepts the **path** to that JSON file, or a bundled
schema name, if you would rather not load it yourself.

## Related

- [Structured Data](structured-data.md): generate tabular data from a planned schema.
- [Schema from Documents](schema-from-documents.md): the document-only inference path, with clarifying questions and packet splitting.

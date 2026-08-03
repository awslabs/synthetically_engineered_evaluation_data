---
title: Ingest
---

# Ingest

Ingest is the **one front door** into SEED. It takes any description of a dataset
— a sentence of prose, a CSV of real rows, a JSON Schema, a SQL `CREATE TABLE`, a
scanned PDF, an ERD diagram — and turns it into a single canonical
`InferredSchema`. That one schema then drives either output modality, so you
describe your data once and choose the shape it comes out in afterwards.

Two things you can do with the result:

- **Structured** — feed the schema to `generate-structured` for tabular
  CSV/Parquet/Excel/JSON. See [Structured Data](structured-data.md).
- **Documents** — feed the *same* schema to `generate-documents` for rendered
  PDFs with paired ground-truth labels.

!!! note "An ingested schema is a draft for review"
    Ingest infers structure and constraints from whatever you gave it. A wrong
    `required` field, a too-narrow numeric range, or a missed relationship would
    skew every record and every document you later generate, so `seed-data
    ingest` **writes the schema and stops** for you to review. Read
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
seed-data ingest "Retail bank customers with credit scores and account tiers, plus the orders each customer placed" \
  --name banking --output ./schema.json
```

Ingest writes one `InferredSchema` JSON file and prints what it found:

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

`Generator.ingest(...)` returns a typed `InferredSchema` — not a dict — so it
drops straight into the generation verbs:

```python
from seed_data import Generator

gen = Generator()
schema = gen.ingest(
    "Retail bank customers with credit scores and account tiers",
    name="banking",
)
print([e.entity_name for e in schema.entities])
```

## Example data

Point ingest at real rows and it reads them, summarizes each column (types,
cardinality, null counts, ranges, sample values), and infers semantic types
(email, phone, date, enum) and constraints from what it sees. `.csv`, `.json`,
`.xls`, and `.xlsx` are recognized.

### CLI

```bash
# a CSV of real rows -> a schema shaped like that data
seed-data ingest ./samples/customers.csv --name customers --output ./schema.json

# a spreadsheet works the same way
seed-data ingest ./samples/sales.xlsx --name sales --output ./schema.json
```

### Python

```python
schema = gen.ingest("./samples/customers.csv", name="customers")
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
seed-data ingest ./contracts/customer.schema.json --name customer --output ./schema.json

# SQL DDL — CREATE TABLE statements, including foreign keys
seed-data ingest ./db/schema.sql --name warehouse --output ./schema.json
```

A `.json` path only counts as a formal schema when the file **exists on disk**; a
description that happens to end in `.json` is treated as free text instead.

### Python

```python
schema = gen.ingest("./db/schema.sql", name="warehouse")
```

## Documents

Documents and images are read with a **vision model**, reusing the same inference
path as [Schema from Documents](schema-from-documents.md). Inputs may be **PDF,
PNG, or JPEG**, from local paths, globs, directories, or `s3://` URIs — an
`s3://` URI is always classified as a document.

### CLI

```bash
# one real invoice -> a schema of the fields it contains
seed-data ingest ./samples/invoice.pdf --name invoice --output ./schema.json

# globs and s3:// both work
seed-data ingest './samples/*.pdf' --name invoice --output ./schema.json
seed-data ingest s3://my-bucket/invoices/ --name invoice --output ./schema.json
```

### Python

```python
schema = gen.ingest("./samples/invoice.pdf", name="invoice")
```

`--name` matters most for this input kind: it becomes the document-type name the
vision inference works against.

## ERD diagrams

An entity-relationship diagram already states the entities, their fields, and the
foreign keys between them. Ingest parses **DBML** (`.dbml`), **PlantUML**
(`.puml`, `.plantuml`), and **Mermaid** (`.mmd`, `.mermaid`).

### CLI

```bash
seed-data ingest ./design/warehouse.dbml --name warehouse --output ./schema.json
```

### Python

```python
schema = gen.ingest("./design/warehouse.dbml", name="warehouse")
```

An ERD is the best input for **multi-entity** datasets, because the relationships
are explicit rather than inferred.

## Combining inputs

Ingest accepts several inputs of **different kinds in one call**. Each is
classified and routed independently, and the resulting entities are merged into
one `InferredSchema`.

### CLI

```bash
seed-data ingest \
  ./design/warehouse.dbml \
  ./samples/customers.csv \
  "Orders skew heavily toward Q4; about 8% are refunded" \
  --name warehouse --output ./schema.json
```

### Python

```python
schema = gen.ingest(
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
constraints. Ingesting them together gets you all three in one schema instead of
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

### CLI

The file `--output` wrote is plain JSON. Read it, edit it in any editor, and pass
it back to either generation command:

```bash
seed-data ingest "..." --name banking --output ./schema.json
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
schema = gen.ingest("Retail bank customers and their orders", name="banking")

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

- [Structured Data](structured-data.md): generate tabular data from an ingested schema.
- [Schema from Documents](schema-from-documents.md): the document-only inference path, with clarifying questions and packet splitting.

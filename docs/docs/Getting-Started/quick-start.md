---
title: Quick Start
---

# Quick Start

From zero to your first generated document — and your first structured dataset —
from either the command line or Python. Both paths produce the same artifacts.

## 1. Install

```bash
pip install seed-data
```

The default renderer (**xhtml2pdf**) is pure Python — there are no system
libraries to install. For the richer-CSS WeasyPrint renderer, see
[Renderers](../Advanced/renderers.md).

## 2. Configure AWS Bedrock

seed-data generates content with Amazon Bedrock models, so you need AWS
credentials with Bedrock access.

```bash
export AWS_PROFILE=your-profile-name
export AWS_REGION=us-east-1
```

## 3. Get the schemas

A **schema** defines a document type — its fields, data rules, and visual style.
Copy the built-in library into a local, editable folder:

```bash
seed-data clone-schema-library ./schemas
```

Browse the library on GitHub:
👉 [awslabs/…/schemas](https://github.com/awslabs/synthetically_engineered_evaluation_data/tree/main/src/seed_data/schemas)

Built-in types include `invoice`, `fcc-invoice`, `bank-statement`, `w2`, `pay-stub`,
`credit-report`, `loan-application`, `police-report`, and more.

## 4. Generate your first document

Generate a single document — pass a bundled schema name or a path:

```bash
seed-data --schema-dir invoice --output ./output
```

This runs the full single-document pipeline (data generation → validation → PDF
render → visual critique). It writes three paired artifacts:

```
output/
├── data/<id>.json                 # ground-truth JSON label
├── generation_scripts/<id>.html   # the HTML the renderer used
└── pdfs/<id>.pdf                  # the final document
```

More CLI examples:

```bash
# Steer the content with a brief; pick faster/cheaper models
seed-data --schema-dir invoice \
  --scenario "Invoices for midwest food distributors, 20-40 line items" \
  --doc-model gpt-oss --critic-model haiku --threshold 3

# A diverse batch of N documents from one brief
seed-data --schema-dir fcc-invoice --count 10 \
  --scenario "Local TV stations across different US regions"

# A coordinated multi-document packet (merged PDF + shared context)
seed-data packet lending-package \
  --scenario "First-time homebuyer in Portland, OR"

# Add scanning/aging artifacts, or a different renderer
seed-data --schema-dir invoice --augment --renderer weasyprint
```

Run `seed-data --help` (and `seed-data packet --help`) to see every option.

## 5. Generate structured data

SEED also generates structured (tabular) data. That stack is opt-in, so install
the extra first:

```bash
pip install "seed-data[structured]"
```

Structured generation starts from an **InferredSchema** — a schema describing one
or more entities, their fields, and the relationships between them. `seed-data
plan` builds one from whatever you have: a plain-English description, a CSV or
JSON of example data, a JSON Schema or SQL DDL, existing PDFs, or an ERD
diagram. Several inputs of different kinds can be combined in one call.

```bash
seed-data plan "Customers and their orders for a regional coffee wholesaler" \
  --name coffee --output ./schema.json
```

That writes the schema to `./schema.json`, which is also where `--output` points
by default. Review and edit it if you want, then generate rows from it:

```bash
seed-data generate-structured ./schema.json --rows 500 --format csv --output ./output
```

One file per entity lands in the output directory, named from the lowercased
entity name with spaces replaced by underscores:

```
output/
├── customer.csv
└── order.csv
```

`--format` also accepts `json`, `excel` (`.xlsx`), and `parquet`. All of them
work with the `[structured]` extra alone — no separate engine install.

If you do not need the intermediate schema file, `seed-data plan-and-generate` does planning and
generation in one shot:

```bash
seed-data plan-and-generate "Customers and their orders for a regional coffee wholesaler" \
  --name coffee --output structured --rows 500 --format csv --output-dir ./output
```

!!! note "`--output` on `plan-and-generate` selects the modality"

    On `plan-and-generate`, `--output` chooses `structured` or `documents`, and `--output-dir`
    is the path. On every other command `--output` is a path. Add
    `--save-schema ./schema.json` to keep the planned schema as well.

The same schema can drive the document pipeline instead — `--output documents` on
`plan_and_generate`, or `seed-data generate-documents ./schema.json`. For a multi-entity schema,
`--entity` picks which entity to render.

---

## Python API Usage

Everything the CLI does is available programmatically through the `Generator`
class — configure it once, then call a verb. Each returns a typed result.

```python
from seed_data import Generator, ModelConfig

gen = Generator(
    models=ModelConfig(doc="gpt-oss", critic="haiku"),
    threshold=3,
    output_dir="./output",
)
```

**Single document** → `GeneratedDoc`:

```python
doc = gen.generate("invoice", scenario="Midwest food-distributor invoice")

print(doc.success, doc.verdict, doc.score)
print(doc.pdf_path)          # the rendered PDF
print(doc.data)              # ground-truth JSON label (lazy-loaded dict)
print(doc.data_json_path)    # ...and its path on disk
```

**Diverse batch** → `BatchResult`:

```python
batch = gen.generate_batch(
    "fcc-invoice",
    count=10,
    scenario="Local TV stations across different US regions",
    on_document=lambda i, n, d: print(f"[{i+1}/{n}] {d.verdict}"),
)
print(batch.count_succeeded, "of", batch.count_requested)
for d in batch.succeeded:
    print(d.pdf_path, d.data_json_path)
```

**Coordinated packet** → `PacketResult`:

```python
pkt = gen.generate_packet("lending-package", scenario="First-time homebuyer in Portland, OR")
print(pkt.merged_pdf)
for s in pkt.sections:
    print(s.document_class, s.page_indices)
```

**Structured data** → `StructuredResult`. `plan` returns an `InferredSchema`,
which `generate_structured` turns into files (needs the `[structured]` extra):

```python
schema = gen.plan(
    "Customers and their orders for a regional coffee wholesaler",
    name="coffee",
)
result = gen.generate_structured(schema, rows=500, format="csv")

print(result.output_paths)   # ['./output/customer.csv', './output/order.csv']
print(result.row_counts)     # {'Customer': 500, 'Order': 500}
print(result.evaluation)     # quality scores per metric
```

`gen.plan_and_generate(...)` collapses those two calls into one, and `output="documents"` sends
the same planned schema down the document pipeline instead:

```python
result = gen.plan_and_generate("...description...", output="structured", rows=500, format="csv")
```

**Schema from real documents** → a `Schema` you can generate from. Point SEED at
example documents and a vision model reverse-engineers the schema for you:

```python
schema = gen.infer_schema("./samples/*.pdf", name="invoice")
doc = gen.generate(schema, scenario="Midwest food distributor")
```

See [Schema from Documents](../Guides/schema-from-documents.md) for inferring from
images, S3, or one concatenated multi-document PDF.

**Define a document type in code** — no files on disk, from a pydantic model:

```python
from pydantic import BaseModel
from seed_data import Schema

class Invoice(BaseModel):
    invoice_number: str
    total: float

schema = Schema(name="invoice", model=Invoice,
                generation_guidance="Totals must equal the sum of line items.")
doc = gen.generate(schema, scenario="IT consulting services")
```

See the [Python API reference](../API-Reference/generator.md) for full signatures.

---

## Edit or create a schema

Because you cloned the library locally, editing a document type is just editing
files:

```
schemas/invoice/
├── schema.json              # fields and types
└── generation_guidance.md   # data-realism rules and visual style
```

Point `--schema-dir` (or `gen.generate(...)`) at any folder with that structure —
your own custom types work exactly the same way.

## Next steps

- [Single Document](../Guides/single-document.md): the full single-doc guide (CLI + Python).
- [Batch Generation](../Guides/batch-generation.md): control diversity and scale.
- [Packets](../Guides/packets.md): coordinated multi-document sets.
- [Create a Document Type](../Guides/creating-a-document-type.md): author your own schema.
- [Plan](../Guides/plan.md): every input type, auto-detection, and the `InferredSchema` it produces.
- [Structured Data](../Guides/structured-data.md): the full tabular guide — formats, relationships, and quality scoring.

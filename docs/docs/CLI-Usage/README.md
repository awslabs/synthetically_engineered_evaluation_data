---
title: CLI Usage
---

# CLI Usage

The `seed-data` command generates synthetic evaluation data from the command line.
Every input kind — a free-text description, example CSVs, a JSON Schema, SQL DDL,
an ERD, or real PDFs — goes through one planning front door that produces a unified
schema, and that schema drives either of two output modalities: PDF documents with
paired ground-truth JSON labels (as a single document, a diverse batch, or a
coordinated multi-document packet), or structured tabular data as CSV, Parquet,
Excel, or JSON. The `plan-and-generate` subcommand does both halves — plan, then generate — in
one shot. This page documents each mode with examples and a complete flag
reference.

## Installation and setup

Install the package and configure Amazon Bedrock credentials:

```bash
pip install seed-data
export AWS_PROFILE=your-profile-name
export AWS_REGION=us-east-1
```

The base install covers the whole document pipeline. Structured (tabular)
generation needs the `[structured]` extra, which adds pandas plus the
file-format engines (openpyxl, pyarrow):

```bash
pip install "seed-data[structured]"   # structured generation
pip install "seed-data[all]"          # every optional feature
```

`plan`, `generate-documents`, `packet`, `infer-schema` and the default mode never
need the extra. `generate-structured` and `plan-and-generate --output structured` do, and raise an
`ImportError` naming the missing dependency if it is absent — install
`seed-data[structured]` to resolve it.

The default renderer, xhtml2pdf, is pure Python and requires no additional system
libraries.

To edit document types locally, copy the bundled schema library into a writable
directory:

```bash
seed-data clone-schema-library ./schemas
```

Every generation mode accepts either a bundled schema name (such as `invoice`) or a
path to a schema directory. The examples below use bundled names, but any path to a
directory containing a `schema.json` is equally valid.

## Plan

The `plan` subcommand is the shared front door: it takes any mix of inputs,
auto-detects what each one is, and merges them into a single `InferredSchema` JSON
file that both output modalities read. Detection is by scheme and file extension —
anything without a recognized extension is treated as free text.

The detected input types are `free_text`, `example_data`, `schema`, `document`, and
`erd`. One example of each:

```bash
# free text — a prose description of the data you want
seed-data plan "Retail customers and their orders, with US shipping addresses" \
  --name retail --output ./schema.json

# example data — sample rows in CSV (also .xls, .xlsx)
seed-data plan ./samples/customers.csv --name retail --output ./schema.json

# schema — a JSON Schema document on disk
seed-data plan ./contracts/order.schema.json --name orders --output ./schema.json

# schema — SQL DDL (.sql, .ddl)
seed-data plan ./db/schema.sql --name warehouse --output ./schema.json

# erd — an ERD diagram (.dbml, .puml, .plantuml, .mmd, .mermaid)
seed-data plan ./design/model.dbml --name warehouse --output ./schema.json

# document — real PDF/PNG/JPEG, read with a vision model
seed-data plan ./samples/invoice.pdf --name invoice --output ./schema.json

# document — the same, from S3 (an object URI or a prefix)
seed-data plan s3://my-bucket/invoices/ --name invoice --output ./schema.json
```

Inputs of different kinds combine in one call, and their entities are merged into
one schema — useful when prose describes intent, a CSV pins down realistic values,
and DDL fixes the column types:

```bash
seed-data plan \
  "Subscription billing for a B2B SaaS company, monthly and annual plans" \
  ./samples/invoices.csv \
  ./db/billing.sql \
  --name billing --output ./schemas/billing.json
```

What lands on disk is an `InferredSchema` — a list of entities, each with typed
fields. Field-level constraints such as `unique`, `pattern`, value bounds, and a
statistical `distribution` are what make the structured pipeline produce plausible
values rather than filler. Note that `required` (must the key be present?) and
`nullable` (may the value be null?) are independent; `required: null` means "infer
it from `nullable`". An excerpt:

```json
{
  "entities": [
    {
      "entity_name": "Customer",
      "description": "A retail customer account",
      "fields": [
        {
          "name": "customer_id",
          "type": "string",
          "description": "Unique customer identifier",
          "nullable": false,
          "required": true,
          "unique": true,
          "pattern": "^CUST-[0-9]{6}$",
          "distribution": null,
          "children": null
        },
        {
          "name": "lifetime_value",
          "type": "float",
          "description": "Total spend to date, in USD",
          "nullable": true,
          "required": null,
          "unique": false,
          "min_value": 0.0,
          "distribution": {
            "type": "log_normal",
            "params": { "mean": 6.1, "std": 0.9 }
          }
        }
      ],
      "relationships": [],
      "structured_relationships": [],
      "generation_guidance": "US retail customers, mixed urban and rural addresses.",
      "reference_samples": []
    },
    {
      "entity_name": "Order",
      "description": "A single customer order",
      "fields": [
        {
          "name": "customer_id",
          "type": "string",
          "description": "Owning customer",
          "nullable": false,
          "required": true
        },
        {
          "name": "order_total",
          "type": "float",
          "description": "Order total in USD",
          "nullable": false,
          "required": true,
          "min_value": 0.0,
          "max_value": 25000.0
        }
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
      ],
      "generation_guidance": "",
      "reference_samples": []
    }
  ]
}
```

The file is plain JSON and meant to be reviewed and edited before you generate from
it. Feed it to `generate-structured` or `generate-documents`.

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `inputs` | required | One or more free-text description(s), file paths/globs, and/or `s3://` URIs |
| `--name` | `dataset` | Logical dataset name |
| `--output` | `./schema.json` | Path to write the `InferredSchema` JSON |
| `--quiet` | off | Suppress progress output |

## Single document

The base command generates one PDF and its paired ground-truth JSON label:

```bash
seed-data --schema-dir invoice --scenario "Midwest food-distributor invoice"
```

Select models, lower the critic threshold for faster iteration, enable
augmentation, or point at a custom schema directory:

```bash
# Select models and use a lower acceptance threshold
seed-data --schema-dir fcc-invoice \
  --data-model gpt-oss --doc-model gpt-oss --critic-model haiku --threshold 3

# Apply scanning and aging artifacts, choose a renderer, and set the output directory
seed-data --schema-dir w2 --augment --renderer weasyprint --output ./out

# Generate from a custom schema directory
seed-data --schema-dir ./my-schemas/purchase-order --scenario "Office supplies, net-30"
```

Each run executes the full single-document pipeline — data generation, schema
validation, PDF rendering, and visual critique — and writes three paired artifacts:

```text
output/
├── data/<id>.json                 # ground-truth JSON label
├── generation_scripts/<id>.html   # the HTML used to render the document
└── pdfs/<id>.pdf                  # the final document
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--schema-dir` | required | Bundled schema name, or a directory containing `schema.json` |
| `--scenario` | | Free-text describing what to generate this run |
| `--data-model` | `gpt-oss` | Model for data generation |
| `--doc-model` | `gpt-oss` | Model for PDF generation |
| `--critic-model` | `sonnet` | Model for critics |
| `--aug-model` | `gpt-oss` | Model for augmentation decisions |
| `--renderer` | `xhtml2pdf` | `xhtml2pdf` (pure Python), `weasyprint`, or `reportlab` |
| `--augment` | off | Apply augraphy image augmentation |
| `--no-critic-samples` | off | Disable reference sample PDFs in the document critic |
| `--threshold` | `5` | Critic acceptance score, 1–10 |
| `--max-attempts` | `5` | Maximum critic-retry cycles |
| `--timeout` | `3600` | Safety timeout in seconds |
| `--output` | `./output` | Output root directory |

## Batch

Setting `--count` greater than 1 enables batch mode. A single high-level brief is
expanded into N distinct scenarios, and each scenario is generated concurrently:

```bash
seed-data --schema-dir fcc-invoice \
  --count 10 \
  --scenario "CPG brands on local TV stations in the American southwest" \
  --threshold 4 --augment
```

Add a determinism seed for regression-stable sets, or select a different renderer
and output directory:

```bash
# A larger set with a specific brief, selected models, and a fixed seed
seed-data --schema-dir invoice --count 20 \
  --scenario "Regional food-distributor invoices across the US midwest" \
  --data-model gpt-oss --doc-model gpt-oss --critic-model haiku \
  --seed 42

# A different renderer, written to a custom output directory
seed-data --schema-dir w2 --count 8 --renderer weasyprint --output ./eval-set
```

Diversity depends on the brief. A specific brief produces substantially more varied
output than a generic one:

```bash
# Generic — produces similar documents
--scenario "Generate diverse FCC invoices"

# Specific — produces genuinely varied documents
--scenario "FCC broadcast invoices for packaged-food companies advertising in the midwest"
--scenario "Local car-dealership TV ads across small-market stations in the southeast"
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--schema-dir` | required | Bundled schema name, or a directory containing `schema.json` |
| `--count` | `1` | Number of documents; a value greater than 1 enables batch mode |
| `--scenario` | | The high-level theme the planner diversifies into `--count` documents |
| `--data-model` | `gpt-oss` | Model for data generation |
| `--doc-model` | `gpt-oss` | Model for PDF generation |
| `--critic-model` | `sonnet` | Model for critics |
| `--batch-model` | `nova2-lite` | Model for scenario planning |
| `--aug-model` | `gpt-oss` | Model for augmentation decisions |
| `--renderer` | `xhtml2pdf` | `xhtml2pdf` (pure Python), `weasyprint`, or `reportlab` |
| `--augment` | off | Apply augraphy image augmentation |
| `--threshold` | `5` | Critic acceptance score, 1–10 |
| `--seed` | | Seed for scenario planning, for regression-stable sets |
| `--max-attempts` | `5` | Maximum critic-retry cycles per document |
| `--timeout` | `3600` | Per-document safety timeout in seconds |
| `--output` | `./output` | Output root directory |

## Packet

The `packet` subcommand generates a coordinated set of related document types that
share context — the same person, address, and dates — and merges them into a single
multi-page PDF. It accepts a bundled packet name or a path to a packet directory:

```bash
seed-data packet lending-package \
  --scenario "First-time homebuyer in Portland, OR, 30-year fixed mortgage" \
  --doc-model gpt-oss --critic-model haiku --threshold 3
```

Generate multiple packets, increase the number of parallel sub-documents, or use a
custom packet directory:

```bash
# Multiple packets with more parallel sub-documents each
seed-data packet insurance-claim-packet --count 3 --doc-workers 4 \
  --scenario "Water-damage claims from burst pipes in suburban Portland homes"

# A custom packet directory, with augmentation
seed-data packet ./my-packets/onboarding --augment --output ./eval-set
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `packet` | required | Bundled packet name, or a path to a packet directory |
| `--count` | `1` | Number of packets to generate |
| `--scenario` | | Scenario shared across the packet's documents |
| `--doc-workers` | `3` | Parallel sub-documents within each packet |
| `--shuffle` | off | Randomize sub-document order in the merged PDF |
| `--data-model` | `gpt-oss` | Model for data generation |
| `--doc-model` | `gpt-oss` | Model for PDF generation |
| `--critic-model` | `sonnet` | Model for critics |
| `--context-model` | `nova2-lite` | Model for shared-context resolution |
| `--aug-model` | `gpt-oss` | Model for augmentation decisions |
| `--renderer` | `xhtml2pdf` | PDF backend |
| `--augment` | off | Apply image augmentation to each sub-document |
| `--threshold` | `5` | Critic acceptance score, 1–10 |
| `--output` | `./output` | Output root directory |

## Documents from a planned schema

The `generate-documents` subcommand runs the same document pipeline as the modes
above, but takes its schema as a positional argument instead of `--schema-dir`. It
accepts an `InferredSchema` JSON file (such as one written by `seed-data plan`), a
schema directory, or a bundled schema name:

```bash
# from a planned schema
seed-data plan ./samples/invoice.pdf --name invoice --output ./schemas/invoice.json
seed-data generate-documents ./schemas/invoice.json --scenario "Net-30 terms, Ohio supplier"

# from a bundled name or a schema directory — same as the default mode
seed-data generate-documents invoice --count 5 --scenario "Regional US food distributors"
seed-data generate-documents ./my-schemas/purchase-order --output ./out
```

A document type is a single entity, so a multi-entity `InferredSchema` needs one
selected with `--entity`. Without it the first entity is used, which is the primary
entity by convention:

```bash
seed-data generate-documents ./schemas/billing.json --entity Invoice \
  --count 10 --scenario "B2B SaaS annual renewals"
```

This is the modern spelling of the default mode, and what lets a planned or
inferred `InferredSchema` drive document generation. The pre-existing default mode
is unchanged and remains the documented path for schema directories and bundled
names — `seed-data --schema-dir invoice` keeps working exactly as before. The two
spellings share the same pipeline, the same model and critic flags, and the same
output layout; `--entity` is the only flag `generate-documents` adds, since a schema
directory always describes exactly one document type.

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `schema` | required | `InferredSchema` JSON path, schema directory, or bundled schema name |
| `--entity` | | For a multi-entity `InferredSchema`: which entity to render |
| `--count` | `1` | Number of docs; a value greater than 1 plans diverse scenarios and fans out |
| `--scenario` | | Free-text describing what to generate this run |
| `--output` | `./output` | Output root directory |
| `--data-model` | `gpt-oss` | Model for data generation |
| `--doc-model` | `gpt-oss` | Model for PDF generation |
| `--critic-model` | `sonnet` | Model for critics |
| `--batch-model` | `nova2-lite` | Model for scenario planning |
| `--aug-model` | `gpt-oss` | Model for augmentation decisions |
| `--renderer` | `xhtml2pdf` | `xhtml2pdf` (pure Python), `weasyprint`, or `reportlab` |
| `--augment` | off | Apply augraphy image augmentation |
| `--no-critic-samples` | off | Disable reference sample PDFs in the document critic |
| `--threshold` | `5` | Critic acceptance score, 1–10 |
| `--max-attempts` | `5` | Maximum critic-retry cycles |
| `--timeout` | `3600` | Safety timeout in seconds |
| `--seed` | | Seed for scenario planning, for regression-stable sets |
| `--quiet` | off | Suppress progress output |

## Structured data

The `generate-structured` subcommand is the other output modality: it produces
tabular records instead of documents. It takes the same kinds of schema argument —
a bundled schema name, an `InferredSchema` JSON path, or a schema directory — and
needs the `[structured]` extra installed:

```bash
# from a bundled schema name
seed-data generate-structured invoice --rows 500 --output ./data

# from a planned schema
seed-data plan ./db/billing.sql --name billing --output ./schemas/billing.json
seed-data generate-structured ./schemas/billing.json --rows 1000 --format parquet

# from a schema directory
seed-data generate-structured ./my-schemas/purchase-order --rows 250
```

All four `--format` values write one file per entity:

```bash
seed-data generate-structured ./schemas/retail.json --format csv     # .csv
seed-data generate-structured ./schemas/retail.json --format json    # .json
seed-data generate-structured ./schemas/retail.json --format excel   # .xlsx
seed-data generate-structured ./schemas/retail.json --format parquet # .parquet
```

Each output file is named from its entity name, lowercased with spaces replaced by
underscores. A schema with entities `Customer` and `Order` at `--format csv`
produces:

```text
output/
├── customer.csv
└── order.csv
```

`--format parquet` needs no extra install beyond `[structured]`, which ships
pyarrow.

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `schema` | required | Bundled schema name, path to an `InferredSchema` JSON, or a schema directory |
| `--rows` | `100` | Target records per entity |
| `--format` | `csv` | `csv`, `parquet`, `excel`, or `json` |
| `--output` | `./output` | Output directory |
| `--quiet` | off | Suppress progress output |

## Infer a schema from documents

The `infer-schema` subcommand reverse-engineers a schema from real example
documents (the inverse of generation). Inputs may be PDF/PNG/JPEG, local or
`s3://`. It writes a schema directory for review, then you generate from it.

```bash
# same-type: example document(s) of one type -> a schema directory
seed-data infer-schema ./samples/invoice.pdf --name invoice --output ./schemas/invoice

# one-shot: infer, then generate (single, or batch with --count >1)
seed-data infer-schema ./samples/invoice.pdf --name invoice --output ./schemas/invoice \
  --then-generate --count 5 --scenario "Regional US food distributors"

# packet: ONE concatenated multi-document PDF -> packet.json + a schema per segment
seed-data infer-schema ./real/lending_package.pdf \
  --packet --name lending-package --output ./packets/lending-package
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `inputs` | required | Document path(s)/glob(s)/dir(s) and/or `s3://` URI(s) — PDF/PNG/JPEG |
| `--name` | required | Document-type name (or packet name with `--packet`) |
| `--output` | required | Schema directory to write (or packet directory with `--packet`) |
| `--infer-model` | `sonnet` | Vision-capable model for inference |
| `--max-docs` | `5` | Max example documents to feed the model |
| `--packet` | off | Treat the input as one concatenated multi-document PDF; split it |
| `--boundaries` | | With `--packet`: fixed page ranges, e.g. `1-3,4,5-8` (overrides detection) |
| `--allow-questions` | off | Let the model ask clarifying questions during inference (interactive terminals only) |
| `--then-generate` | off | After inferring, generate from the schema (not supported with `--packet`) |
| `--count` | `1` | With `--then-generate`: `>1` produces a batch |
| `--scenario` | | With `--then-generate`: scenario / diversity brief |

With `--allow-questions`, the model may ask you to clarify details it can't
determine from the document alone (whether a field is always present, a value
range, an ID format), and your answers shape the inferred schema:

```bash
seed-data infer-schema ./samples/invoice.pdf --name invoice \
  --output ./schemas/invoice --allow-questions
```

It only prompts on an interactive terminal — in a non-interactive shell
(CI, pipe, background job) the flag is safely ignored so nothing hangs.

See [Schema from Documents](../Guides/schema-from-documents.md) for the full guide.

## End-to-end run

The `plan-and-generate` subcommand composes the two halves: it plans its inputs into a schema,
then generates from that schema — no intermediate schema file needed. It accepts the
same inputs as `plan`, and `--output` picks which modality to produce:

```bash
# structured (the default modality)
seed-data plan-and-generate "Retail customers and their orders in the US midwest" \
  --rows 500 --format csv --output-dir ./data

# documents
seed-data plan-and-generate ./samples/invoice.pdf --output documents \
  --count 5 --scenario "Regional US food distributors" --output-dir ./eval-set
```

On `plan-and-generate`, and only on `plan-and-generate`, `--output` names the modality (`structured` or
`documents`) and `--output-dir` names the path. On every other command — the
default mode, `generate-structured`, `generate-documents`, `packet`, `infer-schema` —
`--output` is a path. Getting this backwards is the easiest mistake to make here:

```bash
# WRONG on run: ./data is not a modality, argparse rejects it
seed-data plan-and-generate "..." --output ./data

# RIGHT: modality on --output, path on --output-dir
seed-data plan-and-generate "..." --output structured --output-dir ./data
```

Because `plan-and-generate` discards the schema by default, `--save-schema` writes it out as well.
It is written after planning and before generation, so you keep the schema even if
generation fails:

```bash
seed-data plan-and-generate ./db/billing.sql "Monthly and annual B2B SaaS plans" \
  --name billing --save-schema ./schemas/billing.json \
  --rows 1000 --format parquet --output-dir ./data
```

Flags are per-modality: `--rows` and `--format` apply only to `structured`, and
`--count`, `--scenario`, `--entity`, and `--augment` apply only to `documents`.
`--seed` applies to both, but note it cannot pin the schema: planning is an LLM
step, so a seeded re-run reproduces the *values* drawn for a given schema, not the
schema itself. For a retry budget, or to reuse one reviewed schema across runs, use
`plan` and the generate subcommand separately.

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `inputs` | required | One or more free-text description(s), file paths/globs, and/or `s3://` URIs |
| `--output` | `structured` | Which modality to generate: `structured` or `documents` |
| `--output-dir` | `./output` | Directory to write artifacts to |
| `--name` | `dataset` | Logical dataset name |
| `--save-schema` | | Also write the planned `InferredSchema` JSON to this path |
| `--rows` | `100` | structured only: target records per entity |
| `--format` | `csv` | structured only: `csv`, `parquet`, `excel`, or `json` |
| `--count` | `1` | documents only: how many to generate |
| `--scenario` | | documents only: what to generate this run |
| `--entity` | | documents only: which entity of a multi-entity schema to render |
| `--augment` | off | documents only: apply augraphy image augmentation |
| `--data-model` | `gpt-oss` | Model for data generation |
| `--doc-model` | `gpt-oss` | Model for PDF generation |
| `--critic-model` | `sonnet` | Model for critics |
| `--batch-model` | `nova2-lite` | Model for scenario planning |
| `--aug-model` | `gpt-oss` | Model for augmentation decisions |
| `--renderer` | `xhtml2pdf` | `xhtml2pdf` (pure Python), `weasyprint`, or `reportlab` |
| `--threshold` | `5` | Critic acceptance score, 1–10 |
| `--timeout` | `3600` | Safety timeout in seconds |
| `--quiet` | off | Suppress progress output |

## Utility commands

Copy the bundled schema library into a writable directory for local editing:

```bash
seed-data clone-schema-library ./schemas
```

For a complete list of options, run `seed-data --help` or `--help` on any subcommand:
`plan`, `generate-structured`, `generate-documents`, `plan-and-generate`, `infer-schema`,
`packet`, `clone-schema-library`.

## See also

- [Python API Usage](../Python-API-Usage/README.md) — the same capabilities from Python.
- [Plan](../Guides/plan.md) — the shared front door in depth: every input kind and how they merge.
- [Structured Data](../Guides/structured-data.md) — the structured modality end to end.
- [Schema from Documents](../Guides/schema-from-documents.md) — infer schemas from real documents.
- [Creating a Document Type](../Guides/creating-a-document-type.md) — authoring a schema.
- [Models](../Advanced/models.md) — selecting models per stage.

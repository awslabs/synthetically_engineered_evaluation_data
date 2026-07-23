---
title: CLI Usage
---

# CLI Usage

The `seed-data` command generates synthetic evaluation documents from the command
line. It operates in three modes: a single document, a diverse batch, or a
coordinated multi-document packet. This page documents each mode with examples and
a complete flag reference.

## Installation and setup

Install the package and configure Amazon Bedrock credentials:

```bash
pip install seed-data
export AWS_PROFILE=your-profile-name
export AWS_REGION=us-east-1
```

The default renderer, xhtml2pdf, is pure Python and requires no additional system
libraries.

To edit document types locally, copy the bundled schema library into a writable
directory:

```bash
seed-data clone-schema-library ./schemas
```

Every mode accepts either a bundled schema name (such as `invoice`) or a path to a
schema directory. The examples below use bundled names, but any path to a directory
containing a `schema.json` is equally valid.

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

## Utility commands

Copy the bundled schema library into a writable directory for local editing:

```bash
seed-data clone-schema-library ./schemas
```

For a complete list of options, run `seed-data --help`, `seed-data packet --help`,
and `seed-data infer-schema --help`.

## See also

- [Python API Usage](../Python-API-Usage/README.md) — the same capabilities from Python.
- [Schema from Documents](../Guides/schema-from-documents.md) — infer schemas from real documents.
- [Creating a Document Type](../Guides/creating-a-document-type.md) — authoring a schema.
- [Models](../Advanced/models.md) — selecting models per stage.

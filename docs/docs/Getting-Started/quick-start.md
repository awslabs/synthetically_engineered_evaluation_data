---
title: Quick Start
---

# Quick Start

From zero to your first generated document.

## 1. Install

```bash
pip install seed-data
```

The default renderer (**xhtml2pdf**) is pure Python — there are no system libraries
to install. For the richer-CSS WeasyPrint renderer, see [Renderers](../Advanced/renderers.md).

## 2. Configure AWS Bedrock

seed-data generates content with Amazon Bedrock models, so you need AWS credentials
with Bedrock access.

```bash
export AWS_PROFILE=your-profile-name
export AWS_REGION=us-east-1
```

## 3. Get the schemas

A **schema** defines a document type — its fields, data rules, and visual style.
The built-in library ships inside the package; copy it into a local, editable folder:

```bash
seed-data clone-schema-library ./schemas
```

Browse the library on GitHub before you start:
👉 [awslabs/…/schemas](https://github.com/awslabs/synthetically_engineered_evaluation_data/tree/main/src/seed_data/schemas)

Built-in types include `invoice`, `fcc-invoice`, `bank-statement`, `w2`, `pay-stub`,
`credit-report`, `loan-application`, `police-report`, and more.

## 4. Generate a document

```bash
seed-data --schema-dir ./schemas/invoice --output ./output
```

This runs the full single-document pipeline — data generation, data validation,
PDF rendering, and visual critique. Output lands in `./output/`:

```
output/
├── pdfs/                 # the generated PDF
├── data/                 # ground-truth JSON, paired with the PDF (for IDP/KIE eval)
└── generation_scripts/   # the HTML used to render the PDF
```

## 5. Customize

```bash
# Several documents
seed-data --schema-dir ./schemas/invoice --count 5

# Steer the content with a brief
seed-data --schema-dir ./schemas/invoice \
  --extra "Invoices for midwest food distributors, 20-40 line items"

# Add scanning/faxing artifacts for realism
seed-data --schema-dir ./schemas/invoice --augment

# Pick models and renderer
seed-data --schema-dir ./schemas/invoice --doc-model sonnet --renderer weasyprint
```

Run `seed-data --help` to see every option.

## Edit or create a schema

Because you cloned the library locally, editing a document type is just editing files:

```
schemas/invoice/
├── schema.json              # fields and types
└── generation_guidance.md   # data-realism rules and visual style
```

Point `--schema-dir` at any folder with that structure — your own custom types work
exactly the same way.

## Next steps

- [Create a Document Type](../Guides/creating-a-document-type.md): define your own schema and steering docs.
- [Batch Generation](../Guides/batch-generation.md): control diversity, workers, and output.
- [Packets](../Guides/packets.md): generate coordinated multi-document sets.

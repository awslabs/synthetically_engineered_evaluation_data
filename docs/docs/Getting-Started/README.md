---
title: Getting Started
---

# Getting Started

## What is Synthetically Engineered Evaluation Data?

You are building or benchmarking a document understanding system: it reads scanned invoices, forms, or statements and produces structured JSON. To measure it, you need paired data, an input document plus the exact ground truth it should extract. Real documents are slow to collect and carry PII and redistribution constraints.

Synthetically Engineered Evaluation Data (SEED) generates that pair for you. You describe a document type with a JSON schema, and the pipeline invents realistic fictional data, renders it to a PDF, critiques the render for quality, and saves the source data JSON as the ground-truth labels. Optionally, it applies image augmentation to simulate real-world scanning and faxing artifacts.

## The Pipeline at a Glance

A single document runs through a chain of agents:

```
data_generator → data_critic → doc_generator → doc_critic → [augmentor → aug_critic]
```

- **Data generation** produces JSON data from the schema.
- **Data critique** validates the data against the schema and domain rules.
- **Document generation** writes HTML/CSS and renders a PDF via WeasyPrint (or Python via ReportLab).
- **Document critique** uses a vision model to evaluate layout, typography, truncation, and math.
- **Augmentation** (optional, with `--augment`) applies aging effects and checks legibility.

Critic stages can reject output and send the pipeline back for another attempt, bounded by `--max-attempts`.

## Next Steps

- [Installation](installation.md): install SEED and its dependencies, and configure AWS Bedrock credentials.
- [Quick Start](quick-start.md): generate your first single document and your first batch.
- [Guides](../Guides/README.md): create a new document type, run batches, and build multi-document packets.

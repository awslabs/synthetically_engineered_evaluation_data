---
title: Single Document
---

# Single Document

Generate one document — a rendered PDF plus its paired ground-truth JSON label —
from a schema. This is the core capability that batch and packet generation build
on.

## Pipeline

```
data_generator → data_critic → [doc_generator → doc_critic loop] → (augment) → done
```

The data generator invents schema-conforming JSON; a critic validates it
(deterministic JSON-Schema check + LLM domain review); the doc generator renders
a PDF and a vision critic reviews it, looping until it passes the threshold.

## Three ways to specify the schema

A single-document run accepts a schema as a **bundled name**, a **directory
path**, or an **in-code `Schema`** (a pydantic model or a JSON-Schema dict plus
generation guidance). All three behave identically through the pipeline.

## Output Structure

```
output/
├── pdfs/<doc_id>.pdf                   # rendered PDF
├── data/<doc_id>.json                  # ground-truth JSON label
├── generation_scripts/<doc_id>.html    # HTML used to render
└── augmented/<doc_id>_augmented.pdf    # when augment is enabled
```

## Usage

- **[CLI Usage → Single Document](../CLI-Usage/README.md#single-document)**: the `seed-data` command and its flags.
- **[Python API Usage → Single Document](../Python-API-Usage/README.md#single-document)**: `Generator.generate(...)` and the `GeneratedDoc` result.

## Related

- [Creating a Document Type](creating-a-document-type.md): author the schema.
- [Batch Generation](batch-generation.md): many diverse documents from one brief.
- [Packets](packets.md): coordinated multi-document sets.

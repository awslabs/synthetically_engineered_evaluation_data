---
title: Guides
---

# Guides

Task-focused guides for working with SEED once it is installed.

## Sections

- [Ingest](ingest.md): turn free text, example data, a formal schema, real documents, or an ERD into one canonical `InferredSchema` that drives either output modality.
- [Structured Data](structured-data.md): generate tabular and relational data as CSV, Parquet, Excel, or JSON from a schema, and evaluate it.
- [Creating a Document Type](creating-a-document-type.md): define a new document type with a JSON schema and optional steering docs, then generate your first document from it.
- [Schema from Documents](schema-from-documents.md): reverse-engineer a schema from real example documents, or split a concatenated packet into one schema per document type.
- [Single Document](single-document.md): generate one document — a rendered PDF plus its paired ground-truth JSON label.
- [Batch Generation](batch-generation.md): run the pipeline many times in parallel from a single diversity brief.
- [Packets](packets.md): generate coordinated sets of inter-related documents that share context and merge into a single multi-document PDF.
- [Generation Choices](generation-choices.md): control per-document variation with `x-probability` optional fields and table presentation variations.

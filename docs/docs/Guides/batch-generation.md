---
title: Batch Generation
---

# Batch Generation

For evaluation data you want volume and diversity. A batch turns one high-level
**brief** into N distinct scenarios, then generates a document for each — every
one paired with its ground-truth JSON label.

## How a Batch Works

1. **Scenario planning** — a planner model reads your brief plus the schema's
   `generation_guidance.md` and produces N distinct, specific scenarios.
2. **Concurrent fan-out** — each scenario runs its own self-contained pipeline
   graph as a sibling node; Strands executes them concurrently.
3. **Output** — clean PDFs, data JSON, and optional augmented versions, each
   returned as a typed `GeneratedDoc`.

The planner varies entities, industries, regions, time periods, counts, and
amounts so the set is genuinely diverse. **A specific brief produces far more
varied output than a generic one.**

## What to Expect

- A single document takes roughly 30 to 100 seconds end-to-end.
- All workers launch concurrently; the Python Strands graph has **no built-in
  concurrency cap**, so large counts may hit Bedrock rate limits (adaptive retries
  absorb this, but wall-clock grows). Start with modest counts.
- Partial failures are normal. Failed documents come back with
  `success=False` and `verdict="error"`; the rest still complete.
- Use a **specific** brief. Vague briefs produce same-y output.

## Output Structure

```
output/
├── pdfs/                    # clean PDFs
├── data/                    # ground-truth JSON per document
└── generation_scripts/      # HTML files used to render the PDFs
```

## Usage

- **[CLI Usage → Batch](../CLI-Usage/README.md#batch)**: `--count > 1`, the diversity brief, and batch flags.
- **[Python API Usage → Batch](../Python-API-Usage/README.md#batch)**: `Generator.generate_batch(...)`, `on_document` progress, `seed`, and the `BatchResult`.

## Related

- [Creating a Document Type](creating-a-document-type.md): define the schema you batch over.
- [Packets](packets.md): coordinated multi-document sets.
- [Models](../Advanced/models.md): choose models per stage.

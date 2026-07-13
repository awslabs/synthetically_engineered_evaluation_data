---
title: Quick Start
---

# Quick Start

This page gets you from an installed environment to your first generated documents. It assumes you have completed [Installation](installation.md), including AWS Bedrock credentials.

The repository ships with example schemas under `src/doc_gen_agent/schemas/`. The examples below use `fcc-invoice`.

## Configure Your Environment

```bash
export AWS_PROFILE=your-profile-name
export BYPASS_TOOL_CONSENT=true
```

## Generate a Single Document

```bash
BYPASS_TOOL_CONSENT=true python -m doc_gen_agent \
  --schema-dir src/doc_gen_agent/schemas/fcc-invoice \
  --extra "Local TV station in Portland, Oregon"
```

This runs the full single-document pipeline: data generation, data validation, PDF rendering, and visual critique. Each stage prints its output to the terminal, and the final PDF lands under `output/`.

## Generate a Single Document with Augmentation

Add `--augment` to simulate scanning and faxing artifacts. This adds two more stages: an augmentor picks degradation effects, then an aug critic checks the result is still legible.

```bash
BYPASS_TOOL_CONSENT=true python -m doc_gen_agent \
  --schema-dir src/doc_gen_agent/schemas/fcc-invoice \
  --extra "Local TV station in Portland, Oregon" \
  --augment
```

## Generate a Batch

For evaluation data, you want volume and diversity. The batch script runs the pipeline N times in parallel, each with a unique scenario generated from your `--extra` brief.

```bash
BYPASS_TOOL_CONSENT=true python scripts/batch_generate.py \
  --schema-dir src/doc_gen_agent/schemas/fcc-invoice \
  --count 10 --workers 3 \
  --extra "CPG brands on local TV stations in the American southwest" \
  --augment \
  --batch-name southwest_cpg
```

### What to Expect

- A single document takes roughly 60 to 100 seconds end-to-end.
- With `--count 10 --workers 3`, expect about 5 to 7 minutes wall-clock.
- Do not push `--workers` above 4 or 5, or you will hit Bedrock rate limits.
- Partial failures are normal. If one document fails, the others still complete, and the manifest records which succeeded.
- Use a specific `--extra` brief. Vague briefs produce same-y output.

## Output Structure

A batch writes to `output/<batch-name>/`:

```
output/southwest_cpg/
├── pdfs/                    # Clean PDFs
├── data/                    # Source data JSON per document (ground truth)
├── generation_scripts/      # HTML files used to render PDFs
├── augmented/               # Augmented PDFs (when --augment)
├── config/                  # Copy of schema + guidance for reproducibility
│   └── batch_manifest.json  # Full run metadata, scenarios, timing
```

## Command Reference

```bash
# Single doc, defaults
python -m doc_gen_agent --schema-dir src/doc_gen_agent/schemas/fcc-invoice --extra "context"

# Batch of 20 with augmentation
python scripts/batch_generate.py --schema-dir src/doc_gen_agent/schemas/fcc-invoice \
  --extra "brief for diversity" --count 20 --workers 3 \
  --batch-name my-batch --augment

# See all options
python -m doc_gen_agent --help
python scripts/batch_generate.py --help
python scripts/packet_generate.py --help
```

## Next Steps

- [Create a Document Type](../Guides/creating-a-document-type.md): define your own schema and steering docs.
- [Batch Generation](../Guides/batch-generation.md): control diversity, workers, and output.
- [Packets](../Guides/packets.md): generate coordinated multi-document sets.

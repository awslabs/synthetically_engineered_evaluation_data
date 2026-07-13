---
title: Batch Generation
---

# Batch Generation

For evaluation data you want volume and diversity. The batch script (`scripts/batch_generate.py`) runs the single-document pipeline N times in parallel, each with a unique scenario.

```bash
BYPASS_TOOL_CONSENT=true python scripts/batch_generate.py \
  --schema-dir src/doc_gen_agent/schemas/fcc-invoice \
  --count 10 --workers 3 \
  --extra "CPG brands on local TV stations in the American southwest" \
  --augment \
  --batch-name southwest_cpg
```

## How a Batch Works

1. **Scenario Generation**: an LLM reads your `--extra` brief plus the schema's `generation_guidance.md` and produces N unique, diverse scenario descriptions.
2. **Parallel Execution**: each scenario runs through the full single-document pipeline in parallel via a `ThreadPoolExecutor`, controlled by `--workers`.
3. **Output**: clean PDFs, data JSON, augmented versions, and a batch manifest.

The scenario generator reads the schema's guidance to understand the document type, then creates scenarios that vary advertisers, agencies, stations, regions, time periods, line item counts, and amounts.

## The `--extra` Brief Is the Key to Diversity

`--extra` accepts a high-level brief that the scenario generator uses to create varied documents. A specific brief produces much more diverse output than a generic one:

```bash
# Generic, less diverse
--extra "Generate diverse FCC invoices"

# Specific, much more diverse
--extra "FCC broadcast invoices for packaged food companies advertising in the midwest"
--extra "Local car dealership TV ads across small-market stations in the southeast"
--extra "Political campaign advertising during election season on major metro stations"
```

## CLI Options

Common flags (shared with `python -m doc_gen_agent` and the packet script):

| Flag | Default | Description |
|------|---------|-------------|
| `--schema-dir` | required | Directory with `schema.json` and optional `*.md` steering docs |
| `--output` | `./output` | Output root directory |
| `--extra` | | Diversity brief describing the theme/scenario for generation |
| `--data-model` | `nova2-lite` | Model for data generation |
| `--doc-model` | `gpt-oss` | Model for PDF generation |
| `--critic-model` | `sonnet` | Model for all critics |
| `--aug-model` | `gpt-oss` | Model for augmentation decisions |
| `--renderer` | `weasyprint` | PDF engine: `weasyprint` (HTML/CSS) or `reportlab` (Python) |
| `--augment` | off | Enable augraphy image augmentation |
| `--preview` | off | Enable visual self-inspection (requires a VL model for the doc model) |
| `--threshold` | `7` | Acceptance score 1-10 (7 recommended, 8 requires edit cycles) |
| `--max-attempts` | `5` | Max feedback cycles per loop |
| `--timeout` | `3600` | Safety timeout in seconds |

Batch-only flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--count` | `5` | Number of documents to generate |
| `--workers` | `3` | Max parallel workers (do not exceed 4-5 to avoid Bedrock rate limits) |
| `--batch-name` | timestamp | Name for the batch output directory |

## What to Expect

- A single document takes roughly 60 to 100 seconds end-to-end.
- With `--count 10 --workers 3`, expect about 5 to 7 minutes wall-clock.
- Do not push `--workers` above 4 or 5, or you will hit Bedrock rate limits.
- Partial failures are normal. If one document fails, the others still complete, and the manifest records which succeeded.
- Use a specific `--extra` brief. Vague briefs produce same-y output.

## Output Structure

```
output/<batch-name>/
├── pdfs/                    # Clean PDFs
├── data/                    # Source data JSON per document (ground truth)
├── generation_scripts/      # HTML files used to render PDFs
├── augmented/               # Augmented PDFs (when --augment)
├── config/                  # Copy of schema + guidance for reproducibility
│   └── batch_manifest.json  # Full run metadata, scenarios, timing
```

The `batch_manifest.json` records the CLI command, git hash, model configuration, scenarios, and per-document results, which makes each run reproducible and lets you see which documents succeeded.

## Related

- [Creating a Document Type](creating-a-document-type.md): define the schema you batch over.
- [Generation Choices](generation-choices.md): add per-document variation on top of scenario diversity.
- [Models](../Advanced/models.md): choose models per stage.

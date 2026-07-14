---
title: Packets
---

# Packets

Generate coordinated sets of inter-related documents, like a loan application containing a credit report, pay stubs, and a statement of intent, all sharing consistent context (same applicant, same address, same dates).

The output is a ready-to-use evaluation dataset for document splitting and classification models.

## Quick Start

```bash
BYPASS_TOOL_CONSENT=true python scripts/packet_generate.py \
  --packet src/seed_data/packets/insurance-claim-packet \
  --count 3 --workers 2 \
  --data-model gpt-oss --doc-model gpt-oss --critic-model haiku \
  --extra "Water damage claims from burst pipes in suburban Portland homes"
```

## How It Works

```
1. Load packet config     → Which document types, how many of each
2. Resolve shared context → LLM generates consistent names/addresses/dates
3. Generate sub-documents → Each doc runs through the full pipeline (data → critic → PDF → critic)
4. Merge into packet PDF  → Individual PDFs concatenated, page indices tracked
5. Emit labels            → result.json per section with class, pages, and extracted fields
```

Each sub-document uses the existing single-document pipeline. The packet layer only adds coordination: shared context injection, PDF merging, and label emission.

## Output Structure

The output has two distinct parts: the **evaluation dataset** (what downstream models consume) and the **generation artifacts** (intermediate files for debugging and reproducibility).

```
output/packet_insurance-claim-packet_20260417/
│
│   ┌─────────────────────────────────────────────────────┐
│   │  EVALUATION DATASET                                 │
│   │  This is what you feed to your splitting/           │
│   │  classification model for evaluation.               │
│   └─────────────────────────────────────────────────────┘
│
├── classes.yaml                         # All document types in this packet
│
├── input/                               # Merged multi-document PDFs
│   ├── packet_001.pdf                   #   6 pages: claim + 2 bank stmts + 3 invoices
│   └── packet_002.pdf                   #   4 pages: claim + 1 bank stmt + 2 invoices
│
├── baseline/                            # Ground-truth labels per section
│   ├── packet_001.pdf/
│   │   └── sections/
│   │       ├── 1/result.json            #   { document_class, page_indices, inference_result }
│   │       ├── 2/result.json
│   │       └── ...
│   └── packet_002.pdf/
│       └── sections/
│           └── ...
│
│   ┌─────────────────────────────────────────────────────┐
│   │  GENERATION ARTIFACTS                               │
│   │  Intermediate files: individual PDFs, data JSONs,   │
│   │  HTML scripts, shared context. Useful for debugging │
│   │  and reproducibility.                               │
│   └─────────────────────────────────────────────────────┘
│
├── artifacts/                           # Per-packet generation files
│   ├── packet_001/
│   │   ├── shared_context.json          #   { "claimant_name": "Jane Doe", ... }
│   │   ├── insurance-claim/
│   │   │   ├── pdfs/UUID.pdf            #   Individual sub-document PDF
│   │   │   ├── data/UUID.json           #   Generated data (= inference_result)
│   │   │   └── generation_scripts/UUID.html
│   │   ├── bank-statement/
│   │   │   └── ...
│   │   └── invoice/
│   │       └── ...
│   └── packet_002/
│       └── ...
│
└── config/                              # Run metadata
    ├── packet.json                      #   Copy of the packet config used
    └── packet_manifest.json             #   Full run metadata, timing, per-packet results
```

## Label Format

Each `result.json` contains three fields:

```json
{
  "document_class": {
    "type": "Insurance Claim"
  },
  "split_document": {
    "page_indices": [0]
  },
  "inference_result": {
    "InsuredName": "Michael Andrew Thompson",
    "InsuredAddress": "7425 Evergreen Terrace, Portland, OR 97219",
    "ClaimNumber": "CLM-2024-06789"
  }
}
```

| Field | Description |
|-------|-------------|
| `document_class.type` | The document type label (matches `classes.yaml`) |
| `split_document.page_indices` | Zero-indexed page numbers in the merged PDF |
| `inference_result` | All fields from the generated data JSON, the ground-truth KIE labels |

Sections are numbered sequentially (1-indexed) in the order they appear in the merged PDF.

## Packet Configuration

Packet configs live in `src/seed_data/packets/<name>/packet.json`.

```json
{
  "name": "insurance-claim-packet",
  "description": "Property insurance claim with supporting financial documents.",
  "documents": [
    {
      "document_class": "Insurance Claim",
      "schema_dir": "insurance-claim",
      "required": true,
      "min_instances": 1,
      "max_instances": 1
    },
    {
      "document_class": "Bank Statement",
      "schema_dir": "bank-statement",
      "required": true,
      "min_instances": 1,
      "max_instances": 2
    },
    {
      "document_class": "Invoice",
      "schema_dir": "invoice",
      "required": true,
      "min_instances": 1,
      "max_instances": 3
    }
  ],
  "shared_context": {
    "claimant_name": "Full legal name of the person filing the claim",
    "claimant_address": "Street address of the claimant / insured property",
    "incident_date": "Date of the loss/incident (YYYY-MM-DD format)",
    "claim_amount_range": "Approximate total claim value"
  },
  "shared_context_hint": "All documents relate to the same insurance claim."
}
```

### Config Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Packet type identifier |
| `description` | no | Human-readable description |
| `documents` | yes | List of document types in the packet |
| `documents[].document_class` | yes | Label used in `result.json` and `classes.yaml` |
| `documents[].schema_dir` | yes | Schema directory name (resolved relative to the sibling `schemas/` dir) |
| `documents[].required` | no | Must this doc type appear? Default: `true` |
| `documents[].min_instances` | no | Minimum count per packet. Default: `1` |
| `documents[].max_instances` | no | Maximum count per packet. Default: `1` |
| `shared_context` | no | Explicit shared fields (keys = field names, values = descriptions) |
| `shared_context_hint` | no | Natural language hint about how documents relate |

### Shared Context

Shared context ensures consistency across documents in a packet: the same person name, address, and dates appear in every sub-document. There are two modes:

1. **Explicit**: define `shared_context` in the config with field names and descriptions. The LLM generates values matching those descriptions.
2. **Inferred**: omit `shared_context`. The LLM reads all schemas, identifies fields that represent the same real-world entities, generates consistent values, and logs what it decided.

The optional `shared_context_hint` field gives the LLM additional guidance in either mode.

### Instance Counts

Each document type can appear multiple times in a packet. Set `min_instances` and `max_instances` to control the range; the generator picks a random count within that range for each packet. Optional documents (`required: false`) have a 30% chance of being skipped entirely.

## CLI Reference

Packet-only flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--packet` | required | Path to the packet config directory |
| `--count` | `1` | Number of packets to generate |
| `--workers` | `2` | Parallel packets within the batch |
| `--doc-workers` | `1` | Parallel sub-documents within each packet |
| `--shuffle` | off | Randomize sub-document order in the merged PDF |
| `--context-model` | `gpt-oss` | Model for shared context resolution |

The common flags from [Batch Generation](batch-generation.md) (`--data-model`, `--doc-model`, `--critic-model`, `--augment`, `--threshold`, `--renderer`, `--output`, `--extra`) also apply.

## Design Notes

- **No LLM orchestrator for packets.** The packet structure is deterministic: SEED knows exactly which documents to generate and in what order. The only LLM call in the packet layer is shared context resolution.
- **Per-document augmentation.** Augmentation runs on individual sub-documents before merging, so each sub-document can have different degradation characteristics, which is realistic. Packet-level augmentation of the merged PDF is planned but not yet implemented.
- **Random instance counts.** Real-world packets vary, so randomizing within `[min, max]` creates more diverse training data. The manifest records exactly what was generated for reproducibility.

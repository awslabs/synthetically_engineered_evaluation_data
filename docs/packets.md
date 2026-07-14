# Packet Generation

Generate coordinated sets of inter-related documents — like a loan application
containing a credit report, pay stubs, and a statement of intent, all sharing
consistent context (same applicant, same address, same dates).

The output is a ready-to-use evaluation dataset for document splitting and
classification models.

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

Each sub-document uses the existing single-document pipeline (`orchestrate()`).
The packet layer only adds coordination — shared context injection, PDF merging,
and label emission.

## Output Structure

The output has two distinct parts: the **evaluation dataset** (what downstream
models consume) and the **generation artifacts** (intermediate files for debugging
and reproducibility).

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
│                                        #   classes:
│                                        #     - Bank Statement
│                                        #     - Insurance Claim
│                                        #     - Invoice
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
│   │       ├── 3/result.json
│   │       ├── 4/result.json
│   │       ├── 5/result.json
│   │       └── 6/result.json
│   └── packet_002.pdf/
│       └── sections/
│           └── ...
│
│   ┌─────────────────────────────────────────────────────┐
│   │  GENERATION ARTIFACTS                               │
│   │  Intermediate files — individual PDFs, data JSONs,  │
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
│   │   │   ├── pdfs/UUID.pdf
│   │   │   ├── data/UUID.json
│   │   │   └── generation_scripts/UUID.html
│   │   └── invoice/
│   │       ├── pdfs/UUID.pdf
│   │       ├── data/UUID.json
│   │       └── generation_scripts/UUID.html
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
    "ClaimNumber": "CLM-2024-06789",
    "..."
  }
}
```

| Field | Description |
|-------|-------------|
| `document_class.type` | The document type label (matches `classes.yaml`) |
| `split_document.page_indices` | Zero-indexed page numbers in the merged PDF |
| `inference_result` | All fields from the generated data JSON — ground-truth KIE labels |

Sections are numbered sequentially (1-indexed) in the order they appear in the
merged PDF.

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
| `documents[].schema_dir` | yes | Schema directory name (resolved relative to sibling `schemas/` dir) |
| `documents[].required` | no | Must this doc type appear? Default: `true` |
| `documents[].min_instances` | no | Minimum count per packet. Default: `1` |
| `documents[].max_instances` | no | Maximum count per packet. Default: `1` |
| `shared_context` | no | Explicit shared fields (keys = field names, values = descriptions) |
| `shared_context_hint` | no | Natural language hint about how documents relate |

### Shared Context

Shared context ensures consistency across documents in a packet — the same person
name, address, and dates appear in every sub-document.

**Two modes:**

1. **Explicit** — Define `shared_context` in the config with field names and
   descriptions. The LLM generates values matching those descriptions.

2. **Inferred** — Omit `shared_context`. The LLM reads all schemas, identifies
   fields that represent the same real-world entities, and generates consistent
   values. It logs what it decided.

The `shared_context_hint` field (optional) gives the LLM additional guidance in
either mode.

### Instance Counts

Each document type can appear multiple times in a packet. Set `min_instances` and
`max_instances` to control the range. The generator picks a random count within
that range for each packet.

Optional documents (`required: false`) have a 30% chance of being skipped entirely.

## CLI Reference

```bash
python scripts/packet_generate.py \
  --packet <path>           # Path to packet config directory (required)
  --count <N>               # Number of packets to generate (default: 1)
  --workers <N>             # Max parallel workers (default: 2)
  --shuffle                 # Randomize sub-document order in merged PDF
  --context-model <model>   # Model for shared context resolution (default: nova2-lite)
  --extra <brief>           # Scenario brief for diversity
  --data-model <model>      # Model for data generation (default: nova2-lite)
  --doc-model <model>       # Model for PDF generation (default: nova2-lite)
  --critic-model <model>    # Model for all critics (default: sonnet)
  --augment                 # Enable per-document augmentation
  --aug-model <model>       # Model for augmentation (default: gpt-oss)
  --threshold <N>           # Quality threshold 1-10 (default: 7)
  --renderer <engine>       # weasyprint or reportlab (default: weasyprint)
  --output <dir>            # Output root directory (default: ./output)
```

## Architecture

```
packet_generate.py
  │
  ├── load_packet_config()        Load and validate packet.json
  │
  ├── emit_classes_yaml()         Write classes.yaml
  │
  └── generate_packet()  ×N      One per packet, parallel via ThreadPoolExecutor
        │
        ├── resolve_shared_context()   LLM generates consistent field values
        │     ├── explicit mode: generate values for defined fields
        │     └── inferred mode: analyze schemas → identify shared fields → generate
        │
        ├── _build_document_plan()     Decide instance counts per doc type
        │
        ├── _generate_subdocuments()   For each planned doc:
        │     └── orchestrate()          Full single-doc pipeline (existing code)
        │           data_gen → data_critic → doc_gen → doc_critic → [augment]
        │
        ├── _merge_pdfs()              Concatenate individual PDFs, track page indices
        │
        └── _emit_baseline_labels()    Write result.json per section
```

The packet layer is a thin coordinator on top of the existing single-document
pipeline. It adds shared context, PDF merging, and label emission — nothing else.
All document generation, critique, and augmentation logic lives in `orchestrate.py`
unchanged.

## Design Decisions

**Why not an LLM orchestrator for packets?** The packet structure is deterministic —
we know exactly which documents to generate and in what order. An LLM orchestrator
would add latency and unpredictability for no benefit. The only LLM call in the
packet layer is shared context resolution.

**Why per-document augmentation, not packet-level?** Packet-level augmentation
(applying effects to the merged PDF) is planned but not yet implemented. For now,
augmentation runs on individual sub-documents before merging, which means each
sub-doc can have different degradation characteristics. This is realistic — in a
real packet, some pages might be cleaner than others.

**Why random instance counts?** Real-world packets vary. A loan application might
have 1 or 3 pay stubs. Randomizing within `[min, max]` creates more diverse
training data. The manifest records exactly what was generated for reproducibility.

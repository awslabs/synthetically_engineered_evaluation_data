---
title: Packets
---

# Packets

Generate coordinated sets of inter-related documents — like a loan application
with a credit report, pay stubs, W-2s, and bank statements, all sharing
consistent context (same applicant, address, and dates) and merged into one
multi-page PDF.

The output is a ready-to-use evaluation dataset for document splitting and
classification models.

## How It Works

```
1. Load packet config     → which document types, how many of each
2. Resolve shared context → LLM generates consistent names/addresses/dates
3. Generate sub-documents → each runs the full pipeline (data → critic → PDF → critic)
4. Merge into packet PDF  → individual PDFs concatenated, page indices tracked
5. Emit labels            → per-section ground truth (class, pages, extracted fields)
```

Each sub-document uses the same staged pipeline as single/batch generation; the
packet layer adds coordination: shared-context injection, PDF merging, and label
emission.

## Usage

- **[CLI Usage → Packet](../CLI-Usage/README.md#packet)**: the `seed-data packet` subcommand and its flags.
- **[Python API Usage → Packet](../Python-API-Usage/README.md#packet)**: `Generator.generate_packet(...)` and the `PacketResult`.

---

## Output Structure

The output has two parts: the **evaluation dataset** (what downstream models
consume) and the **generation artifacts** (intermediates for debugging).

```
output/<batch-name>/
├── classes.yaml                   # all document types in this packet
├── input/                         # merged multi-document PDFs
│   └── <packet_id>.pdf
├── baseline/                      # ground-truth labels per section
│   └── <packet_id>.pdf/sections/<n>/result.json
├── artifacts/                     # per-packet generation files
│   └── <packet_id>/
│       ├── shared_context.json
│       └── <doc-type>/{pdfs,data,generation_scripts}/
└── config/
    ├── packet.json                # copy of the packet config used
    └── packet_manifest.json       # full run metadata
```

### Label format

Each `result.json`:

```json
{
  "document_class": { "type": "Insurance Claim" },
  "split_document": { "page_indices": [0] },
  "inference_result": {
    "InsuredName": "Michael Andrew Thompson",
    "ClaimNumber": "CLM-2024-06789"
  }
}
```

| Field | Description |
|-------|-------------|
| `document_class.type` | Document type label (matches `classes.yaml`) |
| `split_document.page_indices` | Zero-indexed pages in the merged PDF |
| `inference_result` | All fields from the generated data — the KIE ground truth |

---

## Packet Configuration

Packet configs live in `src/seed_data/packets/<name>/packet.json`:

```json
{
  "name": "insurance-claim-packet",
  "description": "Property insurance claim with supporting financial documents.",
  "documents": [
    { "document_class": "Insurance Claim", "schema_dir": "insurance-claim",
      "required": true, "min_instances": 1, "max_instances": 1 },
    { "document_class": "Bank Statement", "schema_dir": "bank-statement",
      "required": true, "min_instances": 1, "max_instances": 2 },
    { "document_class": "Invoice", "schema_dir": "invoice",
      "required": true, "min_instances": 1, "max_instances": 3 }
  ],
  "shared_context": {
    "claimant_name": "Full legal name of the person filing the claim",
    "claimant_address": "Street address of the claimant / insured property",
    "incident_date": "Date of the loss/incident (YYYY-MM-DD)"
  },
  "shared_context_hint": "All documents relate to the same insurance claim."
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Packet type identifier |
| `documents` | yes | List of document types in the packet |
| `documents[].document_class` | yes | Label used in `result.json` and `classes.yaml` |
| `documents[].schema_dir` | yes | Schema directory name (resolved against the sibling `schemas/`) |
| `documents[].required` | no | Must this doc type appear? Default `true` (optional docs have a 30% skip chance) |
| `documents[].min_instances` / `max_instances` | no | Count range per packet (random within range) |
| `shared_context` | no | Explicit shared fields (name → description) |
| `shared_context_hint` | no | Natural-language hint about how documents relate |

### Shared context

Ensures the same person, address, and dates appear across every sub-document.
Two modes:

1. **Explicit** — define `shared_context`; the LLM generates values matching the
   descriptions.
2. **Inferred** — omit it; the LLM reads all schemas, finds fields representing
   the same entities, and generates consistent values.

## Related

- [Creating a Document Type](creating-a-document-type.md): the schemas a packet references.
- [Batch Generation](batch-generation.md): many independent documents from one brief.
- [Python API reference](../API-Reference/generator.md): full `Generator` signatures.

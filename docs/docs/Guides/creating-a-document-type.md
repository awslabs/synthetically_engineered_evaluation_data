---
title: Creating a Document Type
---

# Creating a Document Type

Every document type lives in its own directory under `src/seed_data/schemas/`, with at least a `schema.json`. This guide walks through creating one and generating your first document from it.

## Schema Directory Layout

```
schemas/purchase-order/
├── schema.json              # JSON Schema, REQUIRED
├── generation_guidance.md   # Visual style, data ranges, math rules, optional
└── samples/                 # Reference PDFs for the doc critic, optional, local-only
    ├── README.md            # What samples are for + handling rules
    └── *.pdf                # git-ignored, never committed
```

## Step 1: Create the Directory

```bash
mkdir -p src/seed_data/schemas/purchase-order
```

## Step 2: Write the Schema

Create `src/seed_data/schemas/purchase-order/schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Purchase-Order",
  "description": "A purchase order for goods from a supplier.",
  "type": "object",
  "required": ["Buyer", "Supplier", "PONumber", "Items", "Total"],
  "properties": {
    "Buyer": { "type": "string", "description": "Company placing the order" },
    "Supplier": { "type": "string", "description": "Company fulfilling the order" },
    "PONumber": { "type": "string", "description": "Purchase order number" },
    "OrderDate": { "type": "string", "description": "Date in YYYY-MM-DD format" },
    "Items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["Description", "Quantity", "UnitPrice", "Amount"],
        "properties": {
          "Description": { "type": "string" },
          "Quantity": { "type": "integer" },
          "UnitPrice": { "type": "number" },
          "Amount": { "type": "number", "description": "Must equal Quantity * UnitPrice" }
        }
      }
    },
    "Total": { "type": "number", "description": "Sum of all item Amounts" }
  }
}
```

The `title` field becomes the document type name used in output directories.

## Step 3: Add Steering Docs (Optional but Recommended)

Create `src/seed_data/schemas/purchase-order/generation_guidance.md`:

```markdown
# Purchase Order, Generation Guidance

## Visual Style
- Clean business document with company letterhead
- Table with columns: Item, Qty, Unit Price, Amount
- Total prominently displayed at bottom right
- Use 8-10pt body text, compact layout

## Data Realism
- Buyer: realistic company names (manufacturing, retail, construction)
- Supplier: realistic vendor names matching the industry
- PO numbers: format PO-YYYYMMDD-NNN
- 3-10 line items typical
- Unit prices: $5-$5,000 range

## Math Rules (CRITICAL)
- Each item Amount MUST equal Quantity * UnitPrice exactly
- Total MUST equal sum of all item Amounts
- All values to 2 decimal places
```

The pipeline reads all `*.md` files in the directory and injects them into every agent's prompt. This is where you put domain-specific rules, and the agents will follow them. The `generation_guidance.md` file controls:

- **Visual style**: layout, fonts, density, colors.
- **Data realism**: value ranges, naming conventions, line item counts.
- **Math rules**: arithmetic constraints, for example `Total = sum of item Amounts`.
- **Common issues to avoid**: known pitfalls for this document type.

The scenario generator (used by batch runs) also reads this file to create diverse scenarios that respect the document type's constraints.

### Want Diversity Across Runs?

Add optional fields with `x-probability` to your schema and a `## Layout Variations` section to your guidance. See [Generation Choices](generation-choices.md) for the full guide.

## Step 4: Add Reference Samples (Optional)

If you have real examples of this document type, drop PDFs into a `samples/` subdirectory:

```
schemas/purchase-order/
├── schema.json
├── generation_guidance.md
└── samples/
    ├── real_po_001.pdf
    └── real_po_002.pdf
```

The doc critic loads these only as a visual style reference. The generation stages never see them, and no content from them is reproduced in the output.

Sample PDFs are local-only and git-ignored. Do not commit them: real documents may contain third-party names or PII you do not have the right to redistribute. You are responsible for having the rights to any sample you add. Use `--no-critic-samples` to skip samples entirely. The repository ships with no sample documents.

## Step 5: Generate a Single Document

```bash
BYPASS_TOOL_CONSENT=true python -m seed_data \
  --schema-dir src/seed_data/schemas/purchase-order \
  --extra "Industrial plumbing supplies for a construction project in Denver"
```

This runs the full pipeline: data generation, data validation, PDF rendering, and visual critique. The final PDF lands in `output/purchase-order/`.

Add `--augment` to also apply scanning and faxing artifacts.

## Step 6: Tune Quality by Editing Steering Docs

The fastest way to improve output quality is editing the `*.md` steering files. The agents read them on every run. Common tweaks:

- Add specific layout instructions, for example "use alternating row colors in tables".
- Tighten math rules, for example "tax rate must be between 6% and 10.25%".
- Add augmentation context, for example "these documents were faxed in the 1990s".
- Specify data constraints, for example "dates must be within the last 90 days".

You can also raise or lower the acceptance threshold:

```bash
--threshold 8    # stricter (more retries, higher quality)
--threshold 5    # lenient (faster, lower quality)
```

For deeper customization, edit the Jinja2 prompt templates in `src/seed_data/prompts/`:

| Template | Controls |
|----------|----------|
| `data_generator.j2` | How the LLM generates JSON data |
| `data_critic.j2` | What the data critic checks for |
| `doc_generator.j2` | How the LLM writes PDF rendering code |
| `critic_vision.j2` | What the vision critic evaluates |
| `augmentor.j2` | Available augmentations and selection rules |
| `aug_critic.j2` | Augmentation quality criteria |

## Next Steps

- [Batch Generation](batch-generation.md): generate many varied documents of this type at once.
- [Generation Choices](generation-choices.md): add per-document variation with `x-probability`.

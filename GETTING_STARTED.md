# Getting Started with doc-gen-agent

This guide walks you through creating a new document type and generating your first synthetic documents in under 10 minutes.

## Install

```bash
conda create -n doc-gen-agent python=3.12 -y
conda activate doc-gen-agent
pip install -e .
```

## Prerequisites: AWS Access

This tool uses Amazon Bedrock to run foundation models. You need an AWS account with Bedrock model access enabled.

Configure your credentials using any method supported by [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html). We recommend setting up a named profile in `~/.aws/config`:

```bash
export AWS_PROFILE=your-profile-name
```

### About BYPASS_TOOL_CONSENT

The Strands Agents SDK prompts for user confirmation before executing tools (like `python_repl`). Since this pipeline runs many tool calls autonomously, set this environment variable to skip those prompts:

```bash
export BYPASS_TOOL_CONSENT=true
```

This is safe — the agents only execute code they generate for PDF rendering, and all output is validated by the critic agents. You can omit this flag if you want to manually approve each tool call.

## Step 1: Create a Document Type

Every document type lives in its own directory with at least a `schema.json`. Create one:

```bash
mkdir -p src/doc_gen_agent/schemas/purchase-order
```

### Write the schema

Create `src/doc_gen_agent/schemas/purchase-order/schema.json`:

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

### Add steering docs (optional but recommended)

Create `src/doc_gen_agent/schemas/purchase-order/generation_guidance.md`:

```markdown
# Purchase Order — Generation Guidance

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

The pipeline reads all `*.md` files in the directory and injects them into every agent's prompt. This is where you put domain-specific rules — the agents will follow them.

**Want diversity across runs?** Add optional fields with `x-probability` to your
schema and a `## Layout Variations` section to your guidance. See
[docs/generation_choices.md](docs/generation_choices.md) for the full guide.

### Add reference samples (optional)

If you have real examples of this document type, drop PDFs into a `samples/` subdirectory:

```
schemas/purchase-order/
├── schema.json
├── generation_guidance.md
└── samples/
    ├── real_po_001.pdf
    └── real_po_002.pdf
```

The doc critic loads these as visual benchmarks and compares generated documents against them.

## Step 2: Generate a Single Document

```bash
BYPASS_TOOL_CONSENT=true python -m doc_gen_agent \
  --schema-dir src/doc_gen_agent/schemas/purchase-order \
  --extra "Industrial plumbing supplies for a construction project in Denver"
```

This runs the full pipeline: data generation → data validation → PDF rendering → visual critique. You'll see each stage's output in the terminal. The final PDF lands in `output/purchase-order/`.

### With image augmentation

Add `--augment` to simulate scanning/faxing artifacts:

```bash
BYPASS_TOOL_CONSENT=true python -m doc_gen_agent \
  --schema-dir src/doc_gen_agent/schemas/purchase-order \
  --extra "Industrial plumbing supplies" \
  --augment
```

This adds two more stages: an augmentor agent picks degradation effects, then an aug critic checks the result is still legible.

## Step 3: Generate a Batch

For training data, you want volume and diversity. The batch script (`scripts/batch_generate.py`)
runs the pipeline N times in parallel, each with a unique scenario:

```bash
BYPASS_TOOL_CONSENT=true python scripts/batch_generate.py \
  --schema-dir src/doc_gen_agent/schemas/purchase-order \
  --extra "Diverse industries ordering from various suppliers across the US" \
  --count 10 --workers 3 \
  --batch-name po-training-set \
  --augment
```

A scenario generator agent reads your brief and crafts a unique scenario for each
document — different buyers, suppliers, industries, regions, and order types. Then
each scenario runs through the full pipeline in parallel via `ThreadPoolExecutor`
(controlled by `--workers`).

Output goes to `output/po-training-set/`:

```
output/po-training-set/
├── pdfs/              # 10 clean PDFs
├── augmented/         # 10 augmented versions
├── data/              # 10 JSON data files (ground truth)
├── generation_scripts/  # The HTML used to render each PDF
├── config/            # Copy of your schema + guidance for reproducibility
└── config/batch_manifest.json   # CLI command, git hash, model config, per-doc results
```

Tips:
- **Workers vs count**: a single doc takes ~60-100s. With `--count 10 --workers 3`
  expect ~5-7 minutes wall-clock. Don't set `--workers` higher than 4-5; you'll hit
  Bedrock rate limits.
- **Brief specificity matters**: a vague brief produces same-y documents. A specific
  brief ("CPG brands on local TV stations in the southwest") produces real diversity.
- **Partial failures are OK**: if 1 of 10 docs fails, the other 9 are still saved.
  The manifest shows which succeeded.


## Step 4: Customize Models

By default, the pipeline uses DeepSeek V3.2 for generation and Haiku for critics. Override per stage:

```bash
python -m doc_gen_agent \
  --schema-dir src/doc_gen_agent/schemas/purchase-order \
  --extra "Office supplies" \
  --data-model qwen3-vl \
  --doc-model deepseek-v3 \
  --critic-model haiku \
  --count 5 --batch-name office-supplies
```

**Constraint:** `--critic-model` must support document/PDF input (currently only Anthropic models: haiku, sonnet, opus). All other model flags can use any available model.

## Step 5: Tune Quality

### Adjust the acceptance threshold

```bash
--threshold 8    # stricter (more retries, higher quality)
--threshold 5    # lenient (faster, lower quality)
```

### Edit steering docs

The fastest way to improve output quality is editing the `*.md` steering files. The agents read these on every run. Common tweaks:

- Add specific layout instructions ("use alternating row colors in tables")
- Tighten math rules ("tax rate must be between 6% and 10.25%")
- Add augmentation context ("these documents were faxed in the 1990s")
- Specify data constraints ("dates must be within the last 90 days")

### Edit prompt templates

For deeper customization, edit the Jinja2 templates in `src/doc_gen_agent/prompts/`:

| Template | Controls |
|----------|----------|
| `data_generator.j2` | How the LLM generates JSON data |
| `data_critic.j2` | What the data critic checks for |
| `doc_generator.j2` | How the LLM writes PDF rendering code |
| `critic_vision.j2` | What the vision critic evaluates |
| `augmentor.j2` | Available augmentations and selection rules |
| `aug_critic.j2` | Augmentation quality criteria |

## Quick Reference

```bash
# Single doc, defaults
python -m doc_gen_agent --schema-dir schemas/my-type --extra "context"

# Batch of 20 with augmentation
python scripts/batch_generate.py --schema-dir schemas/my-type \
  --extra "brief for diversity" --count 20 --workers 3 \
  --batch-name my-batch --augment

# Use specific models (single-doc; same flags work for batch)
python -m doc_gen_agent --schema-dir schemas/my-type \
  --data-model nova2-lite --doc-model gpt-oss --critic-model sonnet

# See all options
python -m doc_gen_agent --help
python scripts/batch_generate.py --help
python scripts/packet_generate.py --help
```

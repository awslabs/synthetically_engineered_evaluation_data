# Getting Started with seed-data

This guide walks you through creating a new document type and generating your first synthetic documents in under 10 minutes.

## Install

```bash
pip install seed-data
```

Or, working from a repo clone with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Prerequisites: AWS Access

This tool uses Amazon Bedrock to run foundation models. You need an AWS account with Bedrock model access enabled.

Configure your credentials using any method supported by [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html). We recommend setting up a named profile in `~/.aws/config`:

```bash
export AWS_PROFILE=your-profile-name
export AWS_REGION=us-east-1
```

### About BYPASS_TOOL_CONSENT

The Strands Agents SDK prompts for user confirmation before executing tools. Since this pipeline runs many tool calls autonomously, you can set this environment variable to skip those prompts:

```bash
export BYPASS_TOOL_CONSENT=true
```

Leave it **unset** when running untrusted schemas so you can approve each tool call. See the Security section of the [README](README.md#security).

## Step 1: Create a Document Type

Every document type lives in its own directory with at least a `schema.json`. Start from the bundled library, or create your own:

```bash
# Copy the built-in schemas into a local, editable folder
seed-data clone-schema-library ./schemas

# ...then create a new type alongside them
mkdir -p ./schemas/purchase-order
```

### Write the schema

Create `./schemas/purchase-order/schema.json`:

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

Create `./schemas/purchase-order/generation_guidance.md`:

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
[docs/docs/Guides/generation-choices.md](docs/docs/Guides/generation-choices.md) for the full guide.

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

The doc critic loads these as visual benchmarks and compares generated documents against them. Sample PDFs are local-only and git-ignored — see the [README](README.md#samples-reference-documents--important).

## Step 2: Generate a Single Document

```bash
seed-data \
  --schema-dir ./schemas/purchase-order \
  --scenario "Industrial plumbing supplies for a construction project in Denver"
```

This runs the full pipeline: data generation → data validation → PDF rendering → visual critique. You'll see each stage's output in the terminal. The final PDF lands in `./output/pdfs/`, with the ground-truth label in `./output/data/`.

### With image augmentation

Add `--augment` to simulate scanning/faxing artifacts:

```bash
seed-data \
  --schema-dir ./schemas/purchase-order \
  --scenario "Industrial plumbing supplies" \
  --augment
```

This adds two more stages: an augmentor agent picks degradation effects, then an aug critic checks the result is still legible.

## Step 3: Generate a Batch

For evaluation data, you want volume and diversity. Setting `--count > 1` switches
into batch mode: a scenario planner turns your brief into N distinct scenarios,
and each runs its own self-contained pipeline graph as a sibling node — the
Strands graph executes them concurrently (no worker flags to tune):

```bash
seed-data \
  --schema-dir ./schemas/purchase-order \
  --scenario "Diverse industries ordering from various suppliers across the US" \
  --count 10 \
  --augment
```

Output goes to `./output/`:

```
output/
├── pdfs/                 # 10 clean PDFs
├── augmented/            # 10 augmented versions
├── data/                 # 10 ground-truth JSON labels
├── generation_scripts/   # The HTML used to render each PDF
└── config/               # Copy of your schema + guidance for reproducibility
```

Tips:
- **A single doc takes ~30-100s.** All scenarios run concurrently, so a batch is
  bounded by the slowest document plus Bedrock rate limiting, not the sum. Start
  with modest counts.
- **Scenario specificity matters**: a vague scenario produces same-y documents. A specific
  one ("CPG brands on local TV stations in the southwest") produces real diversity.
- **Partial failures are OK**: if 1 of 10 docs fails, the other 9 are still saved.
- **Regression-stable sets**: pass `--seed <n>` to make scenario planning deterministic.

## Step 4: Customize Models

Override the model used at each stage:

```bash
seed-data \
  --schema-dir ./schemas/purchase-order \
  --scenario "Office supplies" \
  --data-model gpt-oss \
  --doc-model gpt-oss \
  --critic-model haiku \
  --count 5
```

**Constraint:** `--critic-model` must support document/PDF input (currently only Anthropic models: `haiku`, `sonnet`, `opus`). All other model flags can use any available model. Run `seed-data --help` for the full list of model keys.

## Step 5: Tune Quality

### Adjust the acceptance threshold

```bash
--threshold 8    # stricter (more retries, higher quality)
--threshold 3    # lenient (faster, lower quality)
```

The default is `5`.

### Edit steering docs

The fastest way to improve output quality is editing the `*.md` steering files. The agents read these on every run. Common tweaks:

- Add specific layout instructions ("use alternating row colors in tables")
- Tighten math rules ("tax rate must be between 6% and 10.25%")
- Add augmentation context ("these documents were faxed in the 1990s")
- Specify data constraints ("dates must be within the last 90 days")

### Edit prompt templates

For deeper customization, edit the Jinja2 templates in `src/seed_data/prompts/`:

| Template | Controls |
|----------|----------|
| `data_generator.j2` | How the LLM generates JSON data |
| `data_critic.j2` | What the data critic checks for |
| `doc_generator.j2` / `doc_generator_html.j2` | How the LLM writes PDF rendering code |
| `critic_vision.j2` | What the vision critic evaluates |
| `augmentor.j2` | Available augmentations and selection rules |
| `aug_critic.j2` | Augmentation quality criteria |

## Prefer Python?

Everything above is available through the typed `Generator` API:

```python
from seed_data import Generator, ModelConfig

gen = Generator(models=ModelConfig(doc="gpt-oss", critic="haiku"), threshold=5)

doc   = gen.generate("./schemas/purchase-order", scenario="Office supplies, net-30")
batch = gen.generate_batch("./schemas/purchase-order", count=10,
                           scenario="Diverse industries across the US")
```

See [Python API Usage](docs/docs/Python-API-Usage/README.md) for the full surface.

## Quick Reference

```bash
# Single doc, defaults
seed-data --schema-dir ./schemas/my-type --scenario "context"

# Batch of 20 with augmentation
seed-data --schema-dir ./schemas/my-type \
  --scenario "brief for diversity" --count 20 --augment

# Use specific models
seed-data --schema-dir ./schemas/my-type \
  --data-model gpt-oss --doc-model gpt-oss --critic-model sonnet

# A coordinated multi-document packet
seed-data packet lending-package --scenario "First-time homebuyer in Portland, OR"

# See all options
seed-data --help
seed-data packet --help
```

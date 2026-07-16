# Synthetically Engineered Evaluation Data (SEED)

AI-powered synthetic document generation pipeline built on the [Strands Agents SDK](https://strandsagents.com/). Produces realistic PDF documents from JSON schemas, validates them through multi-stage critique loops, and optionally applies image augmentation to simulate real-world scanning/faxing artifacts. Each document is paired with a ground-truth JSON label, so the output is a ready-made benchmark set.

Designed for building evaluation datasets for document understanding systems: OCR, Key Information Extraction (KIE), and document classification. Use it from the command line (`seed-data`) or the typed Python API (`seed_data.Generator`).

> **Not a production-ready solution.** This asset represents a proof-of-value
> for the services included and is not intended as a production-ready solution.
> You must determine how the [AWS Shared Responsibility Model](https://aws.amazon.com/compliance/shared-responsibility-model/)
> applies to your specific use case and implement the controls needed to achieve
> your desired security outcomes. AWS offers a broad set of security tools and
> configurations to enable our customers.
>
> Ultimately it is your responsibility as the developer of a full-stack
> application to ensure all of its aspects are secure. We provide security best
> practices in the repository documentation and a secure baseline, but Amazon
> holds no responsibility for the security of applications built from this tool.

> **⚡ New here?** Read the [Quickstart](docs/docs/Getting-Started/quick-start.md) — install from PyPI and generate your first document in a few minutes.

## Quick Start

Install from PyPI (the default renderer is pure Python — nothing else to set up):

```bash
pip install seed-data

# Configure AWS credentials with Bedrock access
export AWS_PROFILE=your-profile-name

# Copy the built-in schema library into a local, editable folder
seed-data clone-schema-library ./schemas

# Generate a single document (PDF + ground-truth JSON) into ./output
seed-data --schema-dir fcc-invoice --output ./output
```

`--schema-dir` accepts a **bundled schema name** (like `fcc-invoice`) or a **path**
to a schema directory, so the command above works with or without the clone step.

Browse the schema library on GitHub:
[awslabs/…/schemas](https://github.com/awslabs/synthetically_engineered_evaluation_data/tree/main/src/seed_data/schemas).
See the [full Quickstart](docs/docs/Getting-Started/quick-start.md) for batches, augmentation, and model selection.

<details>
<summary>Working from a repo clone (uv)?</summary>

```bash
# Install (creates the venv and installs from uv.lock)
uv sync

export AWS_PROFILE=your-profile-name

# Generate a single FCC invoice
uv run seed-data --schema-dir fcc-invoice

# Generate a diverse batch of 4 invoices with augmentation
uv run seed-data --schema-dir fcc-invoice \
  --count 4 --augment \
  --scenario "FCC broadcast invoices for packaged food companies in the midwest"
```
</details>

## Two ways to use it

Everything is available from both the command line and Python; they run the same pipeline and produce the same artifacts.

**Command line:**

```bash
seed-data --schema-dir invoice --scenario "Midwest food-distributor invoice"   # single
seed-data --schema-dir fcc-invoice --count 10 --scenario "Local TV stations"    # batch
seed-data packet lending-package --scenario "First-time homebuyer in Portland"  # packet
```

**Python:**

```python
from seed_data import Generator, ModelConfig

gen = Generator(models=ModelConfig(doc="gpt-oss", critic="haiku"), threshold=5)

doc    = gen.generate("invoice", scenario="Midwest food-distributor invoice")
batch  = gen.generate_batch("fcc-invoice", count=10, scenario="Local TV stations")
packet = gen.generate_packet("lending-package", scenario="First-time homebuyer in Portland")
```

Full docs: [CLI Usage](docs/docs/CLI-Usage/README.md) · [Python API Usage](docs/docs/Python-API-Usage/README.md).

## Architecture

### Single-document pipeline

```
data_generator → data_critic → [doc_generator → doc_critic loop] → (augmentor → aug_critic)
                 ↑ (reject)                      ↑ (reject)              ↑ (reject)
                 └─────────┘                     └──────────┘            └──────────┘
```

The data generator invents schema-conforming JSON; the data critic validates it
(deterministic JSON-Schema check + LLM domain review); the doc generator writes
HTML/CSS and renders a PDF; the vision doc critic reviews the render and loops
until it passes the threshold. With `--augment`, an augmentor applies aging
effects and an aug critic checks legibility.

### Batch (concurrent fan-out)

A batch turns one high-level `--scenario` into N distinct scenarios, then runs a
self-contained pipeline graph for each **as sibling nodes** — the Strands graph
executes them concurrently (no thread pools or worker flags). A specific scenario
produces far more varied output than a generic one:

```bash
# Generic — less diverse
--scenario "Generate diverse FCC invoices"

# Specific — much more diverse
--scenario "FCC broadcast invoices for packaged food companies advertising in the midwest"
--scenario "Local car dealership TV ads across small-market stations in the southeast"
```

### Packet (coordinated multi-document)

A packet is a set of different document types that share context — like a loan
application with a credit report, pay stubs, and bank statements, all for the
same applicant — merged into one multi-page PDF. See the
[Packets guide](docs/docs/Guides/packets.md).

## Agent Descriptions

| Agent | Role | CLI default model |
|-------|------|-------------------|
| Scenario Planner | Creates diverse scenarios from a scenario brief + guidance (batch) | `nova2-lite` |
| Data Generator | Produces JSON data from schema. Has a calculator tool for math. | `gpt-oss` |
| Data Critic | Validates data against schema and domain rules. Structured output. | `sonnet` |
| Doc Generator | Writes HTML/CSS and renders to PDF. Has an editor for targeted fixes. | `gpt-oss` |
| Doc Critic | Vision model evaluates PDF quality — layout, typography, truncation, math. | `sonnet` |
| Augmentor | Picks an augraphy config and applies document aging effects. | `gpt-oss` |
| Aug Critic | Evaluates the augmented doc for legibility and realism. Structured output. | `sonnet` |

## Setup

This project uses [uv](https://docs.astral.sh/uv/) and ships a committed
`uv.lock` for reproducible installs. uv is the recommended workflow.

```bash
# Install uv (see https://docs.astral.sh/uv/getting-started/installation/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create the virtual environment and install all dependencies from uv.lock,
# including the dev group (pytest, ruff, docs). Requires Python 3.12+.
uv sync

# Run any command inside the managed environment with `uv run`, e.g.
uv run seed-data --help
```

`uv sync` installs the `dev` dependency group by default (configured via
`[tool.uv] default-groups`). Use `uv sync --no-dev` for a runtime-only install.

<details>
<summary>Alternative: pip or conda</summary>

```bash
# pip (add the [dev] extra for pytest/ruff/docs tooling)
pip install -e ".[dev]"

# or conda for the environment, then pip for the package
conda create -n seed python=3.12 -y
conda activate seed
pip install -e ".[dev]"
```

Note: pip resolves dependencies fresh and does not use `uv.lock`.
</details>

### PDF renderers

The default renderer is **xhtml2pdf** (pure Python, no system libraries) — a fresh
`pip install seed-data` renders PDFs out of the box. Select a renderer with `--renderer`:

| `--renderer` | Backend | System libraries | Notes |
|---|---|---|---|
| `xhtml2pdf` (default) | ReportLab | none | Pure Python; works everywhere |
| `weasyprint` | WeasyPrint | Pango, Cairo, GDK-PixBuf | Richer CSS; needs the libraries below |
| `reportlab` | ReportLab (Python script) | none | LLM writes a ReportLab script instead of HTML |

WeasyPrint only — install its system libraries first:
```bash
# macOS
brew install pango gdk-pixbuf libffi

# Ubuntu/Debian
apt-get install libpango-1.0-0 libgdk-pixbuf2.0-0
```

## Usage

### Single document

```bash
seed-data --schema-dir fcc-invoice \
  --scenario "Local TV station in Portland, Oregon"
```

### Single document with augmentation

```bash
seed-data --schema-dir fcc-invoice \
  --scenario "Local TV station in Portland, Oregon" \
  --augment
```

### Batch generation

`--count > 1` switches into batch mode and fans out concurrent pipeline graphs:

```bash
seed-data --schema-dir fcc-invoice \
  --count 10 \
  --scenario "CPG brands on local TV stations in the American southwest" \
  --augment
```

### Packet generation

```bash
seed-data packet lending-package \
  --count 3 --doc-workers 2 --augment \
  --scenario "First-time homebuyers in the Pacific Northwest, 30-year fixed mortgage"
```

### CLI Options

Common flags (single-document and batch):

| Flag | Default | Description |
|------|---------|-------------|
| `--schema-dir` | required | Bundled schema name, or a directory with `schema.json` |
| `--output` | `./output` | Output root directory |
| `--scenario` | | What to generate this run (for `--count > 1`, the theme to diversify) |
| `--count` | `1` | Number of documents; `> 1` enables batch mode |
| `--data-model` | `gpt-oss` | Model for data generation |
| `--doc-model` | `gpt-oss` | Model for PDF generation |
| `--critic-model` | `sonnet` | Model for all critics |
| `--batch-model` | `nova2-lite` | Model for batch scenario planning |
| `--aug-model` | `gpt-oss` | Model for augmentation decisions |
| `--renderer` | `xhtml2pdf` | `xhtml2pdf` (pure Python), `weasyprint`, or `reportlab` |
| `--augment` | off | Enable augraphy image augmentation |
| `--no-critic-samples` | off | Disable reference sample PDFs in the doc critic |
| `--threshold` | `5` | Acceptance score, 1–10 |
| `--max-attempts` | `5` | Max critic-retry cycles |
| `--seed` | | Seed for batch scenario planning (regression-stable sets) |
| `--timeout` | `3600` | Safety timeout in seconds |
| `--quiet` | off | Suppress stage progress output |

Packet subcommand (`seed-data packet <name|path>`):

| Flag | Default | Description |
|------|---------|-------------|
| `packet` | required | Bundled packet name, or a packet directory path |
| `--count` | `1` | Number of packets to generate |
| `--doc-workers` | `3` | Parallel sub-documents within each packet |
| `--shuffle` | off | Randomize sub-document order in the merged PDF |
| `--context-model` | `nova2-lite` | Model for shared-context resolution |

Utility subcommand — copy the bundled schema library out to edit locally:

```bash
seed-data clone-schema-library ./schemas
```

Run `seed-data --help` and `seed-data packet --help` for the complete list.

### What to expect from a batch

- A single document takes roughly 30–100 seconds end-to-end.
- All workers launch concurrently. The Python Strands graph has no built-in
  concurrency cap, so large counts may hit Bedrock rate limits (adaptive retries
  absorb this, but wall-clock grows). Start with modest counts.
- Partial failures are normal. Failed documents come back with `success=False`
  and `verdict="error"`; the rest still complete.
- Use a specific `--scenario`. Vague scenarios produce same-y output.

### Available Models

| Key | Model | Best For |
|-----|-------|----------|
| `gpt-oss` | GPT-OSS 120B | Doc/data generation, augmentation (fast tool calling) |
| `sonnet` | Claude Sonnet | Critics (respects scope rules, good at evaluation) |
| `haiku` | Claude Haiku 4.5 | Fast critic (cheaper; less strict than sonnet) |
| `nova2-lite` | Amazon Nova 2 Lite | Scenario/context planning (fast, cheap) |
| `nemotron-super` | Nemotron Super 120B | Doc generation (slow but high first-pass quality) |

`seed-data --help` lists every available model key.

## Schema Directories

Each document type lives in its own directory:

```
schemas/fcc-invoice/
├── schema.json              # JSON Schema — REQUIRED
├── generation_guidance.md   # Visual style, data ranges, math rules — optional
└── samples/                 # Reference PDFs for the doc critic — optional, local-only
    ├── README.md            # What samples are for + handling rules
    └── *.pdf                # git-ignored — never committed
```

### samples/ (reference documents) — important

The optional `samples/` directory holds real example PDFs used **only** by the
document critic as a **visual style reference** — they are never seen by the
generation stages and no content from them is reproduced in the output. See
[critique.py](src/seed_data/critique.py) and any
`schemas/<type>/samples/README.md` for the full explanation.

**Sample PDFs are local-only and git-ignored.** Do not commit them: real
documents may contain third-party names or PII you don't have the right to
redistribute, which can trigger data-distribution policies and block
open-source release. You are responsible for having the rights to any sample
you add. Use `--no-critic-samples` to skip samples entirely. The repository
ships with **no** sample documents.

### generation_guidance.md

This is the key file for controlling document quality and diversity. It tells agents:
- **Visual style**: layout, fonts, density, colors
- **Data realism**: value ranges, naming conventions, line item counts
- **Math rules**: arithmetic constraints (e.g., "GrossTotal = sum of LineItemRate")
- **Common issues to avoid**: known pitfalls for this document type
- **Generation Choices**: optional fields with `x-probability` and table presentation variations (see below)

The scenario planner also reads this file to create diverse scenarios that respect the document type's constraints.

## Generation Choices

Document diversity comes from two sources of per-run variation:

1. **Optional fields with `x-probability`** — schema fields marked with an
   `x-probability` annotation are independently included or omitted per document
   based on their probability.
2. **Table presentation variations** — sections that can render either as tables
   or inline fields, declared in `generation_guidance.md` with ~50/50 probabilities.

See [docs/docs/Guides/generation-choices.md](docs/docs/Guides/generation-choices.md) for the full guide:
conventions, examples for nested and array fields, and how to add it to a new
document type.

## Output Structure

Single-document and batch runs write:

```
output/
├── pdfs/                    # Clean PDFs
├── data/                    # Ground-truth JSON label per document
├── generation_scripts/      # HTML files used to render PDFs
├── augmented/               # Augmented PDFs (when --augment)
└── config/                  # Copy of schema + guidance for reproducibility
```

Packet runs use the evaluation-dataset layout (merged PDFs in `input/`,
per-section labels in `baseline/`); see the [Packets guide](docs/docs/Guides/packets.md).

## Tests

```bash
# Run the full unit-test suite (no LLM calls). Integration tests are excluded
# by default (see addopts in pyproject.toml).
uv run pytest

# Or run a single module
uv run pytest tests/test_unit.py -v

# CLI smoke tests (no Bedrock) — verify the command works out of the box
uv run pytest tests/test_cli_smoke.py -v
```

## Packet Configuration

Packet configs live in `src/seed_data/packets/<packet-name>/packet.json`.
See the [Packets guide](docs/docs/Guides/packets.md) for the full guide including config fields,
shared context modes, label format, and architecture.

### Packet config example

```json
{
  "name": "insurance-claim-packet",
  "description": "Property insurance claim submission packet.",
  "documents": [
    {
      "document_class": "Insurance Claim",
      "schema_dir": "insurance-claim",
      "required": true,
      "min_instances": 1,
      "max_instances": 1
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
    "claimant_address": "Street address of the claimant"
  },
  "shared_context_hint": "All documents relate to the same insurance claim."
}
```

## Security

seed-data runs AI agents that **write and execute code** and **read/write
files** on the host in order to render documents. Read this section before
running it on anything you don't fully trust. See also the disclaimer at the top
of this README — you are responsible for the security of anything you build with
this tool.

### Data provenance

| Aspect | Detail |
|--------|--------|
| Real data in generation? | **No.** The generation stages produce entirely fictional content — all names, addresses, and financial figures are invented. |
| PII in output? | **No.** Output documents and ground-truth JSON contain no real personal or customer data. |
| Document templates? | **No.** Each PDF is rendered from freshly generated HTML/CSS (or ReportLab) code; no templates or real documents are copied. |
| Reference samples? | **Optional, local-only.** Real PDFs in a schema's `samples/` directory are sent **only** to the quality-review critic as a visual style reference. The generation stages never see them and no content from them is reproduced in output. They are git-ignored — see [Schema Directories](#schema-directories). You are responsible for having the rights to any sample you provide. |
| Reproducibility | Batch/packet runs write a manifest recording the command, model versions, git hash, and config. |

### Code & file execution (most important)

The document-generation agent uses tools that act on the host with the
privileges of the user running the CLI:

- **Code execution** — with the `reportlab` renderer the agent runs Python via a
  `shell` tool; with the HTML renderers (`xhtml2pdf`/`weasyprint`) it renders
  agent-authored HTML. Treat all agent-generated code in
  `output/generation_scripts/` as **untrusted model output** — do not blindly
  re-run it later.
- **Filesystem access** — file read/write tools operate on model-supplied paths
  with no built-in sandbox or path allowlist.
- **Tool consent** — the Strands Agents SDK can prompt for human approval before
  executing tools. Setting `BYPASS_TOOL_CONSENT=true` disables that prompt for
  autonomous runs; leave it **unset** when running on untrusted input so you can
  approve tool calls.

**Recommendation:** run the pipeline in an isolated environment (container or VM)
with no sensitive data on disk, restricted network egress, and dedicated,
least-privilege AWS credentials — not your personal developer profile.

### Untrusted schemas, guidance, and scenarios

`schema.json`, `generation_guidance.md`, sample PDFs, and the `--scenario` text
are all injected into agent prompts. Treat content from untrusted sources as a
**prompt-injection** vector: a malicious schema or guidance file could attempt to
steer an agent into misusing the code/file tools. Only run schemas you trust, or
run inside the isolated environment described above.

### AWS credentials

Model calls go to Amazon Bedrock using the credentials resolved from your
`AWS_PROFILE` (or an explicit boto3 session passed to `Generator`). Any code the
agent executes inherits that environment, so those credentials — and whatever
they can access — are reachable by agent-run code. Use a scoped, Bedrock-only
profile and avoid broad/admin credentials.

### Cost

Generation runs make repeated Bedrock calls and use critic-driven retry loops.
Large batch counts or high `--max-attempts` increase token spend. Keep
`--max-attempts`/`--timeout` conservative and monitor Bedrock usage.

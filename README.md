# Synthetically Engineered Evaluation Data (SEED)

AI-powered synthetic document generation pipeline built on the [Strands Agents SDK](https://strandsagents.com/). Produces realistic PDF documents from JSON schemas, validates them through multi-stage critique loops, and optionally applies image augmentation to simulate real-world scanning/faxing artifacts. Each document is paired with a ground-truth JSON label, so the output is a ready-made benchmark set.

Designed for building evaluation datasets for document understanding systems: OCR, Key Information Extraction (KIE), and document classification. The pipeline is invoked as a Python module (`python -m seed_data`) or through the batch and packet scripts.

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
seed-data --schema-dir ./schemas/fcc-invoice --output ./output
```

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
BYPASS_TOOL_CONSENT=true uv run python -m seed_data \
  --schema-dir src/seed_data/schemas/fcc-invoice

# Generate a diverse batch of 4 invoices with augmentation
BYPASS_TOOL_CONSENT=true uv run python scripts/batch_generate.py \
  --schema-dir src/seed_data/schemas/fcc-invoice \
  --count 4 --workers 2 --augment \
  --extra "FCC broadcast invoices for packaged food companies in the midwest"
```
</details>

## Architecture

### Single Document Pipeline

```
data_generator → data_critic → doc_generator → doc_critic → [augmentor → aug_critic]
                 ↑ (reject)                     ↑ (reject)
                 └─────────┘                     └──────────┘
```

### Batch Pipeline (Parallel)

```bash
uv run python scripts/batch_generate.py --count 10 --workers 3 --extra "your brief here"
```

1. **Scenario Generation**: An LLM reads your `--extra` brief + the schema's generation guidance and produces N unique, diverse scenario descriptions
2. **Parallel Execution**: Each scenario runs through the full single-doc pipeline in parallel via ThreadPoolExecutor
3. **Output**: PDFs, data JSON, augmented versions, and a batch manifest

The `--extra` flag is the key to diversity. It accepts a high-level brief that the scenario generator uses to create varied documents:

```bash
# Generic — less diverse
--extra "Generate diverse FCC invoices"

# Specific — much more diverse
--extra "FCC broadcast invoices for packaged food companies advertising in the midwest"
--extra "Local car dealership TV ads across small-market stations in the southeast"
--extra "Political campaign advertising during election season on major metro stations"
```

The scenario generator reads the schema's `generation_guidance.md` to understand the document type, then creates scenarios that vary advertisers, agencies, stations, regions, time periods, line item counts, and amounts.

## Agent Descriptions

| Agent | Role | Default Model |
|-------|------|---------------|
| Scenario Generator | Creates diverse scenarios from brief + guidance | `gpt-oss` |
| Data Generator | Produces JSON data from schema. Has calculator tool for math verification. | `nova2-lite` |
| Data Critic | Validates data against schema and domain rules. Has calculator tool. Structured output. | `sonnet` |
| Doc Generator | Writes HTML/CSS and renders to PDF via WeasyPrint. Has editor for targeted fixes. | `gpt-oss` |
| Doc Critic | Vision model evaluates PDF quality — layout, typography, truncation, math. Free-text output. | `sonnet` |
| Augmentor | Picks augraphy augmentation config and applies document aging effects. | `gpt-oss` |
| Aug Critic | Evaluates augmented doc for legibility and realism. Structured output. | `sonnet` |

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
uv run python -m seed_data --help
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

Configure AWS credentials with Bedrock access:
```bash
export AWS_PROFILE=your-profile-name
```

### Packet Pipeline (Multi-Document)

```bash
BYPASS_TOOL_CONSENT=true uv run python scripts/packet_generate.py \
  --packet src/seed_data/packets/lending-package \
  --count 3 --workers 2 --augment \
  --extra "First-time homebuyers in the Pacific Northwest applying for a 30-year fixed mortgage"
```

A packet is a set of different document types that share context — like a loan
application containing a credit report, pay stubs, and a statement of intent, all
for the same applicant. The pipeline:

1. **Shared Context Resolution**: An LLM reads all schemas in the packet and generates
   consistent shared values (names, addresses, dates). If the packet config defines
   explicit `shared_context` fields, those are used directly; otherwise the agent infers
   them from the schemas.
2. **Sub-Document Generation**: Each document type runs through the full single-doc
   pipeline with shared context injected as extra instructions.
3. **PDF Merging**: Individual PDFs are merged into a single multi-document PDF per packet.
4. **Label Emission**: Per-section `result.json` files with `document_class`,
   `page_indices`, and `inference_result` (KIE ground truth labels).

Output follows the evaluation dataset format for document splitting / classification:

```
output/packet_<name>_<timestamp>/
├── classes.yaml                    # Document type list
├── input/
│   ├── packet_001.pdf              # Merged multi-doc PDF
│   └── packet_002.pdf
├── baseline/
│   ├── packet_001.pdf/
│   │   └── sections/
│   │       ├── 1/result.json       # Sub-doc 1 labels
│   │       └── 2/result.json       # Sub-doc 2 labels
│   └── packet_002.pdf/
├── config/
│   ├── packet.json                 # Copy of packet config
│   └── packet_manifest.json        # Full run metadata
└── artifacts/                      # Intermediate files (individual PDFs, data JSONs)
    ├── packet_001/
    └── packet_002/
```

See [docs/packets.md](docs/packets.md) for the full guide — configuration, label format,
architecture, and design decisions.

See [Packet Configuration](#packet-configuration) for how to define packet types.

## Programmatic API

Besides the CLI, the batch and packet pipelines are available as a stable Python
API for embedding SEED in other tools (a document-processing accelerator, an
evaluation harness, etc.). The entry points are re-exported at the package top
level and resolve lazily, so `import seed_data` stays lightweight and only pulls
in the Strands/Bedrock stack when you actually call a pipeline:

```python
import seed_data

# Parallel batch of single documents; returns the batch manifest dict.
manifest = seed_data.run_batch(
    schema_dir="src/seed_data/schemas/fcc-invoice",
    count=5,
    brief="Local TV stations in the Pacific Northwest",
    output_dir="./output",
    augment=True,
)
docs = [d for d in manifest["documents"] if d["success"]]
# each doc: {"success", "pdf", "data_json", "augmented", ...}

# Multi-document packet; returns a PacketResult.
from seed_data.packet import load_packet_config
config = load_packet_config("src/seed_data/packets/lending-package")
result = seed_data.generate_packet(config, output_dir="./output")
```

Model calls use the AWS credentials resolved from your environment
(`AWS_PROFILE`), same as the CLI.

## Usage

### Single document

```bash
BYPASS_TOOL_CONSENT=true uv run python -m seed_data \
  --schema-dir src/seed_data/schemas/fcc-invoice \
  --extra "Local TV station in Portland, Oregon"
```

### Single document with augmentation

```bash
BYPASS_TOOL_CONSENT=true uv run python -m seed_data \
  --schema-dir src/seed_data/schemas/fcc-invoice \
  --extra "Local TV station in Portland, Oregon" \
  --augment
```

### Parallel batch generation (recommended)

```bash
BYPASS_TOOL_CONSENT=true uv run python scripts/batch_generate.py \
  --schema-dir src/seed_data/schemas/fcc-invoice \
  --count 10 --workers 3 \
  --extra "CPG brands on local TV stations in the American southwest" \
  --augment \
  --batch-name southwest_cpg
```

### CLI Options

Common flags (work for `__main__`, `batch_generate.py`, and `packet_generate.py` unless noted):

| Flag | Default | Description |
|------|---------|-------------|
| `--schema-dir` | required | Directory with `schema.json` + optional `*.md` steering docs |
| `--output` | `./output` | Output root directory |
| `--extra` | | Diversity brief — describes the theme/scenario for generation |
| `--data-model` | `nova2-lite` | Model for data generation |
| `--doc-model` | `gpt-oss` | Model for PDF generation |
| `--critic-model` | `sonnet` | Model for all critics |
| `--aug-model` | `gpt-oss` | Model for augmentation decisions |
| `--renderer` | `weasyprint` | PDF engine: `weasyprint` (HTML/CSS) or `reportlab` (Python) |
| `--augment` | off | Enable augraphy image augmentation |
| `--preview` | off | Enable visual self-inspection (requires VL model for doc-model) |
| `--threshold` | `7` | Acceptance score 1-10 (7 recommended, 8 requires edit cycles) |
| `--max-attempts` | `5` | Max feedback cycles per loop |
| `--timeout` | `3600` | Safety timeout in seconds |

Batch-only flags (`batch_generate.py`):

| Flag | Default | Description |
|------|---------|-------------|
| `--count` | `5` | Number of documents to generate |
| `--workers` | `3` | Max parallel workers (don't exceed 4-5 to avoid Bedrock rate limits) |
| `--batch-name` | timestamp | Name for the batch output directory |

Packet-only flags (`packet_generate.py`):

| Flag | Default | Description |
|------|---------|-------------|
| `--packet` | required | Path to packet config directory |
| `--count` | `1` | Number of packets to generate |
| `--workers` | `2` | Parallel packets within the batch |
| `--doc-workers` | `1` | Parallel sub-documents within each packet |
| `--shuffle` | off | Randomize sub-document order in merged PDF |
| `--context-model` | `gpt-oss` | Model for shared context resolution |

### What to expect from a batch

- A single document takes roughly 60-100 seconds end-to-end.
- With `--count 10 --workers 3` expect ~5-7 minutes wall-clock.
- Don't push `--workers` above 4-5 — you'll hit Bedrock rate limits.
- Partial failures are normal. If one doc fails, the others still complete and the
  manifest records which succeeded.
- Use a specific `--extra` brief. Vague briefs produce same-y output.

### Available Models

| Key | Model | Best For |
|-----|-------|----------|
| `gpt-oss` | GPT-OSS 120B | Doc generation, augmentation (fast tool calling) |
| `sonnet` | Claude Sonnet 4.6 | Critics (respects scope rules, good at evaluation) |
| `nova2-lite` | Amazon Nova 2 Lite | Data generation (fast, cheap, works with calculator) |
| `nemotron-super` | Nemotron Super 120B | Doc generation (slow but high first-pass quality) |
| `haiku` | Claude Haiku 4.5 | Fast critic (but less reliable at scope enforcement than sonnet) |

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

The scenario generator also reads this file to create diverse scenarios that respect the document type's constraints.

## Generation Choices

Document diversity comes from two sources of per-run variation:

1. **Optional fields with `x-probability`** — schema fields marked with an
   `x-probability` annotation are independently included or omitted per document
   based on their probability.
2. **Table presentation variations** — sections that can render either as tables
   or inline fields, declared in `generation_guidance.md` with ~50/50 probabilities.

See [docs/generation_choices.md](docs/generation_choices.md) for the full guide:
conventions, examples for nested and array fields, and how to add it to a new
document type.

## Output Structure

```
output/<batch-name>/
├── pdfs/                    # Clean PDFs
├── data/                    # Source data JSON per document
├── generation_scripts/      # HTML files used to render PDFs
├── augmented/               # Augmented PDFs (when --augment)
├── config/                  # Copy of schema + guidance for reproducibility
│   └── batch_manifest.json  # Full run metadata, scenarios, timing
```

## Tests

```bash
# Run the full unit-test suite (no LLM calls). Integration tests are excluded
# by default (see addopts in pyproject.toml).
uv run pytest

# Or run a single module
uv run pytest tests/test_unit.py -v

# Integration: isolated doc loop test (requires AWS credentials). Lives under
# tests/integration/ and is skipped by the default pytest run above.
BYPASS_TOOL_CONSENT=true uv run python tests/integration/test_doc_gen.py \
  --schema fcc-invoice --model gpt-oss --threshold 7
```

## Packet Configuration

Packet configs live in `src/seed_data/packets/<packet-name>/packet.json`.
See [docs/packets.md](docs/packets.md) for the full guide including config fields,
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

See the CLI Options section above for packet-specific flags.

## Security

doc-gen-agent runs AI agents that **write and execute code** and **read/write
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
  `shell` tool; with the default `weasyprint` renderer it renders agent-authored
  HTML. Treat all agent-generated code in `output/generation_scripts/` as
  **untrusted model output** — do not blindly re-run it later.
- **Filesystem access** — file read/write tools operate on model-supplied paths
  with no built-in sandbox or path allowlist.
- **Tool consent** — the documented run commands set `BYPASS_TOOL_CONSENT=true`,
  which disables the per-tool human-approval prompt. Leave it **unset** when
  running on untrusted input so you can approve tool calls.

**Recommendation:** run the pipeline in an isolated environment (container or VM)
with no sensitive data on disk, restricted network egress, and dedicated,
least-privilege AWS credentials — not your personal developer profile.

### Untrusted schemas, guidance, and briefs

`schema.json`, `generation_guidance.md`, sample PDFs, and the `--extra` brief are
all injected into agent prompts. Treat content from untrusted sources as a
**prompt-injection** vector: a malicious schema or guidance file could attempt to
steer an agent into misusing the code/file tools. Only run schemas you trust, or
run inside the isolated environment described above.

### AWS credentials

Model calls go to Amazon Bedrock using the credentials resolved from your
`AWS_PROFILE` (see [session.py](src/seed_data/session.py)). Any code the agent
executes inherits that environment, so those credentials — and whatever they can
access — are reachable by agent-run code. Use a scoped, Bedrock-only profile and
avoid broad/admin credentials.

### Cost

Generation runs make repeated Bedrock calls and use critic-driven retry loops.
Large batch counts or high `--max-attempts` increase token spend. Keep
`--max-attempts`/`--timeout` conservative and monitor Bedrock usage.

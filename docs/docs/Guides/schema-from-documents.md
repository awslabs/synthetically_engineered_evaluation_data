---
title: Schema from Documents
---

# Schema from Documents

Instead of hand-authoring a schema, you can point SEED at **real example
documents** and have a vision model reverse-engineer the schema for you. This is
the inverse of the generation pipeline: document → schema, which then feeds
straight back into generation to produce unlimited synthetic look-alikes with
ground-truth labels.

Two modes:

- **Single type** — one or more examples of the *same* document type → one
  schema. See [Same-type inference](#same-type-inference).
- **Packet** — one file that is *several different* document types concatenated
  (a lending package, a claim bundle) → one schema per document type, plus a
  packet definition. See [Packet inference](#packet-inference).

Inference reads the documents with a vision model, so `--infer-model` must be a
vision-capable model (`sonnet` is the default). Inputs may be **PDF, PNG, or
JPEG**, from **local paths, globs, directories, or `s3://` URIs**.

!!! note "Inferred schemas are a draft for review"
    The model infers structure and constraints from what it sees. A wrong
    `required` field or an over-specific rule would skew every document you
    later generate, so inference **writes the schema and stops** for you to
    review. Read `schema.json` and `generation_guidance.md`, adjust anything
    off, then generate.

## Same-type inference

Infer a schema from one or more examples of a single document type.

### CLI

```bash
# One example → a schema directory you can review and generate from
seed-data infer-schema ./samples/boarding_pass.pdf \
  --name boarding-pass --output ./schemas/boarding-pass

# Several examples sharpen the inference (which fields are always present,
# realistic value ranges). Globs, directories, and s3:// all work:
seed-data infer-schema './samples/*.pdf' --name invoice --output ./schemas/invoice
seed-data infer-schema s3://my-bucket/invoices/ --name invoice --output ./schemas/invoice
```

This writes a standard schema directory:

```text
schemas/boarding-pass/
├── schema.json               # inferred fields, types, required, x-probability
└── generation_guidance.md    # inferred visual style + data realism, with inference notes
```

Review it, then generate exactly as you would from any schema directory:

```bash
seed-data --schema-dir ./schemas/boarding-pass \
  --scenario "British Airways economy, transatlantic"
```

**One-shot** — infer and immediately generate, with `--then-generate`. The schema
is still written to `--output` first (so you keep it), then generation runs from
it. `--count > 1` produces a batch, mirroring the main command:

```bash
# infer, then generate one synthetic document
seed-data infer-schema ./samples/invoice.pdf --name invoice \
  --output ./schemas/invoice --then-generate --scenario "Midwest food distributor"

# infer, then generate a diverse batch of 10
seed-data infer-schema ./samples/invoice.pdf --name invoice \
  --output ./schemas/invoice --then-generate --count 10 \
  --scenario "Regional US food distributors"
```

### Python

`Generator.infer_schema(...)` returns a `Schema` object that drops straight into
`generate` / `generate_batch`:

```python
from seed_data import Generator, ModelConfig

gen = Generator(models=ModelConfig(doc="gpt-oss", critic="haiku"), threshold=5)

# infer a Schema (optionally write it to disk for review/reuse)
schema = gen.infer_schema(
    "./samples/*.pdf",
    name="invoice",
    output_dir="./schemas/invoice",   # optional; also returns the Schema
)

# generate from the inferred schema
doc = gen.generate(schema, scenario="Midwest food distributor")
print(doc.pdf_path, doc.data_json_path)
```

Or the one-shot convenience methods, which infer then generate in a single call:

```python
# infer → single
doc = gen.generate_from_samples(
    "./samples/invoice.pdf", name="invoice",
    scenario="IT consulting services", output_dir="./schemas/invoice",
)

# infer → batch
batch = gen.generate_batch_from_samples(
    "s3://my-bucket/invoices/", name="invoice",
    count=10, scenario="Regional US variety", output_dir="./schemas/invoice",
)
```

### Clarifying questions

Inferring from a *single* example has a natural limit: the model can't always tell
whether a field that appears once is *always* present, what a realistic value range
is, or what an ID format should be — but **you** often can. Enable a clarifying
dialogue and the model will ask you about exactly those ambiguities, and fold your
answers into the schema and guidance.

From the CLI, add `--allow-questions`:

```bash
seed-data infer-schema ./samples/invoice.pdf --name invoice \
  --output ./schemas/invoice --allow-questions
```

```text
↪ Does the PO number appear on every invoice, or only some?
  your answer > only on net-30 invoices, about half
↪ What's the realistic range for the invoice total?
  your answer > $500 to $50,000
```

The model asks a few targeted questions (capped, and only when genuinely
uncertain), then finalizes. It only prompts on an **interactive terminal** — in a
non-interactive shell (CI, a pipe, a background job) the flag is safely ignored so
a run never hangs waiting for input.

From Python, pass an `on_question` callback — the host decides how to collect the
answer (stdin, a notebook widget, a Slack DM, a web modal):

```python
def ask(question: str) -> str:
    return input(f"{question}\n> ")   # or any UI; return "" to decline

schema = gen.infer_schema(
    "./samples/invoice.pdf", name="invoice",
    output_dir="./schemas/invoice",
    on_question=ask,
)
```

`on_question` works on all four inference verbs (`infer_schema`, `infer_packet`,
`generate_from_samples`, `generate_batch_from_samples`). A `None`/empty answer or a
callback that raises degrades gracefully to "use your best judgment" — a dialogue
hiccup never aborts inference. Omit it (the default) to run fully
non-interactively.

## Packet inference

When you have **one file containing several different document types**
concatenated — a mortgage package (loan application + credit report + pay stubs),
an insurance claim bundle — packet inference splits it into its constituent
documents, infers a schema for each, and writes a packet definition. This is the
inverse of [packet generation](packets.md).

Add `--packet` to `infer-schema`. Here `--name` is the *packet* name and
`--output` is a *packet directory*:

```bash
seed-data infer-schema ./real/lending_package.pdf \
  --packet --name lending-package --output ./packets/lending-package
```

A vision model detects where each document starts and ends and classifies each
segment. If you already know the page boundaries, skip detection with
`--boundaries` (1-indexed, inclusive page ranges):

```bash
seed-data infer-schema ./real/lending_package.pdf \
  --packet --name lending-package --output ./packets/lending-package \
  --boundaries "1-3,4,5-8"
```

The result is a ready-to-use packet directory:

```text
packets/lending-package/
├── packet.json               # document_class + schema_dir per detected segment
├── loan-application/          # a full schema dir per document type
│   ├── schema.json
│   └── generation_guidance.md
├── credit-report/
│   └── ...
└── pay-stub/
    └── ...
```

Review it, then generate synthetic packets from it:

```bash
seed-data packet ./packets/lending-package \
  --scenario "First-time homebuyer in Portland, OR"
```

`--allow-questions` works here too: on an interactive terminal the model may ask
you to clarify an ambiguous split or a per-segment field before finalizing.

### Python

```python
from seed_data import Generator

gen = Generator()
out = gen.infer_packet(
    "./real/lending_package.pdf",
    name="lending-package",
    output_dir="./packets/lending-package",
    boundaries="1-3,4,5-8",   # optional page-range override
)
# then:
result = gen.generate_packet(out, scenario="First-time homebuyer in Portland, OR")
```

## What gets inferred

The inference produces two things per document type:

- **`schema.json`** — every visible field, typed, with nested objects for grouped
  fields (a `header`, an `address`) and arrays for repeating rows (line items,
  transactions). Fields present in every example are marked `required`; fields
  that come and go are marked optional with an `x-probability` estimate (which
  the generator honors for per-document variation). Descriptions capture observed
  constraints ("total = sum of line items", date formats, ID patterns).
- **`generation_guidance.md`** — the visual style (layout, columns, logo
  placement, totals box), realistic data ranges, math rules, and common
  variations, plus per-field *inference notes* so you can sanity-check the model's
  required/optional and type decisions.

## Tips

- **More examples = better inference** for the same-type mode. One document works,
  but 3–5 lets the model distinguish always-present fields from optional ones and
  estimate realistic value ranges — the same "specific input beats generic" effect
  as batch scenarios.
- **Always review before generating at scale.** Inference is a strong first draft;
  editing `generation_guidance.md` is the fastest way to correct or sharpen it.
- **Scanned/low-resolution documents** infer less reliably than clean digital
  PDFs — the vision model reads them, but faint or skewed scans yield fuzzier
  fields. Review those especially closely.
- **Packet splitting** expects the segments to tile the whole file (no gaps or
  overlaps). If the model mis-splits a tricky document, pass explicit
  `--boundaries`.

## Related

- [Creating a Document Type](creating-a-document-type.md): author a schema by hand.
- [Single Document](single-document.md) / [Batch Generation](batch-generation.md): generate from an inferred schema.
- [Packets](packets.md): generate coordinated multi-document sets (the inverse of packet inference).

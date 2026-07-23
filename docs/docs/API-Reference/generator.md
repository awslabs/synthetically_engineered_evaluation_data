---
title: Generator (Python API)
---

# Generator — Python API

The blessed programmatic surface. Import everything from the package top level:

```python
from seed_data import Generator, ModelConfig, Schema, GeneratedDoc, BatchResult
```

The mental model: **configure a `Generator` once** (models, threshold, renderer,
output directory), then call one of its verbs. Configuration lives on the
`Generator`; per-call arguments describe only *what* to make. Every verb returns a
typed result — no stringly-typed dicts.

**Generation** — make synthetic documents:

| Verb | Makes | Returns |
|---|---|---|
| `gen.generate(...)` | one document | `GeneratedDoc` |
| `gen.generate_batch(...)` | N diverse documents from one brief | `BatchResult` |
| `gen.generate_packet(...)` | a coordinated multi-document packet | `PacketResult` (or `list`) |

**Inference** — reverse-engineer a schema from real example documents, then feed it
back into generation (see [Schema from Documents](../Guides/schema-from-documents.md)):

| Verb | Makes | Returns |
|---|---|---|
| `gen.infer_schema(...)` | a `Schema` from sample doc(s) of one type | `Schema` |
| `gen.infer_packet(...)` | a packet dir from one concatenated multi-doc PDF | `str` (output dir) |
| `gen.generate_from_samples(...)` | infer, then generate one document | `GeneratedDoc` |
| `gen.generate_batch_from_samples(...)` | infer, then generate a batch | `BatchResult` |

See also the task-oriented guides:
[Single Document](../Guides/single-document.md) ·
[Batch Generation](../Guides/batch-generation.md) ·
[Packets](../Guides/packets.md) ·
[Schema from Documents](../Guides/schema-from-documents.md).

## `Generator(...)` — configure once

Every argument is keyword-only and optional; the defaults shown below are the real
defaults.

```python
from seed_data import Generator, ModelConfig

gen = Generator(
    models=ModelConfig(doc="gpt-oss", critic="haiku"),  # per-agent model choice; per-field defaults
    threshold=7,             # critic acceptance threshold, 1-10
    renderer="xhtml2pdf",    # PDF backend: "xhtml2pdf" (default) | "weasyprint" | "reportlab"
    output_dir="./output",   # root directory for generated artifacts
    max_attempts=5,          # max critic-retry attempts per document
    timeout=3600,            # per-document timeout, seconds
    critic_samples=True,     # include reference sample PDFs in the doc critic
    augment=False,           # apply image augmentation (aging/scanning) by default
    session=None,            # optional boto3 Session (containers/Lambda/AgentCore)
)

# Discover what's bundled with the package:
Generator.available_schemas()   # -> ["invoice", ...]
Generator.available_packets()   # -> ["lending-package", ...]
```

Passing `session` lets the generator run in-process with explicit credentials
(containers, Lambda, AgentCore). If omitted, credentials resolve from the
environment (`AWS_PROFILE`), and model IDs in `models` may be raw Bedrock IDs for
region portability (EU/GovCloud).

::: seed_data.api.Generator
    options:
      heading_level: 3
      show_root_heading: true
      show_source: true
      members_order: source

## `gen.generate(...)` — one document

Returns a [`GeneratedDoc`](#generateddoc). `schema` accepts a bundled schema name,
a path to a schema directory, or a [`Schema`](#schema-define-a-document-type-in-code)
object.

```python
from seed_data import Generator, ModelConfig

gen = Generator(models=ModelConfig(doc="gpt-oss"), threshold=7)

doc = gen.generate(
    "invoice",                              # bundled name, dir path, or a Schema
    scenario="Midwest food distributor, net-30 terms",  # what to generate this run
    augment=None,                           # None -> use the Generator's default; True/False overrides
    verbose=True,                           # print stage progress
)

if doc.success:
    print(doc.pdf_path)          # rendered PDF on disk
    print(doc.data_json_path)    # ground-truth JSON label on disk
    print(doc.data)              # the label loaded as a dict (lazy; None if missing)
    print(doc.verdict)           # "accepted" | "rejected" | "error" | "unknown"
    print(doc.score)             # critic score 0-10 (or None)
    print(doc.token_usage)       # {"inputTokens": ..., "outputTokens": ..., "totalTokens": ...}
else:
    print("failed:", doc.error)
```

## `gen.generate_batch(...)` — N documents from one brief

A planner turns `scenario` into `count` distinct scenarios; each runs its own pipeline
concurrently. Returns a [`BatchResult`](#batchresult).

```python
from seed_data import Generator, GeneratedDoc

gen = Generator(threshold=7)

def on_document(index: int, total: int, doc: GeneratedDoc) -> None:
    # Fired as each document's result is collected — for host-side progress UIs.
    print(f"[{index}/{total}] {doc.doctype}: {doc.verdict}")

batch = gen.generate_batch(
    "invoice",                       # bundled name, dir path, or a Schema
    count=10,
    scenario="Distributors across the US Midwest, varied totals and terms",
    augment=None,                    # None -> Generator default; True/False overrides
    seed=42,                         # optional: stable scenario set for regressions
    on_document=on_document,
)

print(batch.count_requested, batch.count_succeeded, batch.count_failed)
print(batch.total_tokens)            # summed across all documents

for doc in batch.succeeded:          # only the successful GeneratedDocs
    print(doc.pdf_path, doc.data_json_path)

for doc in batch.documents:          # every attempt, success or not
    print(doc.doctype, doc.success, doc.verdict)
```

## `gen.generate_packet(...)` — a coordinated packet

A packet is several inter-related document types that share context (e.g. a lending
package: credit report + pay stubs + statement of intent, all for one applicant).
Returns a `PacketResult` when `count == 1`, or a `list[PacketResult]` when `count > 1`.

```python
from seed_data import Generator

gen = Generator(threshold=7)

result = gen.generate_packet(
    "lending-package",       # packet dir path or bundled packet name
    count=1,                 # >1 returns a list[PacketResult]
    scenario="First-time homebuyer, 720 credit score",  # shared across the packet
    shuffle=False,           # randomize sub-document order in the merged PDF
    doc_workers=1,           # parallel workers for sub-documents within the packet
    augment=None,            # None -> Generator default; True/False overrides
)

print(result.merged_pdf)     # path to the single merged PDF for the whole packet

for section in result.sections:
    print(section.document_class)     # e.g. "credit_report"
    print(section.page_indices)       # pages this section occupies in the merged PDF
    print(section.inference_result)   # the section's ground-truth JSON label (dict)
```

## `gen.infer_schema(...)` — a Schema from example documents

Reverse-engineer a [`Schema`](#schema-define-a-document-type-in-code) from one or
more real example documents of the *same* type. `inputs` accepts local
paths/globs/directories and/or `s3://` URIs (PDF, PNG, or JPEG). Returns the
`Schema` (and, with `output_dir`, also writes `schema.json` + `generation_guidance.md`
there for review/reuse). See [Schema from Documents](../Guides/schema-from-documents.md).

```python
from seed_data import Generator

gen = Generator()

schema = gen.infer_schema(
    "./samples/*.pdf",          # path, glob, dir, or s3:// URI(s); PDF/PNG/JPEG
    name="invoice",             # the document-type name (schema title)
    model=None,                 # vision-capable model key; None -> "sonnet"
    max_docs=5,                 # cap on how many examples to feed the model
    output_dir="./schemas/invoice",  # optional: also write the schema for review
    on_question=None,           # optional callback -> clarifying dialogue (see below)
)

doc = gen.generate(schema, scenario="Midwest food distributor")
```

## `gen.infer_packet(...)` — a packet from one concatenated PDF

The inverse of `generate_packet`: takes a single file that is several *different*
document types concatenated, detects the boundaries + classes, infers a schema per
segment, and writes a packet directory (`packet.json` + one schema dir per segment)
ready for `generate_packet`. Returns the output directory path.

```python
gen = Generator()

out = gen.infer_packet(
    "./real/lending_package.pdf",   # one concatenated PDF (path or s3:// URI)
    name="lending-package",         # the packet name
    output_dir="./packets/lending-package",
    model=None,                     # vision-capable model; None -> "sonnet"
    boundaries="1-3,4,5-8",         # optional: fixed page ranges (else model-detected)
    on_question=None,               # optional clarifying dialogue (see below)
)

result = gen.generate_packet(out, scenario="First-time homebuyer in Portland, OR")
```

## `gen.generate_from_samples(...)` / `gen.generate_batch_from_samples(...)`

One-shot convenience: infer a schema from example documents, then immediately
generate from it. `generate_from_samples` → one `GeneratedDoc`;
`generate_batch_from_samples` → a `BatchResult`. Both persist the inferred schema
to `output_dir` (when given) so you keep an editable schema, not a throwaway.

```python
gen = Generator()

# infer -> single
doc = gen.generate_from_samples(
    "./samples/invoice.pdf", name="invoice",
    scenario="IT consulting services",
    output_dir="./schemas/invoice",   # optional; keeps the inferred schema
)

# infer -> batch (count>1). Same diversity/seed/on_document knobs as generate_batch.
batch = gen.generate_batch_from_samples(
    "s3://my-bucket/invoices/", name="invoice",
    count=10, scenario="Regional US variety",
    output_dir="./schemas/invoice",
)
```

## Clarifying dialogue (`on_question`)

All four inference verbs accept an `on_question` callback. When provided, the model
may ask you to clarify details it **cannot** determine from the document alone —
whether a field that appears once is always present, a realistic value range, an ID
format — and your answers shape the inferred schema. Without it (the default),
inference runs fully non-interactively.

```python
def ask(question: str) -> str:
    # Collect the answer however your host wants: stdin, a notebook widget,
    # a Slack DM, a web modal. Return "" to decline (the model uses its judgment).
    return input(f"{question}\n> ")

schema = gen.infer_schema("./samples/invoice.pdf", name="invoice", on_question=ask)
```

The callback is host-pluggable and safe: a `None`/empty answer or a raising callback
degrades to "use your best judgment" rather than aborting inference. The CLI wires
this to a terminal prompt via `--allow-questions` (interactive TTYs only).

## Result & config types

<a id="generateddoc"></a>

::: seed_data.stages.pipeline.GeneratedDoc
    options:
      heading_level: 3
      show_root_heading: true

<a id="batchresult"></a>

::: seed_data.api.BatchResult
    options:
      heading_level: 3
      show_root_heading: true

::: seed_data.stages.base.ModelConfig
    options:
      heading_level: 3
      show_root_heading: true

## Schema — define a document type in code

A `Schema` is an **in-code document type**: a JSON Schema (the fields/structure) +
generation guidance (prose steering data realism and visual style) + optional
reference sample PDFs. It's the same thing a schema directory holds on disk
(`schema.json` + `*.md` + `samples/`), but defined in Python — so you can call
`gen.generate(schema)` without any files on disk.

Fields:

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Authoritative — becomes the doctype title (overrides a pydantic model's class name). |
| `json_schema` | `dict \| None` | A raw JSON Schema dict. Provide this **or** `model`. |
| `model` | `BaseModel` subclass `\| None` | A pydantic model class, rendered to JSON Schema. Provide this **or** `json_schema`. |
| `generation_guidance` | `str` | Prose steering the generator and critic. |
| `sample_pdfs` | `list[str]` | Paths to existing reference PDFs; each must exist on disk. |

You must provide **exactly one** of `json_schema` or `model` — supplying both or
neither raises a `ValidationError`.

### From a pydantic model

```python
from pydantic import BaseModel
from seed_data import Generator, Schema

class Invoice(BaseModel):
    invoice_number: str
    vendor: str
    total: float

schema = Schema(
    name="invoice",                 # authoritative doctype title
    model=Invoice,                  # rendered to JSON Schema
    generation_guidance="Totals must equal the sum of line items; use net-30 terms.",
    sample_pdfs=[],                 # optional reference PDFs
)

gen = Generator()
doc = gen.generate(schema, scenario="Midwest food distributor")
```

### From a raw JSON Schema dict

```python
from seed_data import Generator, Schema

schema = Schema(
    name="invoice",
    json_schema={
        "type": "object",
        "properties": {
            "invoice_number": {"type": "string"},
            "vendor": {"type": "string"},
            "total": {"type": "number"},
        },
        "required": ["invoice_number", "vendor", "total"],
    },
    generation_guidance="Realistic vendor names; totals between $100 and $50,000.",
)

gen = Generator()
doc = gen.generate(schema)
```

### Loading one from a directory

`Schema.from_dir(path)` loads a `Schema` from an on-disk schema directory
(`schema.json` + `*.md` guidance + `samples/`):

```python
from seed_data import Schema

schema = Schema.from_dir("./schemas/invoice")
```

::: seed_data.schema.Schema
    options:
      heading_level: 3
      show_root_heading: true

---
title: Generator (Python API)
---

# Generator — Python API

The blessed programmatic surface. Import everything from the package top level:

```python
from seed_data import Generator, ModelConfig, Schema, GeneratedDoc, BatchResult
```

The mental model: **configure a `Generator` once** (models, threshold, renderer,
output directory), then call one of its three verbs. Configuration lives on the
`Generator`; per-call arguments describe only *what* to make. Every verb returns a
typed result — no stringly-typed dicts.

| Verb | Makes | Returns |
|---|---|---|
| `gen.generate(...)` | one document | `GeneratedDoc` |
| `gen.generate_batch(...)` | N diverse documents from one brief | `BatchResult` |
| `gen.generate_packet(...)` | a coordinated multi-document packet | `PacketResult` (or `list`) |

See also the task-oriented guides:
[Single Document](../Guides/single-document.md) ·
[Batch Generation](../Guides/batch-generation.md) ·
[Packets](../Guides/packets.md).

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
    extra="Midwest food distributor, net-30 terms",  # free-text brief steering content
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

A planner turns `brief` into `count` distinct scenarios; each runs its own pipeline
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
    brief="Distributors across the US Midwest, varied totals and terms",
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
    extra="First-time homebuyer, 720 credit score",  # brief shared across the packet
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
doc = gen.generate(schema, extra="Midwest food distributor")
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

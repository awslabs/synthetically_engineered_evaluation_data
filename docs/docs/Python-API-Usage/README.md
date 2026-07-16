---
title: Python API Usage
---

# Python API Usage

The `Generator` class is the programmatic entry point to SEED. It is configured
once, then exposes three methods that mirror the command line: `generate` for a
single document, `generate_batch` for a diverse set, and `generate_packet` for a
coordinated multi-document set. Each method returns a typed result.

## Installation and setup

Install the package and configure Amazon Bedrock credentials in the environment
(`AWS_PROFILE`, `AWS_REGION`) before generating:

```bash
pip install seed-data
```

Create a `Generator`, specifying the models and acceptance threshold to use:

```python
from seed_data import Generator, ModelConfig

gen = Generator(
    models=ModelConfig(data="gpt-oss", doc="gpt-oss", critic="haiku"),
    threshold=5,
    output_dir="./output",
)
```

## Single document

`generate` produces one document and returns a `GeneratedDoc`:

```python
doc = gen.generate("invoice", scenario="Midwest food-distributor invoice, 20 line items")

print(doc.success, doc.verdict, doc.score)
print("PDF:  ", doc.pdf_path)
print("Label:", doc.data_json_path)
```

A `GeneratedDoc` exposes the rendered PDF, the ground-truth label, and run metadata:

```python
doc.success            # bool
doc.pdf_path           # rendered PDF
doc.data               # ground-truth JSON label (lazy-loaded dict)
doc.data_json_path     # path to the label on disk
doc.verdict            # "accepted", "rejected", or "error"
doc.score              # critic score, 0–10
doc.augmented_path     # augmented PDF, when augmentation is enabled
doc.token_usage        # {"inputTokens", "outputTokens", "totalTokens"}
doc.error              # populated on failure
```

The `data` property loads the paired ground-truth label — the exact fields a
document-understanding system should extract from the PDF:

```python
doc = gen.generate("invoice")
if doc.success:
    label = doc.data
    print(label["invoice_number"], label["total"])
```

Individual runs can override the generator defaults:

```python
doc = gen.generate("invoice", augment=True)    # augment this run only
doc = gen.generate("invoice", verbose=False)   # suppress stage progress output
```

## Batch

`generate_batch` expands a single brief into N distinct scenarios, generates each
concurrently, and returns a `BatchResult`:

```python
batch = gen.generate_batch(
    "fcc-invoice",
    count=10,
    scenario="CPG brands on local TV stations in the American southwest",
)

print(batch.count_succeeded, "of", batch.count_requested)
for doc in batch.succeeded:
    print(doc.doc_id, doc.verdict, doc.pdf_path)
```

An optional `on_document` callback reports progress as each document completes:

```python
def on_doc(index, total, doc):
    print(f"[{index+1}/{total}] {doc.verdict:9} {doc.pdf_path or doc.error}")

batch = gen.generate_batch(
    "fcc-invoice", count=10,
    scenario="Political ad invoices during election season on metro-market stations",
    on_document=on_doc,
)
```

A `seed` makes scenario planning deterministic, producing regression-stable sets:

```python
batch = gen.generate_batch("invoice", count=5, scenario="...", seed=42)
```

A `BatchResult` collects every document and provides aggregate accessors:

```python
batch.documents          # list[GeneratedDoc], every result in order
batch.succeeded          # only the documents that passed
batch.count_succeeded    # int
batch.total_tokens       # summed across all documents
```

The results map directly onto an evaluation manifest:

```python
import json
manifest = [
    {"pdf": d.pdf_path, "label": d.data_json_path, "verdict": d.verdict}
    for d in batch.succeeded
]
json.dump(manifest, open("./output/manifest.json", "w"), indent=2)
```

## Packet

`generate_packet` produces a coordinated set of related document types that share
context and are merged into one multi-page PDF, returning a `PacketResult`:

```python
result = gen.generate_packet(
    "lending-package",
    scenario="First-time homebuyer in Portland, OR, 30-year fixed mortgage",
    doc_workers=3,
)

print(result.success, "->", result.merged_pdf)
for s in result.sections:
    print(f"  {s.document_class:24} pages={s.page_indices}  ok={s.success}")
```

A `PacketResult` exposes the merged PDF, the shared context, and one section per
sub-document:

```python
result.packet_id
result.merged_pdf                    # combined multi-page PDF
result.shared_context                # the consistent context shared across sections
result.sections                      # list[SectionResult], one per sub-document

section = result.sections[0]
section.document_class               # e.g. "Loan Application"
section.page_indices                 # pages this section occupies in the merged PDF
section.inference_result             # this section's ground-truth data (dict)
section.pdf_path
section.data_json_path
```

When `count` is greater than 1, `generate_packet` returns a list of `PacketResult`:

```python
results = gen.generate_packet("insurance-claim-packet", count=3,
                              scenario="Storm-damage claims in coastal Florida")
for r in results:
    print(r.packet_id, r.success, len(r.sections), "sections")
```

## Specifying a schema

Every method accepts a schema in three forms — a bundled name, a directory path, or
an in-code [`Schema`](../API-Reference/generator.md#schema-define-a-document-type-in-code):

```python
gen.generate("invoice")                     # bundled schema name
gen.generate("./my-schemas/invoice")        # directory path
gen.generate(my_schema_object)              # in-code Schema (below)
```

An in-code [`Schema`](../API-Reference/generator.md#schema-define-a-document-type-in-code)
defines a document type without files on disk, from either a pydantic model or a
raw JSON-Schema dictionary, plus generation guidance:

```python
from pydantic import BaseModel
from seed_data import Schema

class Invoice(BaseModel):
    invoice_number: str
    vendor: str
    total: float

schema = Schema(
    name="invoice",
    model=Invoice,                       # or: json_schema={...}
    generation_guidance="Totals must equal the sum of line items; US vendors.",
)
doc = gen.generate(schema, scenario="IT consulting services")

# A raw JSON-Schema dictionary instead of a model:
schema = Schema(name="wire", json_schema={
    "type": "object",
    "properties": {"amount": {"type": "number"}, "recipient": {"type": "string"}},
}, generation_guidance="Domestic wire transfer confirmations.")
```

An in-code `Schema` behaves identically across `generate`, `generate_batch`, and
`generate_packet`.

## See also

- [CLI Usage](../CLI-Usage/README.md) — the same three capabilities from the command line.
- [`Generator` API reference](../API-Reference/generator.md) — full method signatures.
- [Creating a Document Type](../Guides/creating-a-document-type.md) — authoring a schema.

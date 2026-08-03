---
title: Python API Usage
---

# Python API Usage

The `Generator` class is the programmatic entry point to SEED. It is configured
once, then exposes one verb per task, each mirroring the command line: `ingest`
turns whatever you have into a schema; `generate`, `generate_batch` and
`generate_packet` make documents from one; `generate_structured` makes tabular
data; and `run` does ingest plus generation end-to-end. Each verb returns a typed
result.

## Installation and setup

Install the package and configure Amazon Bedrock credentials in the environment
(`AWS_PROFILE`, `AWS_REGION`) before generating:

```bash
pip install seed-data
```

The base install covers the document pipeline, and `ingest` for every input kind
except example data. The structured verbs — `generate_structured`, and `run` with
`output="structured"` — need the `[structured]` extra
(pandas/numpy/scipy/openpyxl). Called without it, they report the missing
dependency rather than generating anything:

```bash
pip install "seed-data[structured]"
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

## Ingest

`ingest` is the front door for turning whatever you already have into a schema.
It takes one or more inputs, classifies each one, and returns a single
`InferredSchema` describing every entity it found:

```python
schema = gen.ingest(
    "Customers and the orders they place with a regional coffee wholesaler",
    "./samples/customers.csv",
    "./ddl/orders.sql",
    "./real/order_confirmation.pdf",
    name="coffee",
)
```

Inputs of different kinds can be combined in one call, as above — free-text
descriptions, example data, formal schemas, documents, and ERD diagrams are
detected per input, not per call. The detected kinds are:

```python
from seed_data import Generator

Generator.available_input_types()
# ['free_text', 'example_data', 'schema', 'document', 'erd']
```

Free-text, document, formal-schema and ERD inputs work in the base install.
Profiling an `example_data` file uses pandas, so pass those with the
`[structured]` extra installed.

An `InferredSchema` is a list of entities, each with its own fields:

```python
for entity in schema.entities:
    print(f"{entity.entity_name} — {len(entity.fields)} fields")
    for field in entity.fields:
        print(f"  {field.name:24} {field.type:10} "
              f"required={field.required} nullable={field.nullable}")
```

`required` and `nullable` are independent: `required` says the key must be
present, `nullable` says its value may be null. A required field can legitimately
carry a null value when the source document omits it. `required` is `None` when
the schema does not state it, which means "infer it from `nullable`".

The schema is a pydantic model, so writing it out for review or reuse — and
loading it back — is a one-liner in each direction:

```python
from pathlib import Path
from seed_data import InferredSchema

Path("./schema.json").write_text(schema.model_dump_json(indent=2))

schema = InferredSchema.model_validate_json(Path("./schema.json").read_text())
```

Editing that JSON by hand is the supported way to correct anything ingest got
wrong before you generate from it.

## Structured data

`generate_structured` generates tabular data from an `InferredSchema` and returns
a `StructuredResult`. It accepts an `InferredSchema` object, a path to an
`InferredSchema` JSON file, or a bundled schema name:

```python
gen.generate_structured(schema, rows=500)           # an InferredSchema object
gen.generate_structured("./schema.json", rows=500)  # a written InferredSchema
gen.generate_structured("invoice", rows=500)        # a bundled schema name
```

The result names every file it wrote, how many rows landed in each, and how the
data scored:

```python
result = gen.generate_structured(schema, rows=500, format="csv")

print(result.success, result.format)
for path in result.output_paths:
    print(path)                  # ./output/customer.csv, ./output/order.csv
print(result.row_counts)         # {'Customer': 500, 'Order': 500}
print(result.evaluation)         # {'diversity': 0.82, 'fidelity': 0.91, ...}
if not result.success:
    print(result.error)
```

`generate_structured` reports failure through the result rather than raising, so
always check `success` before reading `output_paths`, and print `error` when it is
`False`.

A `StructuredResult` carries the written files, the per-entity counts, and the
quality scores the pipeline gated on:

```python
result.success           # bool
result.schema            # the InferredSchema the data was generated from
result.output_paths      # list[str], one file per entity
result.format            # "csv", "parquet", "excel", or "json"
result.row_counts        # {entity name: rows written}
result.evaluation        # {metric name: score} — diversity, fidelity, coverage, structural
result.token_usage       # {"inputTokens", "outputTokens", "totalTokens"}
result.error             # populated on failure
```

`rows` is a target per entity, so `row_counts` can come in lower when records are
filtered by validation. One file per entity is written into the generator's
`output_dir`, named from the lowercased entity name with spaces replaced by
underscores. All four formats:

```python
gen.generate_structured(schema, rows=500, format="csv")       # customer.csv
gen.generate_structured(schema, rows=500, format="json")      # customer.json
gen.generate_structured(schema, rows=500, format="excel")     # customer.xlsx
gen.generate_structured(schema, rows=500, format="parquet")   # customer.parquet
```

`format="parquet"` additionally needs a parquet engine (`pip install pyarrow`),
which is not part of the `[structured]` extra.

The natural next step is to load the result back into pandas:

```python
import os
import pandas as pd

frames = {
    os.path.splitext(os.path.basename(path))[0]: pd.read_csv(path)
    for path in result.output_paths
}
print(frames["customer"].shape)
print(frames["order"].head())
```

## End-to-end (run)

`run` chains `ingest` into a generation verb, so no intermediate schema file is
needed. For structured output it returns a `StructuredResult`:

```python
result = gen.run(
    "Customers and the orders they place with a regional coffee wholesaler",
    "./samples/customers.csv",
    output="structured",
    name="coffee",
    rows=500,
    format="csv",
)
print(result.output_paths, result.row_counts)
```

For documents it sends the same ingested schema down the document pipeline:

```python
doc = gen.run(
    "./real/order_confirmation.pdf",
    output="documents",
    scenario="Pacific-northwest coffee wholesaler",
)

batch = gen.run(
    "./real/order_confirmation.pdf",
    output="documents",
    count=10,
    scenario="Coffee wholesalers across different US regions",
    entity="Order",
)
```

The return type follows the arguments: `output="structured"` returns a
`StructuredResult`; `output="documents"` returns a `GeneratedDoc` when `count` is
1, and a `BatchResult` when `count` is greater than 1. Any other `output` value
raises `ValueError`. When the modality is decided at runtime, branch on the type:

```python
from seed_data import BatchResult, GeneratedDoc, StructuredResult

def summarize(result: StructuredResult | GeneratedDoc | BatchResult) -> str:
    if isinstance(result, StructuredResult):
        return f"{len(result.output_paths)} files: {result.row_counts}"
    if isinstance(result, BatchResult):
        return f"{result.count_succeeded} of {result.count_requested} documents"
    if isinstance(result, GeneratedDoc):
        return f"one document: {result.pdf_path}"
    raise TypeError(f"unexpected result type {type(result).__name__}")

print(summarize(gen.run("./real/order_confirmation.pdf", output="documents")))
```

`run` takes no `seed`, and it has no equivalent of the CLI's `--save-schema`. For
structured output the ingested schema comes back on `result.schema`; for documents
there is no handle on it. Call `ingest` and the generation verb separately when you
want to keep the schema on disk, review it before generating, or need a `seed` for
a regression-stable batch.

## Specifying a schema

Every method accepts a schema in three forms — a bundled name, a directory path, or
an in-code [`Schema`](../API-Reference/generator.md#schema-define-a-document-type-in-code).
`generate` and `generate_batch` accept a fourth: an `InferredSchema`, the type
`ingest` returns:

```python
gen.generate("invoice")                     # bundled schema name
gen.generate("./my-schemas/invoice")        # directory path
gen.generate(my_schema_object)              # in-code Schema (below)
gen.generate(inferred_schema)               # InferredSchema, e.g. from gen.ingest(...)
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

An `InferredSchema` describes one or more entities, so `generate` and
`generate_batch` take an `entity=` argument to pick which one is rendered as the
document type. It defaults to the first entity:

```python
schema = gen.ingest("Customers and their orders for a coffee wholesaler", name="coffee")

doc   = gen.generate(schema, entity="Order", scenario="Pacific-northwest wholesaler")
batch = gen.generate_batch(schema, entity="Order", count=10,
                           scenario="Coffee wholesalers across different US regions")
```

The same `InferredSchema` object also feeds `generate_structured`, which uses
every entity rather than one.

## Inferring a schema from documents

Rather than authoring a schema, infer one from real example documents (PDF/PNG/JPEG,
local or `s3://`). `infer_schema` returns a `Schema` that feeds straight into the
generation verbs:

```python
schema = gen.infer_schema(
    "./samples/*.pdf", name="invoice",
    output_dir="./schemas/invoice",   # optional: also write it for review/reuse
)
doc = gen.generate(schema, scenario="Midwest food distributor")
```

The one-shot convenience methods infer then generate in a single call:

```python
doc   = gen.generate_from_samples("./samples/invoice.pdf", name="invoice",
                                  scenario="IT consulting services")
batch = gen.generate_batch_from_samples("s3://bucket/invoices/", name="invoice",
                                        count=10, scenario="Regional US variety")
```

For a single file containing several *different* document types concatenated,
`infer_packet` splits it, infers a schema per segment, and writes a packet
directory ready for `generate_packet`:

```python
out = gen.infer_packet("./real/lending_package.pdf", name="lending-package",
                       output_dir="./packets/lending-package",
                       boundaries="1-3,4,5-8")   # boundaries optional
result = gen.generate_packet(out, scenario="First-time homebuyer in Portland, OR")
```

See [Schema from Documents](../Guides/schema-from-documents.md) for the full guide.

## Evaluating what you generated

`seed_data.evaluation` scores finished output against the schema it came from, for
either modality.

`evaluate_document_labels` scores the ground-truth labels a document run produced
for field completeness and coverage, and flags fields that no document ever
populated. It is pure Python, so it works in the base install:

```python
from seed_data.evaluation import evaluate_document_labels

schema = gen.ingest("Purchase orders for a coffee wholesaler", name="coffee")
batch = gen.generate_batch(schema, entity="Order", count=10,
                           scenario="Coffee wholesalers across different US regions")

report = evaluate_document_labels(
    [doc.data for doc in batch.succeeded], schema, entity_name="Order",
)

print(report.document_count, report.field_count)
print(report.completeness_score, report.coverage_score, report.overall_score)
print(report.per_field_presence)   # {field path: fraction of documents with a value}
for issue in report.issues:
    print(issue)
```

`critique_structured` is the tabular counterpart: an LLM reads a sample of the
dataset (the first 25 rows per entity) and reviews it for intra-record logic,
cross-entity referential integrity, temporal coherence, realism, and
distributional tells:

```python
import os
import pandas as pd
from seed_data.evaluation import critique_structured

result = gen.generate_structured(schema, rows=500, format="csv")
by_stem = {os.path.splitext(os.path.basename(p))[0]: p for p in result.output_paths}
records = {
    entity: pd.read_csv(by_stem[entity.lower().replace(" ", "_")]).to_dict(orient="records")
    for entity in result.row_counts
}

verdict = critique_structured(
    records,
    result.schema,
    steering="Order dates must never precede the customer's signup date.",
    model="haiku",
    threshold=7,
)
print(verdict["score"], verdict["verdict"], verdict["summary"])
for issue in verdict["issues"]:
    print(issue)
```

It returns an advisory dict — `score`, `verdict`, `issues`, `summary` — and never
raises on a failed review. `verdict` is `"accepted"` or `"rejected"` against
`threshold`, or `"error"` with an extra `error` key if the reviewer was
unreachable, so a finished generation run is never lost to a critique failure.
`data` may also be a path to a JSON file holding the same entity-to-records
mapping.

The deterministic tabular scorers behind `StructuredResult.evaluation` are
available directly as `run_evaluation`, which needs the `[structured]` extra:

```python
from seed_data.evaluation import run_evaluation

report = run_evaluation(records, result.schema, quality_threshold=0.7)

print(report.overall_quality_score, report.passes_quality_gate)
print(report.overall_diversity_score, report.overall_fidelity_score)
print(report.overall_coverage_score, report.overall_structural_score)
for issue in report.issues:
    print(issue)
```

## See also

- [CLI Usage](../CLI-Usage/README.md) — the same capabilities from the command line.
- [Ingest](../Guides/ingest.md) — every input type and the `InferredSchema` it produces.
- [Structured Data](../Guides/structured-data.md) — the full tabular guide.
- [Schema from Documents](../Guides/schema-from-documents.md) — infer schemas from real documents.
- [`Generator` API reference](../API-Reference/generator.md) — full method signatures.
- [Creating a Document Type](../Guides/creating-a-document-type.md) — authoring a schema.

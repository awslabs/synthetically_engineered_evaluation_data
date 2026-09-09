---
title: Structured Data
---

# Structured Data

SEED generates **tabular and relational** synthetic data — CSV, Parquet, Excel,
JSON — from the same `InferredSchema` and through the same critique machinery the
document pipeline uses. One schema, two output shapes: rows when you need a
dataset, PDFs when you need documents.

Structured generation is opt-in, because it pulls in pandas and the file-format
engines (openpyxl, pyarrow):

```bash
pip install "seed-data[structured]"
```

The base `pip install seed-data` stays lean and covers documents only; it never
needs this extra. Structured commands raise a clear `ImportError` telling you to
install it.

Two ways in:

- **From a schema** — you already have an `InferredSchema` (from
  [plan](plan.md), from a bundled schema, or hand-authored). See
  [Generating from a schema](#generating-from-a-schema).
- **End to end** — inputs straight to rows in one shot, no intermediate schema
  file. See [The run shortcut](#the-run-shortcut).

## Generating from a schema

Generation runs a graph pipeline: distribution inference, sample generation, bulk
generation, then deterministic evaluation with retry and schema-revision loops
before export. If quality scores fall short the pipeline regenerates with
feedback, and after repeated failures it revises the schema and starts over.

### CLI

`generate-structured` accepts a bundled schema name, a path to an
`InferredSchema` JSON, or a schema directory:

```bash
# from a planned schema
seed-data generate-structured ./schema.json --rows 500 --format csv --output ./data

# from a bundled schema name
seed-data generate-structured invoice --rows 200 --format parquet --output ./data
```

| Flag | Default | Description |
|------|---------|-------------|
| `schema` | required | Bundled schema name, path to an `InferredSchema` JSON, or a schema directory |
| `--rows` | `100` | Target records per entity |
| `--format` | `csv` | `csv`, `parquet`, `excel`, or `json` |
| `--output` | `./output` | Output directory |
| `--quiet` | off | Suppress progress output |

On success it prints per-entity row counts, the files written, and the quality
scores:

```text
============================================================
  Customer: 500 rows
  Order: 500 rows
Files: ./data/customer.csv, ./data/order.csv
Quality: diversity=0.71, fidelity=0.88, coverage=0.62, structural=0.95
```

### Python

`Generator.generate_structured(...)` returns a typed `StructuredResult`:

```python
from seed_data import Generator

gen = Generator(output_dir="./data")
result = gen.generate_structured("./schema.json", rows=500, format="csv")

print(result.success, result.output_paths)
```

The schema argument accepts an `InferredSchema` object, a path to an
`InferredSchema` JSON, or a bundled schema name — so a planned schema goes
straight in without a round trip through disk:

```python
schema = gen.plan("./design/warehouse.dbml", "./samples/customers.csv", name="warehouse")
result = gen.generate_structured(schema, rows=1000, format="parquet")
```

Note that `rows`, `format`, and `verbose` are the only per-call arguments. Output
directory, models, threshold, and session live on the `Generator` — configure
once, generate many.

## Export formats

Four formats, chosen with `--format` / `format=`:

| Format | Extension | Notes |
|--------|-----------|-------|
| `csv` | `.csv` | The default |
| `json` | `.json` | Records-oriented, indented |
| `excel` | `.xlsx` | Written with openpyxl, from the `[structured]` extra |
| `parquet` | `.parquet` | Written with pyarrow, from the `[structured]` extra |

Every format works with the `[structured]` extra alone. If a parquet engine is
somehow missing (a hand-pinned environment, say), the export fails fast with a
message naming the install to run — before writing or clearing any files.

Each entity is written to **its own file** in the output directory. The file name
is the entity name lowercased with spaces replaced by underscores, plus the
format's extension. Entities named `Customer` and `Order` at `--format csv`
produce:

```text
data/
├── customer.csv
└── order.csv
```

An entity named `Line Item` becomes `line_item.csv`. A re-run clears only the
files this exporter would produce for the current entities, across every format —
so switching from `csv` to `parquet` does not leave a stale `customer.csv` behind,
and unrelated files in a shared output directory are left alone.

## Multi-entity schemas and referential integrity

An `InferredSchema` with several entities generates all of them in one run, and
the foreign keys between them are honored — child records reference parent
records that actually exist.

What drives this is each entity's `structured_relationships`: source
entity/field, target entity/field, and a cardinality of `one_to_one`,
`one_to_many`, or `many_to_many`. Generation is told to maintain integrity across
entities, then post-processing **validates every foreign-key value against the
parent's keys** and corrects or filters records that do not resolve. What
survives is scored: `referential_integrity` is the fraction of FK references that
resolve to an existing parent record, and it is a major term in the `structural`
score.

Relationships that come from an ERD or SQL DDL are explicit, which is why those
inputs give the best multi-entity results. If planning missed a foreign key, add it
to `structured_relationships` by hand before generating — free-text
`relationships` entries like `"belongs_to: Customer"` steer the generator but are
not what integrity enforcement and scoring read. See
[The InferredSchema](plan.md#the-inferredschema).

```python
result = gen.generate_structured(schema, rows=500)
print(result.row_counts)          # {'Customer': 500, 'Order': 500}
print(result.evaluation["structural"])
```

## Controlling volume

`--rows` / `rows=` is the target record count **per entity**, not in total. A
three-entity schema at `--rows 500` targets 1,500 records.

### CLI

```bash
seed-data generate-structured ./schema.json --rows 5000 --format parquet
```

### Python

```python
result = gen.generate_structured(schema, rows=5000, format="parquet")
```

It is a *target*, not a guarantee. Post-processing filters records that violate
schema constraints, so `result.row_counts` is the authoritative count of what
landed on disk. Start small while you are still reviewing a schema, then scale up
once the counts and scores look right.

## Reading StructuredResult

`StructuredResult` sits alongside `GeneratedDoc` and `BatchResult` — the
structured verb returns this, never a bare dict:

```python
result.success          # bool — True when files were written
result.schema           # the InferredSchema the data was generated from
result.output_paths     # list[str] — every file written
result.format           # "csv" | "parquet" | "excel" | "json"
result.row_counts       # dict[str, int] — rows actually written, per entity
result.evaluation       # dict[str, float] — diversity/fidelity/coverage/structural
result.token_usage      # {"inputTokens", "outputTokens", "totalTokens"}, as in GeneratedDoc
result.error            # populated on failure
```

A run can complete and still write nothing — for example if every record failed a
non-null constraint and was filtered out. That counts as a failure:
`success=False` with `error` explaining why, rather than a silent empty
directory.

```python
result = gen.generate_structured(schema, rows=500)
if not result.success:
    print("failed:", result.error)
else:
    for entity, count in result.row_counts.items():
        print(f"{entity}: {count} rows")
```

## Evaluating the result

Two complementary evaluators, both imported from `seed_data.evaluation`. One is an
LLM reviewer, the other is deterministic scoring.

`critique_structured` is the **semantic** review: an LLM reads the data against
the schema and reports what a human reviewer would notice. It checks
intra-record logic, cross-entity referential integrity, temporal coherence,
realism, and distributional tells. Large datasets are sampled (the first 25 rows
per entity) before prompting, which also keeps a critique reproducible.

```python
import json
from seed_data.evaluation import critique_structured

with open("./data/customer.json") as f:
    data = {"Customer": json.load(f)}

review = critique_structured(
    data,
    result.schema,
    steering="Credit scores must be consistent with the account tier.",
    model="haiku",
    threshold=7,
)
print(review["score"], review["verdict"])   # 1-10, "accepted" / "rejected"
print(review["summary"])
for issue in review["issues"]:
    print(" -", issue)
```

`data` may also be a **path** to a JSON file containing the
entity-name-to-records mapping. Critique is advisory and never raises: if the
model call fails you get `verdict="error"`, `score=0`, and an `error` key, so a
finished generation run is never lost because the reviewer was unreachable.
`verdict` is `"accepted"` when `score >= threshold`, otherwise `"rejected"`.

`run_evaluation` is the **deterministic** scorer — pure pandas, no model calls.
This is the same evaluation the generation pipeline runs internally, exposed so
you can score data yourself. It needs the `[structured]` extra.

```python
from seed_data.evaluation import run_evaluation

report = run_evaluation(data, result.schema, quality_threshold=0.7)
print(report.overall_quality_score, report.passes_quality_gate)
print(report.issues)
```

Four dimensions, each in `[0, 1]` and higher-is-better — the same keys that appear
in `StructuredResult.evaluation` and in the CLI's `Quality:` line:

| Score | What it measures |
|-------|------------------|
| `diversity` | Value variation: normalized entropy, unique-value ratio, and text dispersion. Low means repetitive, same-y rows. |
| `fidelity` | Conformance to the schema: the rate of constraint violations, plus how closely values match any declared distribution. Low means the data ignores its own schema. |
| `coverage` | How much of the specified value space was explored: enum values seen at least once, the proportion of numeric ranges used, observed value combinations. Low means whole regions of the schema went untested. |
| `structural` | Validity across entities: referential integrity, type conformance, and uniqueness. Low means broken foreign keys or duplicated unique keys. |

`overall_quality_score` is a weighted blend of the four, and
`passes_quality_gate` compares it to `quality_threshold`. `report.entity_reports`
carries the same breakdown per entity, and `report.issues` lists specific
problems — an entity with no records, a high constraint-violation rate, low
referential integrity.

For the document modality the counterpart is `evaluate_document_labels`, which
scores document ground-truth labels for field completeness and coverage and flags
fields never populated in any document. It is pure Python and works in the base
install with no extra.

## Both modalities from one schema

This is the payoff of unification. One planned `InferredSchema` drives structured
generation **and** document generation, so a tabular dataset and a set of PDFs
about the same domain come from the same declared fields, types, and constraints —
not two schemas you have to keep in sync by hand.

### CLI

```bash
# plan once
seed-data plan ./design/warehouse.dbml ./samples/customers.csv \
  --name warehouse --output ./schema.json

# review ./schema.json, then generate rows from it
seed-data generate-structured ./schema.json --rows 1000 --format csv --output ./data

# ...and PDFs from the very same schema
seed-data generate-documents ./schema.json --entity Customer --count 5 --output ./docs
```

`generate-documents` is the modern spelling of the default `--schema-dir` mode,
and it is what lets a planned or inferred `InferredSchema` drive the document
pipeline. For a multi-entity schema, `--entity` selects which entity to render as
the document type; it defaults to the first.

### Python

```python
from seed_data import Generator

gen = Generator()
schema = gen.plan(
    "./design/warehouse.dbml",
    "./samples/customers.csv",
    name="warehouse",
)

# tabular
rows = gen.generate_structured(schema, rows=1000, format="csv")
print(rows.row_counts)

# documents — same schema object
doc = gen.generate(schema, entity="Customer", scenario="Pacific Northwest region")
print(doc.pdf_path, doc.data_json_path)

# or a diverse batch of documents
batch = gen.generate_batch(schema, count=10, scenario="Pacific Northwest region",
                           entity="Customer")
```

## The run shortcut

`plan_and_generate` does planning and generation in a single call, so you go from inputs to
artifacts without an intermediate schema file.

### CLI

!!! note "On `plan-and-generate`, `--output` is the modality"
    On `plan-and-generate` — and **only** on `plan-and-generate` — `--output` selects the *modality*
    (`structured` or `documents`) and `--output-dir` selects the *path*. On every
    other command `--output` is a path. Passing a directory to `--output` here
    fails the choices check rather than silently writing somewhere unexpected.

```bash
# free text -> CSV, in one shot
seed-data plan-and-generate "Retail bank customers with credit scores and account tiers" \
  --output structured --rows 500 --format csv --output-dir ./data

# the same inputs -> a batch of PDFs
seed-data plan-and-generate ./samples/invoice.pdf \
  --output documents --count 5 --scenario "Midwest food distributors" \
  --output-dir ./docs

# keep the planned schema as well
seed-data plan-and-generate ./design/warehouse.dbml --output structured \
  --save-schema ./schema.json --output-dir ./data
```

| Flag | Default | Description |
|------|---------|-------------|
| `inputs` | required | One or more free-text description(s), file paths/globs, and/or `s3://` URIs |
| `--output` | `structured` | Which modality to generate: `structured` or `documents` |
| `--output-dir` | `./output` | Directory to write artifacts to |
| `--name` | `dataset` | Logical dataset name |
| `--save-schema` | | Also write the planned `InferredSchema` JSON here |
| `--rows` | `100` | structured only: target records per entity |
| `--format` | `csv` | structured only: `csv`, `parquet`, `excel`, or `json` |
| `--count` | `1` | documents only: how many to generate |
| `--scenario` | | documents only: what to generate this run |
| `--entity` | | documents only: which entity of a multi-entity schema to render |
| `--augment` | off | documents only: apply image augmentation |
| `--data-model` | `gpt-oss` | Model for data generation |
| `--doc-model` | `gpt-oss` | Model for PDF generation |
| `--critic-model` | `sonnet` | Model for critics |
| `--batch-model` | `nova2-lite` | Model for scenario planning |
| `--aug-model` | `gpt-oss` | Model for augmentation decisions |
| `--renderer` | `xhtml2pdf` | `xhtml2pdf` (pure Python), `weasyprint`, or `reportlab` |
| `--threshold` | `5` | Critic acceptance score, 1–10 |
| `--timeout` | `3600` | Safety timeout in seconds |
| `--quiet` | off | Suppress progress output |

`--save-schema` is worth using on any run you might repeat: the schema is written
before generation starts, so you keep it even if generation fails, and you can
review and reuse it instead of re-planning.

### Python

`Generator.plan_and_generate(...)` mirrors the flags. Its return type follows the output
modality — `StructuredResult` for `output="structured"`, `GeneratedDoc` for
`output="documents"` with `count=1`, and `BatchResult` for `output="documents"`
with `count > 1`:

```python
gen = Generator(output_dir="./data")

# structured -> StructuredResult
rows = gen.plan_and_generate("Retail bank customers and their orders", rows=500, format="csv")

# one document -> GeneratedDoc
doc = gen.plan_and_generate("./samples/invoice.pdf", output="documents",
              scenario="Midwest food distributor")

# many documents -> BatchResult
batch = gen.plan_and_generate("./samples/invoice.pdf", output="documents", count=10,
                scenario="Regional US food distributors")
```

An `output` other than `"structured"` or `"documents"` raises `ValueError`.

## Output layout

Structured output is one file per entity, directly in the output directory.
Documents keep their existing layout, so pointing both modalities at one root is
safe:

```text
output/
├── customer.csv                        # structured: one file per entity
├── order.csv
├── data/<doc_id>.json                  # documents: ground-truth JSON label
├── generation_scripts/<doc_id>.html    # documents: HTML used to render
└── pdfs/<doc_id>.pdf                   # documents: rendered PDF
```

## Related

- [Plan](plan.md): turn any input into the `InferredSchema` these commands consume.
- [CLI Usage](../CLI-Usage/README.md): every command and its flags.
- [Python API Usage](../Python-API-Usage/README.md): the same capabilities from Python.

---
title: Synthetically Engineered Evaluation Data
---

# Synthetically Engineered Evaluation Data

**Synthetically Engineered Evaluation Data (SEED)** is an AI-powered synthetic data generation pipeline. Point it at a schema — or at a plain-English description, a CSV, a JSON Schema, a SQL DDL, or example documents — and it generates one of two things: a realistic PDF document, validated through multi-stage critique loops and paired with a ground-truth JSON label; or realistic structured (tabular) data as CSV, Parquet, Excel, or JSON. The document path produces benchmark data for Intelligent Document Processing (IDP) systems: OCR, Key Information Extraction (KIE), and document classification. The structured path produces populated datasets for testing data pipelines, analytics, and models where real records cannot be used.

Every artifact is entirely fictional. Names, addresses, and financial figures are invented, each PDF is rendered from freshly generated HTML/CSS (or ReportLab) code, and structured rows are synthesized from inferred field distributions — so no real documents, templates, or records are copied into the output.

The pipeline is built on the [Strands Agents SDK](https://strandsagents.com/) and calls foundation models through Amazon Bedrock.

## Quickstart

Install from PyPI — the default renderer is pure Python, so there is nothing else to set up:

```bash
pip install seed-data
```

The base install covers the document pipeline. Structured (tabular) generation needs the `[structured]` extra, which adds pandas/numpy/scipy/openpyxl:

```bash
pip install "seed-data[structured]"
```

Configure AWS Bedrock credentials, then generate a document from either the command line or the Python API. Both produce the same artifacts.

**From the command line:**

```bash
export AWS_PROFILE=your-profile-name

# Copy the built-in schemas into a local, editable folder
seed-data clone-schema-library ./schemas

# Generate an invoice PDF + ground-truth JSON into ./output
seed-data --schema-dir ./schemas/invoice --output ./output
```

**From Python:**

```python
from seed_data import Generator, ModelConfig

gen = Generator(models=ModelConfig(doc="gpt-oss", critic="haiku"), threshold=5)
doc = gen.generate("invoice", scenario="Midwest food-distributor invoice")

print(doc.pdf_path)   # the rendered PDF
print(doc.data)       # ground-truth JSON label (dict)
```

Either path writes three paired artifacts into the output directory — the ground-truth JSON label, the HTML the renderer used, and the final PDF:

```text
output/
├── data/<id>.json                 # ground-truth data / label
├── generation_scripts/<id>.html   # render source
└── pdfs/<id>.pdf                  # final document
```

**Structured data instead of documents** — describe the dataset in prose, and `plan_and_generate` plans it into a schema and generates rows in one shot:

```bash
seed-data plan-and-generate "Customers and their orders for a regional coffee wholesaler" \
  --output structured --rows 500 --format csv --output-dir ./output
```

The same thing from Python:

```python
from seed_data import Generator

gen = Generator(output_dir="./output")
result = gen.plan_and_generate(
    "Customers and their orders for a regional coffee wholesaler",
    output="structured", rows=500, format="csv",
)

print(result.output_paths)   # e.g. ['./output/customer.csv', './output/order.csv']
print(result.row_counts)     # {'Customer': 500, 'Order': 500}
```

One file per entity lands in the output directory, named from the lowercased entity name. On `plan-and-generate`, note that `--output` selects the modality and `--output-dir` selects the path; on every other command `--output` is a path.

Browse the schema library on GitHub:
[awslabs/…/schemas](https://github.com/awslabs/synthetically_engineered_evaluation_data/tree/main/src/seed_data/schemas).

[:octicons-arrow-right-24: Full quickstart](Getting-Started/quick-start.md)

---

## How It Works

Each document flows through a chain of agents. Generation stages produce content and rendering; critic stages review the output and can reject it, sending the pipeline back for another attempt (bounded by `--max-attempts`). Augmentation stages are optional and run only with `--augment`.

```mermaid
graph LR
    A[data_generator] --> B[data_critic]
    B -->|reject| A
    B --> C[doc_generator]
    C --> D[doc_critic]
    D -->|reject| C
    D --> E[augmentor]
    E --> F[aug_critic]
    F -->|reject| E
```

The **data generator** produces JSON data from the schema, the **data critic** validates it against the schema and domain rules, the **doc generator** writes HTML/CSS and renders a PDF, and the **doc critic** uses a vision model to evaluate layout, typography, truncation, and math. With `--augment`, the **augmentor** applies aging effects via augraphy and the **aug critic** checks that the result is still legible.

Batch and packet runs wrap this single-document pipeline. A batch runs N scenarios in parallel from one diversity brief. A packet coordinates several different document types that share context (same person, address, and dates) and merges them into one multi-document PDF.

### Plan, then fork by modality

The agent chain above starts from a schema. Planning is what gets you one. Whatever you hand SEED — prose, example data, a formal schema, documents, an ERD — planning classifies each input, extracts what it can, and merges everything into a single `InferredSchema`. That schema is the fork point: it can drive structured generation or the document pipeline.

```mermaid
graph LR
    A["free text"] --> I[plan]
    B["example data (CSV/JSON/XLSX)"] --> I
    C["formal schema (JSON Schema/SQL DDL)"] --> I
    D["documents (PDF/PNG/JPEG)"] --> I
    E[ERD] --> I
    I --> S[InferredSchema]
    S --> T["structured -> CSV/Parquet/Excel/JSON"]
    S --> P["documents -> PDF + JSON label"]
```

`seed-data plan` writes the schema to disk so you can review and edit it; `generate-structured` and `generate-documents` each consume it. `seed-data plan-and-generate` chains planning and generation in one call when you do not need the intermediate file. Several inputs of different kinds can be combined in one planning call — a prose description plus a CSV of real examples, say.

### Key Use Case: Evaluation Data for IDP and KIE

Benchmarking a document understanding system requires paired data: an input document and the exact ground truth it should extract. Collecting real documents is slow, and real documents carry PII and redistribution constraints. SEED generates the pair directly: a schema defines the structure, the pipeline invents realistic fictional data, renders it to a PDF, critiques the render, and saves the source data JSON as the ground-truth labels. Add image augmentation to simulate scanning and faxing artifacts, and you have a controllable, reproducible evaluation set.

---

<div class="grid cards" markdown>

-   **Getting Started**

    ---

    Install SEED, configure AWS Bedrock credentials, and generate your first document, batch, and structured dataset.

    [:octicons-arrow-right-24: Get started](Getting-Started/README.md)

-   **Guides**

    ---

    Create a document type, run batches, build multi-document packets, control per-document variation, plan a schema from any input, and generate structured data.

    [:octicons-arrow-right-24: Read the guides](Guides/README.md)

-   **Advanced**

    ---

    Available models and model-agnostic design, PDF renderers, and image augmentation.

    [:octicons-arrow-right-24: Go deeper](Advanced/README.md)

-   **API Reference**

    ---

    The `Generator` Python API, `Schema` and `InferredSchema`, typed results, and module-level docs for packets, critique, tools, and utilities.

    [:octicons-arrow-right-24: Browse the API](API-Reference/README.md)

</div>

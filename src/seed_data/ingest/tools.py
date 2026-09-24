"""Input handling for the unified schema extraction agent.

One entry per input modality. Only :func:`analyze_example_data` is a *tool* — it
reads a file the model cannot see, from a path the prompt names. The rest are
plain functions: they take text the caller already has and return it with
format-specific parsing instructions, which :mod:`seed_data.ingest.extract`
inlines into the user message. As tools they were unusable, since only the model
supplies tool arguments and it never saw the text.

pandas is imported lazily (inside the example-data helpers) rather than at module
level: free-text / document / schema ingestion must work in the lean base install
without the ``[structured]`` extra, and this module is on that import path.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from strands import tool

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

SUPPORTED_DOCUMENT_FORMATS = {"pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"}


def parse_schema_definition(schema_text: str, format: str) -> str:
    """Parse a JSON Schema or SQL DDL definition into structured information.

    Args:
        schema_text: The raw schema string (JSON Schema or SQL DDL).
        format: Either 'json_schema' or 'sql_ddl'.

    Returns:
        The schema text with parsing context for the agent.
    """
    logger.info("parse_schema_definition tool — format: %s, length: %d", format, len(schema_text))

    # A lookup, not `json_schema else SQL DDL`: that binary labelled anything
    # unrecognized "SQL DDL", so a mislabelled or novel format arrived at the model
    # described as something it is not.
    format_label = {"json_schema": "JSON Schema", "sql_ddl": "SQL DDL"}.get(
        format, f"schema definition ({format})" if format else "schema definition"
    )

    return json.dumps({
        "format": format,
        "format_label": format_label,
        "schema_text": schema_text,
        "instructions": (
            f"This is a {format_label} definition. Parse it into entity schemas with "
            "complete field definitions, types, constraints, and relationships. "
            "For SQL DDL: map SQL types to SEED types, infer relationships from FOREIGN KEYs. "
            "For JSON Schema: map JSON Schema types/constraints to SEED format."
        ),
    })


@tool
def analyze_example_data(file_path: str) -> str:
    """Analyze a CSV, JSON or Excel file with example data to infer schema.

    Reads the file, computes statistical summaries (types, unique counts,
    sample values, ranges), and returns the analysis for schema inference.
    Each sheet of a multi-sheet workbook is treated as a separate entity.

    Args:
        file_path: Path to a .csv, .json, .xls or .xlsx file of example data.

    Returns:
        Statistical summary of the data for schema inference.
    """
    logger.info("analyze_example_data tool — file: %s", file_path)

    if not os.path.isfile(file_path):
        return json.dumps({"error": f"File not found: {file_path}"})

    ext = os.path.splitext(file_path)[1].lower()

    try:
        dataframes = _load_data(file_path, ext)
    except Exception as e:
        logger.error("Failed to load data: %s", e)
        return json.dumps({"error": f"Failed to load file: {e}"})

    summaries = []
    for entity_name, df in dataframes.items():
        summaries.append(f"=== Entity: {entity_name} ===")
        summaries.append(_summarize_dataframe(df))
        summaries.append("")

    full_summary = "\n".join(summaries)

    return json.dumps({
        "file": os.path.basename(file_path),
        "entities_found": list(dataframes.keys()),
        "summary": full_summary,
        "instructions": (
            "Infer a complete schema from this data summary. Determine semantic types "
            "(email, phone, date, uuid, enum) from sample values. Detect enums from low-cardinality "
            "columns. Infer constraints from statistics and null counts."
        ),
    })


def parse_erd(erd_text: str, format: str) -> str:
    """Parse an ERD diagram definition into structured information.

    Supports DBML, PlantUML, and Mermaid text formats.

    Args:
        erd_text: The ERD definition text.
        format: ERD format: 'dbml', 'plantuml', or 'mermaid'.

    Returns:
        The ERD text with parsing context for the agent.
    """
    logger.info("parse_erd tool — format: %s, length: %d", format, len(erd_text))

    format_labels = {
        "dbml": "DBML",
        "plantuml": "PlantUML",
        "mermaid": "Mermaid ERD",
    }
    format_label = format_labels.get(format, "ERD")

    return json.dumps({
        "format": format,
        "format_label": format_label,
        "erd_text": erd_text,
        "instructions": (
            f"This is a {format_label} definition. Extract all entities, fields with types "
            "and constraints, and all relationships with structured_relationships "
            "(source_entity, source_field, target_entity, target_field, cardinality). "
            "Cardinality notation: "
            "DBML '>' = many-to-one, '<' = one-to-many, '-' = one-to-one; "
            "Mermaid ||--o{{ = one-to-many, ||--|| = one-to-one; "
            "PlantUML '*' = many, '1' = one."
        ),
    })


def apply_schema_overrides(current_schema_text: str, override_instructions: str) -> str:
    """Apply user modifications to an existing schema.

    Takes the current schema JSON and free-text override instructions,
    and returns them together for the agent to process.

    Args:
        current_schema_text: JSON string of the current InferredSchema.
        override_instructions: Free-text instructions describing changes to make.

    Returns:
        The schema and instructions packaged for modification.
    """
    logger.info("apply_schema_overrides tool — instructions: %s", override_instructions[:100])

    return json.dumps({
        "current_schema": current_schema_text,
        "override_instructions": override_instructions,
        "instructions": (
            "Apply the override instructions to the current schema. "
            "Return the COMPLETE modified schema (not just the diff). "
            "Preserve everything not mentioned in the overrides. "
            "If adding a foreign key, also add the relationship definition."
        ),
    })


# ---------------------------------------------------------------------------
# Helper functions (moved from example_data_analysis.py)
# ---------------------------------------------------------------------------


def _load_data(file_path: str, ext: str) -> dict[str, "pd.DataFrame"]:
    import pandas as pd

    if ext == ".csv":
        df = pd.read_csv(file_path)
        entity_name = os.path.splitext(os.path.basename(file_path))[0]
        return {entity_name: df}

    elif ext in (".xls", ".xlsx"):
        # `detect_input_type` classifies .xls/.xlsx as EXAMPLE_DATA and routes them
        # here, so this branch must exist or every spreadsheet ingest fails.
        # Each sheet becomes its own entity — a workbook is the natural way to hand
        # over a multi-table dataset — falling back to the filename for a lone sheet
        # so single-sheet workbooks match the .csv naming.
        sheets = pd.read_excel(file_path, sheet_name=None)
        non_empty = {name: df for name, df in sheets.items() if not df.empty}
        if not non_empty:
            raise ValueError(f"No non-empty sheets found in {os.path.basename(file_path)}")
        if len(non_empty) == 1:
            only_name, only_df = next(iter(non_empty.items()))
            stem = os.path.splitext(os.path.basename(file_path))[0]
            # A default "Sheet1" carries no meaning; the filename does.
            entity_name = stem if only_name.lower().startswith("sheet") else only_name
            return {entity_name: only_df}
        return non_empty

    elif ext == ".json":
        with open(file_path) as f:
            raw = json.load(f)

        if isinstance(raw, list):
            entity_name = os.path.splitext(os.path.basename(file_path))[0]
            return {entity_name: pd.DataFrame(raw)}
        elif isinstance(raw, dict):
            if all(isinstance(v, list) for v in raw.values()):
                return {k: pd.DataFrame(v) for k, v in raw.items() if v}
            else:
                entity_name = os.path.splitext(os.path.basename(file_path))[0]
                return {entity_name: pd.DataFrame([raw])}

    raise ValueError(f"Unsupported file format: {ext}. Use .csv, .json, .xls or .xlsx")


def _summarize_dataframe(df: "pd.DataFrame") -> str:
    lines = []
    lines.append(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")
    lines.append("")

    lines.append("Columns and types:")
    for col in df.columns:
        dtype = str(df[col].dtype)
        nunique = df[col].nunique()
        null_count = df[col].isnull().sum()
        samples = df[col].dropna().head(5).tolist()
        sample_str = ", ".join(repr(s) for s in samples)
        lines.append(f"  - {col} (dtype={dtype}, unique={nunique}, nulls={null_count})")
        lines.append(f"    samples: [{sample_str}]")

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if numeric_cols:
        lines.append("")
        lines.append("Numeric statistics:")
        desc = df[numeric_cols].describe().to_string()
        lines.append(desc)

    return "\n".join(lines)

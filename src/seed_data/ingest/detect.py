"""Input-type auto-detection for the ingest pipeline.

Classifies each raw input string into an :class:`InputType`. Document/image and
``s3://`` inputs are deferred to :mod:`seed_data.inputs` (the v0.0.6 resolver);
this module only adds the non-document types the tabular pipeline introduces
(CSV/Excel example data, SQL DDL, JSON Schema, ERD text, and bare free-text).
"""

import os
from enum import Enum

from seed_data.inputs import SUPPORTED_EXTS


class InputType(str, Enum):
    FREE_TEXT = "free_text"
    EXAMPLE_DATA = "example_data"  # .csv / .json / .xlsx sample rows
    SCHEMA = "schema"              # .json JSON-Schema or .sql DDL
    DOCUMENT = "document"          # PDF/PNG/JPEG (local or s3://) — delegated to infer_schema
    ERD = "erd"                    # .dbml / .puml / .mmd ERD text


# Extensions handled locally by the structured pipeline (not documents).
_EXAMPLE_DATA_EXTS = {".csv", ".xls", ".xlsx"}
_SQL_EXTS = {".sql", ".ddl"}
_ERD_EXTS = {".dbml", ".puml", ".plantuml", ".mmd", ".mermaid"}


def _ext(spec: str) -> str:
    """Lowercased file extension including the dot, or '' if none."""
    return os.path.splitext(spec)[1].lower()


def detect_input_type(spec: str) -> InputType:
    """Classify a single input string.

    Args:
        spec: a path, glob, ``s3://`` URI, or a bare free-text description.

    Returns:
        The detected :class:`InputType`. Detection is by scheme + extension;
        anything without a recognized file extension is treated as free text.
    """
    # S3 URIs are always documents — resolution/handling lives in seed_data.inputs.
    if spec.startswith("s3://"):
        return InputType.DOCUMENT

    ext = _ext(spec)

    # Documents/images: defer classification to the shared inputs module's set.
    if ext in SUPPORTED_EXTS:
        return InputType.DOCUMENT

    if ext in _EXAMPLE_DATA_EXTS:
        return InputType.EXAMPLE_DATA
    if ext in _SQL_EXTS:
        return InputType.SCHEMA
    if ext in _ERD_EXTS:
        return InputType.ERD
    if ext == ".json":
        # A .json file that exists on disk is treated as a JSON-Schema definition;
        # otherwise it's most likely a bare description that happens to end in .json.
        if os.path.isfile(spec):
            return InputType.SCHEMA
        return InputType.FREE_TEXT

    # No recognized extension → free-text description.
    return InputType.FREE_TEXT

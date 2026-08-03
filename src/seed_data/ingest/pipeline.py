"""Ingest entry point: auto-detect inputs → unified :class:`InferredSchema`.

``run_ingest`` classifies each input (see :mod:`seed_data.ingest.detect`), routes
non-document inputs (free-text, CSV/Excel example data, JSON Schema, SQL DDL, ERD)
through the schema-extraction agent, and delegates document/image/``s3://`` inputs
to the existing vision path (:func:`seed_data.infer.infer_schema`), enriching that
``Schema`` into an ``InferredSchema``. The results are merged into a single schema.
"""

import logging

from seed_data.ingest.detect import InputType, detect_input_type
from seed_data.schema.models import InferredSchema

logger = logging.getLogger(__name__)

DEFAULT_INGEST_NAME = "dataset"


def run_ingest(
    *inputs: str,
    name: str = DEFAULT_INGEST_NAME,
    models=None,
    model: str | None = None,
    session=None,
    verbose: bool = True,
) -> InferredSchema:
    """Ingest any mix of inputs into a unified :class:`InferredSchema`.

    Args:
        *inputs: paths, globs, ``s3://`` URIs, or bare free-text descriptions.
        name: logical dataset name (used when delegating documents to infer_schema).
        models: optional ``ModelConfig`` from the Generator facade (its ``data``
            model key is used for extraction when set).
        model: explicit model key override for the extraction agent.
        session: optional boto3 Session (for Bedrock + S3).
        verbose: print progress.

    Returns:
        A single :class:`InferredSchema` merging every input's entities.

    Raises:
        ValueError: if no inputs are provided.
    """
    if not inputs:
        raise ValueError("run_ingest requires at least one input.")

    # Group inputs by detected type.
    buckets: dict[InputType, list[str]] = {}
    for spec in inputs:
        itype = detect_input_type(spec)
        buckets.setdefault(itype, []).append(spec)
        if verbose:
            logger.info("Ingest: '%s' → %s", spec, itype.value)

    entities = []

    # Documents/images/S3 → delegate to the existing vision inference path.
    doc_inputs = buckets.get(InputType.DOCUMENT, [])
    if doc_inputs:
        entities.extend(
            _ingest_documents(doc_inputs, name=name, model=model, session=session, verbose=verbose)
        )

    # Non-document inputs → the schema-extraction agent.
    for itype in (InputType.FREE_TEXT, InputType.EXAMPLE_DATA, InputType.SCHEMA, InputType.ERD):
        for spec in buckets.get(itype, []):
            schema = _extract_one(itype, spec)
            entities.extend(schema.entities)

    return InferredSchema(entities=entities)


def _ingest_documents(specs, *, name, model, session, verbose):
    """Delegate document inputs to infer_schema and enrich the result."""
    from seed_data.infer import infer_schema
    from seed_data.schema.io import from_json_schema

    doc_schema = infer_schema(
        list(specs), name=name, session=session, verbose=verbose,
        **({"model": model} if model else {}),
    )
    inferred = from_json_schema(doc_schema.to_schema_dict(), guidance=doc_schema.generation_guidance)
    return inferred.entities


def _extract_one(itype: InputType, spec: str) -> InferredSchema:
    """Run the schema-extraction agent for a single non-document input."""
    from seed_data.ingest.extract import schema_extraction_agent

    extract = schema_extraction_agent._tool_func

    if itype is InputType.FREE_TEXT:
        result = extract(text_description=spec)
    elif itype is InputType.EXAMPLE_DATA:
        result = extract(file_path=spec)
    elif itype is InputType.SCHEMA:
        schema_format = "sql_ddl" if spec.lower().endswith((".sql", ".ddl")) else "json_schema"
        text = _read_text(spec)
        result = extract(schema_input=text, schema_format=schema_format)
    elif itype is InputType.ERD:
        erd_format = _erd_format(spec)
        text = _read_text(spec)
        result = extract(erd_input=text, erd_format=erd_format)
    else:  # pragma: no cover - defensive
        raise ValueError(f"Unhandled input type: {itype}")

    return InferredSchema.model_validate_json(result)


def _read_text(spec: str) -> str:
    """Read a file's text if it exists on disk, else treat the spec as inline text."""
    import os

    if os.path.isfile(spec):
        with open(spec, encoding="utf-8") as f:
            return f.read()
    return spec


def _erd_format(spec: str) -> str:
    ext = spec.lower().rsplit(".", 1)[-1] if "." in spec else ""
    return {
        "dbml": "dbml",
        "puml": "plantuml",
        "plantuml": "plantuml",
        "mmd": "mermaid",
        "mermaid": "mermaid",
    }.get(ext, "dbml")

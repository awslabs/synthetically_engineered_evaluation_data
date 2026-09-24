"""Schema — an in-code document-type definition.

A document type is: a JSON Schema (the fields/structure), generation guidance
(prose steering data realism + visual style), and optional reference sample PDFs.
On disk that's a directory (``schema.json`` + ``*.md`` + ``samples/``). This module
lets you define the same thing in code, so ``generate()`` can accept either a
name/path (str) or a ``Schema`` object.

    from seed_data import Schema
    from pydantic import BaseModel

    # From a pydantic model:
    class Invoice(BaseModel):
        invoice_number: str
        total: float

    schema = Schema(
        name="invoice",
        model=Invoice,                      # rendered to JSON Schema
        generation_guidance="Totals must equal the sum of line items...",
    )

    # Or from a raw JSON Schema dict:
    schema = Schema(name="invoice", json_schema={...}, generation_guidance="...")

    gen.generate(schema)
"""
from __future__ import annotations

import os
from typing import Type

from pydantic import BaseModel, Field, model_validator


class Schema(BaseModel):
    """An in-code document-type definition.

    Provide exactly one of ``json_schema`` (a JSON Schema dict) or ``model`` (a
    pydantic model class, rendered to JSON Schema). ``generation_guidance`` is the
    prose steering the generator/critic; ``sample_pdfs`` are optional reference
    documents the doc critic compares against.
    """
    model_config = {"arbitrary_types_allowed": True}

    name: str
    json_schema: dict | None = None
    model: Type[BaseModel] | None = None
    generation_guidance: str = ""
    sample_pdfs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_source(self) -> "Schema":
        if (self.json_schema is None) == (self.model is None):
            raise ValueError(
                "Schema requires exactly one of `json_schema` or `model`."
            )
        for p in self.sample_pdfs:
            if not os.path.isfile(p):
                raise FileNotFoundError(f"sample_pdf not found: {p}")
        return self

    def to_schema_dict(self) -> dict:
        """The JSON Schema dict, with ``title`` set to ``name`` (the doctype).

        ``name`` is authoritative: a pydantic model's own title is its class name,
        which is rarely the doctype the user wants, so we override it.
        """
        schema = self.model.model_json_schema() if self.model is not None else dict(self.json_schema)
        schema["title"] = self.name
        return schema

    def resolve(self) -> tuple[dict, str, list[str]]:
        """Return ``(schema_dict, guidance_text, sample_pdfs)`` — the same shape
        as loading a schema directory, so the pipeline treats both uniformly."""
        return self.to_schema_dict(), self.generation_guidance, list(self.sample_pdfs)

    @classmethod
    def from_dir(cls, schema_dir: str) -> "Schema":
        """Load a Schema from a directory (schema.json + *.md + samples/)."""
        from seed_data.utils import load_schema_dir
        schema_dict, guidance, samples = load_schema_dir(schema_dir)
        name = str(schema_dict.get("title", os.path.basename(os.path.normpath(schema_dir))))
        return cls(name=name, json_schema=schema_dict,
                   generation_guidance=guidance, sample_pdfs=samples)

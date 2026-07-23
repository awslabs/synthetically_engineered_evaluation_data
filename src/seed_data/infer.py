"""Infer a document-type ``Schema`` from real sample documents.

This is the inverse of the generation pipeline: instead of schema → document, it
goes document(s) → schema. A vision model reads one or more real examples of a
document type and produces a JSON Schema (fields/structure) plus generation
guidance (visual style + data realism), which drops straight into ``generate()``
or ``generate_batch()`` to mint synthetic look-alikes with ground-truth labels.

The inferred schema is a **draft for human review** — a wrong ``required`` field
or a hallucinated constraint would silently skew every downstream synthetic doc,
so the recommended flow writes the schema dir and stops for the user to check it.
"""
from __future__ import annotations

import json
import os

from pydantic import BaseModel, Field
from strands import Agent

from seed_data import prompts
from seed_data.utils import make_model
from seed_data.inputs import resolve_inputs, Document

# Default number of example documents to feed the model. More examples sharpen
# required/optional and value-range inference, but cost tokens and hit model
# input limits; 5 is a sane ceiling that callers can override.
DEFAULT_MAX_DOCS = 5

# Inference reads images/PDFs, so the model must be vision-capable.
DEFAULT_INFER_MODEL = "sonnet"


class _InferredSchema(BaseModel):
    """Structured output the inference model returns."""
    json_schema: dict = Field(description="A draft-07 JSON Schema object capturing every visible field")
    generation_guidance: str = Field(description="Markdown: visual style, data realism, math rules, variations")
    field_notes: str = Field(default="", description="Per-field rationale for required/optional and type decisions")


def infer_schema(
    inputs: str | list[str],
    *,
    name: str,
    model: str = DEFAULT_INFER_MODEL,
    max_docs: int = DEFAULT_MAX_DOCS,
    session=None,
    on_question=None,
    verbose: bool = True,
) -> "Schema":  # noqa: F821  (Schema imported lazily to keep import light)
    """Infer a :class:`~seed_data.schema.Schema` from sample documents.

    Args:
        inputs: local path(s)/glob(s)/dir(s) and/or ``s3://`` URI(s) pointing at
            real example documents (PDF, PNG, or JPEG). Mixed freely.
        name: the document-type name (becomes the schema title / doctype).
        model: a vision-capable model key (default ``sonnet``).
        max_docs: cap on how many examples to feed the model.
        session: optional boto3 Session (used for both S3 and Bedrock).
        on_question: optional ``callback(question:str) -> answer:str`` enabling a
            clarifying dialogue — when provided, the model may ask the user about
            genuinely ambiguous details (required-vs-optional, value ranges). The
            callback collects the answer however the host wants (stdin, notebook,
            web). ``None`` (default) runs fully non-interactively.
        verbose: print progress.

    Returns:
        A ``Schema`` with the inferred ``json_schema`` and ``generation_guidance``.

    Raises:
        FileNotFoundError: if no supported documents could be resolved.
    """
    from seed_data.schema import Schema

    docs, skipped = resolve_inputs(inputs, session=session)
    if verbose and skipped:
        print(f"Skipped {len(skipped)} input(s):")
        for s in skipped:
            print(f"  - {s}")
    if not docs:
        raise FileNotFoundError(
            "No supported documents (PDF/PNG/JPEG) resolved from the given inputs."
        )

    used = docs[:max_docs]
    if verbose:
        print(f"Inferring '{name}' schema from {len(used)} document(s) "
              f"using {model}:")
        for d in used:
            print(f"  - {d.name} ({d.kind}, {len(d.data):,} bytes)")
        if len(docs) > max_docs:
            dropped = [d.name for d in docs[max_docs:]]
            print(f"  (capped at max_docs={max_docs}; not used: {', '.join(dropped)})")

    schema, guidance = _run_inference(
        used, name=name, model=model, session=session,
        on_question=on_question, verbose=verbose,
    )
    return Schema(name=name, json_schema=schema, generation_guidance=guidance)


def _run_inference(docs: list[Document], *, name: str, model: str,
                   session, on_question=None, verbose: bool = True) -> tuple[dict, str]:
    """One vision call: sample documents → (json_schema dict, guidance str).

    When ``on_question`` is provided, the agent is given an ``ask_user`` tool and
    may run a short clarifying dialogue before returning its structured answer.
    """
    system_prompt = prompts.render(
        "schema_inference", n_docs=len(docs), doctype=name,
        allow_questions=on_question is not None,
    )
    tools = []
    if on_question is not None:
        from seed_data.tools import make_ask_user_tool
        tools = [make_ask_user_tool(on_question)]
    agent = Agent(model=make_model(model, session=session), system_prompt=system_prompt, tools=tools)

    user_message: list = []
    for i, d in enumerate(docs):
        user_message.append({"text": f"--- Example document {i + 1} of {len(docs)}: {d.name} ---"})
        user_message.append(d.to_content_block())
    user_message.append({"text":
        f"Analyze the {len(docs)} example(s) above and produce the JSON Schema and "
        f"generation guidance for the '{name}' document type."})

    result = agent(user_message, structured_output_model=_InferredSchema)
    if result.structured_output is None:
        raise ValueError(
            "The model returned no structured schema (likely a content-filter or "
            "guardrail refusal on the document). Try a different --infer-model."
        )
    inferred: _InferredSchema = result.structured_output

    # Force the title to the requested name (authoritative doctype), regardless
    # of what the model put there — mirrors Schema.to_schema_dict.
    schema = dict(inferred.json_schema)
    schema["title"] = name

    guidance = inferred.generation_guidance
    if inferred.field_notes:
        guidance = (guidance.rstrip()
                    + "\n\n---\n\n## Inference Notes\n\n"
                    + "_Auto-generated from sample documents — review before generating._\n\n"
                    + inferred.field_notes.strip() + "\n")

    if verbose:
        n_props = len(schema.get("properties", {}))
        n_required = len(schema.get("required", []))
        print(f"Inferred schema: {n_props} top-level field(s), {n_required} required.")

    return schema, guidance


def write_schema_dir(schema: "Schema", dest: str) -> str:  # noqa: F821
    """Write an inferred ``Schema`` to a directory as ``schema.json`` +
    ``generation_guidance.md`` — the on-disk shape ``--schema-dir`` expects.

    Returns the destination path. Raises if ``dest`` exists as a non-empty dir
    with a schema already in it (avoid clobbering hand-edited work).
    """
    os.makedirs(dest, exist_ok=True)
    schema_path = os.path.join(dest, "schema.json")
    guidance_path = os.path.join(dest, "generation_guidance.md")

    if os.path.exists(schema_path):
        raise FileExistsError(
            f"A schema already exists at {schema_path}. "
            "Choose a different --output or remove it first."
        )

    with open(schema_path, "w") as f:
        json.dump(schema.to_schema_dict(), f, indent=2)
        f.write("\n")
    if schema.generation_guidance:
        with open(guidance_path, "w") as f:
            f.write(schema.generation_guidance)
            if not schema.generation_guidance.endswith("\n"):
                f.write("\n")
    return dest

"""Public Python API for seed-data.

The blessed entry point is the :class:`Generator` — construct it once with your
configuration (models, threshold, renderer, output directory), then call a verb.

Generation verbs make synthetic documents:

    from seed_data import Generator, ModelConfig

    gen = Generator(models=ModelConfig(doc="gpt-oss", critic="haiku"), threshold=5)

    doc    = gen.generate("invoice", scenario="Midwest food distributors")
    docs   = gen.generate_batch("invoice", count=10, scenario="...")
    packet = gen.generate_packet("lending-package", count=3)

Inference verbs reverse-engineer a schema from real example documents, then feed
it back into generation:

    schema = gen.infer_schema("./samples/*.pdf", name="invoice")
    out    = gen.infer_packet("./lending_package.pdf", name="lending-package",
                              output_dir="./packets/lending-package")
    doc    = gen.generate_from_samples("./invoice.pdf", name="invoice", scenario="...")
    docs   = gen.generate_batch_from_samples("./invoice.pdf", name="invoice",
                                             count=10, scenario="...")

Configuration lives on the ``Generator``; per-call arguments describe only *what*
to make. Every verb returns a typed result (``GeneratedDoc`` / ``BatchResult`` /
``PacketResult`` / ``Schema``) — no stringly-typed dicts.

``generate()`` runs the modern staged pipeline (``seed_data.stages.pipeline``).
``generate_batch()`` and ``generate_packet()`` wrap the existing batch/packet
engines; the inference verbs live in ``seed_data.infer`` / ``seed_data.packet_infer``.
The engines are internal; this facade is the supported surface.
"""
from __future__ import annotations

import json
import os
import warnings
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, Field

from seed_data.schema.models import InferredSchema
from seed_data.stages.base import ModelConfig
from seed_data.stages.pipeline import GeneratedDoc, generate as _pipeline_generate

if TYPE_CHECKING:
    # Only used in string annotations (legacy in-code schema); imported here so
    # tools that evaluate annotations resolve the name, without a runtime import.
    from seed_data.schema import Schema


class BatchResult(BaseModel):
    """Typed result of a batch run — the per-document results plus a rollup."""
    count_requested: int
    count_succeeded: int
    count_failed: int
    documents: list[GeneratedDoc] = Field(default_factory=list)

    @property
    def succeeded(self) -> list[GeneratedDoc]:
        return [d for d in self.documents if d.success]

    @property
    def total_tokens(self) -> int:
        return sum(d.token_usage.get("totalTokens", 0) for d in self.documents)


# ``StructuredResult.schema`` shadows ``BaseModel.schema`` (pydantic v1's
# deprecated JSON-Schema accessor), which makes pydantic emit a UserWarning at
# class-creation time. There is no config knob for it, and ``schema`` is the
# right name for the field, so scope a filter to just this class definition
# instead of renaming — otherwise the warning prints on every CLI invocation.
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=r'Field name "schema" in "StructuredResult" shadows an attribute',
        category=UserWarning,
    )

    class StructuredResult(BaseModel):
        """Typed result of a structured-data generation run.

        Sits alongside ``GeneratedDoc`` / ``BatchResult`` / ``PacketResult`` — the
        structured verb returns this, never a bare dict.
        """
        success: bool
        schema: InferredSchema
        output_paths: list[str] = Field(default_factory=list)   # written files
        format: str                                            # csv | parquet | excel | json
        row_counts: dict[str, int] = Field(default_factory=dict)  # per-entity row count
        evaluation: dict[str, float] = Field(default_factory=dict)  # metric scores
        token_usage: dict = Field(
            default_factory=lambda: {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
        )
        error: str | None = None


class Generator:
    """Configure once, generate many. The main entry point for seed-data.

    Args:
        models: Which model each agent uses (``ModelConfig``). Defaults applied
            per-field, so ``ModelConfig(doc="gpt-oss")`` overrides only the doc model.
        threshold: Critic acceptance threshold, 1-10.
        renderer: PDF backend — "xhtml2pdf" (default, pure Python), "weasyprint",
            or "reportlab".
        output_dir: Root directory for generated artifacts.
        max_attempts: Max critic-retry attempts per document.
        timeout: Per-document timeout (seconds).
        critic_samples: Include reference sample PDFs in the doc critic.
        augment: Apply image augmentation (aging/scanning artifacts) by default.
        session: Optional boto3 Session for in-process use (containers, Lambda,
            AgentCore). If omitted, credentials resolve from the environment
            (``AWS_PROFILE``). Model IDs in ``models`` may be raw Bedrock IDs for
            region portability (EU/GovCloud).
    """

    def __init__(
        self,
        *,
        models: ModelConfig | None = None,
        threshold: int = 7,
        renderer: str = "xhtml2pdf",
        output_dir: str = "./output",
        max_attempts: int = 5,
        timeout: int = 3600,
        critic_samples: bool = True,
        augment: bool = False,
        session: Any = None,
    ):
        self.models = models or ModelConfig()
        self.threshold = threshold
        self.renderer = renderer
        self.output_dir = output_dir
        self.max_attempts = max_attempts
        self.timeout = timeout
        self.critic_samples = critic_samples
        self.augment = augment
        self.session = session

    def __repr__(self) -> str:
        return (
            f"Generator(models={self.models!r}, threshold={self.threshold}, "
            f"renderer={self.renderer!r}, output_dir={self.output_dir!r})"
        )

    # -- verbs ---------------------------------------------------------------

    def generate(
        self,
        schema: "str | Schema | InferredSchema",
        *,
        scenario: str = "",
        augment: bool | None = None,
        entity: str | None = None,
        verbose: bool = True,
    ) -> GeneratedDoc:
        """Generate a single document. Returns a typed ``GeneratedDoc``.

        Args:
            schema: One of —
                - a bundled schema name (e.g. ``"invoice"``),
                - a path to a schema directory,
                - a :class:`Schema` object defined in code (JSON schema or a
                  pydantic model, plus generation guidance), or
                - an :class:`InferredSchema` (e.g. from ``ingest``), adapted
                  internally to the pipeline's schema triple.
            scenario: Free-text describing what to generate this run (the vendor,
                industry, region, size, etc.) — steers the content.
            augment: Override the instance's augment setting for this call.
            entity: For a multi-entity ``InferredSchema``, which entity to render
                as the document type. Defaults to the first.
            verbose: Print stage progress.
        """
        common = dict(
            output_dir=self.output_dir,
            extra=scenario,
            models=self.models,
            threshold=self.threshold,
            max_attempts=self.max_attempts,
            timeout=self.timeout,
            renderer=self.renderer,
            critic_samples=self.critic_samples,
            augment=self.augment if augment is None else augment,
            verbose=verbose,
            session=self.session,
        )
        resolved = self._resolve_for_documents(schema, entity=entity)
        if resolved is not None:
            return _pipeline_generate(resolved=resolved, **common)
        return _pipeline_generate(schema_dir=self._resolve_schema(schema), **common)

    def generate_batch(
        self,
        schema: "str | Schema | InferredSchema",
        *,
        count: int,
        scenario: str,
        augment: bool | None = None,
        entity: str | None = None,
        seed: int | None = None,
        on_document: Callable[[int, int, GeneratedDoc], None] | None = None,
        verbose: bool = True,
    ) -> BatchResult:
        """Generate a diverse batch of documents from one high-level scenario.

        A planner turns ``scenario`` into ``count`` distinct, specific scenarios;
        each runs its own self-contained pipeline graph as a sibling node, and
        Strands executes them concurrently.

        ``schema`` accepts a bundled name, a directory path, a ``Schema``, or an
        ``InferredSchema``.

        Args:
            scenario: The high-level theme the planner diversifies into ``count``
                specific documents. A specific scenario yields far more varied
                output than a generic one.
            entity: For a multi-entity ``InferredSchema``, which entity to render.
            seed: optional seed for scenario planning (regression-stable sets).
            on_document: optional ``callback(index, total, GeneratedDoc)`` fired as
                each document's result is collected — for host-side progress UIs.
        """
        from seed_data.stages.batch import generate_batch as _batch

        common = dict(
            count=count, brief=scenario, output_dir=self.output_dir,
            models=self.models, threshold=self.threshold,
            max_attempts=self.max_attempts, timeout=self.timeout,
            renderer=self.renderer, critic_samples=self.critic_samples,
            augment=self.augment if augment is None else augment,
            verbose=verbose, session=self.session, seed=seed,
            on_document=on_document,
        )
        resolved = self._resolve_for_documents(schema, entity=entity)
        if resolved is not None:
            docs = _batch(resolved=resolved, **common)
        else:
            docs = _batch(schema_dir=self._resolve_schema(schema), **common)

        succeeded = sum(1 for d in docs if d.success)
        return BatchResult(
            count_requested=count,
            count_succeeded=succeeded,
            count_failed=len(docs) - succeeded,
            documents=docs,
        )

    def generate_packet(
        self,
        packet: str,
        *,
        count: int = 1,
        scenario: str = "",
        shuffle: bool = False,
        doc_workers: int = 1,
        augment: bool | None = None,
    ):
        """Generate a coordinated multi-document packet.

        Args:
            packet: Path to a packet directory (containing a packet config), or a
                bundled packet name.
            count: Number of packets to generate.
            scenario: Free-text scenario shared across the packet's documents
                (the same applicant, situation, etc.).
            shuffle: Randomize sub-document order in the merged PDF.
            doc_workers: Parallel workers for sub-documents within a packet.

        Returns a ``PacketResult`` (count==1) or a list of them (count>1).
        """
        from seed_data.packet import load_packet_config, generate_packet as _gen_packet

        config = load_packet_config(self._resolve_packet(packet))
        common = dict(
            output_dir=self.output_dir,
            extra=scenario,
            shuffle=shuffle,
            doc_workers=doc_workers,
            data_model=self.models.data,
            doc_model=self.models.doc,
            critic_model=self.models.critic,
            aug_model=self.models.aug,
            context_model=self.models.batch,
            threshold=self.threshold,
            max_attempts=self.max_attempts,
            timeout=self.timeout,
            augment=self.augment if augment is None else augment,
            critic_samples=self.critic_samples,
            renderer=self.renderer,
        )
        if count == 1:
            return _gen_packet(config=config, **common)
        return [_gen_packet(config=config, **common) for _ in range(count)]

    # -- schema inference (documents -> Schema) ------------------------------

    def infer_schema(
        self,
        inputs: "str | list[str]",
        *,
        name: str,
        model: str | None = None,
        max_docs: int = 5,
        output_dir: str | None = None,
        on_question: "Callable[[str], str] | None" = None,
        verbose: bool = True,
    ) -> "Schema":
        """Infer a document-type ``Schema`` from real sample documents.

        The inverse of ``generate``: reads one or more real examples (PDF, PNG, or
        JPEG; local paths/globs/dirs and/or ``s3://`` URIs) with a vision model and
        returns a ``Schema`` (JSON Schema + generation guidance) ready to feed back
        into ``generate`` / ``generate_batch``.

        Args:
            inputs: sample document location(s) — mixed local and S3 accepted.
            name: the document-type name (becomes the schema title / doctype).
            model: vision-capable model key; defaults to ``sonnet``.
            max_docs: cap on how many examples to feed the model.
            output_dir: if given, also write the inferred schema there as
                ``schema.json`` + ``generation_guidance.md`` for review/reuse.
            on_question: optional ``callback(question) -> answer`` enabling a
                clarifying dialogue — the model may ask about ambiguous details
                (required-vs-optional, value ranges) and the callback collects the
                answer (stdin, notebook, web). ``None`` runs non-interactively.
            verbose: print progress.

        Returns:
            The inferred ``Schema`` (always returned, even when also written).
        """
        from seed_data.infer import infer_schema as _infer, write_schema_dir, DEFAULT_INFER_MODEL
        schema = _infer(
            inputs, name=name, model=model or DEFAULT_INFER_MODEL,
            max_docs=max_docs, session=self.session,
            on_question=on_question, verbose=verbose,
        )
        if output_dir:
            write_schema_dir(schema, output_dir)
            if verbose:
                print(f"Wrote inferred schema to {output_dir}/ (schema.json + generation_guidance.md)")
        return schema

    def infer_packet(
        self,
        inputs: "str | list[str]",
        *,
        name: str,
        output_dir: str,
        model: str | None = None,
        boundaries: str | None = None,
        on_question: "Callable[[str], str] | None" = None,
        verbose: bool = True,
    ) -> str:
        """Infer a packet definition from ONE concatenated multi-document PDF.

        The inverse of ``generate_packet``: takes a single file containing several
        *different* document types concatenated (e.g. a lending package), detects
        the document boundaries + classes with a vision model (or a ``boundaries``
        page-range override), infers a schema per segment, and writes a
        ``packet.json`` + one schema dir per segment to ``output_dir`` — the shape
        ``generate_packet`` / ``seed-data packet`` consumes.

        Args:
            inputs: a single concatenated PDF (path or ``s3://`` URI).
            name: the packet name.
            output_dir: where to write packet.json + per-segment schema dirs.
            model: vision-capable model key; defaults to ``sonnet``.
            boundaries: optional ``"1-2,3,4-5"`` page-range override for splitting.
            verbose: print progress.

        Returns:
            The output directory path (containing packet.json + schema dirs).
        """
        from seed_data.packet_infer import infer_packet as _infer_packet
        from seed_data.infer import DEFAULT_INFER_MODEL
        return _infer_packet(
            inputs, name=name, output_dir=output_dir,
            model=model or DEFAULT_INFER_MODEL, boundaries=boundaries,
            session=self.session, on_question=on_question, verbose=verbose,
        )

    def generate_from_samples(
        self,
        inputs: "str | list[str]",
        *,
        name: str,
        scenario: str = "",
        infer_model: str | None = None,
        max_docs: int = 5,
        output_dir: str | None = None,
        on_question: "Callable[[str], str] | None" = None,
        augment: bool | None = None,
        verbose: bool = True,
    ) -> GeneratedDoc:
        """Infer a schema from sample documents, then generate ONE synthetic doc.

        A convenience one-shot: ``infer_schema(...)`` followed by ``generate(...)``
        against the inferred ``Schema``. If ``output_dir`` is given the inferred
        schema is also persisted there for review/reuse (recommended), so you keep
        an editable schema rather than a throwaway. ``on_question`` enables the
        clarifying dialogue during inference (see ``infer_schema``).
        """
        schema = self.infer_schema(
            inputs, name=name, model=infer_model, max_docs=max_docs,
            output_dir=output_dir, on_question=on_question, verbose=verbose,
        )
        return self.generate(schema, scenario=scenario, augment=augment, verbose=verbose)

    def generate_batch_from_samples(
        self,
        inputs: "str | list[str]",
        *,
        name: str,
        count: int,
        scenario: str,
        infer_model: str | None = None,
        max_docs: int = 5,
        output_dir: str | None = None,
        on_question: "Callable[[str], str] | None" = None,
        augment: bool | None = None,
        seed: int | None = None,
        on_document: Callable[[int, int, GeneratedDoc], None] | None = None,
        verbose: bool = True,
    ) -> BatchResult:
        """Infer a schema from sample documents, then generate a diverse BATCH.

        A convenience one-shot: ``infer_schema(...)`` followed by
        ``generate_batch(...)`` against the inferred ``Schema``. ``on_question``
        enables the clarifying dialogue during inference (see ``infer_schema``).
        """
        schema = self.infer_schema(
            inputs, name=name, model=infer_model, max_docs=max_docs,
            output_dir=output_dir, on_question=on_question, verbose=verbose,
        )
        return self.generate_batch(
            schema, count=count, scenario=scenario, augment=augment,
            seed=seed, on_document=on_document, verbose=verbose,
        )

    # -- structured data (tabular) ------------------------------------------

    def ingest(self, *inputs: str, name: str = "dataset", verbose: bool = True) -> InferredSchema:
        """Ingest any inputs (text, CSV, PDF, JSON Schema, SQL DDL, ERD) into a
        unified :class:`InferredSchema`. Auto-detects each input's type.

        Documents/images/``s3://`` inputs are routed through the existing vision
        path (``infer_schema``); non-document inputs go through the schema
        extraction agent. Returns a typed ``InferredSchema`` — not a dict —
        consistent with the other verbs.

        Args:
            *inputs: paths, globs, ``s3://`` URIs, or bare free-text descriptions.
            name: logical dataset name (used when delegating documents).
            verbose: print progress.
        """
        from seed_data.ingest import run_ingest
        return run_ingest(
            *inputs, name=name, models=self.models,
            session=self.session, verbose=verbose,
        )

    def generate_structured(
        self,
        schema: "str | InferredSchema",
        *,
        rows: int = 100,
        format: str = "csv",
        verbose: bool = True,
    ) -> StructuredResult:
        """Generate structured data (CSV/Parquet/Excel/JSON) from a schema.

        ``schema`` accepts a bundled schema name, a path to an ``InferredSchema``
        JSON file, or an ``InferredSchema`` object. Returns a typed
        ``StructuredResult`` — consistent with ``GeneratedDoc`` / ``BatchResult`` /
        ``PacketResult``.

        Args:
            schema: bundled name, JSON path, or ``InferredSchema`` object.
            rows: target records per entity.
            format: ``csv`` / ``parquet`` / ``excel`` / ``json``.
            verbose: print progress.
        """
        from seed_data.structured import run_structured
        resolved = self._resolve_inferred(schema)
        return run_structured(
            resolved, target_count=rows, export_format=format,
            output_dir=self.output_dir, models=self.models,
            threshold=self.threshold, session=self.session, verbose=verbose,
        )

    # -- end-to-end ----------------------------------------------------------

    def run(
        self,
        *inputs: str,
        output: str = "structured",
        name: str = "dataset",
        rows: int = 100,
        format: str = "csv",
        count: int = 1,
        scenario: str = "",
        entity: str | None = None,
        augment: bool | None = None,
        verbose: bool = True,
    ) -> "GeneratedDoc | BatchResult | StructuredResult":
        """End-to-end: ingest inputs, then generate — in one call.

        Chains :meth:`ingest` into :meth:`generate_structured` (``output="structured"``)
        or :meth:`generate` / :meth:`generate_batch` (``output="documents"``).
        Configuration stays on the ``Generator``; per-call args describe only what
        to make.

        Args:
            *inputs: anything ``ingest`` accepts — free text, paths, globs, ``s3://``.
            output: ``"structured"`` (CSV/Parquet/Excel) or ``"documents"`` (PDFs).
            name: logical dataset name passed through to ``ingest``.
            rows: structured only — target records per entity.
            format: structured only — ``csv`` / ``parquet`` / ``excel`` / ``json``.
            count: documents only — how many to generate (>1 dispatches to batch).
            scenario: documents only — free-text steering the content.
            entity: documents only — which entity of a multi-entity schema to render.
            augment: documents only — override the instance augment setting.
            verbose: print progress.

        Returns:
            ``StructuredResult`` for structured output; ``GeneratedDoc``
            (``count == 1``) or ``BatchResult`` (``count > 1``) for documents.

        Raises:
            ValueError: if ``output`` is not ``"structured"`` or ``"documents"``.
        """
        if output not in ("structured", "documents"):
            raise ValueError(
                f"output must be 'structured' or 'documents', got {output!r}"
            )

        schema = self.ingest(*inputs, name=name, verbose=verbose)

        if output == "structured":
            return self.generate_structured(
                schema, rows=rows, format=format, verbose=verbose,
            )

        if count == 1:
            return self.generate(
                schema, scenario=scenario, augment=augment,
                entity=entity, verbose=verbose,
            )
        return self.generate_batch(
            schema, count=count, scenario=scenario, augment=augment,
            entity=entity, verbose=verbose,
        )

    # -- discovery -----------------------------------------------------------

    @staticmethod
    def available_schemas() -> list[str]:
        """Names of schemas bundled with the package."""
        root = _bundled_dir("schemas")
        return _list_subdirs(root)

    @staticmethod
    def available_packets() -> list[str]:
        """Names of packets bundled with the package."""
        root = _bundled_dir("packets")
        return _list_subdirs(root)

    @staticmethod
    def available_input_types() -> list[str]:
        """Input types the ``ingest`` verb can auto-detect."""
        from seed_data.ingest import InputType
        return [t.value for t in InputType]

    # -- internals -----------------------------------------------------------

    def _resolve_schema(self, schema: str) -> str:
        return _resolve(schema, "schemas")

    def _resolve_packet(self, packet: str) -> str:
        return _resolve(packet, "packets")

    def _resolve_for_documents(
        self, schema: "str | Schema | InferredSchema", *, entity: str | None = None,
    ) -> tuple[dict, str, list[str]] | None:
        """Resolve an in-code schema to the pipeline's ``(dict, guidance, samples)``.

        Returns ``None`` for a plain string, signalling the caller to fall back to
        the ``schema_dir=`` path (bundled name or directory) — which keeps the
        existing behaviour for every already-published call shape.
        """
        from seed_data.schema import Schema

        if isinstance(schema, Schema):
            return schema.resolve()
        if isinstance(schema, InferredSchema):
            from seed_data.schema.adapter import inferred_to_resolved
            return inferred_to_resolved(schema, entity_name=entity)
        return None

    def _resolve_inferred(self, schema: "str | InferredSchema") -> InferredSchema:
        """Resolve a schema spec into an :class:`InferredSchema`.

        Accepts an ``InferredSchema`` (returned as-is), a path to a JSON file
        (an ``InferredSchema`` dump or a JSON-Schema document), or a bundled
        schema name (resolved to its ``schema.json`` and converted).
        """
        if isinstance(schema, InferredSchema):
            return schema

        from seed_data.schema.io import from_json_schema

        if isinstance(schema, str):
            path = schema if os.path.isfile(schema) else None
            if path is None:
                # Try a bundled schema directory.
                from seed_data.schema.io import from_schema_dir
                resolved_dir = _resolve(schema, "schemas")
                return from_schema_dir(resolved_dir)

            with open(path) as f:
                data = json.load(f)
            # An InferredSchema dump has a top-level "entities" list.
            if isinstance(data, dict) and "entities" in data:
                return InferredSchema.model_validate(data)
            return from_json_schema(data)

        raise TypeError(f"Cannot resolve schema of type {type(schema).__name__}")


# ---------------------------------------------------------------------------
# path helpers — accept either a real directory or a bundled name
# ---------------------------------------------------------------------------
def _bundled_dir(kind: str) -> str:
    return os.path.join(os.path.dirname(__file__), kind)


def _list_subdirs(root: str) -> list[str]:
    if not os.path.isdir(root):
        return []
    return sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))


def _resolve(name_or_path: str, kind: str) -> str:
    """Resolve a schema/packet argument to a directory: a real path wins,
    otherwise fall back to the bundled entry of that name."""
    if os.path.isdir(name_or_path):
        return name_or_path
    bundled = os.path.join(_bundled_dir(kind), name_or_path)
    if os.path.isdir(bundled):
        return bundled
    available = ", ".join(_list_subdirs(_bundled_dir(kind))) or "(none)"
    raise FileNotFoundError(
        f"{kind[:-1].capitalize()} '{name_or_path}' is not a directory and is not "
        f"bundled. Available bundled {kind}: {available}"
    )

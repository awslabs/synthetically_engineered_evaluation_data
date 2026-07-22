"""Public Python API for seed-data.

The blessed entry point is the :class:`Generator` — construct it once with your
configuration (models, threshold, renderer, output directory), then call one of
its three verbs:

    from seed_data import Generator, ModelConfig

    gen = Generator(models=ModelConfig(doc="gpt-oss", critic="haiku"), threshold=5)

    doc    = gen.generate("invoice", scenario="Midwest food distributors")
    docs   = gen.generate_batch("invoice", count=10, scenario="...")
    packet = gen.generate_packet("lending-package", count=3)

Configuration lives on the ``Generator``; per-call arguments describe only *what*
to make. Every verb returns a typed result (``GeneratedDoc`` / ``BatchResult`` /
``PacketResult``) — no stringly-typed dicts.

``generate()`` runs the modern staged pipeline (``seed_data.stages.pipeline``).
``generate_batch()`` and ``generate_packet()`` wrap the existing batch/packet
engines. The engines are internal; this facade is the supported surface.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from pydantic import BaseModel, Field

from seed_data.stages.base import ModelConfig
from seed_data.stages.pipeline import GeneratedDoc, generate as _pipeline_generate


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
        schema: "str | Schema",
        *,
        scenario: str = "",
        augment: bool | None = None,
        verbose: bool = True,
    ) -> GeneratedDoc:
        """Generate a single document. Returns a typed ``GeneratedDoc``.

        Args:
            schema: One of —
                - a bundled schema name (e.g. ``"invoice"``),
                - a path to a schema directory, or
                - a :class:`Schema` object defined in code (JSON schema or a
                  pydantic model, plus generation guidance).
            scenario: Free-text describing what to generate this run (the vendor,
                industry, region, size, etc.) — steers the content.
            augment: Override the instance's augment setting for this call.
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
        from seed_data.schema import Schema
        if isinstance(schema, Schema):
            return _pipeline_generate(resolved=schema.resolve(), **common)
        return _pipeline_generate(schema_dir=self._resolve_schema(schema), **common)

    def generate_batch(
        self,
        schema: "str | Schema",
        *,
        count: int,
        scenario: str,
        augment: bool | None = None,
        seed: int | None = None,
        on_document: Callable[[int, int, GeneratedDoc], None] | None = None,
        verbose: bool = True,
    ) -> BatchResult:
        """Generate a diverse batch of documents from one high-level scenario.

        A planner turns ``scenario`` into ``count`` distinct, specific scenarios;
        each runs its own self-contained pipeline graph as a sibling node, and
        Strands executes them concurrently.

        ``schema`` accepts a bundled name, a directory path, or a ``Schema``.

        Args:
            scenario: The high-level theme the planner diversifies into ``count``
                specific documents. A specific scenario yields far more varied
                output than a generic one.
            seed: optional seed for scenario planning (regression-stable sets).
            on_document: optional ``callback(index, total, GeneratedDoc)`` fired as
                each document's result is collected — for host-side progress UIs.
        """
        from seed_data.stages.batch import generate_batch as _batch
        from seed_data.schema import Schema

        common = dict(
            count=count, brief=scenario, output_dir=self.output_dir,
            models=self.models, threshold=self.threshold,
            max_attempts=self.max_attempts, timeout=self.timeout,
            renderer=self.renderer, critic_samples=self.critic_samples,
            augment=self.augment if augment is None else augment,
            verbose=verbose, session=self.session, seed=seed,
            on_document=on_document,
        )
        if isinstance(schema, Schema):
            docs = _batch(resolved=schema.resolve(), **common)
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

    # -- internals -----------------------------------------------------------

    def _resolve_schema(self, schema: str) -> str:
        return _resolve(schema, "schemas")

    def _resolve_packet(self, packet: str) -> str:
        return _resolve(packet, "packets")


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

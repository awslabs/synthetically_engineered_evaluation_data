"""Public Python API for seed-data.

The blessed entry point is the :class:`Generator` — construct it once with your
configuration (models, threshold, renderer, output directory), then call one of
its three verbs:

    from seed_data import Generator, ModelConfig

    gen = Generator(models=ModelConfig(doc="gpt-oss", critic="haiku"), threshold=5)

    doc    = gen.generate("invoice", extra="Midwest food distributors")
    docs   = gen.generate_batch("invoice", count=10, brief="...")
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
        extra: str = "",
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
            extra: Free-text brief steering the content.
            augment: Override the instance's augment setting for this call.
            verbose: Print stage progress.
        """
        common = dict(
            output_dir=self.output_dir,
            extra=extra,
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
        brief: str,
        augment: bool | None = None,
        seed: int | None = None,
        on_document: Callable[[int, int, GeneratedDoc], None] | None = None,
        verbose: bool = True,
    ) -> BatchResult:
        """Generate a diverse batch of documents from one brief.

        A planner turns ``brief`` into ``count`` distinct scenarios; each runs its
        own self-contained pipeline graph as a sibling node, and Strands executes
        them concurrently.

        ``schema`` accepts a bundled name, a directory path, or a ``Schema``.

        Args:
            seed: optional seed for scenario planning (regression-stable sets).
            on_document: optional ``callback(index, total, GeneratedDoc)`` fired as
                each document's result is collected — for host-side progress UIs.
        """
        from seed_data.stages.batch import generate_batch as _batch
        from seed_data.schema import Schema

        common = dict(
            count=count, brief=brief, output_dir=self.output_dir,
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
        extra: str = "",
        shuffle: bool = False,
        doc_workers: int = 1,
        augment: bool | None = None,
    ):
        """Generate a coordinated multi-document packet.

        Args:
            packet: Path to a packet directory (containing a packet config), or a
                bundled packet name.
            count: Number of packets to generate.
            extra: Scenario brief shared across the packet's documents.
            shuffle: Randomize sub-document order in the merged PDF.
            doc_workers: Parallel workers for sub-documents within a packet.

        Returns a ``PacketResult`` (count==1) or a list of them (count>1).
        """
        from seed_data.packet import load_packet_config, generate_packet as _gen_packet

        config = load_packet_config(self._resolve_packet(packet))
        common = dict(
            output_dir=self.output_dir,
            extra=extra,
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

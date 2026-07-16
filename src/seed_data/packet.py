"""Packet generation — coordinated sets of inter-related documents.

A packet is a collection of different document types that share context
(e.g., a loan application containing a credit report, pay stubs, and a
statement of intent — all for the same applicant).

This module handles:
  - Loading and validating packet configuration
  - Resolving shared context (explicit or LLM-inferred)
  - Generating individual sub-documents via the v2 staged pipeline
    (``seed_data.stages.pipeline.generate``)
  - Merging sub-document PDFs into a single packet PDF
  - Emitting evaluation labels (document_class, page_indices, inference_result)
"""
from __future__ import annotations

import json
import os
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

import pypdf

from seed_data.utils import load_schema_dir, make_model


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DocumentSpec:
    """A single document type within a packet."""

    document_class: str
    schema_dir: str
    required: bool = True
    min_instances: int = 1
    max_instances: int = 1


@dataclass
class PacketConfig:
    """Parsed packet configuration."""

    name: str
    description: str
    documents: list[DocumentSpec]
    shared_context: dict[str, str] | None = None
    shared_context_hint: str = ""


@dataclass
class SectionResult:
    """Result for one sub-document section in the merged packet."""

    document_class: str
    page_indices: list[int]
    inference_result: dict[str, Any]
    pdf_path: str | None = None
    data_json_path: str | None = None
    doc_id: str = ""
    success: bool = True


@dataclass
class PacketResult:
    """Result of generating a single packet."""

    packet_id: str
    merged_pdf: str | None = None
    sections: list[SectionResult] = field(default_factory=list)
    shared_context: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str | None = None


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_packet_config(packet_dir: str) -> PacketConfig:
    """Load and validate a packet.json configuration.

    Args:
        packet_dir: Directory containing packet.json.

    Returns:
        Parsed PacketConfig.
    """
    config_path = os.path.join(packet_dir, "packet.json")
    with open(config_path) as f:
        raw = json.load(f)

    documents = [
        DocumentSpec(
            document_class=doc["document_class"],
            schema_dir=_resolve_schema_dir(doc["schema_dir"]),
            required=doc.get("required", True),
            min_instances=doc.get("min_instances", 1),
            max_instances=doc.get("max_instances", 1),
        )
        for doc in raw["documents"]
    ]

    return PacketConfig(
        name=raw["name"],
        description=raw.get("description", ""),
        documents=documents,
        shared_context=raw.get("shared_context"),
        shared_context_hint=raw.get("shared_context_hint", ""),
    )


def _resolve_schema_dir(schema_dir: str) -> str:
    """Resolve a schema_dir to an absolute path.

    Absolute paths are returned as-is. Relative names are looked up
    in the package's schemas/ directory.
    """
    if os.path.isabs(schema_dir) and os.path.isdir(schema_dir):
        return schema_dir

    schemas_root = os.path.join(os.path.dirname(__file__), "schemas")
    resolved = os.path.join(schemas_root, schema_dir)
    if os.path.isdir(resolved):
        return os.path.abspath(resolved)

    raise FileNotFoundError(
        f"Schema directory '{schema_dir}' not found. "
        f"Looked in: {schemas_root}"
    )


# ---------------------------------------------------------------------------
# Shared context resolution
# ---------------------------------------------------------------------------

def resolve_shared_context(
    config: PacketConfig,
    extra: str = "",
    model: str = "nova2-lite",
) -> dict[str, Any]:
    """Resolve shared context fields for a packet.

    If the packet config defines explicit shared_context fields, use those
    as the schema and ask the LLM to generate values. If not defined, the
    LLM analyzes all document schemas to infer common fields, then generates
    values.

    Args:
        config: Parsed packet configuration.
        extra: Extra instructions / scenario brief from the user.
        model: Model key for the context-generation agent.

    Returns:
        Dictionary of shared context field names → generated values.
    """
    from pydantic import BaseModel, Field
    from strands import Agent

    # Gather schema summaries for the LLM
    schema_summaries = _collect_schema_summaries(config)

    if config.shared_context:
        return _generate_values_for_explicit_context(
            config, schema_summaries, extra, model,
        )

    return _infer_and_generate_context(
        config, schema_summaries, extra, model,
    )


def _collect_schema_summaries(config: PacketConfig) -> str:
    """Build a text summary of all schemas in the packet for LLM consumption."""
    parts = []
    for doc_spec in config.documents:
        schema, steering, _ = load_schema_dir(doc_spec.schema_dir)
        parts.append(
            f"## {doc_spec.document_class}\n"
            f"Schema fields: {json.dumps(list(schema.get('properties', {}).keys()))}\n"
            f"Full schema:\n```json\n{json.dumps(schema, indent=2)}\n```"
        )
    return "\n\n".join(parts)


def _generate_values_for_explicit_context(
    config: PacketConfig,
    schema_summaries: str,
    extra: str,
    model: str,
) -> dict[str, Any]:
    """Generate values for explicitly defined shared context fields."""
    from strands import Agent

    agent = Agent(
        model=make_model(model),
        system_prompt=(
            "You generate realistic shared context values for a document packet. "
            "Be highly creative and diverse — vary names, ethnicities, locations, occupations, "
            "income levels, and property types as much as possible. "
            "Never reuse common placeholder names like John Smith or Jane Doe. "
            "Draw from a wide range of cultural backgrounds, US regions, and life situations. "
            "Return ONLY valid JSON — no markdown, no explanation."
        ),
    )

    field_descriptions = "\n".join(
        f"- {k}: {v}" for k, v in config.shared_context.items()
    )

    prompt = (
        f"Generate realistic values for these shared context fields that will be "
        f"used across multiple documents in a '{config.name}' packet.\n\n"
        f"Fields:\n{field_descriptions}\n\n"
        f"Document types in this packet:\n{schema_summaries}\n\n"
        f"Be creative — vary the borrower profile significantly from any previous runs. "
        f"Use diverse names, uncommon but realistic locations, varied income levels, "
        f"and interesting life situations.\n\n"
    )
    if extra:
        prompt += f"Scenario brief: {extra}\n\n"
    if config.shared_context_hint:
        prompt += f"Context hint: {config.shared_context_hint}\n\n"
    prompt += "Return a JSON object with the field names as keys and generated values."

    result = agent(prompt)
    return _parse_json_from_response(str(result))


def _infer_and_generate_context(
    config: PacketConfig,
    schema_summaries: str,
    extra: str,
    model: str,
) -> dict[str, Any]:
    """Infer shared fields from schemas, then generate values."""
    from strands import Agent

    agent = Agent(
        model=make_model(model),
        system_prompt=(
            "You analyze document schemas to find fields that should be consistent "
            "across related documents, then generate realistic values. "
            "Be highly creative and diverse — vary names, ethnicities, locations, occupations, "
            "income levels, and property types as much as possible. "
            "Never reuse common placeholder names like John Smith or Jane Doe. "
            "Draw from a wide range of cultural backgrounds, US regions, and life situations. "
            "Return ONLY valid JSON — no markdown, no explanation."
        ),
    )

    prompt = (
        f"Analyze these document schemas from a '{config.name}' packet "
        f"({config.description}).\n\n"
        f"{schema_summaries}\n\n"
        f"Identify fields that represent the same real-world entity across documents "
        f"(e.g., person names, addresses, dates, account numbers). "
        f"Then generate realistic, consistent values for those shared fields.\n\n"
    )
    if extra:
        prompt += f"Scenario brief: {extra}\n\n"
    if config.shared_context_hint:
        prompt += f"Context hint: {config.shared_context_hint}\n\n"
    prompt += (
        "Return a JSON object where keys are descriptive field names "
        "(e.g., 'applicant_name', 'property_address') and values are the "
        "generated values. Include only fields that genuinely appear across "
        "multiple document types."
    )

    result = agent(prompt)
    context = _parse_json_from_response(str(result))

    # Log what was inferred
    print(f"  Inferred shared context: {json.dumps(context, indent=2)}")

    return context


def _parse_json_from_response(text: str) -> dict[str, Any]:
    """Extract a JSON object from an LLM response, handling markdown fences."""
    # Strip markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end])
        return {}


# ---------------------------------------------------------------------------
# Single packet generation
# ---------------------------------------------------------------------------

def generate_packet(
    config: PacketConfig,
    output_dir: str,
    packet_id: str | None = None,
    extra: str = "",
    shared_context: dict[str, Any] | None = None,
    shuffle: bool = False,
    doc_workers: int = 1,
    data_model: str = "nova2-lite",
    doc_model: str = "nova2-lite",
    critic_model: str = "sonnet",
    aug_model: str = "gpt-oss",
    context_model: str = "nova2-lite",
    threshold: int = 7,
    max_attempts: int = 5,
    timeout: int = 3600,
    augment: bool = False,
    critic_samples: bool = True,
    renderer: str = "xhtml2pdf",
    enable_preview: bool = False,
) -> PacketResult:
    """Generate a single packet: resolve context, generate docs, merge, emit labels.

    Args:
        config: Parsed packet configuration.
        output_dir: Root output directory for this packet batch.
        packet_id: Unique ID for this packet (auto-generated if None).
        extra: Scenario brief / extra instructions.
        shared_context: Pre-resolved shared context (skips resolution if provided).
        shuffle: Randomize sub-document order in merged PDF.
        doc_workers: Parallel workers for sub-document generation within this packet.
        data_model: Model for data generation.
        doc_model: Model for document generation.
        critic_model: Model for critique.
        aug_model: Model for augmentation.
        context_model: Model for shared context resolution.
        threshold: Quality threshold for critics.
        max_attempts: Max retry attempts per document.
        timeout: Timeout per document generation.
        augment: Enable per-document augmentation.
        critic_samples: Use reference samples in critic.
        renderer: PDF rendering engine.
        enable_preview: Accepted for CLI compatibility; not used by the v2
            pipeline (no preview stage yet).

    Returns:
        PacketResult with merged PDF path, section results, and metadata.
    """
    packet_id = packet_id or uuid.uuid4().hex[:12]
    workspace_dir = os.path.join(output_dir, "artifacts", packet_id)
    os.makedirs(workspace_dir, exist_ok=True)

    # Step 1: Resolve shared context
    if shared_context is None:
        print(f"  Resolving shared context for packet {packet_id}...")
        shared_context = resolve_shared_context(config, extra=extra, model=context_model)

    # Save shared context for reproducibility
    context_path = os.path.join(workspace_dir, "shared_context.json")
    with open(context_path, "w") as f:
        json.dump(shared_context, f, indent=2)

    # Step 2: Build the document plan (resolve instance counts)
    doc_plan = _build_document_plan(config, shared_context)

    # Step 3: Generate each sub-document through the v2 staged pipeline
    from seed_data.stages.base import ModelConfig
    models = ModelConfig(
        data=data_model, doc=doc_model, critic=critic_model,
        aug=aug_model, batch=context_model,
    )
    section_results = _generate_subdocuments(
        doc_plan=doc_plan,
        shared_context=shared_context,
        workspace_dir=workspace_dir,
        extra=extra,
        doc_workers=doc_workers,
        models=models,
        threshold=threshold,
        max_attempts=max_attempts,
        timeout=timeout,
        augment=augment,
        critic_samples=critic_samples,
        renderer=renderer,
    )

    # Step 4: Optionally shuffle order
    if shuffle:
        random.shuffle(section_results)

    # Step 5: Merge PDFs and compute page indices
    successful_sections = [s for s in section_results if s.success and s.pdf_path]
    if not successful_sections:
        return PacketResult(
            packet_id=packet_id,
            shared_context=shared_context,
            sections=section_results,
            success=False,
            error="No sub-documents were generated successfully.",
        )

    merged_pdf_name = f"{packet_id}.pdf"
    merged_pdf_path = os.path.join(output_dir, "input", merged_pdf_name)
    os.makedirs(os.path.dirname(merged_pdf_path), exist_ok=True)

    page_offset = 0
    for section in successful_sections:
        page_count = _count_pdf_pages(section.pdf_path)
        section.page_indices = list(range(page_offset, page_offset + page_count))
        page_offset += page_count

    _merge_pdfs(
        pdf_paths=[s.pdf_path for s in successful_sections],
        output_path=merged_pdf_path,
    )

    # Step 6: Emit baseline labels
    _emit_baseline_labels(
        sections=successful_sections,
        merged_pdf_name=merged_pdf_name,
        output_dir=output_dir,
    )

    # Step 7: Write single packet summary JSON
    _write_packet_summary(
        packet_id=packet_id,
        merged_pdf_name=merged_pdf_name,
        shared_context=shared_context,
        sections=successful_sections,
        workspace_dir=workspace_dir,
    )

    return PacketResult(
        packet_id=packet_id,
        merged_pdf=merged_pdf_path,
        sections=section_results,
        shared_context=shared_context,
        success=True,
    )


# ---------------------------------------------------------------------------
# Document plan
# ---------------------------------------------------------------------------

@dataclass
class PlannedDocument:
    """A single document instance to generate."""

    document_class: str
    schema_dir: str
    instance_index: int  # 0-based within this document type


def _build_document_plan(
    config: PacketConfig,
    shared_context: dict[str, Any],
) -> list[PlannedDocument]:
    """Decide how many instances of each document type to generate.

    For types with min_instances == max_instances, the count is fixed.
    Otherwise, pick a random count in [min, max].
    """
    plan = []
    for doc_spec in config.documents:
        if not doc_spec.required and random.random() < 0.3:
            # 30% chance to skip optional documents
            continue

        count = doc_spec.min_instances
        if doc_spec.max_instances > doc_spec.min_instances:
            count = random.randint(doc_spec.min_instances, doc_spec.max_instances)

        for i in range(count):
            plan.append(PlannedDocument(
                document_class=doc_spec.document_class,
                schema_dir=doc_spec.schema_dir,
                instance_index=i,
            ))

    return plan


# ---------------------------------------------------------------------------
# Sub-document generation
# ---------------------------------------------------------------------------

def _generate_subdocuments(
    doc_plan: list[PlannedDocument],
    shared_context: dict[str, Any],
    workspace_dir: str,
    extra: str,
    doc_workers: int = 1,
    **generate_kwargs,
) -> list[SectionResult]:
    """Generate each sub-document through the v2 staged pipeline.

    Args:
        doc_plan: List of documents to generate.
        shared_context: Shared context values for consistency.
        workspace_dir: Directory for intermediate artifacts.
        extra: Extra instructions / scenario brief.
        doc_workers: Number of parallel workers for sub-document generation.
            1 = sequential (default), >1 = parallel via ThreadPoolExecutor.
        **generate_kwargs: Passed through to ``stages.pipeline.generate`` (models,
            threshold, renderer, timeout, augment, critic_samples, ...).

    Returns:
        List of SectionResult in the same order as doc_plan.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from seed_data.stages.pipeline import generate as _generate

    def _generate_one(index: int, planned_doc: PlannedDocument) -> tuple[int, SectionResult]:
        instance_label = (
            f" (instance {planned_doc.instance_index + 1})"
            if planned_doc.instance_index > 0 else ""
        )
        print(f"    Generating: {planned_doc.document_class}{instance_label}")

        context_instructions = _format_shared_context_instructions(
            shared_context, planned_doc.document_class,
        )
        combined_extra = "\n\n".join(filter(None, [extra, context_instructions]))

        doc_output_dir = os.path.join(
            workspace_dir,
            planned_doc.document_class.lower().replace(" ", "-"),
        )
        os.makedirs(doc_output_dir, exist_ok=True)

        try:
            doc = _generate(
                schema_dir=planned_doc.schema_dir,
                output_dir=doc_output_dir,
                extra=combined_extra,
                verbose=False,
                **generate_kwargs,
            )
        except Exception as e:
            print(f"    ✗ {planned_doc.document_class}{instance_label}: {e}")
            return index, SectionResult(
                document_class=planned_doc.document_class,
                page_indices=[],
                inference_result={},
                success=False,
            )

        inference_result = doc.data or {}
        status = "✓" if doc.success else "✗"
        print(f"    {status} {planned_doc.document_class}{instance_label}")

        return index, SectionResult(
            document_class=planned_doc.document_class,
            page_indices=[],  # filled in during merge step
            inference_result=inference_result,
            pdf_path=doc.pdf_path,
            data_json_path=doc.data_json_path,
            doc_id=doc.doc_id,
            success=doc.success,
        )

    # Sequential when doc_workers=1, parallel otherwise
    if doc_workers <= 1:
        return [_generate_one(i, doc)[1] for i, doc in enumerate(doc_plan)]

    # Parallel: preserve original order via index tracking
    results: list[SectionResult | None] = [None] * len(doc_plan)
    with ThreadPoolExecutor(max_workers=doc_workers) as pool:
        futures = {
            pool.submit(_generate_one, i, doc): i
            for i, doc in enumerate(doc_plan)
        }
        for future in as_completed(futures):
            idx, section = future.result()
            results[idx] = section

    return results


def _format_shared_context_instructions(
    shared_context: dict[str, Any],
    document_class: str,
) -> str:
    """Format shared context as extra instructions for the data generator."""
    if not shared_context:
        return ""

    lines = [
        "SHARED CONTEXT — Use these values where applicable in this document. "
        "These fields must be consistent across all documents in this packet:"
    ]
    for key, value in shared_context.items():
        lines.append(f"  - {key}: {value}")

    return "\n".join(lines)


def _load_inference_result(data_json_path: str | None) -> dict[str, Any]:
    """Load the generated data JSON as the inference_result for labels."""
    if not data_json_path or not os.path.exists(data_json_path):
        return {}
    try:
        with open(data_json_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Packet summary
# ---------------------------------------------------------------------------

def _write_packet_summary(
    packet_id: str,
    merged_pdf_name: str,
    shared_context: dict[str, Any],
    sections: list[SectionResult],
    workspace_dir: str,
) -> str:
    """Write a single packet_summary.json combining shared context and all section labels.

    Structure:
        artifacts/<packet_id>/packet_summary.json
    """
    summary = {
        "packet_id": packet_id,
        "merged_pdf": merged_pdf_name,
        "shared_context": shared_context,
        "sections": [
            {
                "document_class": s.document_class,
                "page_indices": s.page_indices,
                "doc_id": s.doc_id,
                "inference_result": s.inference_result,
            }
            for s in sections
        ],
    }
    summary_path = os.path.join(workspace_dir, "packet_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Packet summary: {summary_path}")
    return summary_path


# ---------------------------------------------------------------------------
# PDF merging
# ---------------------------------------------------------------------------

def _merge_pdfs(pdf_paths: list[str], output_path: str) -> None:
    """Merge multiple PDFs into a single file using pypdf."""
    merged = pypdf.PdfWriter()
    for path in pdf_paths:
        merged.append(path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    merged.write(output_path)
    merged.close()


def _count_pdf_pages(pdf_path: str) -> int:
    """Count pages in a PDF."""
    reader = pypdf.PdfReader(pdf_path)
    return len(reader.pages)


# ---------------------------------------------------------------------------
# Label emission
# ---------------------------------------------------------------------------

def _emit_baseline_labels(
    sections: list[SectionResult],
    merged_pdf_name: str,
    output_dir: str,
) -> None:
    """Write result.json files in the baseline directory structure.

    Structure:
        baseline/<merged_pdf_name>/sections/<N>/result.json
    """
    baseline_dir = os.path.join(output_dir, "baseline", merged_pdf_name, "sections")

    for i, section in enumerate(sections, start=1):
        section_dir = os.path.join(baseline_dir, str(i))
        os.makedirs(section_dir, exist_ok=True)

        label = {
            "document_class": {"type": section.document_class},
            "split_document": {"page_indices": section.page_indices},
            "inference_result": section.inference_result,
        }

        with open(os.path.join(section_dir, "result.json"), "w") as f:
            json.dump(label, f, indent=2)


def emit_classes_yaml(
    config: PacketConfig,
    output_dir: str,
) -> str:
    """Write classes.yaml listing all document types in the packet.

    Returns:
        Path to the written classes.yaml.
    """
    import yaml

    classes = sorted({doc.document_class for doc in config.documents})
    classes_path = os.path.join(output_dir, "classes.yaml")
    with open(classes_path, "w") as f:
        yaml.dump({"classes": classes}, f, default_flow_style=False)

    return classes_path


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def write_packet_manifest(
    results: list[PacketResult],
    config: PacketConfig,
    output_dir: str,
    command: str = "",
    elapsed_s: float = 0,
    **extra_metadata,
) -> str:
    """Write a packet_manifest.json summarizing the batch of packets.

    Returns:
        Path to the written manifest.
    """
    import subprocess as _sp

    try:
        git_hash = _sp.check_output(
            ["git", "rev-parse", "HEAD"], stderr=_sp.DEVNULL, text=True,
        ).strip()
    except Exception:
        git_hash = "unknown"

    succeeded = sum(1 for r in results if r.success)

    manifest = {
        "packet_type": config.name,
        "description": config.description,
        "command": command,
        "git_hash": git_hash,
        "count_requested": len(results),
        "count_succeeded": succeeded,
        "elapsed_s": round(elapsed_s, 1),
        **extra_metadata,
        "packets": [
            {
                "packet_id": r.packet_id,
                "success": r.success,
                "merged_pdf": r.merged_pdf,
                "shared_context": r.shared_context,
                "error": r.error,
                "sections": [
                    {
                        "document_class": s.document_class,
                        "page_indices": s.page_indices,
                        "doc_id": s.doc_id,
                        "success": s.success,
                        "pdf_path": s.pdf_path,
                        "data_json_path": s.data_json_path,
                    }
                    for s in r.sections
                ],
            }
            for r in results
        ],
    }

    config_dir = os.path.join(output_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    manifest_path = os.path.join(config_dir, "packet_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    return manifest_path

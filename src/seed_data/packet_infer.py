"""Infer a packet definition from ONE concatenated multi-document PDF.

The inverse of ``generate_packet``: a user hands over a single file that is
several *different* document types concatenated (a lending package: loan app +
credit report + pay stubs in one PDF). This module:

  1. Detects document boundaries + classes across the pages (vision model, or a
     user-supplied ``--boundaries`` override).
  2. Splits the PDF into a sub-PDF per segment.
  3. Runs single-type schema inference (``infer.infer_schema``) on each segment.
  4. Writes a ``packet.json`` + one schema dir per segment — the on-disk shape
     ``seed-data packet`` consumes, closing the round-trip.

Only PDF input is supported here (splitting needs page structure); images are a
single-document concept and belong to ``infer_schema`` instead.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile

from pydantic import BaseModel, Field, model_validator
from strands import Agent

from seed_data import prompts
from seed_data.utils import make_model
from seed_data.inputs import resolve_inputs
from seed_data.infer import infer_schema, write_schema_dir, DEFAULT_INFER_MODEL


class _Segment(BaseModel):
    """One detected sub-document within the concatenated PDF."""
    document_class: str = Field(description="Human-readable document type label, e.g. 'Loan Application'")
    schema_dir_name: str = Field(description="kebab-case directory name for this type, e.g. 'loan-application'")
    start_page: int = Field(description="First page of this document, 1-indexed inclusive", ge=1)
    end_page: int = Field(description="Last page of this document, 1-indexed inclusive", ge=1)

    @model_validator(mode="after")
    def _end_after_start(self) -> "_Segment":
        if self.end_page < self.start_page:
            raise ValueError(
                f"segment end_page ({self.end_page}) < start_page ({self.start_page})"
            )
        return self


class _PacketLayout(BaseModel):
    """The full page-to-document segmentation the splitter model returns."""
    segments: list[_Segment] = Field(description="Detected documents, in page order, covering the file")


def parse_boundaries(spec: str, n_pages: int) -> list[tuple[int, int]]:
    """Parse a ``--boundaries`` spec like ``"1-2,3,4-5"`` into (start,end) pairs.

    Pages are 1-indexed inclusive. Validates coverage is within the document and
    non-overlapping/ascending — a malformed override should fail loudly, not
    silently mis-split.
    """
    ranges: list[tuple[int, int]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < 1 or end < start or end > n_pages:
            raise ValueError(
                f"Invalid boundary range '{part}' for a {n_pages}-page document."
            )
        if ranges and start <= ranges[-1][1]:
            raise ValueError(
                f"Boundary range '{part}' overlaps or precedes the previous segment."
            )
        ranges.append((start, end))
    if not ranges:
        raise ValueError("--boundaries was empty.")
    return ranges


def _pdf_page_count(pdf_bytes: bytes) -> int:
    import pypdf
    return len(pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)


def _extract_pages(pdf_bytes: bytes, start: int, end: int) -> bytes:
    """Extract pages [start, end] (1-indexed inclusive) into a new PDF's bytes."""
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    writer = pypdf.PdfWriter()
    for i in range(start - 1, end):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _detect_segments(
    pdf_bytes: bytes,
    *,
    packet_name: str,
    model: str,
    session,
    boundaries: list[tuple[int, int]] | None,
    on_question=None,
    verbose: bool,
) -> list[_Segment]:
    """Vision call: classify pages into document segments (class + page range).

    If ``boundaries`` is provided, the page ranges are fixed and the model only
    names/classifies each pre-split segment; otherwise it detects both. When
    ``on_question`` is provided (and boundaries are NOT fixed), the model may ask
    the user to clarify an ambiguous split.
    """
    n_pages = _pdf_page_count(pdf_bytes)
    # Only offer split-clarification questions when the model is actually deciding
    # boundaries — with fixed --boundaries there is nothing to ask about.
    ask_split = on_question is not None and boundaries is None
    system_prompt = prompts.render(
        "packet_split", packet_name=packet_name, n_pages=n_pages,
        boundaries=boundaries, allow_questions=ask_split,
    )
    tools = []
    if ask_split:
        from seed_data.tools import make_ask_user_tool
        tools = [make_ask_user_tool(on_question)]
    agent = Agent(model=make_model(model, session=session), system_prompt=system_prompt, tools=tools)

    user_message = [
        {"document": {"format": "pdf", "name": "concatenated-packet",
                      "source": {"bytes": pdf_bytes}}},
        {"text": f"This PDF has {n_pages} page(s). Identify the distinct documents "
                 f"and return the segmentation."},
    ]
    result = agent(user_message, structured_output_model=_PacketLayout)
    if result.structured_output is None:
        raise ValueError(
            "The model returned no structured segmentation (likely a content-filter "
            "or guardrail refusal on the document). Try a different --infer-model."
        )
    segments = result.structured_output.segments

    if boundaries:
        # Trust the user's page ranges; keep only the model's class labels,
        # aligned positionally. If counts mismatch, fall back to generic names.
        aligned = []
        for i, (start, end) in enumerate(boundaries):
            seg = segments[i] if i < len(segments) else None
            aligned.append(_Segment(
                document_class=seg.document_class if seg else f"Document {i + 1}",
                schema_dir_name=seg.schema_dir_name if seg else f"document-{i + 1}",
                start_page=start, end_page=end,
            ))
        segments = aligned

    if verbose:
        print(f"Detected {len(segments)} document segment(s):")
        for s in segments:
            pages = f"p{s.start_page}" if s.start_page == s.end_page else f"p{s.start_page}-{s.end_page}"
            print(f"  - {s.document_class} ({s.schema_dir_name}) [{pages}]")
    return segments


def _validate_segments(segments: list[_Segment], n_pages: int,
                       *, require_full_coverage: bool = True) -> None:
    """Validate detected segments before page extraction.

    The safety invariants — in range, ascending, non-overlapping — always hold:
    they are what prevent a hallucinated range from crashing as an ``IndexError``
    deep inside pypdf (or extracting an empty PDF). Those are enforced regardless
    of how the split was produced.

    ``require_full_coverage`` (contiguous tiling of pages 1..n_pages) is enforced
    only for **model-detected** splits, where a gap means the model missed a
    document. For a **user-supplied ``--boundaries``** split the user has
    explicitly declared what to extract, so partial coverage (e.g. ``"1,2"`` on a
    3-page file) is intentional and allowed.
    """
    if not segments:
        raise ValueError("No document segments were detected in the PDF.")
    expected_start = 1
    for i, s in enumerate(segments):
        if not (1 <= s.start_page <= s.end_page <= n_pages):
            raise ValueError(
                f"Segment {i + 1} ('{s.document_class}') has an invalid page range "
                f"{s.start_page}-{s.end_page} for a {n_pages}-page document."
            )
        # Ascending + non-overlapping is a safety invariant (both paths).
        if s.start_page < expected_start:
            raise ValueError(
                f"Segments overlap or are out of order: segment {i + 1} starts at "
                f"page {s.start_page}, at or before the previous segment's end."
            )
        # A gap is only an error when the model was supposed to tile the file.
        if require_full_coverage and s.start_page != expected_start:
            raise ValueError(
                f"Segments must tile the document with no gaps: segment "
                f"{i + 1} starts at page {s.start_page}, expected {expected_start}."
            )
        expected_start = s.end_page + 1
    if require_full_coverage and expected_start != n_pages + 1:
        raise ValueError(
            f"Segments cover pages 1-{expected_start - 1} but the document has "
            f"{n_pages} page(s)."
        )


def _safe_dir_name(name: str, fallback: str) -> str:
    """Reduce a model-supplied schema_dir_name to a single safe path segment.

    The name is model-controlled and used as a directory component, so strip any
    path separators / traversal and reject empties — otherwise ``..`` could
    escape output_dir or ``''`` could drop schema.json into the packet root.
    """
    # keep only the basename, drop dots/separators that enable traversal
    base = os.path.basename(name.strip().replace("\\", "/").rstrip("/"))
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "-" for c in base).strip("-.")
    return cleaned or fallback


def _dedupe_names(segments: list[_Segment]) -> None:
    """Ensure schema_dir_name is unique AND a safe single path segment.

    Collision-proof: seeds the taken set with every sanitized original name, then
    for a repeat keeps incrementing the suffix until the candidate is genuinely
    free — so a model that emits ['pay-stub','pay-stub','pay-stub-2'] does not
    produce two 'pay-stub-2' dirs.
    """
    for i, s in enumerate(segments):
        s.schema_dir_name = _safe_dir_name(s.schema_dir_name, f"document-{i + 1}")

    taken: set[str] = set()
    for s in segments:
        name = s.schema_dir_name
        if name in taken:
            n = 2
            while f"{name}-{n}" in taken or any(
                other.schema_dir_name == f"{name}-{n}" for other in segments
            ):
                n += 1
            name = f"{name}-{n}"
            s.schema_dir_name = name
        taken.add(name)


def infer_packet(
    inputs: str | list[str],
    *,
    name: str,
    output_dir: str,
    model: str = DEFAULT_INFER_MODEL,
    boundaries: str | None = None,
    session=None,
    on_question=None,
    verbose: bool = True,
) -> str:
    """Infer a packet definition from a concatenated multi-document PDF.

    Args:
        inputs: a single concatenated PDF (path or ``s3://`` URI). If it resolves
            to more than one file, only the first PDF is used (with a note).
        name: the packet name (packet.json ``name`` / directory identity).
        output_dir: where to write ``packet.json`` + per-segment schema dirs.
        model: vision-capable model key (default ``sonnet``).
        boundaries: optional ``"1-2,3,4-5"`` page-range override for splitting.
        session: optional boto3 Session (S3 + Bedrock).
        verbose: print progress.

    Returns:
        The output directory path (containing packet.json + schema dirs).
    """
    docs, skipped = resolve_inputs(inputs, session=session)
    if verbose and skipped:
        for s in skipped:
            print(f"  skipped: {s}")
    pdfs = [d for d in docs if d.kind == "pdf"]
    if not pdfs:
        raise FileNotFoundError("infer-packet requires a PDF input (concatenated documents).")
    if verbose and len(pdfs) > 1:
        print(f"Multiple PDFs resolved; using the first: {pdfs[0].name} "
              f"(the others are ignored — a packet is one concatenated file).")
    pdf = pdfs[0]

    # Refuse to write into a non-empty directory — a partial prior run (or any
    # unrelated content) must not be silently mixed with / clobbered by this one.
    if os.path.isdir(output_dir) and os.listdir(output_dir):
        raise FileExistsError(
            f"Output directory {output_dir} is not empty. "
            "Choose a different --output or remove it first."
        )

    n_pages = _pdf_page_count(pdf.data)
    if n_pages < 1:
        raise ValueError(f"{pdf.name} has no pages.")
    parsed_boundaries = parse_boundaries(boundaries, n_pages) if boundaries else None

    if verbose:
        print(f"Inferring packet '{name}' from {pdf.name} ({n_pages} pages) using {model}.")

    segments = _detect_segments(
        pdf.data, packet_name=name, model=model, session=session,
        boundaries=parsed_boundaries, on_question=on_question, verbose=verbose,
    )
    # Validate before extraction. Safety invariants (in-range, non-overlapping)
    # always apply; full-coverage tiling is required only for model-detected
    # splits — user-supplied --boundaries may intentionally skip pages.
    _validate_segments(segments, n_pages, require_full_coverage=parsed_boundaries is None)
    _dedupe_names(segments)

    # Build into a staging dir and move into place only if everything succeeds,
    # so a mid-loop failure (throttle, guardrail) never leaves a poisoned output.
    final_dir = os.path.abspath(output_dir)
    staging = tempfile.mkdtemp(prefix=".seed_packet_", dir=os.path.dirname(final_dir) or ".")
    try:
        doc_specs = []
        for seg in segments:
            seg_bytes = _extract_pages(pdf.data, seg.start_page, seg.end_page)
            final_seg_dir = os.path.join(final_dir, seg.schema_dir_name)
            staging_seg_dir = os.path.join(staging, seg.schema_dir_name)
            if verbose:
                print(f"\nInferring schema for '{seg.document_class}' "
                      f"(pages {seg.start_page}-{seg.end_page}) -> {final_seg_dir}")
            schema = _infer_segment_schema(
                seg_bytes, name=seg.schema_dir_name, model=model, session=session,
                on_question=on_question, verbose=verbose,
            )
            write_schema_dir(schema, staging_seg_dir)
            doc_specs.append({
                "document_class": seg.document_class,
                # Absolute FINAL path so `seed-data packet <output_dir>` resolves it
                # (the packet loader looks up bare names only in the bundled root).
                "schema_dir": final_seg_dir,
                "required": True,
                "min_instances": 1,
                "max_instances": 1,
            })

        packet_config = {
            "name": name,
            "description": f"Packet inferred from {pdf.name} ({len(doc_specs)} document types).",
            "documents": doc_specs,
        }
        with open(os.path.join(staging, "packet.json"), "w") as f:
            json.dump(packet_config, f, indent=2)
            f.write("\n")

        # Atomic-ish promotion: move the fully-built staging dir into place.
        os.makedirs(os.path.dirname(final_dir) or ".", exist_ok=True)
        if os.path.isdir(final_dir):
            os.rmdir(final_dir)  # empty (guarded above) — replace with the built tree
        shutil.move(staging, final_dir)
        staging = None
    finally:
        if staging and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)

    if verbose:
        print(f"\nWrote packet definition to {final_dir}/ "
              f"(packet.json + {len(doc_specs)} schema dir(s)).")
    return final_dir


def _infer_segment_schema(seg_bytes: bytes, *, name, model, session, on_question=None, verbose=True):
    """Run single-type schema inference on one extracted segment's PDF bytes.

    We already hold the bytes, so we bridge into infer_schema's core via a
    temp file — reusing the exact same inference path as standalone infer-schema.
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(seg_bytes)
        tmp_path = tf.name
    try:
        return infer_schema(tmp_path, name=name, model=model, session=session,
                            on_question=on_question, verbose=verbose)
    finally:
        os.unlink(tmp_path)

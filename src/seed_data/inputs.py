"""Resolve document inputs (local paths, globs, or s3:// URIs) to bytes.

Schema inference and any other "read some sample documents" feature only ever
needs ``(name, bytes, media_type)`` triples — it does not care whether the bytes
came from disk or S3. This module is that thin, source-agnostic loader.

Supported inputs (mixed freely in one call):
    - a local file path              e.g. "invoice.pdf"
    - a local glob                   e.g. "./samples/*.pdf"
    - a local directory              e.g. "./samples/"  (non-recursive)
    - an s3:// object URI            e.g. "s3://bucket/key/invoice.pdf"
    - an s3:// prefix (folder) URI   e.g. "s3://bucket/invoices/"

Only document-like media are kept: PDF and PNG/JPEG images. Anything else is
skipped with a logged note (never silently dropped).
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

# Bedrock content-block media types we support, keyed by file extension.
# PDFs become a {"document": ...} block; images become an {"image": ...} block.
_PDF_EXTS = {".pdf"}
_IMAGE_EXTS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}
SUPPORTED_EXTS = set(_PDF_EXTS) | set(_IMAGE_EXTS)


@dataclass
class Document:
    """One resolved input document."""
    name: str          # a human/model-facing label (basename)
    data: bytes        # the raw file bytes
    kind: str          # "pdf" or "image"
    media_format: str  # bedrock format token: "pdf" | "png" | "jpeg"

    def to_content_block(self) -> dict:
        """Render as a Bedrock Converse content block (document or image)."""
        if self.kind == "pdf":
            # Bedrock requires a document name of only alphanumerics, spaces,
            # hyphens, parens, and square brackets — sanitize the label.
            safe = _safe_doc_name(self.name)
            return {"document": {"format": "pdf", "name": safe,
                                 "source": {"bytes": self.data}}}
        return {"image": {"format": self.media_format,
                          "source": {"bytes": self.data}}}


def _safe_doc_name(name: str) -> str:
    """Bedrock document names allow [alnum, space, hyphen, paren, bracket]."""
    keep = []
    for ch in name:
        keep.append(ch if (ch.isalnum() or ch in " -()[]") else "-")
    cleaned = "".join(keep).strip() or "document"
    return cleaned[:200]


def _classify(path_or_key: str) -> tuple[str, str] | None:
    """Map a filename to (kind, media_format), or None if unsupported."""
    ext = os.path.splitext(path_or_key)[1].lower()
    if ext in _PDF_EXTS:
        return "pdf", "pdf"
    if ext in _IMAGE_EXTS:
        return "image", _IMAGE_EXTS[ext]
    return None


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Split ``s3://bucket/key/or/prefix`` into ``(bucket, key)``."""
    rest = uri[len("s3://"):]
    if "/" not in rest:
        return rest, ""            # bucket root prefix
    bucket, key = rest.split("/", 1)
    return bucket, key


def _resolve_one_local(spec: str) -> list[str]:
    """Expand a single local spec (file, dir, or glob) to concrete file paths."""
    if os.path.isdir(spec):
        # a directory: take supported files directly inside it (non-recursive)
        return sorted(
            os.path.join(spec, f) for f in os.listdir(spec)
            if _classify(f) is not None
        )
    if any(ch in spec for ch in "*?[") or glob.has_magic(spec):
        return sorted(glob.glob(spec))
    return [spec]  # a plain path (may or may not exist — checked when read)


def _load_local(paths: list[str], skipped: list[str]) -> list[Document]:
    docs = []
    for p in paths:
        cls = _classify(p)
        if cls is None:
            skipped.append(f"{p} (unsupported type)")
            continue
        if not os.path.isfile(p):
            skipped.append(f"{p} (not found)")
            continue
        kind, fmt = cls
        with open(p, "rb") as f:
            docs.append(Document(name=os.path.basename(p), data=f.read(),
                                 kind=kind, media_format=fmt))
    return docs


def _load_s3(uri: str, skipped: list[str], session=None) -> list[Document]:
    """Load one s3:// object, or every supported object under an s3:// prefix."""
    from botocore.exceptions import ClientError
    from seed_data.session import get_boto_session
    s3 = (session or get_boto_session()).client("s3")
    bucket, key = _parse_s3_uri(uri)

    # A trailing slash, an empty key, or a key with no extension → treat as prefix.
    is_prefix = uri.endswith("/") or key == "" or _classify(key) is None
    keys: list[str] = []
    if is_prefix:
        # Normalize to a folder boundary so "s3://b/invoices" does NOT also match
        # sibling prefixes like "invoices-archive/" — a raw S3 Prefix is a plain
        # string match, which would silently load wrong-type documents.
        prefix = key if (key == "" or key.endswith("/")) else key + "/"
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if _classify(obj["Key"]) is not None:
                    keys.append(obj["Key"])
        keys.sort()
        if not keys:
            skipped.append(f"{uri} (no PDF/PNG/JPEG objects under prefix)")
    else:
        keys = [key]

    docs = []
    for k in keys:
        cls = _classify(k)
        if cls is None:
            skipped.append(f"s3://{bucket}/{k} (unsupported type)")
            continue
        kind, fmt = cls
        # Skip an object that vanished / is inaccessible rather than aborting the
        # whole resolve (mirrors the local loader's graceful missing-file skip).
        try:
            body = s3.get_object(Bucket=bucket, Key=k)["Body"].read()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "error")
            skipped.append(f"s3://{bucket}/{k} (fetch failed: {code})")
            continue
        docs.append(Document(name=os.path.basename(k), data=body,
                             kind=kind, media_format=fmt))
    return docs


def resolve_inputs(
    inputs: str | list[str],
    *,
    session=None,
) -> tuple[list[Document], list[str]]:
    """Resolve mixed local/S3 inputs to ``Document`` objects.

    Args:
        inputs: one spec or a list of specs. Each may be a local path, glob,
            directory, or an ``s3://`` object/prefix URI.
        session: optional boto3 Session for S3 (falls back to the env session).

    Returns:
        ``(documents, skipped)`` — the loaded documents, and human-readable
        notes about anything skipped (so callers can surface it, never silent).
    """
    specs = [inputs] if isinstance(inputs, str) else list(inputs)
    docs: list[Document] = []
    skipped: list[str] = []

    for spec in specs:
        if spec.startswith("s3://"):
            docs.extend(_load_s3(spec, skipped, session=session))
        else:
            docs.extend(_load_local(_resolve_one_local(spec), skipped))

    return docs, skipped

"""Tests for schema inference (documents -> Schema) — no Bedrock, no S3.

Covers the deterministic, offline surface: input resolution (local globs/dirs +
s3:// parsing with a stubbed client), media classification, Bedrock content-block
shaping, and write_schema_dir. The single vision call in infer_schema is mocked
so the whole file runs in CI without credentials.
"""
import json
import os

import pytest

from seed_data.inputs import (
    resolve_inputs, Document, _classify, _parse_s3_uri, _safe_doc_name,
)


# --- media classification ---------------------------------------------------

def test_classify_supported_types():
    assert _classify("invoice.pdf") == ("pdf", "pdf")
    assert _classify("scan.PNG") == ("image", "png")
    assert _classify("photo.jpg") == ("image", "jpeg")
    assert _classify("photo.jpeg") == ("image", "jpeg")


def test_classify_unsupported_returns_none():
    assert _classify("notes.txt") is None
    assert _classify("data.json") is None
    assert _classify("archive.zip") is None


# --- Document content blocks ------------------------------------------------

def test_pdf_content_block():
    d = Document(name="my invoice #3.pdf", data=b"%PDF-1.4", kind="pdf", media_format="pdf")
    block = d.to_content_block()
    assert block["document"]["format"] == "pdf"
    assert block["document"]["source"]["bytes"] == b"%PDF-1.4"
    # name sanitized to Bedrock's allowed charset (no '#')
    assert "#" not in block["document"]["name"]


def test_image_content_block():
    d = Document(name="receipt.png", data=b"\x89PNG", kind="image", media_format="png")
    block = d.to_content_block()
    assert block["image"]["format"] == "png"
    assert block["image"]["source"]["bytes"] == b"\x89PNG"


def test_safe_doc_name_strips_disallowed():
    # Bedrock document names allow only [alnum, space, hyphen, paren, bracket];
    # slash, colon, asterisk AND the '.' extension dot all become hyphens.
    assert _safe_doc_name("a/b:c*d.pdf") == "a-b-c-d-pdf"
    assert _safe_doc_name("invoice (1).pdf") == "invoice (1)-pdf"
    assert _safe_doc_name("") == "document"


# --- s3 URI parsing ---------------------------------------------------------

def test_parse_s3_uri():
    assert _parse_s3_uri("s3://bucket/path/to/file.pdf") == ("bucket", "path/to/file.pdf")
    assert _parse_s3_uri("s3://bucket/prefix/") == ("bucket", "prefix/")
    assert _parse_s3_uri("s3://bucket") == ("bucket", "")


# --- local resolution -------------------------------------------------------

def _write(path, data=b"%PDF-1.4 x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def test_resolve_local_glob(tmp_path):
    _write(str(tmp_path / "a.pdf"))
    _write(str(tmp_path / "b.pdf"))
    _write(str(tmp_path / "note.txt"), b"hi")
    docs, skipped = resolve_inputs(str(tmp_path / "*.pdf"))
    assert sorted(d.name for d in docs) == ["a.pdf", "b.pdf"]
    assert skipped == []  # the .txt wasn't matched by the glob


def test_resolve_local_directory_filters_unsupported(tmp_path):
    _write(str(tmp_path / "a.pdf"))
    _write(str(tmp_path / "b.png"), b"\x89PNG")
    _write(str(tmp_path / "note.txt"), b"hi")
    docs, skipped = resolve_inputs(str(tmp_path))
    # directory scan keeps only supported types, silently (they never matched)
    assert sorted(d.name for d in docs) == ["a.pdf", "b.png"]


def test_resolve_missing_file_is_skipped_not_crash(tmp_path):
    docs, skipped = resolve_inputs(str(tmp_path / "nope.pdf"))
    assert docs == []
    assert any("not found" in s for s in skipped)


def test_resolve_unsupported_explicit_file_is_skipped(tmp_path):
    _write(str(tmp_path / "data.csv"), b"a,b")
    docs, skipped = resolve_inputs(str(tmp_path / "data.csv"))
    assert docs == []
    assert any("unsupported type" in s for s in skipped)


def test_resolve_mixed_specs(tmp_path):
    _write(str(tmp_path / "a.pdf"))
    _write(str(tmp_path / "b.png"), b"\x89PNG")
    docs, skipped = resolve_inputs([str(tmp_path / "a.pdf"), str(tmp_path / "b.png")])
    assert {d.kind for d in docs} == {"pdf", "image"}


# --- s3 resolution (stubbed client) -----------------------------------------

class _FakeBody:
    def __init__(self, data): self._data = data
    def read(self): return self._data


class _FakeS3:
    """Minimal stub of the S3 client surface resolve_inputs uses."""
    def __init__(self, objects):  # objects: {key: bytes}
        self._objects = objects

    def get_object(self, Bucket, Key):
        return {"Body": _FakeBody(self._objects[Key])}

    def get_paginator(self, _name):
        objects = self._objects
        class _Paginator:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in objects if k.startswith(Prefix)]}
        return _Paginator()


class _FakeSession:
    def __init__(self, s3): self._s3 = s3
    def client(self, name):
        assert name == "s3"
        return self._s3


def test_resolve_s3_single_object():
    s3 = _FakeS3({"docs/invoice.pdf": b"%PDF-1.4 s3"})
    docs, skipped = resolve_inputs("s3://bkt/docs/invoice.pdf", session=_FakeSession(s3))
    assert len(docs) == 1
    assert docs[0].name == "invoice.pdf"
    assert docs[0].data == b"%PDF-1.4 s3"
    assert docs[0].kind == "pdf"


def test_resolve_s3_prefix_lists_supported_only():
    s3 = _FakeS3({
        "inv/a.pdf": b"%PDF a",
        "inv/b.png": b"\x89PNG",
        "inv/readme.txt": b"skip me",
    })
    docs, skipped = resolve_inputs("s3://bkt/inv/", session=_FakeSession(s3))
    assert sorted(d.name for d in docs) == ["a.pdf", "b.png"]


def test_resolve_s3_empty_prefix_notes_skip():
    s3 = _FakeS3({"other/x.txt": b"nope"})
    docs, skipped = resolve_inputs("s3://bkt/inv/", session=_FakeSession(s3))
    assert docs == []
    assert any("no PDF/PNG/JPEG" in s for s in skipped)


# --- write_schema_dir -------------------------------------------------------

def test_write_schema_dir_emits_both_files(tmp_path):
    from seed_data.schema import Schema
    from seed_data.infer import write_schema_dir

    schema = Schema(name="invoice",
                    json_schema={"type": "object", "properties": {"total": {"type": "number"}}},
                    generation_guidance="## Visual Style\nBoxed totals.")
    dest = str(tmp_path / "invoice")
    write_schema_dir(schema, dest)

    with open(os.path.join(dest, "schema.json")) as f:
        written = json.load(f)
    assert written["title"] == "invoice"           # title forced to name
    assert "total" in written["properties"]
    assert os.path.exists(os.path.join(dest, "generation_guidance.md"))


def test_write_schema_dir_refuses_clobber(tmp_path):
    from seed_data.schema import Schema
    from seed_data.infer import write_schema_dir

    schema = Schema(name="x", json_schema={"type": "object"}, generation_guidance="g")
    dest = str(tmp_path / "x")
    write_schema_dir(schema, dest)
    with pytest.raises(FileExistsError):
        write_schema_dir(schema, dest)   # second write must not overwrite


def test_written_schema_loads_back_via_load_schema_dir(tmp_path):
    """The dir we write must be readable by the same loader --schema-dir uses."""
    from seed_data.schema import Schema
    from seed_data.infer import write_schema_dir
    from seed_data.utils import load_schema_dir

    schema = Schema(name="invoice",
                    json_schema={"type": "object", "properties": {"n": {"type": "string"}},
                                 "required": ["n"]},
                    generation_guidance="## Data Realism\nNames are US-style.")
    dest = str(tmp_path / "invoice")
    write_schema_dir(schema, dest)

    loaded_schema, steering, samples = load_schema_dir(dest)
    assert loaded_schema["title"] == "invoice"
    assert "Data Realism" in steering
    assert samples == []


# --- infer_schema orchestration (vision call mocked) ------------------------

def test_infer_schema_mocked(tmp_path, monkeypatch):
    """infer_schema wires resolve_inputs -> vision -> Schema without Bedrock."""
    import seed_data.infer as infer_mod
    from seed_data.infer import _InferredSchema

    _write(str(tmp_path / "a.pdf"))
    _write(str(tmp_path / "b.pdf"))

    captured = {}

    def fake_run(docs, *, name, model, session, on_question=None, verbose):
        captured["n_docs"] = len(docs)
        captured["name"] = name
        return ({"type": "object", "properties": {"total": {"type": "number"}}, "title": "wrong"},
                "## Visual Style\nClean.")
    monkeypatch.setattr(infer_mod, "_run_inference", fake_run)

    schema = infer_mod.infer_schema(str(tmp_path / "*.pdf"), name="invoice", verbose=False)
    assert schema.name == "invoice"
    assert schema.to_schema_dict()["title"] == "invoice"   # name is authoritative
    assert captured["n_docs"] == 2


def test_infer_schema_no_docs_raises(tmp_path):
    from seed_data.infer import infer_schema
    with pytest.raises(FileNotFoundError):
        infer_schema(str(tmp_path / "*.pdf"), name="invoice", verbose=False)


def test_infer_schema_respects_max_docs(tmp_path, monkeypatch):
    import seed_data.infer as infer_mod
    for i in range(4):
        _write(str(tmp_path / f"d{i}.pdf"))

    seen = {}
    def fake_run(docs, *, name, model, session, on_question=None, verbose):
        seen["n"] = len(docs)
        return ({"type": "object"}, "g")
    monkeypatch.setattr(infer_mod, "_run_inference", fake_run)

    infer_mod.infer_schema(str(tmp_path / "*.pdf"), name="x", max_docs=2, verbose=False)
    assert seen["n"] == 2


def test_inferred_schema_structured_model():
    from seed_data.infer import _InferredSchema
    m = _InferredSchema(json_schema={"type": "object"}, generation_guidance="g")
    assert m.field_notes == ""   # optional, defaults empty


# --- clarifying-dialogue tool (make_ask_user_tool) --------------------------

def _call_tool(tool, question):
    """Invoke a Strands @tool the way the agent does, tolerating either the
    decorated-callable or the .func form, and return its text payload."""
    fn = getattr(tool, "func", tool)
    out = fn(question=question) if _accepts_kw(fn) else fn(question)
    # Strands tool results: {"status":..., "content":[{"text":...}]}
    return out["content"][0]["text"]


def _accepts_kw(fn):
    import inspect
    try:
        return "question" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return True


def test_ask_user_tool_routes_to_callback():
    from seed_data.tools import make_ask_user_tool
    seen = {}
    def cb(q):
        seen["q"] = q
        return "always present"
    tool = make_ask_user_tool(cb)
    answer = _call_tool(tool, "Is the PO number always present?")
    assert seen["q"] == "Is the PO number always present?"
    assert "always present" in answer


def test_ask_user_tool_handles_no_answer():
    from seed_data.tools import make_ask_user_tool
    tool = make_ask_user_tool(lambda q: None)      # user declined
    answer = _call_tool(tool, "anything?")
    assert "did not answer" in answer.lower() or "best judgment" in answer.lower()


def test_ask_user_tool_handles_empty_answer():
    from seed_data.tools import make_ask_user_tool
    tool = make_ask_user_tool(lambda q: "   ")     # whitespace only
    answer = _call_tool(tool, "anything?")
    assert "best judgment" in answer.lower()


def test_ask_user_tool_survives_callback_exception():
    from seed_data.tools import make_ask_user_tool
    def boom(q):
        raise RuntimeError("UI crashed")
    tool = make_ask_user_tool(boom)
    # must not raise — a broken dialogue UI cannot abort inference
    answer = _call_tool(tool, "anything?")
    assert "no answer" in answer.lower() or "best judgment" in answer.lower()


def test_infer_schema_passes_on_question_through(tmp_path, monkeypatch):
    """on_question reaches _run_inference (the agent only gets ask_user then)."""
    import seed_data.infer as infer_mod

    def _write(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(b"%PDF-1.4 x")
    _write(str(tmp_path / "a.pdf"))

    captured = {}
    def fake_run(docs, *, name, model, session, on_question, verbose):
        captured["on_question"] = on_question
        return ({"type": "object"}, "g")
    monkeypatch.setattr(infer_mod, "_run_inference", fake_run)

    cb = lambda q: "yes"
    infer_mod.infer_schema(str(tmp_path / "a.pdf"), name="x", on_question=cb, verbose=False)
    assert captured["on_question"] is cb

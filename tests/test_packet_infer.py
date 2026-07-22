"""Tests for packet inference (one concatenated PDF -> packet.json + schemas).

Covers the deterministic surface with no Bedrock: --boundaries parsing/validation,
PDF page extraction, schema-dir-name deduping, and full packet assembly with the
vision splitter and per-segment schema inference mocked. Also asserts the written
packet.json round-trips through the real load_packet_config.
"""
import io
import json
import os

import pytest

from seed_data.packet_infer import (
    parse_boundaries, _extract_pages, _pdf_page_count, _dedupe_names, _Segment,
    _validate_segments, _safe_dir_name,
)


# --- boundary parsing -------------------------------------------------------

def test_parse_boundaries_ranges_and_singles():
    assert parse_boundaries("1-2,3,4-5", 5) == [(1, 2), (3, 3), (4, 5)]


def test_parse_boundaries_single_whole_doc():
    assert parse_boundaries("1-3", 3) == [(1, 3)]


def test_parse_boundaries_rejects_overlap():
    with pytest.raises(ValueError):
        parse_boundaries("1-3,2-4", 5)


def test_parse_boundaries_rejects_out_of_range():
    with pytest.raises(ValueError):
        parse_boundaries("1-2,3-9", 5)   # 9 > 5 pages


def test_parse_boundaries_rejects_backwards():
    with pytest.raises(ValueError):
        parse_boundaries("3-1", 5)


def test_parse_boundaries_rejects_empty():
    with pytest.raises(ValueError):
        parse_boundaries("", 5)


# --- PDF page extraction (real pypdf, synthetic multi-page PDF) -------------

def _make_pdf(n_pages: int) -> bytes:
    import pypdf
    w = pypdf.PdfWriter()
    for _ in range(n_pages):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_pdf_page_count():
    assert _pdf_page_count(_make_pdf(5)) == 5


def test_extract_pages_subsets_correctly():
    src = _make_pdf(6)
    sub = _extract_pages(src, 2, 4)      # pages 2,3,4 -> 3 pages
    assert _pdf_page_count(sub) == 3


def test_extract_single_page():
    assert _pdf_page_count(_extract_pages(_make_pdf(4), 3, 3)) == 1


# --- schema_dir_name deduping -----------------------------------------------

def test_dedupe_names_disambiguates_repeats():
    segs = [
        _Segment(document_class="Pay Stub", schema_dir_name="pay-stub", start_page=1, end_page=1),
        _Segment(document_class="Pay Stub", schema_dir_name="pay-stub", start_page=2, end_page=2),
        _Segment(document_class="W-2", schema_dir_name="w2", start_page=3, end_page=3),
    ]
    _dedupe_names(segs)
    assert [s.schema_dir_name for s in segs] == ["pay-stub", "pay-stub-2", "w2"]


def test_dedupe_names_collision_proof_against_model_numbering():
    # Model itself emits 'pay-stub-2' — the dedupe of the 2nd 'pay-stub' must not
    # collide with it. All three names must end up distinct.
    segs = [
        _Segment(document_class="Pay Stub", schema_dir_name="pay-stub", start_page=1, end_page=1),
        _Segment(document_class="Pay Stub", schema_dir_name="pay-stub", start_page=2, end_page=2),
        _Segment(document_class="Pay Stub", schema_dir_name="pay-stub-2", start_page=3, end_page=3),
    ]
    _dedupe_names(segs)
    names = [s.schema_dir_name for s in segs]
    assert len(set(names)) == 3, names


def test_safe_dir_name_blocks_traversal_and_empty():
    assert _safe_dir_name("../shared", "fallback") == "shared"
    assert _safe_dir_name("a/b/c", "fallback") == "c"
    assert _safe_dir_name("", "fallback") == "fallback"
    assert _safe_dir_name("..", "fallback") == "fallback"
    assert _safe_dir_name("pay stub!", "fallback") == "pay-stub"


def test_dedupe_sanitizes_unsafe_model_names():
    segs = [_Segment(document_class="X", schema_dir_name="../escape", start_page=1, end_page=1)]
    _dedupe_names(segs)
    assert "/" not in segs[0].schema_dir_name and ".." not in segs[0].schema_dir_name


# --- segment validation (untrusted model output) ---------------------------

def test_validate_segments_accepts_contiguous_cover():
    segs = [
        _Segment(document_class="A", schema_dir_name="a", start_page=1, end_page=2),
        _Segment(document_class="B", schema_dir_name="b", start_page=3, end_page=3),
    ]
    _validate_segments(segs, n_pages=3)   # no raise


def test_validate_segments_rejects_out_of_range():
    segs = [_Segment(document_class="A", schema_dir_name="a", start_page=1, end_page=9)]
    with pytest.raises(ValueError):
        _validate_segments(segs, n_pages=3)


def test_validate_segments_rejects_gap():
    segs = [
        _Segment(document_class="A", schema_dir_name="a", start_page=1, end_page=1),
        _Segment(document_class="B", schema_dir_name="b", start_page=3, end_page=3),  # skips p2
    ]
    with pytest.raises(ValueError):
        _validate_segments(segs, n_pages=3)


def test_validate_segments_rejects_incomplete_cover():
    segs = [_Segment(document_class="A", schema_dir_name="a", start_page=1, end_page=2)]
    with pytest.raises(ValueError):
        _validate_segments(segs, n_pages=4)   # only covers 1-2 of 4


def test_segment_model_rejects_backwards_range():
    with pytest.raises(Exception):   # pydantic validation error
        _Segment(document_class="A", schema_dir_name="a", start_page=3, end_page=1)


# --- full packet inference (splitter + per-segment inference mocked) --------

def test_infer_packet_writes_config_and_schema_dirs(tmp_path, monkeypatch):
    import seed_data.packet_infer as pkt
    from seed_data.schema import Schema

    src = _make_pdf(4)
    pdf_path = str(tmp_path / "package.pdf")
    with open(pdf_path, "wb") as f:
        f.write(src)

    # Mock the vision splitter: 3 segments across the 4 pages, one repeated type.
    def fake_detect(pdf_bytes, *, packet_name, model, session, boundaries, on_question=None, verbose):
        return [
            _Segment(document_class="Loan Application", schema_dir_name="loan-application", start_page=1, end_page=2),
            _Segment(document_class="Pay Stub", schema_dir_name="pay-stub", start_page=3, end_page=3),
            _Segment(document_class="Pay Stub", schema_dir_name="pay-stub", start_page=4, end_page=4),
        ]
    monkeypatch.setattr(pkt, "_detect_segments", fake_detect)

    # Mock per-segment schema inference (no Bedrock).
    def fake_infer_segment(seg_bytes, *, name, model, session, on_question=None, verbose):
        return Schema(name=name, json_schema={"type": "object", "properties": {"x": {"type": "string"}}},
                      generation_guidance=f"## {name}")
    monkeypatch.setattr(pkt, "_infer_segment_schema", fake_infer_segment)

    out = str(tmp_path / "lending")
    result = pkt.infer_packet(pdf_path, name="lending-package", output_dir=out, verbose=False)
    assert result == out

    # packet.json written with 3 documents; repeated type deduped
    cfg = json.load(open(os.path.join(out, "packet.json")))
    assert cfg["name"] == "lending-package"
    assert [d["document_class"] for d in cfg["documents"]] == ["Loan Application", "Pay Stub", "Pay Stub"]
    dirs = [os.path.basename(d["schema_dir"]) for d in cfg["documents"]]
    assert dirs == ["loan-application", "pay-stub", "pay-stub-2"]
    # schema_dir paths are absolute (so `seed-data packet` resolves them)
    assert all(os.path.isabs(d["schema_dir"]) for d in cfg["documents"])
    # each schema dir actually written
    for d in dirs:
        assert os.path.exists(os.path.join(out, d, "schema.json"))


def test_infer_packet_roundtrips_through_load_packet_config(tmp_path, monkeypatch):
    """The packet.json we write must parse with the real packet loader."""
    import seed_data.packet_infer as pkt
    from seed_data.schema import Schema
    from seed_data.packet import load_packet_config

    src = _make_pdf(2)
    pdf_path = str(tmp_path / "pkg.pdf")
    with open(pdf_path, "wb") as f:
        f.write(src)

    monkeypatch.setattr(pkt, "_detect_segments", lambda *a, **k: [
        _Segment(document_class="Invoice", schema_dir_name="invoice", start_page=1, end_page=2),
    ])
    monkeypatch.setattr(pkt, "_infer_segment_schema", lambda *a, **k:
        Schema(name="invoice", json_schema={"type": "object"}, generation_guidance="g"))

    out = str(tmp_path / "pk")
    pkt.infer_packet(pdf_path, name="pk", output_dir=out, verbose=False)

    config = load_packet_config(out)     # the real loader `seed-data packet` uses
    assert config.name == "pk"
    assert len(config.documents) == 1
    assert config.documents[0].document_class == "Invoice"
    # loader resolved the absolute schema_dir to a real directory
    assert os.path.isdir(config.documents[0].schema_dir)


def test_infer_packet_refuses_clobber(tmp_path, monkeypatch):
    import seed_data.packet_infer as pkt
    out = str(tmp_path / "pk")
    os.makedirs(out)
    with open(os.path.join(out, "packet.json"), "w") as f:
        f.write("{}")
    with open(str(tmp_path / "p.pdf"), "wb") as f:
        f.write(_make_pdf(1))
    with pytest.raises(FileExistsError):
        pkt.infer_packet(str(tmp_path / "p.pdf"), name="pk", output_dir=out, verbose=False)


def test_infer_packet_rejects_non_pdf(tmp_path):
    from seed_data.packet_infer import infer_packet
    img = str(tmp_path / "photo.png")
    with open(img, "wb") as f:
        f.write(b"\x89PNG fake")
    with pytest.raises(FileNotFoundError):   # no PDF among inputs
        infer_packet(img, name="pk", output_dir=str(tmp_path / "o"), verbose=False)


def test_infer_packet_rejects_model_bad_range_with_valueerror(tmp_path, monkeypatch):
    """A hallucinated out-of-range segment must raise ValueError (CLI-caught),
    NOT an IndexError from deep inside pypdf."""
    import seed_data.packet_infer as pkt
    src = _make_pdf(2)
    pdf_path = str(tmp_path / "pkg.pdf")
    with open(pdf_path, "wb") as f:
        f.write(src)
    monkeypatch.setattr(pkt, "_detect_segments", lambda *a, **k: [
        _Segment(document_class="A", schema_dir_name="a", start_page=1, end_page=9),  # 9 > 2
    ])
    with pytest.raises(ValueError):
        pkt.infer_packet(pdf_path, name="pk", output_dir=str(tmp_path / "o"), verbose=False)


def test_infer_packet_refuses_nonempty_output(tmp_path):
    from seed_data.packet_infer import infer_packet
    out = str(tmp_path / "pk")
    os.makedirs(out)
    with open(os.path.join(out, "stray.txt"), "w") as f:  # non-empty, but no packet.json
        f.write("x")
    with open(str(tmp_path / "p.pdf"), "wb") as f:
        f.write(_make_pdf(1))
    with pytest.raises(FileExistsError):
        infer_packet(str(tmp_path / "p.pdf"), name="pk", output_dir=out, verbose=False)


def test_infer_packet_leaves_no_poison_on_midloop_failure(tmp_path, monkeypatch):
    """If per-segment inference fails mid-loop, the output dir must not exist
    (staging is cleaned up), so a retry starts clean."""
    import seed_data.packet_infer as pkt
    src = _make_pdf(2)
    pdf_path = str(tmp_path / "pkg.pdf")
    with open(pdf_path, "wb") as f:
        f.write(src)
    monkeypatch.setattr(pkt, "_detect_segments", lambda *a, **k: [
        _Segment(document_class="A", schema_dir_name="a", start_page=1, end_page=1),
        _Segment(document_class="B", schema_dir_name="b", start_page=2, end_page=2),
    ])

    calls = {"n": 0}
    def flaky_infer(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated Bedrock throttle on segment 2")
        from seed_data.schema import Schema
        return Schema(name="a", json_schema={"type": "object"}, generation_guidance="g")
    monkeypatch.setattr(pkt, "_infer_segment_schema", flaky_infer)

    out = str(tmp_path / "pk")
    with pytest.raises(RuntimeError):
        pkt.infer_packet(pdf_path, name="pk", output_dir=out, verbose=False)
    # no poisoned partial output left behind
    assert not os.path.exists(out)
    # and no leftover staging dirs beside it
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".seed_packet_")]
    assert leftovers == []

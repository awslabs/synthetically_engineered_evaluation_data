"""Tests for the augment-stage hardening — no Bedrock, no augraphy execution.

Covers the three fixes for the "augment wedges generate_batch" report:
  1. node_timeout is actually set on the built pipeline graph (the hard bound
     against a wedged node — the root cause of the infinite hang).
  2. scalar -> range coercion for range-expecting augraphy params (the
     InkBleed(severity=<int>) TypeError).
  3. the augment critic accepts best-effort after MAX_AUG_ATTEMPTS instead of
     looping the augmentor->critic edge forever.
"""
import os

from seed_data.stages.base import StageContext, ModelConfig, Verdict


def _ctx(tmp_path, threshold=7) -> StageContext:
    return StageContext(
        schema_dict={"title": "invoice", "type": "object"},
        output_path=os.path.join(tmp_path, "pdfs", "doc.pdf"),
        data_json_path=os.path.join(tmp_path, "data", "doc.json"),
        script_path=os.path.join(tmp_path, "scripts", "doc.html"),
        models=ModelConfig(),
        output_dir=str(tmp_path),
        threshold=threshold,
    )


# --- (1) node_timeout is set on the built graph ----------------------------

def test_pipeline_graph_sets_node_timeout(tmp_path):
    from seed_data.stages.pipeline import build_pipeline_graph
    g = build_pipeline_graph(_ctx(str(tmp_path)), augment=True)
    # Strands stores it on the built Graph; must be a positive number, not None.
    assert getattr(g, "node_timeout", None), "node_timeout must be set (guards against wedged nodes)"
    assert g.node_timeout > 0


def test_pipeline_graph_node_timeout_configurable(tmp_path):
    from seed_data.stages.pipeline import build_pipeline_graph
    g = build_pipeline_graph(_ctx(str(tmp_path)), node_timeout=123)
    assert g.node_timeout == 123


# --- (2) signature-driven param coercion (the InkBleed/SubtleNoise crashes) -

def test_coerce_scalar_where_range_expected():
    """InkBleed(severity=3) previously raised 'int object is not subscriptable'.
    A scalar given for a tuple-default param becomes a (x, x) range."""
    from seed_data.augment import _coerce_to_default_shape
    assert _coerce_to_default_shape(3, (0.3, 0.4)) == (3, 3)


def test_coerce_range_where_scalar_expected():
    """SubtleNoise(subtle_range=[10,15]) previously raised 'unary -: tuple'.
    subtle_range's default is a bare int, so a list is reduced to its low bound."""
    from seed_data.augment import _coerce_to_default_shape
    assert _coerce_to_default_shape([10, 15], 10) == 10


def test_coerce_float_to_int_tuple():
    """NoiseTexturize(sigma_range=[15.0,25.0]) previously raised 'float ... integer'.
    An int-typed tuple default forces int bounds."""
    from seed_data.augment import _coerce_to_default_shape
    assert _coerce_to_default_shape([15.0, 25.0], (3, 10)) == (15, 25)


def test_coerce_preserves_float_range():
    from seed_data.augment import _coerce_to_default_shape
    assert _coerce_to_default_shape([0.5, 0.8], (0.4, 0.7)) == (0.5, 0.8)


def test_inkbleed_scalar_severity_builds():
    """End-to-end: the exact crash case now instantiates cleanly."""
    from seed_data.augment import _build_augmentation
    assert type(_build_augmentation("InkBleed", {"severity": 3})).__name__ == "InkBleed"


def test_subtle_noise_list_builds():
    """The exact wedge-causing case: SubtleNoise given a list must not crash."""
    from seed_data.augment import _build_augmentation
    assert type(_build_augmentation("SubtleNoise", {"subtle_range": [10, 15]})).__name__ == "SubtleNoise"


# --- (3) max-reject cap: critic accepts best-effort, breaking the loop ------

def _run_critic(ctx, monkeypatch, *, score, aug_pdf_exists=True):
    """Drive build_critic's inner function directly, stubbing the vision critic."""
    import seed_data.stages.augment_stage as aug
    # Make the "augmented PDF exists" guard deterministic.
    if aug_pdf_exists:
        p = aug._aug_output_path(ctx)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(b"%PDF-1.4 aug")
    monkeypatch.setattr(
        "seed_data.augment.critique_augmented_document",
        lambda **kw: {"verdict": "rejected" if score < ctx.threshold else "accepted",
                      "score": score, "summary": "s", "issues": []},
    )
    node = aug.build_critic(ctx)
    # FunctionNode wraps our closure; call it the way the node would.
    return node.func


def test_aug_critic_accepts_best_effort_after_cap(tmp_path, monkeypatch):
    import seed_data.stages.augment_stage as aug
    ctx = _ctx(str(tmp_path), threshold=9)   # high bar so the score always rejects
    run = _run_critic(ctx, monkeypatch, score=3)

    verdicts = [Verdict.from_node_text(run("", ctx)) for _ in range(aug.MAX_AUG_ATTEMPTS)]
    # First MAX-1 attempts reject (loop), the last accepts best-effort (exits).
    assert verdicts[-1].accepted is True
    assert any(not v.accepted for v in verdicts[:-1]) or aug.MAX_AUG_ATTEMPTS == 1
    # and it keeps the real score, not a fake pass
    assert verdicts[-1].score == 3


def test_aug_critic_accepts_immediately_when_above_threshold(tmp_path, monkeypatch):
    ctx = _ctx(str(tmp_path), threshold=5)
    run = _run_critic(ctx, monkeypatch, score=8)
    v = Verdict.from_node_text(run("", ctx))
    assert v.accepted is True and v.score == 8


def test_aug_critic_gives_up_when_no_pdf_after_cap(tmp_path, monkeypatch):
    """If augmentation never produces a PDF, accept (keep clean doc) after the cap
    rather than loop asking for a re-run forever."""
    import seed_data.stages.augment_stage as aug
    ctx = _ctx(str(tmp_path), threshold=7)
    # no aug PDF on disk; critique_augmented_document should never be called
    node = aug.build_critic(ctx)
    verdicts = [Verdict.from_node_text(node.func("", ctx)) for _ in range(aug.MAX_AUG_ATTEMPTS)]
    assert verdicts[-1].accepted is True   # gave up -> accept so the graph exits
    assert verdicts[0].accepted is False   # first attempt asked for a re-run

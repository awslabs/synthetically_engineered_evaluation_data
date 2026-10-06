"""Optional-dependency guard tests.

Deliberately free of ``importorskip``: these must run in the lean ``test-base``
CI job, which installs no ``[structured]`` extra. The point is the message a base
user sees, so the tests simulate absence rather than requiring it — that way they
assert the same behavior in both CI jobs.
"""
import sys

import pytest

from seed_data.common.deps import require_structured


def test_require_structured_passes_when_available(monkeypatch):
    monkeypatch.setattr("seed_data.common.deps.structured_available", lambda: True)
    require_structured("anything")  # must not raise


def test_require_structured_message_is_actionable(monkeypatch):
    """The error must name the feature, the extra, and the exact install command.

    A bare `ModuleNotFoundError: No module named 'pandas'` is what this replaces:
    it names neither what was refused nor how to fix it.
    """
    monkeypatch.setattr("seed_data.common.deps.structured_available", lambda: False)

    with pytest.raises(ImportError) as exc:
        require_structured("Generator.generate_structured")

    msg = str(exc.value)
    assert "Generator.generate_structured" in msg
    assert "seed-data[structured]" in msg
    assert "pip install" in msg


def test_structured_available_survives_a_raising_finder(monkeypatch):
    """Regression: the check must not leak the error it exists to translate.

    `find_spec` returns None for an absent module but *raises* when a meta-path
    finder objects or a parent package is broken. An unguarded call let the raw
    `ImportError: No module named 'pandas'` escape from inside the detector, so
    the CLI printed the bare message instead of the install hint.
    """
    from seed_data.common import deps

    def raising(name):
        raise ImportError("No module named 'pandas'")

    monkeypatch.setattr(deps, "find_spec", raising)
    assert deps.structured_available() is False


def test_structured_available_probes_pandas_not_numpy(monkeypatch):
    """numpy/scipy must not be the probe — the `[augment]` extra pulls them in too.

    Probing them would report the structured extra as present on an install that
    only has augmentation, which is the bug this indirection exists to avoid.
    """
    from seed_data.common import deps

    assert deps._STRUCTURED_PROBE == "pandas"

    monkeypatch.setattr(deps, "find_spec", lambda name: None if name == "pandas" else object())
    assert deps.structured_available() is False


def test_generate_structured_raises_before_resolving_schema(monkeypatch):
    """The guard must fire before schema resolution and before the pipeline runs.

    Regression: the missing dependency used to surface from deep inside
    run_graph_pipeline, where run_structured's broad `except` turned it into
    StructuredResult(success=False, error="No module named 'pandas'") — a missing
    install reported as if the pipeline had run and failed.
    """
    from seed_data import Generator

    monkeypatch.setattr("seed_data.common.deps.structured_available", lambda: False)

    g = Generator()
    called = []
    monkeypatch.setattr(
        Generator, "_resolve_inferred",
        lambda self, s: called.append(s) or s,
    )

    with pytest.raises(ImportError, match=r"seed-data\[structured\]"):
        g.generate_structured("invoice", rows=5, verbose=False)

    assert not called, "schema resolution must not run when the extra is missing"


def test_plan_and_generate_structured_checks_extra_before_planning(monkeypatch):
    """`plan_and_generate(output='structured')` must not pay for planning before
    failing.

    Planning is a multi-agent LLM run; failing after it would bill the user for the
    expensive half of the chain to report something knowable up front.
    """
    from seed_data import Generator

    monkeypatch.setattr("seed_data.common.deps.structured_available", lambda: False)

    planned = []
    monkeypatch.setattr(
        Generator, "plan",
        lambda self, *a, **k: planned.append(a) or "schema",
    )

    with pytest.raises(ImportError, match=r"seed-data\[structured\]"):
        Generator().plan_and_generate("some text", output="structured", verbose=False)

    assert not planned, "planning must not run when the extra is missing"


def test_plan_and_generate_documents_does_not_require_the_extra(monkeypatch):
    """The document modality must stay reachable on the base install.

    This is the published offering; the guard must not leak into its path.
    """
    from seed_data import Generator

    monkeypatch.setattr("seed_data.common.deps.structured_available", lambda: False)
    monkeypatch.setattr(Generator, "plan", lambda self, *a, **k: "schema")

    sentinel = object()
    monkeypatch.setattr(Generator, "generate", lambda self, *a, **k: sentinel)

    assert Generator().plan_and_generate("text", output="documents", verbose=False) is sentinel


def test_evaluation_lazy_attr_error_names_the_extra(monkeypatch):
    """A tabular scorer whose import fails for want of the extra must name it.

    Simulates the lean install by making the submodule import raise the way a
    missing pandas does, then asserts the bare "No module named 'pandas'" is
    rewritten to name both the attribute and the extra. This is also the path
    `from seed_data.evaluation import *` takes, since it binds every name in
    __all__ through this same __getattr__.
    """
    import importlib

    import seed_data.evaluation as ev

    monkeypatch.setattr("seed_data.common.deps.structured_available", lambda: False)

    def no_pandas(name, *a, **k):
        raise ImportError("No module named 'pandas'")

    monkeypatch.setattr(importlib, "import_module", no_pandas)

    with pytest.raises(ImportError) as exc:
        ev.CoverageMetrics

    msg = str(exc.value)
    assert "CoverageMetrics" in msg
    assert "seed-data[structured]" in msg


def test_evaluation_lazy_attr_preserves_a_genuine_import_error(monkeypatch):
    """A real bug must not be relabelled as a missing extra.

    With the extra installed, a broken submodule should surface its own error —
    blaming the install would send the user chasing a dependency that is present.
    """
    import importlib

    import seed_data.evaluation as ev

    monkeypatch.setattr("seed_data.common.deps.structured_available", lambda: True)

    def broken(name, *a, **k):
        raise ImportError("cannot import name 'Foo' from partially initialized module")

    monkeypatch.setattr(importlib, "import_module", broken)

    with pytest.raises(ImportError, match="partially initialized"):
        ev.CoverageMetrics


def test_run_evaluation_resolves_without_the_extra(monkeypatch):
    """`run_evaluation` must stay *resolvable* on a lean install.

    The package documents that a mere import never requires the tabular stack:
    metrics.py defers its pandas import into the function body, so attribute
    access has to succeed and only *calling* it may fail. An eager extra-check in
    __getattr__ would break that contract.
    """
    import seed_data.evaluation as ev

    monkeypatch.setattr("seed_data.common.deps.structured_available", lambda: False)
    monkeypatch.delitem(sys.modules, "seed_data.evaluation.metrics", raising=False)

    assert callable(ev.run_evaluation)


def test_evaluation_document_side_needs_no_extra(monkeypatch):
    """The pure-Python document scorers must not be gated."""
    import seed_data.evaluation as ev

    monkeypatch.setattr("seed_data.common.deps.structured_available", lambda: False)

    # Eagerly imported at module level, so the guard must never see these.
    assert ev.evaluate_document_labels is not None
    assert ev.DocumentLabelReport is not None
    assert ev.critique_structured is not None


def test_all_names_are_resolvable_with_the_extra():
    """Every advertised name must resolve when the extra IS installed.

    Guards against a typo in the _LAZY table silently turning a public name into
    an AttributeError.
    """
    pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")

    import seed_data.evaluation as ev

    for name in ev.__all__:
        assert getattr(ev, name) is not None, f"{name} in __all__ but unresolvable"


# --- model registry / import structure --------------------------------------

def test_model_registry_is_a_leaf_module():
    """`seed_data.model_registry` must import nothing.

    `common.config` needs the registry. It used to reach it via `from seed_data
    import MODELS`, which imports the package root — the same root that exposes
    the API surface. That worked only because `MODELS` was bound before the lazy
    `__getattr__`; one eager import added above it would have turned config's
    import into a circular ImportError. This test pins the property that makes
    the leaf safe rather than the accident that made the old path work.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c",
         "import sys\n"
         "from seed_data.model_registry import MODELS\n"
         "banned = [m for m in ('strands', 'boto3', 'botocore', 'pandas', 'numpy')\n"
         "          if m in sys.modules]\n"
         "assert not banned, banned\n"
         "assert 'seed_data.api' not in sys.modules\n"
         "print(len(MODELS))\n"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) > 0


def test_common_config_imports_standalone():
    """Importing `common.config` first, with no prior `import seed_data`, must work.

    A fresh interpreter is the only way to test this: within the test session
    `seed_data` is already fully imported, which is exactly the condition that
    hid the fragility.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c",
         "from seed_data.common.config import MODEL_ID, MAX_TOKENS\n"
         "assert MODEL_ID and MAX_TOKENS > 0\n"
         "print('ok')\n"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_models_is_still_exported_from_the_package_root():
    """`from seed_data import MODELS` is the documented public name — moving the
    definition to a leaf module must not change it."""
    import seed_data
    from seed_data.model_registry import MODELS as leaf_models

    assert seed_data.MODELS is leaf_models
    assert "MODELS" in seed_data.__all__


# --- [augment] extra -----------------------------------------------------------

def test_require_augment_passes_when_available(monkeypatch):
    monkeypatch.setattr("seed_data.common.deps.augment_available", lambda: True)
    from seed_data.common.deps import require_augment
    require_augment("anything")  # must not raise


def test_require_augment_message_is_actionable(monkeypatch):
    monkeypatch.setattr("seed_data.common.deps.augment_available", lambda: False)
    from seed_data.common.deps import require_augment

    with pytest.raises(ImportError) as exc:
        require_augment("--augment")

    msg = str(exc.value)
    assert "--augment" in msg
    assert "seed-data[augment]" in msg
    assert "pip install" in msg


def test_augment_available_probes_augraphy(monkeypatch):
    from seed_data.common import deps

    assert deps._AUGMENT_PROBE == "augraphy"
    monkeypatch.setattr(deps, "find_spec", lambda name: None if name == "augraphy" else object())
    assert deps.augment_available() is False


def test_augment_available_survives_a_raising_finder(monkeypatch):
    from seed_data.common import deps

    def raising(name):
        raise ImportError("No module named 'augraphy'")

    monkeypatch.setattr(deps, "find_spec", raising)
    assert deps.augment_available() is False


def test_augmented_graph_build_raises_before_any_node_runs(monkeypatch, tmp_path):
    """Asking for augmentation without the extra must fail at graph build — before
    the data generator spends tokens — not as a failed augment node afterwards."""
    import os
    from seed_data.stages.base import ModelConfig, StageContext
    from seed_data.stages.pipeline import build_pipeline_graph

    monkeypatch.setattr("seed_data.common.deps.augment_available", lambda: False)
    ctx = StageContext(
        schema_dict={"title": "invoice", "type": "object"},
        output_path=os.path.join(tmp_path, "pdfs", "doc.pdf"),
        data_json_path=os.path.join(tmp_path, "data", "doc.json"),
        script_path=os.path.join(tmp_path, "scripts", "doc.html"),
        models=ModelConfig(), output_dir=str(tmp_path), threshold=7,
    )
    with pytest.raises(ImportError, match=r"seed-data\[augment\]"):
        build_pipeline_graph(ctx, augment=True)
    build_pipeline_graph(ctx, augment=False)  # the un-augmented path is unaffected


def test_augmented_batch_raises_before_scenario_planning(monkeypatch):
    """generate_batch plans scenarios with a paid model call before it builds any
    per-document graph, so the guard has to sit ahead of the planner."""
    from seed_data.stages import batch

    monkeypatch.setattr("seed_data.common.deps.augment_available", lambda: False)

    def planner_must_not_run(*a, **k):
        raise AssertionError("scenario planner ran before the augment guard")

    monkeypatch.setattr(batch, "plan_scenarios", planner_must_not_run)
    with pytest.raises(ImportError, match=r"seed-data\[augment\]"):
        batch.generate_batch(schema_dir="unused", count=2, brief="x", augment=True)

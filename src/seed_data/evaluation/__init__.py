"""Evaluation for both generation modalities.

Split by dependency weight so the lean base install can import this package:

- ``evaluate_document_labels`` / ``DocumentLabelReport`` and the ``critique_*``
  helpers are pure-Python (or Strands-only) — always importable.
- The tabular scorers (``run_evaluation`` and the ``*Metrics`` classes) need the
  ``[structured]`` extra (pandas/numpy/scipy). They are resolved lazily via
  ``__getattr__`` so a mere ``import seed_data.evaluation`` never requires that
  stack — only actually touching a scorer does, and then the missing dependency
  surfaces at that point rather than at import time.

``__all__`` lists both groups, because it documents the package's public surface
rather than what any one environment can resolve. Two consequences on a lean
install: ``from seed_data.evaluation import *`` binds every name in ``__all__``,
so it reaches the ``*Metrics`` classes and raises — import the document-side names
explicitly to stay within the base install. And when a scorer's import does fail
for want of the extra, ``__getattr__`` rewrites the bare
``No module named 'pandas'`` into a message naming the extra to install.
"""
from .critique import (
    StructuredCritiqueResult,
    StructuredIssue,
    critique_structured,
)
from .metrics import (
    DocumentLabelReport,
    EntityEvaluationReport,
    EvaluationReport,
    evaluate_document_labels,
)

__all__ = [
    "CoverageMetrics",
    "DiversityMetrics",
    "DocumentLabelReport",
    "EntityEvaluationReport",
    "EvaluationReport",
    "FidelityMetrics",
    "StructuralMetrics",
    "StructuredCritiqueResult",
    "StructuredIssue",
    "critique_structured",
    "evaluate_document_labels",
    "run_evaluation",
]

# Tabular scorers live behind pandas (the `[structured]` extra). Import them only
# when referenced so the base install can use the document-side evaluation above.
_LAZY = {
    "CoverageMetrics": ("seed_data.evaluation.coverage", "CoverageMetrics"),
    "DiversityMetrics": ("seed_data.evaluation.diversity", "DiversityMetrics"),
    "FidelityMetrics": ("seed_data.evaluation.fidelity", "FidelityMetrics"),
    "StructuralMetrics": ("seed_data.evaluation.structural", "StructuralMetrics"),
    "run_evaluation": ("seed_data.evaluation.metrics", "run_evaluation"),
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        module_name, attr = _LAZY[name]
        try:
            return getattr(importlib.import_module(module_name), attr)
        except ImportError as exc:
            # Translate the raw "No module named 'pandas'" into a message naming
            # both the scorer and the extra. Only a *failed* import is rewritten,
            # deliberately: `run_evaluation` defers its own pandas import into the
            # function body, so resolving that attribute must keep working on a
            # lean install. Pre-checking the extra would break the deferral this
            # package documents.
            from seed_data.common.deps import require_structured, structured_available

            if structured_available():
                raise  # a real import error, not a missing extra
            require_structured(f"seed_data.evaluation.{name}")
            raise AssertionError("unreachable") from exc  # require_structured raised
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

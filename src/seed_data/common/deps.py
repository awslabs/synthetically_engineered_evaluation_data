"""Optional-dependency guards.

The base ``pip install seed-data`` deliberately omits the tabular stack, so every
entry point into structured generation or tabular evaluation can be reached
without pandas installed. Left unguarded, those paths fail with a bare
``ModuleNotFoundError: No module named 'pandas'`` raised from somewhere deep in
the call graph — which names neither the feature the user asked for nor the
extra that would fix it. Worse, ``run_structured`` catches broadly and reports
that string as a generation failure, so it reads like a bug in the pipeline.

:func:`require_structured` turns that into one actionable message, raised at the
boundary where the user's intent is still known.
"""
from __future__ import annotations

from importlib.util import find_spec

# pandas is the load-bearing import: every tabular module reaches it directly or
# via numpy/scipy, so its absence is a reliable proxy for "extra not installed".
# numpy and scipy are NOT checked — they arrive as transitive base dependencies
# of augraphy, so probing them would pass even on a lean install.
_STRUCTURED_PROBE = "pandas"


def structured_available() -> bool:
    """Whether the ``[structured]`` extra's tabular stack can be imported.

    ``find_spec`` returns ``None`` for a module that is simply absent, but it
    *raises* when a parent package is broken or a meta-path finder objects — so a
    bare call would let the very ``ImportError`` this module exists to translate
    escape from the check itself. Any failure to locate the module is treated as
    unavailable, which is the useful answer either way.
    """
    try:
        return find_spec(_STRUCTURED_PROBE) is not None
    except (ImportError, ValueError):
        return False


def require_structured(feature: str) -> None:
    """Raise an actionable :class:`ImportError` if the tabular stack is missing.

    Args:
        feature: what the caller was trying to do, named the way the user asked
            for it (a CLI subcommand, facade method, or metric name). It leads
            the message, so the error says which action was refused.

    Raises:
        ImportError: if the ``[structured]`` extra is not installed.
    """
    if structured_available():
        return
    raise ImportError(
        f"{feature} needs the optional structured-data dependencies, which are "
        "not installed. Install them with:\n\n"
        "    pip install 'seed-data[structured]'\n\n"
        "The base install covers document generation only; see the "
        "'Install options' section of the README."
    )

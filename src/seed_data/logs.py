"""Progress output for the ``verbose`` / ``--quiet`` flag.

The structured and ingest engines report progress through ``logger.info``. A
library that never configures logging has no handler, so those records went to
the "last resort" handler at WARNING and were dropped: a ``seed-data
plan-and-generate`` run made several minutes of Bedrock calls and printed
nothing, which is indistinguishable from a hang. (The document path uses
``print`` and did produce output, so ``--quiet`` also meant different things in
the two modalities.)

:func:`configure_progress_logging` attaches one stderr handler to the ``seed_data``
logger, and only when nothing else has claimed the output — a host application
that configured its own logging keeps control of formatting and destination, and
only the level is set. stderr rather than stdout so progress cannot corrupt piped
machine-readable output.
"""

from __future__ import annotations

import logging
import sys

_PACKAGE_LOGGER = "seed_data"
_HANDLER_NAME = "seed_data.progress"


def _has_progress_handler(logger: logging.Logger) -> bool:
    return any(getattr(h, "name", None) == _HANDLER_NAME for h in logger.handlers)


def configure_progress_logging(verbose: bool = True) -> None:
    """Route ``seed_data``'s progress logging to stderr.

    Idempotent: repeated calls (the facade verbs each call it, and
    ``plan_and_generate`` calls two of them) do not stack handlers.

    Args:
        verbose: ``True`` shows INFO-level progress; ``False`` leaves only
            warnings and errors, which is what ``--quiet`` asks for.
    """
    logger = logging.getLogger(_PACKAGE_LOGGER)
    logger.setLevel(logging.INFO if verbose else logging.WARNING)

    # A host that configured logging owns the handlers; adding ours would
    # duplicate its records. Setting the level above is still correct and is all
    # `verbose` can mean in that case.
    host_configured = bool(logging.getLogger().handlers)
    if host_configured or _has_progress_handler(logger):
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    # Records stop here rather than climbing to the root logger, which has no
    # handler in this branch and would fall through to the last-resort handler.
    logger.propagate = False


__all__ = ["configure_progress_logging"]

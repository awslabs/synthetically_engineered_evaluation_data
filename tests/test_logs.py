"""Progress-output wiring for `verbose` / `--quiet`.

The engines report progress through ``logger.info``, and nothing in ``src/`` ever
attached a handler — so a multi-minute Bedrock run printed nothing at all, which
is indistinguishable from a hang. These tests pin the handler down and, more
importantly, pin down when it must *not* be attached.
"""
import logging

import pytest

from seed_data.logs import _HANDLER_NAME, _PACKAGE_LOGGER, configure_progress_logging


@pytest.fixture
def clean_package_logger():
    """Restore the package logger, so a test cannot leak a handler into the rest
    of the suite."""
    logger = logging.getLogger(_PACKAGE_LOGGER)
    saved = (list(logger.handlers), logger.level, logger.propagate)
    logger.handlers = [h for h in logger.handlers if getattr(h, "name", None) != _HANDLER_NAME]
    yield logger
    logger.handlers, logger.level, logger.propagate = saved


def _progress_handlers(logger):
    return [h for h in logger.handlers if getattr(h, "name", None) == _HANDLER_NAME]


def test_verbose_attaches_a_handler(clean_package_logger, monkeypatch):
    monkeypatch.setattr(logging.getLogger(), "handlers", [])

    configure_progress_logging(verbose=True)

    assert len(_progress_handlers(clean_package_logger)) == 1
    assert clean_package_logger.level == logging.INFO


def test_repeated_calls_do_not_stack_handlers(clean_package_logger, monkeypatch):
    """`plan_and_generate` runs both engines, so this is called more than once per
    run; a per-call handler would print every progress line twice, then three
    times."""
    monkeypatch.setattr(logging.getLogger(), "handlers", [])

    for _ in range(4):
        configure_progress_logging(verbose=True)

    assert len(_progress_handlers(clean_package_logger)) == 1


def test_quiet_lowers_the_level(clean_package_logger, monkeypatch):
    monkeypatch.setattr(logging.getLogger(), "handlers", [])

    configure_progress_logging(verbose=False)

    assert clean_package_logger.level == logging.WARNING


def test_host_configured_logging_is_left_alone(clean_package_logger, monkeypatch):
    """A host application that configured its own logging owns the handlers and
    the formatting; adding ours would duplicate every record it emits."""
    monkeypatch.setattr(logging.getLogger(), "handlers", [logging.NullHandler()])

    configure_progress_logging(verbose=True)

    assert _progress_handlers(clean_package_logger) == []
    # The level is still ours to set — it is all `verbose` can mean here.
    assert clean_package_logger.level == logging.INFO


def test_progress_reaches_stderr(clean_package_logger, monkeypatch, capsys):
    """stderr, not stdout: progress must not corrupt piped machine-readable
    output."""
    monkeypatch.setattr(logging.getLogger(), "handlers", [])
    configure_progress_logging(verbose=True)

    logging.getLogger("seed_data.ingest.pipeline").info("ingesting things")

    captured = capsys.readouterr()
    assert "ingesting things" in captured.err
    assert "ingesting things" not in captured.out

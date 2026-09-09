"""Shared fixtures for integration tests.

Everything under ``tests/integration/`` hits live Bedrock and is excluded from
the default run (see ``addopts = --ignore=tests/integration`` in pyproject).
Invoke explicitly, with credentials:

    AWS_PROFILE=your-profile uv run pytest tests/integration -v

Even when invoked explicitly, individual tests skip (rather than error) if no
usable AWS credentials are resolvable, so a bare ``pytest tests/integration``
degrades to "skipped" instead of a wall of ``NoCredentialsError``.
"""
import os

import pytest

# The document pipeline drives strands_tools' `file_write` / `editor`, which
# prompt for interactive confirmation before touching the filesystem. Under
# pytest there is no tty, so prompt_toolkit cannot attach to stdin and the
# prompt dies with `OSError: [Errno 22] Invalid argument` — the doc agent then
# retries until the 600s node timeout and every document test fails. Setting
# this is the documented way to run the pipeline non-interactively (see
# GETTING_STARTED.md "About BYPASS_TOOL_CONSENT"); the equivalent flag is
# already required for the CLI examples in the docs.
#
# Set at import time, before any test constructs an Agent, and only when the
# caller has not made an explicit choice.
os.environ.setdefault("BYPASS_TOOL_CONSENT", "true")


def _credential_error() -> str | None:
    """Return a human-readable reason the creds are unusable, or None if usable.

    A ``get_credentials()`` object exists even when the token is expired, so we
    make one cheap STS call: that turns "expired token" into a clean skip with a
    clear message instead of a confusing failure deep inside the model client.
    """
    try:
        from seed_data.session import get_boto_session

        session = get_boto_session()
        if session.get_credentials() is None:
            return "no AWS credentials resolvable"
        session.client("sts").get_caller_identity()
        return None
    except Exception as e:  # ExpiredToken, no region, unreachable STS, etc.
        return f"{type(e).__name__}: {str(e)[:120]}"


@pytest.fixture(scope="session")
def aws_credentials():
    """Skip the test unless usable AWS credentials are present."""
    reason = _credential_error()
    if reason is not None:
        pytest.skip(f"AWS credentials not usable ({reason}) — set/refresh AWS_PROFILE to run integration tests")


@pytest.fixture
def generator(aws_credentials, tmp_path):
    """A Generator writing into an isolated temp dir, with public-Bedrock models."""
    from seed_data import Generator, ModelConfig

    return Generator(
        models=ModelConfig(data="sonnet", doc="sonnet", critic="haiku"),
        output_dir=str(tmp_path / "out"),
    )

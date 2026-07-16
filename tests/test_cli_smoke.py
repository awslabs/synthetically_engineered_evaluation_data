"""CLI smoke tests — verify `seed-data` works out of the box, without Bedrock.

These exercise argument parsing, subcommand dispatch, bundled-name resolution,
and the console-script entry point — everything up to (but not including) the
actual model calls. They catch "the CLI is broken on a fresh install" without
needing AWS credentials or spending tokens.
"""
import subprocess
import sys

import pytest


def _run(*args, **kwargs):
    """Invoke the CLI as `python -m seed_data <args>` and capture output."""
    return subprocess.run(
        [sys.executable, "-m", "seed_data", *args],
        capture_output=True, text=True, timeout=60, **kwargs,
    )


# --- the entry point exists and parses -------------------------------------

def test_help_exits_clean():
    r = _run("--help")
    assert r.returncode == 0
    assert "seed-data" in r.stdout
    assert "--schema-dir" in r.stdout
    assert "--count" in r.stdout


def test_packet_subcommand_help():
    r = _run("packet", "--help")
    assert r.returncode == 0
    assert "packet" in r.stdout.lower()
    assert "--doc-workers" in r.stdout


def test_clone_schema_library_help():
    r = _run("clone-schema-library", "--help")
    assert r.returncode == 0


# --- required-arg / bad-input handling (argparse exits 2) ------------------

def test_missing_schema_dir_errors():
    r = _run()  # no --schema-dir
    assert r.returncode == 2
    assert "schema-dir" in (r.stderr + r.stdout)


def test_bad_model_choice_errors():
    r = _run("--schema-dir", "invoice", "--doc-model", "not-a-real-model")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr.lower()


# --- console-script entry point is installed -------------------------------

def test_console_script_installed():
    r = subprocess.run(["seed-data", "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0
    assert "--schema-dir" in r.stdout


# --- clone-schema-library actually works (no Bedrock) ----------------------

def test_clone_schema_library_copies(tmp_path):
    dest = tmp_path / "schemas"
    r = _run("clone-schema-library", str(dest))
    assert r.returncode == 0, r.stderr
    assert dest.is_dir()
    # should contain the bundled schema dirs (each with a schema.json)
    subdirs = [p for p in dest.iterdir() if p.is_dir()]
    assert len(subdirs) > 5
    assert (subdirs[0] / "schema.json").exists()


def test_clone_schema_library_refuses_existing(tmp_path):
    dest = tmp_path / "schemas"
    assert _run("clone-schema-library", str(dest)).returncode == 0
    # second time: destination exists -> clean failure, not a clobber
    r = _run("clone-schema-library", str(dest))
    assert r.returncode == 1
    assert "exists" in (r.stderr + r.stdout).lower()

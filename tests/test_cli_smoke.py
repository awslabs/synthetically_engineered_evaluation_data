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

def _seed_data_script() -> str | None:
    """Locate the installed `seed-data` console script.

    Prefer PATH, but fall back to the bin/Scripts dir next to the running
    interpreter — so the test passes when the package is installed in a venv
    that isn't `activate`d on PATH (e.g. pytest run via an absolute venv python),
    and only skips when the script genuinely isn't installed.
    """
    import os
    import shutil
    found = shutil.which("seed-data")
    if found:
        return found
    bindir = os.path.dirname(sys.executable)
    for name in ("seed-data", "seed-data.exe"):
        cand = os.path.join(bindir, name)
        if os.path.isfile(cand):
            return cand
    return None


def test_console_script_installed():
    script = _seed_data_script()
    if script is None:
        pytest.skip("seed-data console script not installed in this environment")
    r = subprocess.run([script, "--help"], capture_output=True, text=True, timeout=60)
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


# --- infer-schema subcommand parses (no Bedrock) ---------------------------

def test_infer_schema_help_exits_clean():
    r = _run("infer-schema", "--help")
    assert r.returncode == 0
    out = r.stdout
    # the flags that define the feature must all be discoverable
    for flag in ("--name", "--output", "--packet", "--boundaries",
                 "--allow-questions", "--then-generate", "--infer-model"):
        assert flag in out, f"{flag} missing from infer-schema --help"


def test_infer_schema_requires_name_and_output():
    # inputs given but no --name / --output -> argparse exits 2
    r = _run("infer-schema", "somefile.pdf")
    assert r.returncode == 2
    assert "name" in (r.stderr + r.stdout).lower()


def test_infer_schema_bad_model_choice_errors():
    r = _run("infer-schema", "x.pdf", "--name", "x", "--output", "/tmp/x",
             "--infer-model", "not-a-real-model")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr.lower()


def test_infer_schema_packet_with_then_generate_rejected():
    # --packet and --then-generate are mutually exclusive -> clean argparse error
    r = _run("infer-schema", "x.pdf", "--name", "x", "--output", "/tmp/x",
             "--packet", "--then-generate")
    assert r.returncode == 2
    assert "then-generate" in (r.stderr + r.stdout).lower()

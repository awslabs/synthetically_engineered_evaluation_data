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


# --- ingest subcommand parses (no Bedrock) ---------------------------------

def test_ingest_help_exits_clean():
    r = _run("ingest", "--help")
    assert r.returncode == 0
    out = r.stdout
    for flag in ("--name", "--output", "--quiet"):
        assert flag in out, f"{flag} missing from ingest --help"


def test_ingest_requires_inputs():
    # no positional inputs -> argparse exits 2
    r = _run("ingest")
    assert r.returncode == 2


# --- generate-structured subcommand parses (no Bedrock) --------------------

def test_generate_structured_help_exits_clean():
    r = _run("generate-structured", "--help")
    assert r.returncode == 0
    out = r.stdout
    for flag in ("--rows", "--format", "--output", "--quiet"):
        assert flag in out, f"{flag} missing from generate-structured --help"


def test_generate_structured_requires_schema():
    # no positional schema -> argparse exits 2
    r = _run("generate-structured")
    assert r.returncode == 2


def test_generate_structured_bad_format_errors():
    r = _run("generate-structured", "somefile.json", "--format", "not-a-format")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr.lower()


# --- generate-documents subcommand parses (no Bedrock) ---------------------

def test_generate_documents_help_exits_clean():
    r = _run("generate-documents", "--help")
    assert r.returncode == 0
    out = r.stdout
    for flag in ("--entity", "--count", "--scenario", "--output", "--quiet"):
        assert flag in out, f"{flag} missing from generate-documents --help"


def test_generate_documents_requires_schema():
    r = _run("generate-documents")
    assert r.returncode == 2


def test_generate_documents_bad_model_choice_errors():
    r = _run("generate-documents", "invoice", "--doc-model", "not-a-real-model")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr.lower()


# --- run subcommand parses (no Bedrock) ------------------------------------

def test_run_help_exits_clean():
    r = _run("run", "--help")
    assert r.returncode == 0
    out = r.stdout
    # `run`'s defining split: --output selects the MODALITY, --output-dir the path.
    for flag in ("--output", "--output-dir", "--rows", "--count", "--name"):
        assert flag in out, f"{flag} missing from run --help"


def test_run_requires_inputs():
    r = _run("run")
    assert r.returncode == 2


def test_run_invalid_output_errors():
    # --output must be structured|documents -> argparse rejects other choices
    r = _run("run", "some text", "--output", "invalid")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr.lower()


# --- all subcommands are discoverable from the top-level help --------------

def test_all_subcommands_listed():
    r = _run("--help")
    assert r.returncode == 0
    out = r.stdout
    for sub in ("ingest", "generate-structured", "generate-documents", "run",
                "packet", "infer-schema", "clone-schema-library"):
        assert sub in out, f"{sub} not listed in top-level --help"


# --- optional-dependency isolation -----------------------------------------

def test_base_import_isolation_without_structured_deps():
    """The base (documents-only) surface must import with the `[structured]`
    extra absent — no pandas/numpy/scipy/openpyxl.

    Runs in a subprocess with those modules blocked at import. (Importing in *this*
    interpreter, which already has them installed, could never detect the failure —
    the flaw in the plan's original isolation test.)
    """
    program = (
        "import builtins\n"
        "real = builtins.__import__\n"
        "blocked = {'pandas', 'numpy', 'scipy', 'openpyxl'}\n"
        "def guard(name, *a, **k):\n"
        "    if name.split('.')[0] in blocked:\n"
        "        raise ImportError('blocked: ' + name)\n"
        "    return real(name, *a, **k)\n"
        "builtins.__import__ = guard\n"
        # the documented base public surface
        "from seed_data import Generator, Schema, ModelConfig, InferredSchema\n"
        "Generator()\n"
        # document-side evaluation is base-safe; tabular scorers are opt-in
        "from seed_data.evaluation import evaluate_document_labels\n"
        "print('BASE OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", program],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    assert "BASE OK" in r.stdout


# --- missing [structured] extra is reported, not traced ----------------------

# Simulates a base install by making `import pandas` fail inside the subprocess,
# so these assert the same behavior whether or not the extra is installed locally.
# sitecustomize (not usercustomize) is used deliberately: it is imported at
# interpreter startup even when user-site is disabled, which is the case in a venv.
_NO_PANDAS_SITECUSTOMIZE = """
import sys, importlib.abc


class _Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] == "pandas":
            raise ImportError("No module named 'pandas'")
        return None


sys.meta_path.insert(0, _Blocker())
"""


@pytest.fixture
def no_pandas_env(tmp_path):
    """Env for a subprocess in which pandas is unimportable.

    Asserts the block actually takes effect before handing the env over. Without
    that check a silently-ineffective blocker turns these into live Bedrock calls —
    slow, credential-dependent, and green for the wrong reason.
    """
    import os

    sitedir = tmp_path / "nopandas"
    sitedir.mkdir()
    (sitedir / "sitecustomize.py").write_text(_NO_PANDAS_SITECUSTOMIZE)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(sitedir), "src", env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    probe = subprocess.run(
        [sys.executable, "-c", "import pandas"],
        capture_output=True, text=True, timeout=60, env=env,
    )
    assert probe.returncode != 0, (
        "pandas import was not blocked; this test would make live model calls"
    )
    return env


def _run_env(env, *args):
    return subprocess.run(
        [sys.executable, "-m", "seed_data", *args],
        capture_output=True, text=True, timeout=120, env=env,
    )


def test_generate_structured_without_extra_prints_install_hint(no_pandas_env):
    """A base user must get the install command, not an ImportError traceback."""
    r = _run_env(no_pandas_env, "generate-structured", "invoice", "--rows", "5")

    assert r.returncode == 1
    assert "seed-data[structured]" in r.stderr
    assert "pip install" in r.stderr
    assert "Traceback" not in r.stderr, "the guidance must not be buried in a traceback"


def test_run_structured_without_extra_fails_before_ingest(no_pandas_env):
    """`run --output structured` must refuse up front, not after a paid ingest.

    ingest is a multi-agent LLM run; reaching it would mean spending tokens (and
    needing credentials) before reporting something knowable at startup.
    """
    r = _run_env(no_pandas_env, "run", "some free text", "--output", "structured")

    assert r.returncode == 1
    assert "seed-data[structured]" in r.stderr
    assert "Traceback" not in r.stderr
    # Generation never started: no export summary, no quality line.
    assert "Quality:" not in r.stdout
    assert "Files:" not in r.stdout


def test_generate_documents_without_extra_still_parses(no_pandas_env):
    """The document modality must stay usable without the extra.

    This is the published offering; --help must work with no pandas anywhere.
    """
    r = _run_env(no_pandas_env, "generate-documents", "--help")

    assert r.returncode == 0
    assert "--entity" in r.stdout

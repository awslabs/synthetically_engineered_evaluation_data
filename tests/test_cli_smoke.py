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


# --- plan subcommand parses (no Bedrock) -----------------------------------

def test_plan_help_exits_clean():
    r = _run("plan", "--help")
    assert r.returncode == 0
    out = r.stdout
    for flag in ("--name", "--output", "--quiet", "--data-model"):
        assert flag in out, f"{flag} missing from plan --help"


def test_plan_requires_inputs():
    # no positional inputs -> argparse exits 2
    r = _run("plan")
    assert r.returncode == 2


def test_plan_rejects_unknown_data_model():
    """`plan` had no model flag at all, so extraction was stuck on the default."""
    r = _run("plan", "some text", "--data-model", "not-a-model")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr.lower()


# --- generate-structured subcommand parses (no Bedrock) --------------------

def test_generate_structured_help_exits_clean():
    r = _run("generate-structured", "--help")
    assert r.returncode == 0
    out = r.stdout
    for flag in ("--rows", "--format", "--output", "--quiet", "--data-model"):
        assert flag in out, f"{flag} missing from generate-structured --help"


def test_generate_structured_requires_schema():
    # no positional schema -> argparse exits 2
    r = _run("generate-structured")
    assert r.returncode == 2


def test_generate_structured_rejects_unknown_data_model():
    """`generate-structured` had no model flag, so the whole pipeline was pinned."""
    r = _run("generate-structured", "somefile.json", "--data-model", "not-a-model")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr.lower()


def test_generate_structured_bad_format_errors():
    r = _run("generate-structured", "somefile.json", "--format", "not-a-format")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr.lower()


def test_generate_structured_missing_schema_file_has_no_traceback(tmp_path):
    """Regression: `_generate_structured` called into the API bare, so a typo'd
    path printed a raw FileNotFoundError traceback while every other subcommand
    printed the message. Runs from tmp_path so the argument cannot resolve to a
    real file in the repo."""
    r = _run("generate-structured", "definitely-not-here.json", cwd=str(tmp_path))
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    assert r.stderr.strip()


def test_generate_structured_unparseable_schema_has_no_traceback(tmp_path):
    bad = tmp_path / "schema.json"
    bad.write_text("{not valid json")
    r = _run("generate-structured", str(bad))
    assert r.returncode == 1
    assert "Traceback" not in r.stderr


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


# --- plan-and-generate subcommand parses (no Bedrock) ----------------------

def test_plan_and_generate_help_exits_clean():
    r = _run("plan-and-generate", "--help")
    assert r.returncode == 0
    out = r.stdout
    # The defining split: --output selects the MODALITY, --output-dir the path.
    for flag in ("--output", "--output-dir", "--rows", "--count", "--name"):
        assert flag in out, f"{flag} missing from plan-and-generate --help"


def test_plan_and_generate_requires_inputs():
    r = _run("plan-and-generate")
    assert r.returncode == 2


def test_plan_and_generate_invalid_output_errors():
    # --output must be structured|documents -> argparse rejects other choices
    r = _run("plan-and-generate", "some text", "--output", "invalid")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr.lower()


# --- all subcommands are discoverable from the top-level help --------------

def test_all_subcommands_listed():
    r = _run("--help")
    assert r.returncode == 0
    out = r.stdout
    for sub in ("plan", "generate-structured", "generate-documents",
                "plan-and-generate", "packet", "infer-schema",
                "clone-schema-library"):
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


def test_plan_and_generate_structured_without_extra_fails_before_planning(no_pandas_env):
    """`plan-and-generate --output structured` must refuse up front, not after a
    paid planning run.

    Planning is a multi-agent LLM run; reaching it would mean spending tokens (and
    needing credentials) before reporting something knowable at startup.
    """
    r = _run_env(no_pandas_env, "plan-and-generate", "some free text",
                 "--output", "structured")

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


# --- deprecated subcommand aliases -----------------------------------------

@pytest.mark.parametrize("old,new", [("ingest", "plan"), ("run", "plan-and-generate")])
def test_deprecated_subcommand_still_dispatches(old, new):
    """The retired spelling reaches the same handler, and says so on stderr.

    `--help` is the probe because it proves dispatch without a Bedrock call: the
    renamed handler is the only thing that could have printed that usage text.
    """
    r = _run(old, "--help")
    assert r.returncode == 0
    assert f"seed-data {new}" in r.stdout, "alias did not reach the renamed handler"
    assert "deprecated" in r.stderr.lower()
    assert f"seed-data {new}" in r.stderr, "the warning must name the replacement"


@pytest.mark.parametrize("old", ["ingest", "run"])
def test_deprecated_subcommands_are_not_advertised(old):
    """A deprecated alias must not appear in top-level --help.

    Listing it would recommend the name being retired. This is what keeps
    DEPRECATED_SUBCOMMANDS a separate table from SUBCOMMANDS rather than extra
    keys in it — `test_all_subcommands_listed` iterates the latter.
    """
    out = _run("--help").stdout
    assert f"  {old} " not in out


# --- model flags reach the Generator, not just argparse ----------------------
#
# In-process rather than via `_run`: the subprocess tests above prove the flag
# parses, which is not the same as it being wired. `plan` and `generate-structured`
# previously built a bare `Generator()`, so there was nothing to wire — every other
# subcommand took a model and these two silently used ModelConfig's default.

def _fake_generator(captured):
    """A Generator stand-in that records the ModelConfig it was constructed with."""
    class _Schema:
        entities = []
        def model_dump_json(self, **kw): return "{}"

    class _StructuredResult:
        success = True
        row_counts = {}
        output_paths = []
        evaluation = None

    class _FakeGenerator:
        def __init__(self, *, models=None, **kw):
            captured["models"] = models

        def plan(self, *inputs, **kw):
            return _Schema()

        def generate_structured(self, schema, **kw):
            return _StructuredResult()

    return _FakeGenerator


def test_plan_passes_data_model_to_generator(monkeypatch, tmp_path):
    from seed_data import __main__ as cli

    captured = {}
    monkeypatch.setattr("seed_data.Generator", _fake_generator(captured))
    cli._plan(["some text", "--data-model", "haiku",
               "--output", str(tmp_path / "schema.json")])

    assert captured["models"].data == "haiku"


def test_generate_structured_passes_data_model_to_generator(monkeypatch, tmp_path):
    from seed_data import __main__ as cli

    captured = {}
    monkeypatch.setattr("seed_data.Generator", _fake_generator(captured))
    cli._generate_structured(["somefile.json", "--data-model", "opus",
                              "--output", str(tmp_path)])

    assert captured["models"].data == "opus"


@pytest.mark.parametrize("subcommand,argv", [
    ("plan", ["some text"]),
    ("generate-structured", ["somefile.json"]),
])
def test_new_model_flags_default_to_the_shared_data_model(monkeypatch, tmp_path, subcommand, argv):
    """`plan` and `generate-structured` must default to the same model as everyone else.

    Both built a bare `Generator()` before, so they silently ran ModelConfig's
    `sonnet` while every other subcommand's `--data-model` defaulted to `gpt-oss` —
    which made `plan` + `generate-structured` use a different model than the one-shot
    `plan-and-generate` the docs present as their equivalent.
    """
    from seed_data import __main__ as cli

    captured = {}
    monkeypatch.setattr("seed_data.Generator", _fake_generator(captured))
    handler = cli._plan if subcommand == "plan" else cli._generate_structured
    handler([*argv, "--output", str(tmp_path / "out.json")])

    assert captured["models"].data == cli.DEFAULT_DATA_MODEL


def test_no_model_flag_hard_codes_its_default():
    """Every model flag's default must be a named constant, not a string literal.

    The invariant the constants exist to hold: five subcommands each hard-coded
    "gpt-oss" for --data-model while `plan` and `generate-structured` had no flag and
    ran ModelConfig's `sonnet`, so the same work used different models depending on
    which subcommand you reached it through.

    Checked by parsing the source rather than `--help` output: argparse does not print
    defaults here and every constant's value is already in the `choices` list, so a
    text assertion passes even when a subcommand reintroduces a literal.
    """
    import ast
    import pathlib

    from seed_data import __main__ as cli

    tree = ast.parse(pathlib.Path(cli.__file__).read_text())
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument" and node.args):
            continue
        flag = node.args[0]
        if not (isinstance(flag, ast.Constant) and isinstance(flag.value, str)
                and flag.value.endswith("-model")):
            continue
        default = next((k.value for k in node.keywords if k.arg == "default"), None)
        # A Name/Attribute is a constant reference; a str Constant is a literal.
        if isinstance(default, ast.Constant) and isinstance(default.value, str):
            offenders.append(f"{flag.value}={default.value!r}")

    assert not offenders, f"model flags with hard-coded defaults: {offenders}"


@pytest.mark.parametrize("subcommand", [
    "plan", "generate-structured", "generate-documents",
    "plan-and-generate", "infer-schema", "packet",
])
def test_every_subcommand_offers_data_model(subcommand):
    """--data-model must be reachable from every subcommand that generates data."""
    out = _run(subcommand, "--help").stdout
    assert "--data-model" in out, f"{subcommand} has no --data-model"


def test_infer_model_default_stays_vision_capable():
    """--infer-model must not follow DEFAULT_DATA_MODEL onto a text-only model.

    `gpt-oss` is `openai.gpt-oss-120b`, which cannot take image blocks, and the
    vision path is what reads PDFs. This is why the infer role has its own default
    sourced from `infer.DEFAULT_INFER_MODEL` rather than the CLI constants.
    """
    from seed_data import __main__ as cli
    from seed_data.infer import DEFAULT_INFER_MODEL

    assert DEFAULT_INFER_MODEL != cli.DEFAULT_DATA_MODEL
    assert DEFAULT_INFER_MODEL == "sonnet"

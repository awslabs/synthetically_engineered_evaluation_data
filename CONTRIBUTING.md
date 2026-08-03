# Contributing Guidelines

Thank you for your interest in contributing to Synthetically Engineered Evaluation Data (SEED)! Whether it's a bug report, new feature, correction, or additional documentation, we greatly value feedback and contributions from our community.

Please read through this document before submitting any issues or pull requests to ensure we have all the necessary
information to effectively respond to your bug report or contribution.


## Quick Start for Contributors

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or pip
- Git

No system libraries are required. The default renderer is `xhtml2pdf`, which is
pure Python and installs with the package.

Only if you opt into the WeasyPrint renderer (`--renderer weasyprint`) do you
need its system libraries:

```bash
# macOS
brew install pango gdk-pixbuf libffi

# Ubuntu/Debian
apt-get install libpango-1.0-0 libgdk-pixbuf2.0-0
```

### Setup

```bash
# Clone and setup
git clone https://github.com/awslabs/synthetically_engineered_evaluation_data.git
cd synthetically_engineered_evaluation_data

# Option 1: uv (recommended) — installs the full dev environment,
# including the structured-data stack
uv sync

# Option 2: pip + venv — the dev extra implies [all], so this also
# installs the structured-data stack
pip install -e ".[dev]"
```

Both options give you the full feature set, which is what you want as a contributor: the structured and evaluation test suites call `pytest.importorskip("pandas")`, so without the `[structured]` extras installed they skip themselves rather than fail, and you would get a green run that never exercised your change.

> **Using pip + venv?** If you installed with `pip install -e ".[dev]"`, run the tools directly (e.g., `pytest`). If you use uv, prefix commands with `uv run` (e.g., `uv run pytest`).

### Development Workflow

1. Create a branch from `develop`: `git checkout -b feature/your-feature develop`
2. Make your changes
3. Run the unit tests: `pytest`
4. Run linting: `ruff check .`
5. Commit with conventional format: `feat: add new feature`
6. Submit PR to `develop` branch

## Quick Reference

### Common Commands

| Task | Command |
|------|---------|
| Run unit tests | `pytest` |
| Run unit tests (make target) | `make test` |
| Run only the ingest/structured/evaluation tests | `make test-structured` |
| Run the CLI smoke test (no Bedrock) | `pytest tests/test_cli_smoke.py` |
| Run the integration tests | `uv run pytest tests/integration` |
| Lint check | `ruff check .` |
| Lint check (make target) | `make lint` |
| Lint fix | `ruff check --fix .` |
| Serve the docs site locally | `make docs` |

The `make` targets run through `uv run`, so use them if you installed with `uv sync`; run `make install` first if you have not synced yet.

Integration tests under `tests/integration/` hit live Bedrock and are excluded from the default run (`addopts = --ignore=tests/integration` in `pyproject.toml`), so you have to invoke them explicitly. They need live AWS credentials:

```bash
AWS_PROFILE=your-profile uv run pytest tests/integration -v
```

Without usable credentials they skip cleanly with a clear reason rather than failing, so a bare `uv run pytest tests/integration` degrades to "skipped" instead of a wall of credential errors.

### Commit Message Format

```
type: brief description
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

### Documentation Contributions

Documentation is built with MkDocs and lives in the `docs/` directory.

```bash
# Setup and serve docs locally
cd docs
make install  # Install dependencies
make docs     # Start dev server at http://127.0.0.1:8000
```

When contributing documentation:
- Edit Markdown files in `docs/docs/`
- Follow existing structure and style
- Test locally with `make docs` before submitting a PR
- Documentation PRs should also target the `develop` branch

## Extending SEED

The package layout, for orientation:

```text
src/seed_data/
  api.py                 Generator facade — the public surface
  __main__.py            argparse CLI (SUBCOMMANDS dict + default document parser)
  schema/                InferredSchema/EntitySchema/FieldDefinition + converters
  ingest/                detect.py, extract.py, pipeline.py, tools.py
  structured/            pipeline.py, generation.py, sampling.py, exporter.py,
                         distributions/, postprocessing/
  evaluation/            metrics.py, critique.py, coverage/diversity/fidelity/
                         structural.py
  stages/                document pipeline stages
  prompts/               Jinja2 templates, rendered via prompts.render(name, **kw)
  common/config.py       shared model/config plumbing
```

### Adding a CLI subcommand

The whole CLI lives in `src/seed_data/__main__.py`. A module-level `SUBCOMMANDS` dict maps a subcommand name to its handler function:

```python
SUBCOMMANDS = {
    "clone-schema-library": _clone_schema_library,
    "packet": _packet,
    "infer-schema": _infer_schema,
    "ingest": _ingest,
    "generate-structured": _generate_structured,
    "generate-documents": _generate_documents,
    "run": _run,
}
```

`main()` looks up `sys.argv[1]` in that dict and calls the handler with `sys.argv[2:]`. If `sys.argv[1]` is not a key, it falls through to the default document parser (the pre-existing `--schema-dir` flow), which is why adding a subcommand cannot disturb the default mode.

The conventions to follow when you add one:

- Name the handler `_<verb>` (underscored), matching the hyphenated subcommand name, and take a single `argv` argument.
- Build your own `argparse.ArgumentParser` inside the handler over that `argv`. Set `prog="seed-data <verb>"` so `--help` reads correctly. There is no shared subparser tree; each handler owns its own parser.
- If the subcommand reaches Bedrock, call `load_dotenv()` at the top of the handler, and import `Generator` (and `MODELS`/`ModelConfig`) inside the handler rather than at module scope, so `seed-data --help` stays fast and the heavy imports stay lazy.
- Accept `--quiet` as `action="store_true"` and pass `verbose=not args.quiet` down to the `Generator` verb.
- For model flags, derive the choices from the shared registry: `model_choices = list(MODELS.keys())` where `MODELS` comes from `seed_data`. Never hard-code a model list.
- Do the actual work by calling a `Generator` verb (or, for non-generation utilities, a helper in `seed_data.utils`). The handler should be argument parsing, printing, and exit codes only.
- Add the subcommand to the epilog listing in `main()`'s parser, so it shows up in the top-level `--help`.

Every subcommand needs a CLI smoke test in `tests/test_cli_smoke.py`. That suite shells out to the CLI without touching Bedrock and asserts, per subcommand, that `--help` exits clean and lists the expected flags, that required positionals are enforced, and that bad `--format`/model choices are rejected. `test_all_subcommands_listed` additionally asserts your subcommand appears in the top-level `--help`, so it fails until you update the epilog.

### Adding a Generator verb

`Generator` in `src/seed_data/api.py` is the public Python surface. Everything under `ingest/`, `structured/` and `evaluation/` is internal; users are expected to reach it through a verb.

A verb is a thin facade. The pattern each existing one follows:

1. Resolve the caller's `schema` argument into the form the engine wants, using the private helpers rather than reimplementing path handling. `_resolve_inferred` turns an `InferredSchema` object, a JSON path, or a bundled schema name into an `InferredSchema`. On the document side, `_resolve_for_documents` converts an in-code `Schema` or `InferredSchema` into the pipeline's resolved triple and returns `None` for a plain string, signalling the caller to fall back to `_resolve_schema` (bundled name or directory -> directory path) — which is what keeps every already-published call shape behaving as before.
2. Import the engine inside the method body, not at module scope (`from seed_data.structured import run_structured`), so an optional-dependency engine is only imported when actually used.
3. Delegate, passing the instance-level settings the caller configured on `Generator` (`self.models`, `self.threshold`, `self.output_dir`, `self.session`) plus the verb's own keyword arguments.
4. Return a typed pydantic result — `GeneratedDoc`, `BatchResult`, `StructuredResult` — never a bare dict. Failures that a caller can reasonably inspect belong in the result (`success=False` plus `error`), not in an exception.

Keyword-only arguments (everything after `*`) with defaults are the norm, and existing defaults are frozen: the published signatures must keep working unchanged.

If your verb introduces a new public name (a new result type, for example), export it from `src/seed_data/__init__.py`. That module keeps `import seed_data` light: `MODELS` is a plain module-level dict, but everything else in `__all__` is resolved by a module-level `__getattr__` that imports the defining module on first attribute access and returns the object — `Generator`/`BatchResult`/`StructuredResult` from `seed_data.api`, `Schema` from `seed_data.schema`, `InferredSchema` from `seed_data.schema.models`, `ModelConfig` from `seed_data.stages.base`, `GeneratedDoc` from `seed_data.stages.pipeline`, and `AttributeError` for anything else. So a new export means two edits: add the name to `__all__`, and add its lazy branch to `__getattr__`. Importing it at the top of `__init__.py` instead would pull `strands`/`boto3` into every `import seed_data`.

### Adding a prompt

Prompts are Jinja2 templates in `src/seed_data/prompts/`, one `.j2` file per prompt. Render them by name, without the extension:

```python
from seed_data import prompts

SCHEMA_EXTRACTION_PROMPT = prompts.render("schema_extraction")
FIELD_FILL_PROMPT = prompts.render("string_field_fill", entity=entity_name)
```

`prompts.render(name, **kwargs)` loads `<name>.j2` from the package directory and renders it with the keyword arguments. Keep prompt text in the template rather than in Python string literals, so it stays reviewable as prose.

Templates are shipped by the `[tool.setuptools.package-data]` globs in `pyproject.toml`:

```text
seed_data = ["schemas/**/*.json", "schemas/**/*.md", "prompts/*.j2", "prompts/*.md", "packets/**/*.json"]
```

A new `.j2` directly under `prompts/` is covered by the existing glob and needs no packaging change. A prompt asset with a different extension, or one in a subdirectory, does — and the failure mode is a template that resolves in your checkout but raises at runtime from an installed wheel. The CI `build-smoke` job installs the built wheel in a clean venv, so verify packaged assets there rather than only from the source tree.

### Optional dependencies

`pandas`, `numpy`, `scipy` and `openpyxl` belong to the `[structured]` extra, not the base dependency set. `pip install seed-data` gets the document pipeline and nothing heavier; structured generation is opt-in via `pip install "seed-data[structured]"`.

The rule that follows: never import those packages at module level in a code path a base install can reach. Concretely, that covers `seed_data/__init__.py`, `api.py`, `schema/`, `stages/`, `evaluation/__init__.py`, `evaluation/metrics.py`, `evaluation/critique.py`, and anything imported transitively from them. Two ways to stay inside the rule:

```python
# Deferred import — inside the function that actually needs it.
def _load_frame(path: str):
    import pandas as pd
    return pd.read_csv(path)

# TYPE_CHECKING — annotations only, never evaluated at runtime.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

def _summarize(df: "pd.DataFrame") -> str:
    ...
```

Modules that exist only to serve the structured surface (`structured/exporter.py`, `evaluation/coverage.py`, and friends) do import pandas at module level, and that is fine: they are only reachable through a lazy path. `seed_data.evaluation` keeps its tabular scorers behind a module-level `__getattr__`, and `Generator.generate_structured` imports `run_structured` inside the method — so on a base install the missing extra surfaces as an `ImportError` when you call the structured surface, instead of breaking `import seed_data` for everyone. Keep it that way: if you add a new entry point into the structured stack, route it through a lazy import too.

Enforcement is the `test-base` job in `.github/workflows/test.yml`. It builds the wheel, installs it with no extras into a clean venv, asserts `import pandas` fails, and runs the suite against that environment — so a stray module-level import fails CI rather than shipping. Reproduce it locally:

```bash
uv build --wheel
python3 -m venv /tmp/base
/tmp/base/bin/pip install --upgrade pip
/tmp/base/bin/pip install dist/*.whl pytest
/tmp/base/bin/python -c "import pandas" && echo "not a lean install"
/tmp/base/bin/python -m pytest tests/ --ignore=tests/integration -p no:cacheprovider
```

For a faster check without a build, `tests/test_cli_smoke.py::test_base_import_isolation_without_structured_deps` imports the documented base surface in a subprocess with `pandas`/`numpy`/`scipy`/`openpyxl` blocked at import, and runs in the normal suite.

---

## Reporting Bugs/Feature Requests

We welcome you to use the GitHub issue tracker to report bugs or suggest features.

When filing an issue, please check existing open, or recently closed, issues to make sure somebody else hasn't already
reported the issue. Please try to include as much information as you can. Details like these are incredibly useful:

* A reproducible test case or series of steps
* The version of our code being used
* Any modifications you've made relevant to the bug
* Anything unusual about your environment or deployment


## Contributing via Pull Requests

Contributions via pull requests are much appreciated. Before sending us a pull request, please ensure that:

1. You are working against the latest source on the **develop** branch.
2. You check existing open, and recently merged, pull requests to make sure someone else hasn't addressed the problem already.
3. You open an issue to discuss any significant work - we would hate for your time to be wasted.

### Pull Request Process

To send us a pull request, please:

1. Fork the repository.
2. Create a feature branch from the **develop** branch (not main).
3. Modify the source; please focus on the specific change you are contributing. If you also reformat all the code, it will be hard for us to focus on your change.
4. Ensure local tests pass.
5. Commit to your fork using clear commit messages.
6. **Submit your pull request to the develop branch** (not main).
7. Pay attention to any automated CI failures reported in the pull request, and stay involved in the conversation.

### Pull Request Template

When creating a pull request, please use the following template to ensure all necessary information is included:

```
*Issue #, if available:*

*Description of changes:*


By submitting this pull request, I confirm that you can use, modify, copy, and redistribute this contribution, under the terms of your choice.
```

### Branch Guidelines

- **All pull requests must target the `develop` branch**
- The `main` branch is reserved for stable releases; releases are cut via a PR from `develop` to `main`
- Use descriptive branch names (e.g., `feature/add-new-schema`, `bugfix/fix-memory-leak`)
- Keep your branch up to date with the latest `develop` branch before submitting

### Commit Message Guidelines

- Use clear and meaningful commit messages
- Follow the format: `type: brief description`
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- Example: `feat: add new document schema`

Refer to [this guide](https://www.conventionalcommits.org/en/v1.0.0/#examples) for clear commit guidelines <br>

GitHub provides additional documentation on [forking a repository](https://help.github.com/articles/fork-a-repo/) and
[creating a pull request](https://help.github.com/articles/creating-a-pull-request/).


## Finding contributions to work on
Looking at the existing issues is a great way to find something to contribute on. As our projects, by default, use the default GitHub issue labels (enhancement/bug/duplicate/help wanted/invalid/question/wontfix), looking at any 'help wanted' issues is a great place to start.


## Code of Conduct
This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct).
For more information see the [Code of Conduct FAQ](https://aws.github.io/code-of-conduct-faq) or contact
opensource-codeofconduct@amazon.com with any additional questions or comments.


## Security issue notifications
If you discover a potential security issue in this project we ask that you notify AWS/Amazon Security via our [vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/), or by following the process described in [SECURITY.md](SECURITY.md). Please do **not** create a public GitHub issue.


## Licensing

See the [LICENSE](LICENSE) file for our project's licensing. Contributions are made under the Apache-2.0 license. We will ask you to confirm the licensing of your contribution.

# Milestone 5: Polish, CI, and Open-Source Release

**Goal:** Unified repo is ready for public release with both modalities. CI runs, docs are updated, no internal references remain, fresh-clone experience is verified.

**Duration:** ~1 week

**Depends on:** Milestones 1–4

---

## What Changes

| File / Dir | Action |
|---|---|
| ~~`.github/workflows/ci.yml`~~ → `.github/workflows/test.yml` | **MODIFIED**, not new — the repo already had `test.yml` (a single `pytest` job plus `build-smoke`). Rather than stand up a second, competing workflow, that file was **extended to four jobs**: `lint`, `pytest`, `test-base`, `build-smoke`. See §5.1. |
| `README.md` | **MODIFIED** — add structured data section, unified architecture diagram |
| `docs/docs/Getting-Started/quick-start.md` | **MODIFIED** — add structured quickstart |
| `docs/docs/CLI-Usage/README.md` | **MODIFIED** — document new subcommands |
| `docs/docs/Python-API-Usage/README.md` | **MODIFIED** — document `ingest`, `generate_structured`, `run` |
| `CONTRIBUTING.md` | **MODIFIED** — how to add input modes and output modalities |
| `pyproject.toml` | **MODIFIED** — add `[all]` optional dep group |
| `Makefile` | **MODIFIED** — add targets for structured tests |

Rows the original table omitted, added here for the record (all shipped):

| File / Dir | Action |
|---|---|
| `docs/docs/Guides/ingest.md` | **NEW** — the ingest guide §5.5 called for (input types, auto-detection, examples) |
| `docs/docs/Guides/structured-data.md` | **NEW** — the structured-generation guide §5.5 called for |
| `docs/docs/Guides/.nav.yml` | **MODIFIED** — **required**, not cosmetic: the site uses `mkdocs-awesome-nav`, whose `nav:` list is exhaustive. A guide that is not listed is silently dropped from the site, so both new guides had to be added to this file to be reachable at all. `docs/docs/Guides/README.md` (the guides index) gained matching entries. |
| `docs/docs/index.md` | **MODIFIED** — docs landing page reframed from "document generation pipeline" to two modalities; adds the `[structured]` extra and a structured `run` example |
| `docs/docs/Getting-Started/installation.md` | **MODIFIED** — base vs `[structured]` vs `[all]` install matrix, why structured is opt-in, the `--format parquet`/pyarrow caveat, and a structured-extra verification command |
| `docs/docs/API-Reference/generator.md` | **MODIFIED** — the new verbs (`ingest`, `generate_structured`, `run`) added to the verb tables and given reference sections; top-level import example extended with `InferredSchema` / `StructuredResult` |
| `pyproject.toml` | **MODIFIED** (beyond the `[all]` group) — new `[tool.ruff]` / `[tool.ruff.lint]` config so the CI lint gate is pinned in-repo (`line-length = 88`, `target-version = "py312"`, `select = ["F", "E4", "E7", "E9"]`), `ruff>=0.15,<0.16` pin, structured stack added to the uv `test` group, and `prompts/*.md` added to `package-data`. See §5.2. |

---

## Implementation Steps

### 5.1 GitHub Actions CI

~~This step originally specified a new `.github/workflows/ci.yml` containing three
jobs — `lint` (`ruff check` + `ruff format --check`), `test-documents`
(`uv sync` + the non-integration suite) and `test-structured`
(`uv sync --extra structured` + the ingest/structured/evaluation suites).~~

**Actual:** no `ci.yml` was created. The repo already had
`.github/workflows/test.yml` (triggering on push to `main`/`dev` and on every PR,
with `permissions: contents: read`), carrying a `pytest` job and a `build-smoke`
job. A second workflow would have duplicated the trigger and the environment setup
for no gain, so `test.yml` was **extended in place** to four jobs. What is there
now, read off the file:

| Job | What it does | Notes |
|---|---|---|
| `lint` | `uv sync --only-group lint`, then `uv run ruff check .` | `--only-group`, **not** `--group`: `[tool.uv] default-groups = ["dev"]` means `--group lint` would additionally resolve the whole dev set (~155 packages) just to run ruff. `--only-group` installs ruff alone. |
| `pytest` | `uv python install 3.12`, `uv sync`, `uv run pytest` | The full environment. `default-groups = ["dev"]` pulls in the structured stack, so the structured + evaluation suites actually run here rather than skipping. `addopts = "--ignore=tests/integration"` keeps the credential-dependent integration tests out. |
| `test-base` | Builds the wheel (`uv build --wheel`), installs it **with no extras** plus `pytest` into a clean `python3 -m venv /tmp/base`, hard-fails if `import pandas` succeeds, then runs `pytest tests/ --ignore=tests/integration -p no:cacheprovider` against that venv | This is the real enforcement of the optional-dependency boundary — a stray module-level `import pandas` in a base-reachable path fails CI instead of shipping. Needs `fetch-depth: 0` so setuptools-scm can derive a version from tags. |
| `build-smoke` | `uv build` (sdist + wheel), installs the wheel in a clean venv, then `import seed_data`, reads `importlib.metadata.version("seed-data")`, and runs `seed-data --help` | Pre-existing job, unchanged. Catches packaging breakage (missing package data, bad entry point, broken version) that the unit tests cannot see. Also `fetch-depth: 0`. |

Every `uses:` is SHA-pinned with a trailing `# v4` / `# v5` comment
(`actions/checkout@34e1148… # v4`, `astral-sh/setup-uv@d4b2f3b… # v5`), so a
compromised or retagged action release cannot change what CI runs.

Two divergences from the plan, both deliberate:

1. **`ruff format --check .` is NOT in the lint gate.** Only `ruff check .` is.
   Ruff *lint* is configured in `pyproject.toml` (`select = ["F", "E4", "E7",
   "E9"]`, `line-length = 88`, `target-version = "py312"`) and the tree is clean
   against it. `ruff format`, by contrast, would rewrite 72 files under
   `src/` + `tests/` (measured: 3383 insertions / 1266 deletions), which would bury
   the feature diff of this whole unification under a mechanical reformat. The
   existing code predates any formatter; a repo-wide format belongs in its own
   isolated commit, not inside a feature milestone. The reason is recorded as a
   comment on `[tool.ruff.lint]` in `pyproject.toml`. Consequently the acceptance
   criterion below is ticked for `ruff check`, not for `ruff format --check`.
2. **`test-documents` / `test-structured` became `pytest` / `test-base`.** The
   planned split ran the *same* environment twice and named the halves after
   subsets of test files, which does not actually prove anything about the
   dependency boundary: `uv sync --extra structured` and `uv sync` both end up with
   pandas present, because the `dev` group implies the structured stack. The
   shipped shape inverts it — one job with *everything* installed (`pytest`, so
   nothing skips) and one job with *nothing optional* installed (`test-base`, which
   asserts pandas is absent before running). That is strictly stronger: it tests
   the boundary rather than test-file naming. The `test-structured` idea survives
   as a local convenience target instead — see the Makefile note in §5.2.

### 5.2 Add `[all]` dependency group

```toml
[project.optional-dependencies]
structured = ["pandas>=2.0", "numpy>=1.26", "scipy>=1.12", "openpyxl>=3.1"]
all = ["seed-data[structured]"]
dev = [
    "seed-data[all]",
    "pytest", "ruff",
    "mkdocs", "mkdocs-material", "mkdocs-awesome-nav", "mkdocstrings-python", "pymdown-extensions",
]
```

Shipped essentially as planned. The `structured` and `all` extras match the sketch
exactly; the reconciliations in `pyproject.toml` are:

- **`ruff` is pinned**, not bare: `"ruff>=0.15,<0.16"` in both the `dev` extra and
  the uv `lint` group, so a ruff minor upgrade cannot silently change what the CI
  lint gate enforces (new rules or new defaults landing mid-release would otherwise
  turn a green tree red without a code change).
- **uv dependency-groups mirror the extras.** The repo carries both
  `[project.optional-dependencies]` (pip-compatible, for `pip install -e ".[dev]"`)
  and `[dependency-groups]` (uv-native, for `uv sync`), and they must be kept in
  sync — there is a comment on each block saying so. The groups are
  `dev = [include test, include lint, include docs]`, `test = [pytest + the
  structured stack]`, `lint = [ruff]`, `docs = [the mkdocs set]`, with
  `[tool.uv] default-groups = ["dev"]`. `test` duplicates the structured pins
  rather than referencing the extra, which is what makes the `pytest` CI job run
  the structured suites instead of skipping them, and what makes `--only-group
  lint` (§5.1) meaningful.
- **`[tool.ruff]` / `[tool.ruff.lint]` are new config**, not just a dependency:
  `line-length = 88`, `target-version = "py312"`, `select = ["F", "E4", "E7",
  "E9"]`. Pinning these in-repo is what makes a contributor's local
  `ruff check` agree with CI regardless of their own ruff defaults.
- Unrelated to the extras but shipped in the same edit: `prompts/*.md` was added to
  `[tool.setuptools.package-data]` (`reportlab_cheatsheet.md` is loaded at runtime
  by `stages/document.py`, and relying on the git-file finder would silently drop it
  if the file were ever untracked).

**Makefile.** The `Makefile` row in the What Changes table shipped as two new
targets alongside the existing `help` / `install` / `test` / `docs`:

```make
test-structured:
	uv run pytest tests/test_ingest.py tests/test_structured.py tests/test_evaluation.py tests/test_evaluation_cross.py

lint:
	uv run ruff check .
```

`make lint` is deliberately the *exact* command the CI `lint` job runs, so the gate
is reproducible locally. `make test-structured` is the local survivor of the
planned `test-structured` CI job (§5.1) — a fast inner loop over the four suites
that need the `[structured]` extra; `uv sync` already installs that stack, so it
needs no extra setup. Both are declared in `.PHONY` and listed by `make help`.

### 5.3 Audit for internal references

Scan for:
- Internal model IDs not available on public Bedrock (e.g., `gpt-oss` is internal)
- Internal URLs (`a2z.com`, `aws.dev`, `code.amazon.com`)
- Internal package names
- Hardcoded account IDs or ARNs

~~For model IDs: the public release should document which models require cross-region inference or aren't publicly available, and provide fallback configurations using public models (Claude, Nova).~~

**Audit results (run against the tree — see the grep commands under Testing Plan):**

- Internal URLs: **clean.** `grep -rn "a2z.com\|aws.dev\|code.amazon.com\|midway\|isengard" src/ docs/` matches nothing outside this planning document (which names the strings only as the audit pattern).
- Hardcoded account IDs / ARNs: **clean.** No 12-digit literal near `account`/`arn`/`role` anywhere in `src/`.
- Internal package names: **clean.** The dependency set is all public PyPI.
- Model IDs: **finding stands.** `gpt-oss` (plus 11 other `MODELS` keys — the
  `gpt-oss-*`, `qwen3-*`, `nemotron*` and `deepseek-v3` families) are not generally
  available on public Bedrock, and the CLI defaults `--data-model`, `--doc-model`
  and `--aug-model` to `gpt-oss` in all five parsers that expose them.

**Decision — closed, not an open action item: the CLI `gpt-oss` defaults stay
exactly as they are.** No fallback configuration was added and no default was
changed. The rationale is the project's own non-negotiable constraint (see
`docs/planning/README.md`, "Preserve the published `seed-data` offering"): the
published v0.0.6 CLI already ships these defaults, so a user's existing
`seed-data --schema-dir invoice` invocation resolves to `gpt-oss` today. Silently
repointing it at a different model would change generation behaviour, cost and
output character for every existing caller — the one thing every milestone in this
plan is constrained not to do. Model choice is already fully explicit and
discoverable at the call site: `--data-model` / `--doc-model` / `--critic-model` /
`--batch-model` / `--aug-model` derive their `choices` from the shared `MODELS`
registry, so a user without `gpt-oss` access passes e.g.
`--data-model sonnet --doc-model sonnet`, and the Python API's
`ModelConfig(doc=..., critic=...)` is the same knob. This is documented, not
defaulted around.

**Consequence for the criteria below:** the "no internal model IDs without
documentation" criterion is ticked on the basis of the *documentation* half
(`MODELS` is enumerable, the model table in `README.md` and
`docs/docs/Advanced/models.md` lists every key, and every model flag advertises its
choices). No criterion is ticked claiming public-model fallback configs exist,
because they do not.

### 5.4 Update README

Add sections:
- **Structured Data Generation** (quickstart, examples)
- **Architecture** — updated diagram showing both paths:
  ```
  INPUT → seed-data ingest → InferredSchema.json
                                    ↓
              ┌─────────────────────┼─────────────────────┐
              ↓                                           ↓
  seed-data generate-structured           seed-data generate-documents
         ↓                                           ↓
    CSV/Parquet/Excel                          PDF + JSON labels
  ```
- **`seed-data run`** — unified entry point

All three shipped. The architecture diagram was redrawn rather than transcribed: the
shipped version ("Shared front door, two modalities") fans the *input* kinds in on
the left — free text, example data, schema, documents, ERD — before `ingest`, then
fans the one `InferredSchema` out to the two pipelines, which is the point the
plan's version leaves implicit by starting at a single `INPUT`. It also states the
consequence explicitly: modality is chosen *after* ingestion, so one schema drives
tables, documents, or both, and `--schema-dir` with a legacy schema directory still
enters the document pipeline directly without going through ingest at all.

### 5.5 Update existing docs

- `docs/docs/Getting-Started/quick-start.md` — add structured path
- `docs/docs/CLI-Usage/README.md` — document `ingest`, `generate-structured`, `generate-documents`, `run`
- `docs/docs/Python-API-Usage/README.md` — document `ingest()`, `generate_structured()`, `run()`
- New: `docs/docs/Guides/structured-data.md` — full guide for structured generation
- New: `docs/docs/Guides/ingest.md` — input types, auto-detection, examples

All five shipped, plus `docs/docs/index.md`,
`docs/docs/Getting-Started/installation.md` and
`docs/docs/API-Reference/generator.md`, which this list omitted (see the added rows
in What Changes).

**One step this list missed, which is load-bearing:** the two new guides also had to
be registered in `docs/docs/Guides/.nav.yml`. The site is built with
`mkdocs-awesome-nav`, whose `nav:` list is exhaustive rather than additive — a
markdown file in the directory that is not named in `.nav.yml` is silently dropped
from the built site. Writing the guide is not enough to publish it; both
`ingest.md` and `structured-data.md` were added to that file (and linked from the
`Guides/README.md` index).

### 5.6 CONTRIBUTING.md updates

Add:
- How to add a new input mode (implement detector in `ingest/detect.py`, add extractor)
- How to add a new output modality (implement generator, ~~wire to `run.py` dispatch~~)
- How to add a new schema type (both structured and document)
- How to add evaluation dimensions

**Correction: there is no `run.py`.** No such module was ever created (see also M4
§4.1, where the planned `src/seed_data/_dispatch.py` was likewise not needed). The
two extension points a new output modality actually has to be wired into are:

1. **`Generator.run()` in `src/seed_data/api.py`** — the modality dispatch. It
   validates `output` against the allowed modalities up front, calls
   `self.ingest(...)`, and then branches to the matching generate verb. Adding a
   modality means adding it to that check and adding a branch; the verb itself is a
   normal `Generator` verb.
2. **The `SUBCOMMANDS` dict in `src/seed_data/__main__.py`** — the CLI. The whole
   CLI lives in that one module: `SUBCOMMANDS = {name: handler}` at module level,
   each handler building its own `argparse.ArgumentParser` over its `argv`, and
   `main()` dispatching `sys.argv[1]` through the table (falling through to the
   untouched default `--schema-dir` document parser when it is not a key). Note
   `src/seed_data/cli.py` exists but is only a legacy `base_parser()` helper for old
   scripts — it is **not** where subcommands live and was not modified.

**Shipped:** `CONTRIBUTING.md` gained an **"Extending SEED"** section covering
exactly these points, with a package-layout orientation map plus subsections:

| Subsection | Covers |
|---|---|
| Adding a CLI subcommand | The `SUBCOMMANDS` table and `main()` dispatch, the per-handler `argparse` convention, `prog="seed-data <verb>"`, lazy `Generator`/`MODELS` imports inside the handler, `--quiet` → `verbose=`, deriving model `choices` from the `MODELS` registry rather than hard-coding, updating the `main()` epilog, and the requirement of a `tests/test_cli_smoke.py` smoke test (`test_all_subcommands_listed` fails until the epilog is updated) |
| Adding a Generator verb | `api.py` as the only public surface; the `_resolve_inferred` / `_resolve_for_documents` / `_resolve_schema` resolution helpers; in-method engine imports; delegating instance config (`self.models`, `self.threshold`, `self.output_dir`, `self.session`); returning a typed pydantic result with failures in the result rather than as exceptions; frozen published defaults; and the two-edit rule for a new export (`__all__` + a lazy `__getattr__` branch in `seed_data/__init__.py`) |
| Adding a prompt | `prompts.render(name, **kwargs)` over `.j2` templates, keeping prompt text out of Python literals, and the `package-data` glob (with `build-smoke` as the place a mis-packaged asset gets caught) |
| Optional dependencies | The rule that `pandas`/`numpy`/`scipy`/`openpyxl` are never imported at module level on a base-reachable path, deferred-import and `TYPE_CHECKING` patterns, which modules are allowed to import them eagerly, and how `test-base` enforces it — including the local reproduction recipe |

The plan's "new input mode" and "evaluation dimensions" items are covered by the
layout map plus the Generator-verb and optional-dependency subsections rather than
as their own headings.

### 5.7 Fresh-clone verification

Document as a manual QA checklist:

```bash
# Clone fresh
git clone https://github.com/awslabs/synthetically_engineered_evaluation_data.git
cd synthetically_engineered_evaluation_data

# Install all
pip install ".[all]"

# Verify CLI
seed-data --help
seed-data run --help
seed-data ingest --help
seed-data generate-structured --help
seed-data generate-documents --help

# Document generation (requires Bedrock)
export AWS_PROFILE=your-profile
seed-data --schema-dir fcc-invoice --count 1

# Structured generation (requires Bedrock)
seed-data run "Generate customer orders with priority, status, and shipping fields" --output structured --rows 50

# Both from same input
seed-data ingest "Simple invoice: number, date, vendor, total" --output /tmp/schema.json
seed-data generate-structured /tmp/schema.json --rows 20 --format csv
seed-data generate-documents /tmp/schema.json --count 2
```

**Status: the manual checklist above has NOT been executed against a real fresh
clone.** Every command in it was verified to match the shipped parsers (`ingest`
takes `--output` for the schema path; `generate-structured` takes `--rows` /
`--format {csv,parquet,excel,json}` / `--output`; `generate-documents` takes
`--count` / `--entity` / `--output`; `run` takes `--output {structured,documents}`
for the modality and `--output-dir` for the directory), and the `--help` of all four
was confirmed to exit clean from a clean-venv wheel install. But the two
Bedrock-backed steps were not run from a from-scratch `git clone` of the published
repo, so the corresponding acceptance criteria stay unticked below.

**What is automated instead.** The CI `build-smoke` and `test-base` jobs cover the
automatable part of this checklist — build, clean-venv install, `import seed_data`,
version resolution, `seed-data --help`, and the whole non-integration suite under a
lean install. What they cannot cover is the live-Bedrock half, which needs
credentials CI does not have; that is what `tests/integration/` exists for, and it
is excluded from the default run via `addopts`.

Verified locally against the built wheel (`uv build --wheel`) in three throwaway
venvs, which is the install-matrix half of the checklist:

| Install | Result |
|---|---|
| `pip install dist/*.whl` (base) | `import seed_data` OK; version resolves; `seed-data --help` OK; all four new subcommands' `--help` exit clean; `import pandas` fails as intended; `generate_structured` returns `success=False` with `error="No module named 'pandas'"` — a contained failure, not a crash |
| `pip install "dist/*.whl[structured]"` | pandas 3.0.5 / numpy 2.4.6 / scipy 1.18.0 / openpyxl all importable |
| `pip install "dist/*.whl[all]"` | same as `[structured]` (`all` currently resolves to it); `seed-data --help` OK |

---

## Testing Plan

### CI Validation

Reconciled with the four jobs that shipped in `.github/workflows/test.yml` (§5.1).

| Test | What it verifies |
|---|---|
| `lint` job passes | `ruff check .` clean against `select = ["F", "E4", "E7", "E9"]`, using the `ruff>=0.15,<0.16` pin from the `lint` group. **`ruff format --check .` is deliberately excluded** — see §5.1, divergence 1 |
| `pytest` job passes | The whole non-integration suite in the full environment (structured stack present, so nothing skips): 347 passed |
| `test-base` job passes | The suite against a clean venv holding the base wheel + pytest and nothing else, with `import pandas` asserted to fail *first*: 323 passed / 2 skipped (347 − 17 `test_structured.py` − 7 `test_evaluation.py`). This is the authoritative optional-dependency check |
| `build-smoke` job passes | sdist + wheel build, wheel installs in a clean venv, `import seed_data` works, `importlib.metadata.version("seed-data")` resolves, `seed-data --help` exits 0 |
| ~~`test-documents` job passes~~ | **Job does not exist.** Replaced by `test-base`, which is stricter: the planned job would have run with pandas installed anyway (the `dev` group implies it), so it could not have verified what its "without `[structured]` deps" description claimed |
| ~~`test-structured` job passes~~ | **Job does not exist.** Merged into `pytest`, which runs the structured suites in the full environment. Survives locally as `make test-structured` |
| ~~Optional deps truly optional — verify with `--import-mode=importlib`~~ | **Wrong mechanism.** `--import-mode` controls how pytest imports *test modules*; it has no bearing on whether `seed_data` transitively imports pandas. The real verification is `test-base`'s explicit `if python -c "import pandas"; then exit 1` gate plus running the suite in that venv |

### Audit Checks (automated)

```bash
# Check for internal URLs
grep -rn "a2z.com\|aws.dev\|code.amazon.com\|midway\|isengard" src/ docs/ --include="*.py" --include="*.md"

# Check for hardcoded account IDs (12-digit numbers in likely contexts)
grep -rn "[0-9]\{12\}" src/ --include="*.py" | grep -i "account\|arn\|role"

# Check model IDs are documented
python -c "from seed_data import MODELS; [print(k) for k in MODELS]"
```

### Import Isolation Test

```python
def test_structured_import_isolation():
    """Verify that importing seed_data without structured deps doesn't fail."""
    import subprocess, sys
    # Create a venv without structured deps, try to import
    result = subprocess.run(
        [sys.executable, "-c", "from seed_data import Generator, Schema; print('OK')"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
```

**This test as written is a no-op and was not implemented.** The comment says
"Create a venv without structured deps", but the code does no such thing: it
subprocesses `sys.executable` — the *same* interpreter running the test suite, in
the same environment, which by construction already has pandas installed (the `dev`
group implies `[structured]`, precisely so the structured suites run). So the
import under test always succeeds, and would keep succeeding even if `api.py`
grew a module-level `import pandas`. It asserts nothing. Two things shipped in its
place, at different levels:

**1. A real in-suite isolation test** —
`tests/test_cli_smoke.py::test_base_import_isolation_without_structured_deps`. It
subprocesses a program that installs a `builtins.__import__` guard raising
`ImportError` for anything whose top-level package is in
`{pandas, numpy, scipy, openpyxl}`, and *then* imports the documented base surface:
`Generator`, `Schema`, `ModelConfig`, `InferredSchema`, constructs a `Generator()`,
and imports `evaluation.evaluate_document_labels` (base-safe by design, unlike the
tabular scorers). A stray module-level structured import in any of those paths
fails the test. It runs in the normal suite, needs no build, and is the fast
feedback loop.

**2. The CI `test-base` job, which is the authoritative check.** The in-suite test
is a good smoke test but it is not a substitute for a genuinely dependency-free
environment, for a reason worth recording because it was found empirically:
**`pytest.importorskip` uses `importlib.import_module`, which BYPASSES a patched
`builtins.__import__`.** `tests/test_structured.py` and
`tests/test_evaluation.py` guard themselves with
`pytest.importorskip("pandas")` / `("numpy")` at module scope, and those calls go
through `importlib`, not the `__import__` builtin — so a monkeypatch of
`builtins.__import__` cannot make those modules skip. (Blocking at the
`sys.meta_path` level *can*, but only if the injected finder raises
`ModuleNotFoundError` specifically: as of pytest 9.1 `importorskip` defaults to
`exc_type=ModuleNotFoundError`, so a plain `ImportError` propagates as a collection
error instead of a skip.) That is why a suite-scope monkeypatch cannot substitute
for a real clean venv, and why the boundary is enforced by installing the wheel with
no extras into a fresh `venv` and asserting `import pandas` fails before pytest
even starts. Reproduced locally: 323 passed, 2 skipped (the two `importorskip`
modules), with the skip reason "requires the `[structured]` optional dependencies".

### Fresh Install Test (manual / CI matrix)

```yaml
  fresh-install:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        extra: ["", "structured", "all"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ".[${{ matrix.extra }}]"
      - run: seed-data --help
      - run: python -c "from seed_data import Generator, Schema; print('base OK')"
      - if: matrix.extra == 'structured' || matrix.extra == 'all'
        run: python -c "from seed_data import ingest, generate_structured; print('structured OK')"
```

**Two bugs in the snippet above, both fatal, neither shipped.**

1. **The empty matrix entry does not work.** `extra: ""` expands
   `pip install ".[${{ matrix.extra }}]"` to `pip install ".[]"`, which is not a
   valid requirement specifier — pip rejects it, so the one leg of the matrix that
   was supposed to prove the base install works is the leg that fails. There is no
   way to spell "no extras" as an extras-bracket substitution; the base case has to
   be a different command, not a matrix value.
2. **`from seed_data import ingest, generate_structured` does not exist.** Those are
   not module-level functions and never were — a deliberate, plan-level decision
   recorded in `docs/planning/README.md` ("New verbs on existing `Generator` class …
   No bare module-level functions"). `seed_data.__all__` is
   `[BatchResult, GeneratedDoc, Generator, InferredSchema, MODELS, ModelConfig,
   Schema, StructuredResult]`. The structured surface is reached as
   `Generator().ingest(...)` / `Generator().generate_structured(...)`, so the import
   in the last step would raise `ImportError` on every leg of the matrix, including
   the ones expected to pass.

**What shipped instead:** no matrix. Two fixed jobs, each of which installs one
concrete thing (§5.1), which sidesteps the substitution problem entirely and is
what makes the base leg meaningful:

- **`test-base`** — `uv build --wheel`, then `pip install dist/*.whl pytest` into a
  clean venv with **no extras at all** (no extras-bracket syntax involved), then
  `if python -c "import pandas"; then exit 1`, then the suite. This is the base leg,
  and it asserts the absence of the optional stack rather than merely not installing
  it.
- **`build-smoke`** — `uv build` (sdist + wheel), `pip install dist/*.whl` in a
  clean venv, then `import seed_data`, the resolved
  `importlib.metadata.version("seed-data")`, and `seed-data --help`.

The `structured` and `all` legs are not in CI. They are covered by §5.7's local
wheel matrix (verified: `[structured]` and `[all]` both bring in
pandas/numpy/scipy/openpyxl and keep `seed-data --help` working), on the reasoning
that installing an extra whose contents are four ordinary PyPI pins is a pip
behaviour, not a SEED behaviour — the SEED-specific risk is the *base* install
accidentally depending on them, and that is the leg CI runs on every push.

---

## Acceptance Criteria

- [x] GitHub Actions CI passes on push (~~lint + test-documents + test-structured~~ → **lint + pytest + test-base + build-smoke**, the four jobs in `.github/workflows/test.yml`; the planned job split was superseded, see §5.1 divergence 2. `uv run ruff check .` → All checks passed; `uv run pytest` → 347 passed, 13 warnings)
- [x] `pip install .` works without structured deps (documents-only install) (CI `test-base`; reproduced locally — base wheel + pytest in a clean venv, `import pandas` fails, `import seed_data` and `seed-data --help` work, 323 passed / 2 skipped. `generate_structured` on that install returns a contained `success=False, error="No module named 'pandas'"`)
- [x] `pip install ".[all]"` installs everything (verified against the built wheel in a throwaway venv: pandas/numpy/scipy/openpyxl all import, `seed-data --help` OK. `all = ["seed-data[structured]"]`, so it currently resolves to the structured stack by construction)
- [x] `pip install ".[structured]"` adds pandas/numpy/scipy (verified in a throwaway venv: pandas 3.0.5, numpy 2.4.6, scipy 1.18.0, plus openpyxl)
- [x] No internal URLs, internal model IDs without documentation, or hardcoded credentials in source (§5.3: the internal-URL and account-ID/ARN greps return nothing; every `MODELS` key is enumerable and documented in the `README.md` / `docs/docs/Advanced/models.md` model tables, and every model flag advertises its `choices` from that registry. **Scope note:** ticked on the *documented* half only — the `gpt-oss` CLI defaults are intentionally unchanged and no public-model fallback config was added, see the closed decision in §5.3)
- [x] README documents both modalities with quickstart examples (`README.md`: "Structured Data Generation" section, a shared-front-door architecture diagram showing ingest fanning out to both pipelines, CLI + Python quickstarts for `generate-structured` and `run`, and the `[structured]` install note)
- [x] CONTRIBUTING.md explains how to extend (input modes, output modalities, schemas) ("Extending SEED" section — layout map, adding a CLI subcommand, adding a `Generator` verb, adding a prompt, optional dependencies; §5.6. Note the plan's `run.py` dispatch point does not exist — the real ones are `Generator.run()` in `api.py` and the `SUBCOMMANDS` dict in `__main__.py`)
- [ ] Fresh clone → install → generate documents works — **outstanding.** Not executed from a from-scratch clone with live Bedrock credentials. CI `build-smoke` (wheel installs and `seed-data --help` works in a clean venv) and `test-base` (suite green on a lean install) cover the automatable part; `tests/integration/test_document_gen_unified.py` covers schema-file → PDF, but from the working tree, not a fresh clone
- [ ] Fresh clone → install → generate structured works — **outstanding**, same reason. The nearest automated evidence is `tests/integration/test_e2e.py::test_generator_run_structured_text` (live, but from the working tree and excluded from the default run) plus the local wheel-install matrix in §5.7
- [x] All docs pages updated (CLI, Python API, guides) (`docs/docs/index.md`, `Getting-Started/installation.md`, `Getting-Started/quick-start.md`, `CLI-Usage/README.md`, `Python-API-Usage/README.md`, `API-Reference/generator.md`, `Guides/README.md`, and two new guides `Guides/ingest.md` + `Guides/structured-data.md` — both registered in `Guides/.nav.yml`, without which awesome-nav would drop them from the site)
- [x] `seed-data run` unified command documented with examples (`README.md` quickstart line, `docs/docs/index.md` structured `run` example, and a dedicated "End-to-end run" section with a full flag reference in `docs/docs/CLI-Usage/README.md`; `gen.run(...)` in `docs/docs/API-Reference/generator.md` and `Python-API-Usage/README.md`)

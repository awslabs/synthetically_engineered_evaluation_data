# Milestone 5: Polish, CI, and Open-Source Release

**Goal:** Unified repo is ready for public release with both modalities. CI runs, docs are updated, no internal references remain, fresh-clone experience is verified.

**Duration:** ~1 week

**Depends on:** Milestones 1–4

---

## What Changes

| File / Dir | Action |
|---|---|
| `.github/workflows/ci.yml` | **NEW** — GitHub Actions CI (lint + test, both dep groups) |
| `README.md` | **MODIFIED** — add structured data section, unified architecture diagram |
| `docs/docs/Getting-Started/quick-start.md` | **MODIFIED** — add structured quickstart |
| `docs/docs/CLI-Usage/README.md` | **MODIFIED** — document new subcommands |
| `docs/docs/Python-API-Usage/README.md` | **MODIFIED** — document `ingest`, `generate_structured`, `run` |
| `CONTRIBUTING.md` | **MODIFIED** — how to add input modes and output modalities |
| `pyproject.toml` | **MODIFIED** — add `[all]` optional dep group |
| `Makefile` | **MODIFIED** — add targets for structured tests |

---

## Implementation Steps

### 5.1 GitHub Actions CI

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --group lint
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  test-documents:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run pytest tests/ -v --ignore=tests/integration

  test-structured:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra structured
      - run: uv run pytest tests/test_ingest.py tests/test_structured.py tests/test_evaluation.py -v
```

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

### 5.3 Audit for internal references

Scan for:
- Internal model IDs not available on public Bedrock (e.g., `gpt-oss` is internal)
- Internal URLs (`a2z.com`, `aws.dev`, `code.amazon.com`)
- Internal package names
- Hardcoded account IDs or ARNs

For model IDs: the public release should document which models require cross-region inference or aren't publicly available, and provide fallback configurations using public models (Claude, Nova).

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

### 5.5 Update existing docs

- `docs/docs/Getting-Started/quick-start.md` — add structured path
- `docs/docs/CLI-Usage/README.md` — document `ingest`, `generate-structured`, `generate-documents`, `run`
- `docs/docs/Python-API-Usage/README.md` — document `ingest()`, `generate_structured()`, `run()`
- New: `docs/docs/Guides/structured-data.md` — full guide for structured generation
- New: `docs/docs/Guides/ingest.md` — input types, auto-detection, examples

### 5.6 CONTRIBUTING.md updates

Add:
- How to add a new input mode (implement detector in `ingest/detect.py`, add extractor)
- How to add a new output modality (implement generator, wire to `run.py` dispatch)
- How to add a new schema type (both structured and document)
- How to add evaluation dimensions

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

---

## Testing Plan

### CI Validation

| Test | What it verifies |
|---|---|
| Lint job passes | `ruff check .` + `ruff format --check .` clean |
| test-documents job passes | All non-integration tests pass without `[structured]` deps |
| test-structured job passes | Structured-specific tests pass with `[structured]` deps |
| Optional deps truly optional | `test-documents` job doesn't `import pandas` — verify with `--import-mode=importlib` |

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

---

## Acceptance Criteria

- [ ] GitHub Actions CI passes on push (lint + test-documents + test-structured)
- [ ] `pip install .` works without structured deps (documents-only install)
- [ ] `pip install ".[all]"` installs everything
- [ ] `pip install ".[structured]"` adds pandas/numpy/scipy
- [ ] No internal URLs, internal model IDs without documentation, or hardcoded credentials in source
- [ ] README documents both modalities with quickstart examples
- [ ] CONTRIBUTING.md explains how to extend (input modes, output modalities, schemas)
- [ ] Fresh clone → install → generate documents works
- [ ] Fresh clone → install → generate structured works
- [ ] All docs pages updated (CLI, Python API, guides)
- [ ] `seed-data run` unified command documented with examples

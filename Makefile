# Makefile for Synthetically Engineered Evaluation Data (SEED)
#
# Convenience targets for common development tasks. All targets run inside the
# uv-managed environment; run `make install` first if you have not synced yet.

# Declare phony targets (targets that don't represent files)
.PHONY: help install test test-structured lint docs

# help: List the available targets
#
# Usage: make help (or just `make`)
help:
	@echo "Available targets:"
	@echo "  make install         Sync the uv environment (including the dev group)"
	@echo "  make test            Run the unit test suite (integration tests excluded)"
	@echo "  make test-structured Run only the structured/ingest/evaluation tests"
	@echo "  make lint            Run the ruff lint checks"
	@echo "  make docs            Serve the documentation site locally with live reload"

# install: Sync the uv environment
#
# Installs all dependencies from uv.lock, including the dev group (pytest, ruff,
# docs tooling). Requires Python 3.12+.
#
# Usage: make install
install:
	uv sync

# test: Run the unit test suite
#
# Runs pytest inside the uv environment. Integration tests under
# tests/integration/ are excluded by default (see addopts in pyproject.toml),
# since they require live AWS credentials.
#
# Usage: make test
test:
	uv run pytest

# test-structured: Run only the structured-data tests
#
# Exercises the ingest, structured-generation, and evaluation suites (the pieces
# that need the [structured] optional dependencies). Useful for a fast inner loop
# when working on that surface. `uv sync` already installs the structured stack.
#
# Usage: make test-structured
test-structured:
	uv run pytest tests/test_ingest.py tests/test_structured.py tests/test_evaluation.py tests/test_evaluation_cross.py

# lint: Run the ruff lint checks
#
# Runs the same `ruff check` the CI lint gate runs. Add `--fix` yourself for
# autofixes: `uv run ruff check --fix .`
#
# Usage: make lint
lint:
	uv run ruff check .

# docs: Serve the documentation site locally with live reload
#
# Starts the MkDocs dev server on http://127.0.0.1:8000, rebuilding as you edit.
# The docs dependency group must be installed (make install, or the dev group).
#
# Usage: make docs
docs:
	cd docs && uv run mkdocs serve

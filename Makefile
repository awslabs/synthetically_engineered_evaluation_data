# Makefile for Synthetically Engineered Evaluation Data (SEED)
#
# Convenience targets for common development tasks. All targets run inside the
# uv-managed environment; run `make install` first if you have not synced yet.

# Declare phony targets (targets that don't represent files)
.PHONY: help install test docs

# help: List the available targets
#
# Usage: make help (or just `make`)
help:
	@echo "Available targets:"
	@echo "  make install  Sync the uv environment (including the dev group)"
	@echo "  make test     Run the unit test suite (integration tests excluded)"
	@echo "  make docs     Serve the documentation site locally with live reload"

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

# docs: Serve the documentation site locally with live reload
#
# Starts the MkDocs dev server on http://127.0.0.1:8000, rebuilding as you edit.
# The docs dependency group must be installed (make install, or the dev group).
#
# Usage: make docs
docs:
	cd docs && uv run mkdocs serve

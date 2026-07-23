# Contributing Guidelines

Thank you for your interest in contributing to Synthetically Engineered Evaluation Data (SEED)! Whether it's a bug report, new feature, correction, or additional documentation, we greatly value feedback and contributions from our community.

Please read through this document before submitting any issues or pull requests to ensure we have all the necessary
information to effectively respond to your bug report or contribution.


## Quick Start for Contributors

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or pip
- Git

WeasyPrint (the default renderer) requires system libraries:

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

# Option 1: uv (recommended)
uv sync

# Option 2: pip + venv
pip install -e ".[dev]"
```

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
| Run the CLI smoke test (no Bedrock) | `pytest tests/test_cli_smoke.py` |
| Lint check | `ruff check .` |
| Lint fix | `ruff check --fix .` |

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

---
title: Installation
---

# Installation

## Requirements

- Python 3.12+
- An AWS account with Amazon Bedrock model access enabled

The default PDF renderer (`xhtml2pdf`) is pure Python and needs no system libraries. System libraries are only required if you opt into the WeasyPrint renderer (see [Optional: WeasyPrint renderer](#optional-weasyprint-renderer)).

## Install the package

Install from PyPI:

```bash
pip install seed-data
```

This works out of the box: the default `xhtml2pdf` renderer requires no additional system libraries.

Verify with `seed-data --help` (see [Verify Installation](#verify-installation)).

### From source (contributors)

If you are working from a clone of the repository, install the package in editable mode with the `dev` extras:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Or with `uv`, which handles the Python version, virtual environment, and dependencies in one step:

```bash
uv sync
```

## Optional: WeasyPrint renderer

The default `xhtml2pdf` renderer needs nothing extra. If you instead choose `--renderer weasyprint` (see [Renderers](../Advanced/renderers.md)), WeasyPrint depends on native libraries that pip cannot install. Install them with your system package manager:

```bash
# macOS
brew install pango gdk-pixbuf libffi

# Ubuntu/Debian
apt-get install libpango-1.0-0 libgdk-pixbuf2.0-0
```

## AWS Bedrock Credentials

SEED runs foundation models through Amazon Bedrock. You need an AWS account with Bedrock model access enabled for the models you plan to use.

Configure your credentials using any method supported by [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html). The recommended approach is a named profile in `~/.aws/config`, selected through the `AWS_PROFILE` environment variable:

```bash
export AWS_PROFILE=your-profile-name
```

Use a scoped, Bedrock-only profile rather than broad or administrator credentials. Any code the agents execute inherits this environment, so those credentials, and whatever they can access, are reachable by agent-run code.

## About BYPASS_TOOL_CONSENT

The Strands Agents SDK prompts for confirmation before executing a tool (for example, running rendering code). Because the pipeline runs many tool calls autonomously, the documented commands set an environment variable to skip those prompts:

```bash
export BYPASS_TOOL_CONSENT=true
```

Leave this variable unset when running schemas or briefs you do not fully trust, so you can approve each tool call. See the security notes in the project README for the full explanation of code and file execution.

## Verify Installation

```bash
seed-data --help          # or: python -m seed_data --help
```

You can also run the test suite (no AWS credentials required):

```bash
make test                 # or: uv run pytest
```

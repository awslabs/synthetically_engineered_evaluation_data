---
title: Installation
---

# Installation

## Requirements

- Python 3.12+
- An AWS account with Amazon Bedrock model access enabled
- System libraries for WeasyPrint (the default PDF renderer), see below

## Install the package

### Option 1: pip

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### Option 2: uv

```bash
uv sync
```

`uv` handles the Python version, virtual environment, and dependency installation in one step.

## WeasyPrint System Libraries

WeasyPrint is the default renderer and depends on native libraries that pip cannot install. Install them with your system package manager:

```bash
# macOS
brew install pango gdk-pixbuf libffi

# Ubuntu/Debian
apt-get install libpango-1.0-0 libgdk-pixbuf2.0-0
```

If you use the `reportlab` renderer instead (see [Renderers](../Advanced/renderers.md)), these libraries are not required.

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
python -m doc_gen_agent --help
```

You can also run the tests that do not require AWS credentials:

```bash
python scripts/test_unit.py      # Unit tests (no LLM calls)
python scripts/test_subgraph.py  # Graph wiring tests (no LLM calls)
```

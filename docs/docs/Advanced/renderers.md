---
title: Renderers
---

# Renderers

The doc generator agent produces code that renders to a PDF. SEED supports two rendering engines, selected with `--renderer`:

```bash
--renderer weasyprint   # default
--renderer reportlab
```

## WeasyPrint (default)

With `weasyprint`, the agent writes HTML and CSS, and WeasyPrint renders that markup to a PDF. This is the default because HTML/CSS is expressive for document layout: tables, typography, letterheads, and multi-column sections.

WeasyPrint depends on native system libraries that pip cannot install. Install them before using this renderer:

```bash
# macOS
brew install pango gdk-pixbuf libffi

# Ubuntu/Debian
apt-get install libpango-1.0-0 libgdk-pixbuf2.0-0
```

See [Installation](../Getting-Started/installation.md) for the full setup.

## ReportLab

With `reportlab`, the agent writes Python that uses the ReportLab library to lay out and render the PDF. This renderer does not require the WeasyPrint system libraries.

Because the ReportLab path runs agent-authored Python through a shell tool, the agent executes code on the host with the privileges of the user running the CLI. Treat all agent-generated code in `output/generation_scripts/` as untrusted model output: do not blindly re-run it later, and prefer running the pipeline in an isolated environment. See the security notes in the project README for the full guidance.

## Choosing a Renderer

| | WeasyPrint | ReportLab |
|---|---|---|
| Agent writes | HTML/CSS | Python |
| System libraries | Required (pango, gdk-pixbuf, libffi) | Not required |
| Code execution on host | Renders agent-authored markup | Runs agent-authored Python via a shell tool |
| Default | Yes | No |

Both renderers feed the same downstream stages: the doc critic evaluates the rendered PDF, and augmentation (if enabled) applies to the resulting PDF regardless of renderer.

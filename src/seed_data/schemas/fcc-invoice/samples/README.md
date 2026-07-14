# `samples/` — reference documents for the doc critic

This directory is **optional** and is **intentionally empty** in this repository.

## What goes here

Place real example PDFs of this document type here (e.g. `samples/example1.pdf`)
if you want to improve generation quality. The tool picks up any `*.pdf` in this
folder automatically — no configuration needed.

## How samples are used

- Samples are sent **only** to the **Document Critic** (quality-review stage) via
  the Amazon Bedrock API. See [`critique.py`](../../../critique.py).
- The critic uses them purely as a **visual style benchmark** — judging layout
  density, formatting, and overall professionalism of the *generated* document
  against the examples.
- **The generation stages never see the samples.** They do not influence the
  invented data, the rendered document, or the augmentation. Think of it as
  showing a designer an example and saying "match this style."
- **No content is extracted, copied, or reproduced** from samples into the
  generated output. All generated names, addresses, and figures are fictional.
- Disable sample use entirely with the `--no-critic-samples` flag.

## ⚠️ Do not commit sample PDFs

Sample documents are **local-only** and are **git-ignored** (see the root
[`.gitignore`](../../../../../../.gitignore)). Real documents may contain real
third-party names, PII, or other content you do not have the right to
redistribute — committing them could trigger data-distribution policies and
blocks open-source release.

**You are responsible for ensuring you have the rights to use any sample you
place here.** Prefer synthetic or properly-licensed public documents.

The original FCC invoice samples that previously lived here were removed for
exactly these reasons; they are not required for the tool to run.

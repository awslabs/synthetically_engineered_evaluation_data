---
title: Models
---

# Models

SEED calls foundation models through Amazon Bedrock. Each pipeline stage can use a different model, selected by a CLI flag, so you can trade off speed, cost, and quality per stage.

## Available Models

| Key | Model | Best For |
|-----|-------|----------|
| `gpt-oss` | GPT-OSS 120B | Doc generation, augmentation (fast tool calling) |
| `sonnet` | Claude Sonnet 4.6 | Critics (respects scope rules, good at evaluation) |
| `nova2-lite` | Amazon Nova 2 Lite | Data generation (fast, cheap, works with the calculator) |
| `nemotron-super` | Nemotron Super 120B | Doc generation (slow but high first-pass quality) |
| `haiku` | Claude Haiku 4.5 | Fast critic (less reliable at scope enforcement than sonnet) |

## Per-Stage Model Selection

Each stage has its own flag and default:

| Flag | Default | Stage |
|------|---------|-------|
| `--data-model` | `nova2-lite` | Data generation |
| `--doc-model` | `gpt-oss` | PDF generation |
| `--critic-model` | `sonnet` | All critics |
| `--aug-model` | `gpt-oss` | Augmentation decisions |
| `--context-model` | `gpt-oss` | Shared context resolution (packets only) |

Example, overriding models per stage:

```bash
python -m seed_data \
  --schema-dir src/seed_data/schemas/fcc-invoice \
  --extra "Office supplies" \
  --data-model nova2-lite \
  --doc-model gpt-oss \
  --critic-model sonnet
```

## Critic Model Constraint

The critic stages evaluate rendered PDFs with a vision model, so `--critic-model` must support document/PDF input. Currently that means an Anthropic model: `haiku`, `sonnet`, or `opus`. All other model flags can use any available model.

## Model-Agnostic Design

The pipeline is model-agnostic: the seven agents (scenario generator, data generator, data critic, doc generator, doc critic, augmentor, aug critic) each read a model key and construct a Bedrock-backed model, so you can mix and match. The default assignments reflect what works well for each role:

| Agent | Role | Default Model |
|-------|------|---------------|
| Scenario Generator | Creates diverse scenarios from brief + guidance | `gpt-oss` |
| Data Generator | Produces JSON data from schema. Has a calculator tool for math verification. | `nova2-lite` |
| Data Critic | Validates data against schema and domain rules. Has a calculator tool. Structured output. | `sonnet` |
| Doc Generator | Writes HTML/CSS and renders to PDF via WeasyPrint. Has an editor for targeted fixes. | `gpt-oss` |
| Doc Critic | Vision model evaluates PDF quality: layout, typography, truncation, math. Free-text output. | `sonnet` |
| Augmentor | Picks an augraphy augmentation config and applies document aging effects. | `gpt-oss` |
| Aug Critic | Evaluates the augmented doc for legibility and realism. Structured output. | `sonnet` |

## Cost Notes

Generation runs make repeated Bedrock calls and use critic-driven retry loops. Large batch counts or a high `--max-attempts` increase token spend. Keep `--max-attempts` and `--timeout` conservative and monitor Bedrock usage.

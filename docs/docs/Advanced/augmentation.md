---
title: Augmentation
---

# Augmentation

Real documents in an IDP pipeline are rarely pristine: they are scanned, faxed, photocopied, folded, and stained. To make evaluation data realistic, SEED can apply image augmentation that simulates these effects. Enable it with `--augment`:

```bash
BYPASS_TOOL_CONSENT=true python -m doc_gen_agent \
  --schema-dir src/doc_gen_agent/schemas/fcc-invoice \
  --extra "Local TV station in Portland, Oregon" \
  --augment
```

## How It Works

Augmentation uses [augraphy](https://github.com/sparkfish/augraphy), a library of document degradation effects. When `--augment` is set, two stages are added after the clean PDF is produced:

1. **Augmentor**: an LLM agent chooses an augmentation configuration and applies it. The config is organized into three phases:
   - **Ink phase**: affects the text/ink layer (for example `InkBleed`, `LowInkRandomLines`, `LinesDegradation`, `Dithering`).
   - **Paper phase**: affects the paper/background (for example `NoiseTexturize`, `BrightnessTexturize`, `ColorPaper`).
   - **Post phase**: affects the final output (for example `SubtleNoise`, `Jpeg`, `Brightness`, `Gamma`, `DirtyDrum`, `DirtyRollers`, `Faxify`, `BadPhotoCopy`).
2. **Aug critic**: evaluates the augmented document for legibility and realism, producing a structured score. If the result is illegible or unrealistic, the loop can retry with a different configuration.

Under the hood, the augmentor converts each PDF page to an image, runs the augraphy pipeline (ink, paper, then post phases), and writes the augmented pages back out as a PDF. The chosen configuration is saved alongside the output for reproducibility.

## Steering Augmentation

The augmentor reads the document type's steering docs, so you can add augmentation context in `generation_guidance.md`, for example:

```markdown
Augmentation context: these documents were faxed in the 1990s and photocopied
several times before scanning.
```

The augmentor uses this to pick effects that match the intended provenance of the document.

## Output

Augmented PDFs are written to the `augmented/` directory of a batch, alongside the clean `pdfs/`. The augmentation configuration is saved so a given augmented document can be reproduced.

## Packet Augmentation

In packets, augmentation runs per sub-document before the individual PDFs are merged, so each sub-document can have different degradation characteristics. This is realistic: in a real packet, some pages may be cleaner than others. Packet-level augmentation of the merged PDF is planned but not yet implemented. See [Packets](../Guides/packets.md) for details.

"""Augraphy augmentation tool wrapper.

Handles PDF → PNG → augraphy pipeline → PNG → PDF conversion.
The LLM agent decides the augmentation config; this module executes it.
"""
import json
import os

import augraphy
import numpy as np
import pypdfium2 as pdfium
from PIL import Image
from strands import tool



# Registry of available augraphy augmentations the agent can choose from
AUGMENTATION_REGISTRY = {
    # Ink phase (affects text/ink layer)
    "InkBleed": augraphy.InkBleed,
    "InkColorSwap": augraphy.InkColorSwap,
    "InkMottling": augraphy.InkMottling,
    "InkShifter": augraphy.InkShifter,
    "BleedThrough": augraphy.BleedThrough,
    "Dithering": augraphy.Dithering,
    "Hollow": augraphy.Hollow,
    "Letterpress": augraphy.Letterpress,
    "LinesDegradation": augraphy.LinesDegradation,
    "LowInkPeriodicLines": augraphy.LowInkPeriodicLines,
    "LowInkRandomLines": augraphy.LowInkRandomLines,
    # Paper phase (affects paper/background)
    "BadPhotoCopy": augraphy.BadPhotoCopy,
    "ColorPaper": augraphy.ColorPaper,
    "NoiseTexturize": augraphy.NoiseTexturize,
    "BrightnessTexturize": augraphy.BrightnessTexturize,
    "DelaunayTessellation": augraphy.DelaunayTessellation,
    "VoronoiTessellation": augraphy.VoronoiTessellation,
    # Post phase (affects final output)
    "BadPhotoCopy_post": augraphy.BadPhotoCopy,
    "Brightness": augraphy.Brightness,
    "ColorShift": augraphy.ColorShift,
    "DirtyDrum": augraphy.DirtyDrum,
    "DirtyRollers": augraphy.DirtyRollers,
    "Faxify": augraphy.Faxify,
    "Folding": augraphy.Folding,
    "Gamma": augraphy.Gamma,
    "Geometric": augraphy.Geometric,
    "GlitchEffect": augraphy.GlitchEffect,
    "Jpeg": augraphy.Jpeg,
    "Markup": augraphy.Markup,
    "PageBorder": augraphy.PageBorder,
    "Scribbles": augraphy.Scribbles,
    "ShadowCast": augraphy.ShadowCast,
    "SubtleNoise": augraphy.SubtleNoise,
    "WaterMark": augraphy.WaterMark,
    "BookBinding": augraphy.BookBinding,
    "Stains": augraphy.Stains,
    "DepthSimulatedBlur": augraphy.DepthSimulatedBlur,
    "LightingGradient": augraphy.LightingGradient,
    "Moire": augraphy.Moire,
    "DotMatrix": augraphy.DotMatrix,
}


import inspect as _inspect


def _coerce_to_default_shape(value, default):
    """Coerce an LLM-supplied param value to match augraphy's expected shape.

    Augraphy params are shape- and type-sensitive in ways the model gets wrong:
    some want a scalar (``SubtleNoise.subtle_range`` is a bare int), some want an
    int tuple (``NoiseTexturize.sigma_range``), some a float tuple
    (``InkBleed.severity``). Rather than a hand-maintained param table, we read
    the augmentation's own default and shape ``value`` to match it — version-
    accurate, and it repairs the two model mistakes seen in the wild:
      - a scalar given where a range is expected → ``(x, x)``
      - a range given where a scalar is expected → the low bound
      - float given where the default is int-typed → ``int(...)``
    JSON has no tuples, so lists always become tuples for range params.
    """
    want_tuple = isinstance(default, tuple)
    # Is the default integer-typed? (a tuple of ints, or a bare int)
    if want_tuple:
        want_int = all(isinstance(x, int) for x in default) if default else False
    else:
        want_int = isinstance(default, int) and not isinstance(default, bool)

    def _num(x):
        if isinstance(x, bool):
            return x
        if want_int and isinstance(x, (int, float)):
            return int(x)
        return x

    if want_tuple:
        if isinstance(value, (list, tuple)):
            seq = list(value)
        else:                       # scalar given where a range is expected
            seq = [value, value]
        # match the default's arity (usually 2) when we synthesized from a scalar
        return tuple(_num(x) for x in seq)
    # scalar expected
    if isinstance(value, (list, tuple)):
        value = value[0] if value else default   # range given where scalar expected
    return _num(value)


def _build_augmentation(name: str, params: dict):
    """Instantiate an augraphy augmentation by name, coercing params to the
    shapes/types augraphy actually expects (see ``_coerce_to_default_shape``)."""
    cls = AUGMENTATION_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown augmentation: {name}. Available: {list(AUGMENTATION_REGISTRY.keys())}")

    try:
        defaults = {
            k: p.default
            for k, p in _inspect.signature(cls.__init__).parameters.items()
            if p.default is not _inspect.Parameter.empty
        }
    except (ValueError, TypeError):
        defaults = {}

    converted = {}
    for k, v in params.items():
        if k in defaults and isinstance(defaults[k], (int, float, tuple)) \
                and not isinstance(defaults[k], bool):
            converted[k] = _coerce_to_default_shape(v, defaults[k])
        elif isinstance(v, list):
            # Unknown param that's a 2-list → tuple (augraphy convention); else as-is.
            converted[k] = tuple(v) if len(v) == 2 else v
        else:
            converted[k] = v
    return cls(**converted)


def _pdf_to_images(pdf_path: str, dpi: int = 200) -> list[np.ndarray]:
    """Convert PDF pages to numpy arrays."""
    doc = pdfium.PdfDocument(pdf_path)
    images = []
    for page in doc:
        bitmap = page.render(scale=dpi / 72)
        img = np.asarray(bitmap.to_pil().convert("RGB"))
        images.append(img)
        page.close()
    doc.close()
    return images


def _images_to_pdf(images: list[np.ndarray], output_path: str, dpi: int = 200):
    """Convert numpy arrays back to a PDF."""
    pages = [Image.fromarray(img) for img in images]
    # resolution embeds DPI so the physical page size matches the source render
    pages[0].save(
        output_path,
        format="PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=float(dpi),
    )


def run_augmentation(pdf_path: str, config: dict, dpi: int = 150) -> str:
    """Apply augraphy augmentations to a PDF.

    Args:
        pdf_path: Path to the input PDF.
        config: Dict with keys "ink_phase", "paper_phase", "post_phase".
                Each is a list of {"name": str, "params": dict}.
        dpi: Resolution for PDF rendering (lower = faster).

    Returns:
        Path to the augmented PDF.

    Note: augraphy's ``pipeline(img)`` is synchronous CPU work and cannot be
    safely interrupted from a worker thread (``signal.alarm`` is main-thread
    only, and there is no safe thread-kill). The hard bound against a wedged
    augment run is the graph's per-node timeout (``build_pipeline_graph``'s
    ``node_timeout``), which unblocks the pipeline even if this call stalls.
    """

    ink_phase = [_build_augmentation(a["name"], a.get("params", {}))
                 for a in config.get("ink_phase", [])]
    paper_phase = [_build_augmentation(a["name"], a.get("params", {}))
                   for a in config.get("paper_phase", [])]
    post_phase = [_build_augmentation(a["name"], a.get("params", {}))
                  for a in config.get("post_phase", [])]

    pipeline = augraphy.AugraphyPipeline(
        ink_phase=ink_phase,
        paper_phase=paper_phase,
        post_phase=post_phase,
    )

    images = _pdf_to_images(pdf_path, dpi=dpi)

    augmented_images = []
    for i, img in enumerate(images):
        augmented = pipeline(img)
        augmented_images.append(augmented)
        print(f"  Page {i+1}: augmented successfully")
        # Explicitly free original image to reduce peak memory
        del img

    images.clear()

    base, ext = os.path.splitext(pdf_path)
    output_path = f"{base}_augmented.pdf"
    _images_to_pdf(augmented_images, output_path, dpi=dpi)

    # Explicitly free augmented images after writing
    augmented_images.clear()
    import gc
    gc.collect()

    # Clean up augraphy cache
    import shutil as _shutil
    cache_dir = os.path.join(os.getcwd(), "augraphy_cache")
    if os.path.isdir(cache_dir):
        _shutil.rmtree(cache_dir, ignore_errors=True)

    return output_path


@tool
def apply_augmentation(pdf_path: str, augmentation_config: str) -> dict:
    """Apply augraphy augmentations to a PDF document.

    Takes a clean PDF and applies document aging/degradation effects.

    Args:
        pdf_path: Path to the clean PDF to augment.
        augmentation_config: JSON string with augmentation configuration.
            Must have keys "ink_phase", "paper_phase", "post_phase".
            Each is a list of objects with "name" and "params".
            ONLY use these safe augmentations:
            - ink_phase: InkBleed, LowInkRandomLines, LowInkPeriodicLines, LinesDegradation, Dithering
            - paper_phase: NoiseTexturize, BrightnessTexturize, ColorPaper
            - post_phase: SubtleNoise, Jpeg, Brightness, Gamma, DirtyDrum, DirtyRollers, Faxify, BadPhotoCopy

    Returns:
        Path to the augmented PDF, or error message.
    """
    try:
        config = json.loads(augmentation_config)

        # Log the augmentation chain
        all_augs = []
        for phase in ("ink_phase", "paper_phase", "post_phase"):
            for aug in config.get(phase, []):
                all_augs.append(f"  [{phase}] {aug['name']}: {aug.get('params', {})}")
        chain_log = "\n".join(all_augs) if all_augs else "  (none)"
        print(f"\nAugmentation chain:\n{chain_log}")

        output_path = run_augmentation(pdf_path, config)
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            # Save the aug config for reproducibility
            config_path = output_path.replace("_augmented.pdf", "_aug_config.json")
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            return {
                "status": "success",
                "content": [{"text": f"Augmented PDF saved to: {output_path} ({size:,} bytes)\nConfig saved to: {config_path}"}],
            }
        else:
            return {
                "status": "error",
                "content": [{"text": "Augmentation completed but output file was not created."}],
            }
    except Exception as e:
        return {
            "status": "error",
            "content": [{"text": f"Augmentation failed: {e}. Try simpler augmentations (SubtleNoise, Jpeg, Brightness)."}],
        }


def critique_augmented_document(pdf_path: str, model: str = "haiku", threshold: int = 7, session=None) -> dict:
    """Critique an augmented PDF using structured_output."""
    from seed_data import prompts as p
    from seed_data.critique import CritiqueResult
    from seed_data.utils import make_model as _make_model
    from strands import Agent

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    system_prompt = p.render("aug_critic", threshold=threshold)
    agent = Agent(model=_make_model(model, session=session), system_prompt=system_prompt)

    user_message = [
        {"document": {"format": "pdf", "name": "augmented_doc",
                       "source": {"bytes": pdf_bytes}}},
        {"text": f"Evaluate this augmented document. Threshold: {threshold}/10."},
    ]

    result = agent(user_message, structured_output_model=CritiqueResult)
    critique = result.structured_output
    verdict = "accepted" if critique.score >= threshold else "rejected"

    print(f"\n--- Aug Critique ({model}) ---")
    print(f"  Score:   {critique.score}/10 → {verdict}")
    print(f"  Summary: {critique.summary}")
    for issue in critique.issues:
        print(f"  [{issue.severity}] ({issue.category}) {issue.description}")
    print("--- End Aug Critique ---\n")

    return {
        "score": critique.score,
        "verdict": verdict,
        "issues": [i.model_dump() for i in critique.issues],
        "summary": critique.summary,
    }

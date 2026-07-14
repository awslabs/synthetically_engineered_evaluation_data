"""Batch orchestrator — LLM agent that generates diverse documents using orchestrate as a tool."""
import glob
import json
import os
import shutil
import sys
import time
from datetime import datetime

from strands import Agent, tool

from seed_data.orchestrate import orchestrate
from seed_data.utils import make_model

_pipeline_config = {}
_batch_results = []


@tool
def generate_document(extra_instructions: str) -> dict:
    """Generate a single document using the full pipeline.

    Args:
        extra_instructions: Specific scenario for this document. Be detailed:
            include advertiser name, industry, station/location, time period,
            and any other specifics that make this document unique.

    Returns:
        Summary of the generation result.
    """
    cfg = _pipeline_config
    start = time.time()

    result = orchestrate(
        schema_dir=cfg["schema_dir"],
        output_dir=cfg["batch_dir"],
        extra_instructions=extra_instructions,
        data_model=cfg["data_model"],
        doc_model=cfg["doc_model"],
        critic_model=cfg["critic_model"],
        aug_model=cfg["aug_model"],
        threshold=cfg["threshold"],
        max_attempts=cfg["max_attempts"],
        timeout=cfg["timeout"],
        augment=cfg["augment"],
        critic_samples=cfg.get("critic_samples", True),
        verbose=False,
    )
    elapsed = time.time() - start

    doc_id = result.get("doc_id", "unknown")

    # Track result
    usage = result.get("token_usage", {})
    entry = {
        "doc_id": doc_id,
        "success": result["success"],
        "verdict": result.get("verdict", "error"),
        "extra": extra_instructions,
        "pdf": result.get("path"),
        "data_json": result.get("data_json"),
        "augmented": result.get("augmented_path"),
        "time_s": round(elapsed, 1),
        "tokens": usage.get("inputTokens", 0) + usage.get("outputTokens", 0),
    }
    if not result["success"]:
        entry["error"] = result.get("error", "unknown")
    _batch_results.append(entry)

    status = "✓" if result["success"] else "✗"
    print(f"  {status} [{len(_batch_results)}] {extra_instructions[:60]}... ({elapsed:.0f}s)")
    if not result["success"]:
        print(f"    ERROR: {result.get('error', 'unknown')[:120]}")

    # Bail early if first 2 docs both fail (likely a config/auth issue)
    if len(_batch_results) >= 2 and all(not r["success"] for r in _batch_results):
        msg = "First 2 documents failed — likely a configuration issue. Aborting batch."
        print(f"\n  ⚠ {msg}")
        return {"status": "error", "content": [{"text": msg}]}

    # Return concise summary to keep batch agent context small
    summary = {k: entry[k] for k in ("success", "verdict", "doc_id", "time_s")}
    return {"status": "success", "content": [{"text": json.dumps(summary)}]}


def run_batch(
    schema_dir: str,
    count: int,
    brief: str,
    batch_name: str = None,
    output_dir: str = "./output",
    batch_model: str = "sonnet",
    data_model: str = "sonnet",
    doc_model: str = "sonnet",
    critic_model: str = "haiku",
    aug_model: str = "sonnet",
    threshold: int = 7,
    max_attempts: int = 5,
    timeout: int = 3600,
    augment: bool = False,
    critic_samples: bool = True,
) -> dict:
    """Run the batch orchestrator agent.

    Creates a batch directory under output_dir with subdirectories for
    pdfs/, data/, and augmented/. Writes a batch_manifest.json at the end.
    """
    global _pipeline_config, _batch_results
    _batch_results = []

    # Create batch directory
    if not batch_name:
        batch_name = datetime.now().strftime("batch_%Y%m%d_%H%M%S")
    batch_dir = os.path.join(output_dir, batch_name)
    os.makedirs(batch_dir, exist_ok=True)

    # Copy schema and steering docs into config/ folder for reproducibility
    config_dir = os.path.join(batch_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    for f in glob.glob(os.path.join(schema_dir, "*.json")) + glob.glob(os.path.join(schema_dir, "*.md")):
        shutil.copy2(f, config_dir)

    _pipeline_config = {
        "schema_dir": schema_dir,
        "batch_dir": batch_dir,
        "data_model": data_model,
        "doc_model": doc_model,
        "critic_model": critic_model,
        "aug_model": aug_model,
        "threshold": threshold,
        "max_attempts": max_attempts,
        "timeout": timeout,
        "augment": augment,
        "critic_samples": critic_samples,
    }

    system_prompt = f"""You are a batch document generation orchestrator. Your job is to
generate {count} diverse, unique documents by calling generate_document repeatedly.

RULES:
- Call generate_document exactly {count} times
- Each call MUST have completely different extra_instructions
- Vary: advertiser names, industries, station locations, time periods, spot types
- Track what you've generated to avoid repetition
- If a generation fails, note it and continue with the next one
- After all {count} calls, output a brief summary line: "BATCH COMPLETE: X/Y succeeded"
- Do NOT explain your plan — just start generating immediately
"""

    agent = Agent(
        model=make_model(batch_model),
        system_prompt=system_prompt,
        tools=[generate_document],
    )

    print(f"Batch:  {batch_name}")
    print(f"Count:  {count}")
    print(f"Brief:  {brief}")
    print(f"Output: {batch_dir}")
    print("=" * 60)

    batch_start = time.time()
    agent(f"Generate {count} diverse documents. Brief: {brief}")
    batch_elapsed = time.time() - batch_start

    # Write manifest
    succeeded = sum(1 for r in _batch_results if r["success"])
    total_tokens = sum(r.get("tokens", 0) for r in _batch_results)
    total_cost = total_tokens * 3 / 1_000_000  # rough estimate

    # Get git hash for reproducibility
    import subprocess as _sp
    try:
        git_hash = _sp.check_output(
            ["git", "rev-parse", "HEAD"], stderr=_sp.DEVNULL, text=True
        ).strip()
    except Exception:
        git_hash = "unknown"

    manifest = {
        "batch_name": batch_name,
        "brief": brief,
        "command": " ".join(sys.argv),
        "git_hash": git_hash,
        "count_requested": count,
        "count_succeeded": succeeded,
        "count_failed": len(_batch_results) - succeeded,
        "total_tokens": total_tokens,
        "est_cost_usd": round(total_cost, 4),
        "elapsed_s": round(batch_elapsed, 1),
        "config": {
            "schema_dir": schema_dir,
            "data_model": data_model,
            "doc_model": doc_model,
            "critic_model": critic_model,
            "aug_model": aug_model,
            "threshold": threshold,
            "augment": augment,
        },
        "documents": _batch_results,
    }
    manifest_path = os.path.join(batch_dir, "config", "batch_manifest.json")
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Batch complete: {succeeded}/{count} succeeded")
    print(f"Manifest: {manifest_path}")
    print(f"Tokens:   {total_tokens:,}  Est cost: ${total_cost:.4f}")
    print(f"Time:     {batch_elapsed:.1f}s ({batch_elapsed/max(count,1):.1f}s avg)")

    return manifest

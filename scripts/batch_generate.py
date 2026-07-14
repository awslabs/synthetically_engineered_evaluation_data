"""Parallel batch document generation.

Runs N documents in parallel using ThreadPoolExecutor.
No LLM orchestrator — just concurrent orchestrate() calls.

Usage:
  AWS_PROFILE=your-profile-name BYPASS_TOOL_CONSENT=true python scripts/batch_generate.py \
    --schema-dir src/seed_data/schemas/fcc-invoice \
    --count 5 --workers 3 --threshold 6 --augment
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from dotenv import load_dotenv


def main():
    load_dotenv()

    from seed_data.cli import base_parser
    from seed_data.orchestrate import orchestrate

    parser = base_parser("Parallel batch document generation")
    parser.add_argument("--count", type=int, default=5, help="Number of docs to generate")
    parser.add_argument("--workers", type=int, default=3, help="Max parallel workers")
    parser.add_argument("--batch-name", default=None, help="Batch directory name")
    parser.add_argument("--scenario-model", default="nova2-lite",
                        help="Model for scenario generation (default: nova2-lite)")
    args = parser.parse_args()

    batch_name = args.batch_name or datetime.now().strftime("batch_%Y%m%d_%H%M%S")
    batch_dir = os.path.join(args.output, batch_name)
    os.makedirs(batch_dir, exist_ok=True)

    # Copy schema + steering into config/ for reproducibility
    import shutil
    import glob
    config_dir = os.path.join(batch_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    for f in glob.glob(os.path.join(args.schema_dir, "*.json")) + \
             glob.glob(os.path.join(args.schema_dir, "*.md")):
        shutil.copy2(f, config_dir)

    print(f"Batch:   {batch_name}")
    print(f"Count:   {args.count}")
    print(f"Workers: {args.workers}")
    print(f"Models:  data={args.data_model}  doc={args.doc_model}  critic={args.critic_model}")
    if args.augment:
        print(f"Augment: enabled (model={args.aug_model})")
    print(f"Output:  {batch_dir}")
    print("=" * 60)

    # --- Step 0: Generate diverse scenarios using LLM ---
    from pydantic import BaseModel, Field
    from typing import List
    from seed_data.utils import make_model, load_schema_dir
    from strands import Agent

    _, steering, _ = load_schema_dir(args.schema_dir)
    brief = args.extra or "Generate diverse, realistic documents"

    class Scenarios(BaseModel):
        scenarios: List[str] = Field(description="List of unique scenario descriptions")

    scenario_agent = Agent(
        model=make_model(args.scenario_model),
        system_prompt="You generate diverse document scenarios. Each scenario should be 1-2 sentences describing a unique situation.",
    )
    print(f"Generating {args.count} diverse scenarios (model={args.scenario_model})...")
    prompt = (
        f"Generate exactly {args.count} unique, diverse scenarios for this document type.\n\n"
        f"Brief: {brief}\n\n"
        f"Document guidance:\n{steering}\n\n"
        f"Each scenario should vary: names, industries, locations, time periods, amounts, "
        f"and number of line items (vary between small and large). Make each one distinct."
    )
    scenario_result = scenario_agent(prompt, structured_output_model=Scenarios)
    scenarios = scenario_result.structured_output.scenarios
    for i, s in enumerate(scenarios):
        print(f"  [{i+1}] {s[:80]}...")
    print()

    def run_one(i):
        extra = scenarios[i] if i < len(scenarios) else f"Generate a unique document (variant {i+1})"
        start = time.time()
        result = orchestrate(
            schema_dir=args.schema_dir,
            output_dir=batch_dir,
            extra_instructions=extra,
            data_model=args.data_model,
            doc_model=args.doc_model,
            critic_model=args.critic_model,
            aug_model=args.aug_model,
            threshold=args.threshold,
            max_attempts=args.max_attempts,
            timeout=args.timeout,
            augment=args.augment,
            critic_samples=not args.no_critic_samples,
            renderer=args.renderer,
            enable_preview=args.preview,
            verbose=False,
        )
        elapsed = time.time() - start
        status = "✓" if result["success"] else "✗"
        verdict = result.get("verdict", "error")
        print(f"  {status} [{i+1}/{args.count}] {result.get('doc_id', '?')[:12]} "
              f"— {verdict} ({elapsed:.0f}s)")
        if not result["success"]:
            print(f"    ERROR: {result.get('error', 'unknown')[:120]}")
        return {**result, "time_s": round(elapsed, 1)}

    batch_start = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, i): i for i in range(args.count)}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                i = futures[future]
                print(f"  ✗ [{i+1}/{args.count}] EXCEPTION: {e}")
                results.append({"success": False, "error": str(e), "time_s": 0})

    batch_elapsed = time.time() - batch_start
    succeeded = sum(1 for r in results if r.get("success"))

    # Write manifest
    import subprocess as _sp
    try:
        git_hash = _sp.check_output(
            ["git", "rev-parse", "HEAD"], stderr=_sp.DEVNULL, text=True
        ).strip()
    except Exception:
        git_hash = "unknown"

    manifest = {
        "batch_name": batch_name,
        "command": " ".join(sys.argv),
        "git_hash": git_hash,
        "count_requested": args.count,
        "count_succeeded": succeeded,
        "workers": args.workers,
        "elapsed_s": round(batch_elapsed, 1),
        "config": {
            "schema_dir": args.schema_dir,
            "data_model": args.data_model,
            "doc_model": args.doc_model,
            "critic_model": args.critic_model,
            "aug_model": args.aug_model,
            "threshold": args.threshold,
            "augment": args.augment,
        },
        "documents": results,
    }
    manifest_path = os.path.join(batch_dir, "config", "batch_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print(f"Batch complete: {succeeded}/{args.count} succeeded")
    print(f"Manifest: {manifest_path}")
    print(f"Time:     {batch_elapsed:.1f}s ({batch_elapsed/max(args.count,1):.1f}s avg)")


if __name__ == "__main__":
    main()

"""Packet generation — generate sets of inter-related documents.

Generates N packets in parallel, where each packet contains multiple
document types sharing consistent context (e.g., a loan application
with credit report, pay stubs, and statement of intent).

Output follows the evaluation dataset format:
  input/       — merged multi-document PDFs
  baseline/    — per-section result.json labels
  classes.yaml — document type list

Usage:
  BYPASS_TOOL_CONSENT=true python scripts/packet_generate.py \
    --packet src/seed_data/packets/loan-application \
    --count 3 --workers 2 --augment \
    --extra "First-time homebuyers in the Pacific Northwest"
"""
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from dotenv import load_dotenv


def main():
    load_dotenv()

    from seed_data.cli import base_parser
    from seed_data.packet import (
        load_packet_config,
        generate_packet,
        emit_classes_yaml,
        write_packet_manifest,
    )

    parser = base_parser("Packet document generation")
    parser.add_argument("--packet", required=True, help="Path to packet config directory")
    parser.add_argument("--count", type=int, default=1, help="Number of packets to generate")
    parser.add_argument("--workers", type=int, default=2, help="Max parallel workers")
    parser.add_argument("--batch-name", default=None, help="Batch directory name")
    parser.add_argument("--shuffle", action="store_true",
                        help="Randomize sub-document order in merged PDF")
    parser.add_argument("--doc-workers", type=int, default=3,
                        help="Parallel workers for sub-documents within each packet (default: 3)")
    parser.add_argument("--context-model", default="gpt-oss",
                        help="Model for shared context resolution (default: nova2-lite)")

    # Remove --schema-dir requirement (packets use their own schema refs)
    # We override it to be optional since packets define their own schemas
    for action in parser._actions:
        if hasattr(action, "dest") and action.dest == "schema_dir":
            action.required = False
            action.default = None
            break

    args = parser.parse_args()

    # Load packet config
    config = load_packet_config(args.packet)

    batch_name = args.batch_name or datetime.now().strftime(f"packet_{config.name}_%Y%m%d_%H%M%S")
    batch_dir = os.path.join(args.output, batch_name)
    os.makedirs(batch_dir, exist_ok=True)

    # Copy packet config for reproducibility
    config_dir = os.path.join(batch_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    shutil.copy2(os.path.join(args.packet, "packet.json"), config_dir)

    # Emit classes.yaml
    emit_classes_yaml(config, batch_dir)

    print(f"Packet:  {config.name} — {config.description}")
    print(f"Docs:    {', '.join(d.document_class for d in config.documents)}")
    print(f"Count:   {args.count}")
    print(f"Workers: {args.workers}")
    print(f"Doc workers: {args.doc_workers}")
    print(f"Shuffle: {args.shuffle}")
    print(f"Models:  data={args.data_model}  doc={args.doc_model}  critic={args.critic_model}")
    if args.augment:
        print(f"Augment: enabled (model={args.aug_model})")
    print(f"Output:  {batch_dir}")
    print("=" * 60)

    def run_one(i: int):
        packet_id = f"packet_{i + 1:03d}"
        print(f"\n--- Packet {i + 1}/{args.count} ({packet_id}) ---")
        start = time.time()

        result = generate_packet(
            config=config,
            output_dir=batch_dir,
            packet_id=packet_id,
            extra=args.extra or "",
            shuffle=args.shuffle,
            doc_workers=args.doc_workers,
            data_model=args.data_model,
            doc_model=args.doc_model,
            critic_model=args.critic_model,
            aug_model=args.aug_model,
            context_model=args.context_model,
            threshold=args.threshold,
            max_attempts=args.max_attempts,
            timeout=args.timeout,
            augment=args.augment,
            critic_samples=not args.no_critic_samples,
            renderer=args.renderer,
            enable_preview=args.preview,
        )

        elapsed = time.time() - start
        status = "✓" if result.success else "✗"
        section_count = sum(1 for s in result.sections if s.success)
        print(f"  {status} {packet_id}: {section_count}/{len(result.sections)} docs ({elapsed:.0f}s)")
        if not result.success:
            print(f"    ERROR: {result.error}")

        return result

    batch_start = time.time()
    results = []

    if args.workers == 1 or args.count == 1:
        # Sequential — simpler output, easier to debug
        for i in range(args.count):
            results.append(run_one(i))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_one, i): i for i in range(args.count)}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    i = futures[future]
                    print(f"  ✗ packet_{i + 1:03d}: EXCEPTION: {e}")
                    from seed_data.packet import PacketResult
                    results.append(PacketResult(
                        packet_id=f"packet_{i + 1:03d}",
                        success=False,
                        error=str(e),
                    ))

    batch_elapsed = time.time() - batch_start
    succeeded = sum(1 for r in results if r.success)

    # Write manifest
    manifest_path = write_packet_manifest(
        results=results,
        config=config,
        output_dir=batch_dir,
        command=" ".join(sys.argv),
        elapsed_s=batch_elapsed,
        config_args={
            "data_model": args.data_model,
            "doc_model": args.doc_model,
            "critic_model": args.critic_model,
            "aug_model": args.aug_model,
            "context_model": args.context_model,
            "threshold": args.threshold,
            "augment": args.augment,
            "shuffle": args.shuffle,
            "renderer": args.renderer,
        },
    )

    print(f"\n{'=' * 60}")
    print(f"Packets complete: {succeeded}/{args.count} succeeded")
    print(f"Manifest: {manifest_path}")
    print(f"Time:     {batch_elapsed:.1f}s ({batch_elapsed / max(args.count, 1):.1f}s avg)")


if __name__ == "__main__":
    main()

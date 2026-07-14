"""CLI entrypoint: python -m seed_data"""
import argparse
import json
import sys
import time

from dotenv import load_dotenv


def _clone_schema_library(argv):
    """Handle the `clone-schema-library` subcommand."""
    from seed_data.utils import clone_schema_library, SCHEMA_LIBRARY_URL
    parser = argparse.ArgumentParser(
        prog="seed-data clone-schema-library",
        description="Copy the bundled schema library to a local, editable directory.",
    )
    parser.add_argument("dest", nargs="?", default="./schemas",
                        help="Destination directory (default: ./schemas)")
    args = parser.parse_args(argv)
    try:
        target = clone_schema_library(args.dest)
    except (FileExistsError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    print(f"Copied schema library to {target}")
    print(f"Edit the schemas there, then run: seed-data --schema-dir {target}/<name>")
    print(f"Browse the library on GitHub: {SCHEMA_LIBRARY_URL}")


def main():
    # Subcommand dispatch (kept separate so the default generate flow is untouched).
    if len(sys.argv) > 1 and sys.argv[1] == "clone-schema-library":
        _clone_schema_library(sys.argv[2:])
        return

    load_dotenv()

    from seed_data import MODELS
    from seed_data.orchestrate import orchestrate

    model_choices = list(MODELS.keys())
    parser = argparse.ArgumentParser(
        prog="seed-data",
        description="AI-powered document generation pipeline",
    )
    parser.add_argument("--schema-dir", required=True, help="Schema directory")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--extra", default=None, help="Extra instructions / brief")
    parser.add_argument("--count", type=int, default=1, help="Number of docs (>1 uses batch agent)")
    parser.add_argument("--batch-name", default=None, help="Batch directory name (default: timestamp)")
    parser.add_argument("--data-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--doc-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--critic-model", default="sonnet", choices=model_choices)
    parser.add_argument("--batch-model", default="nova2-lite", choices=model_choices,
                        help="Model for batch orchestrator")
    parser.add_argument("--augment", action="store_true")
    parser.add_argument("--no-critic-samples", action="store_true",
                        help="Disable reference sample PDFs in doc critic")
    parser.add_argument("--aug-model", default="deepseek-v3", choices=model_choices)
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.count > 1:
        # Batch mode: LLM orchestrator generates diverse documents
        from seed_data.batch import run_batch
        brief = args.extra or "Generate diverse, realistic documents"
        result = run_batch(
            schema_dir=args.schema_dir,
            count=args.count,
            brief=brief,
            batch_name=args.batch_name,
            output_dir=args.output,
            batch_model=args.batch_model,
            data_model=args.data_model,
            doc_model=args.doc_model,
            critic_model=args.critic_model,
            aug_model=args.aug_model,
            threshold=args.threshold,
            max_attempts=args.max_attempts,
            timeout=args.timeout,
            augment=args.augment,
            critic_samples=not args.no_critic_samples,
        )
        print(f"\n{'=' * 60}")
        print(f"Batch time: {result['elapsed_s']}s")
    else:
        # Single doc mode
        start = time.time()
        result = orchestrate(
            schema_dir=args.schema_dir,
            output_dir=args.output,
            extra_instructions=args.extra,
            data_model=args.data_model,
            doc_model=args.doc_model,
            critic_model=args.critic_model,
            aug_model=args.aug_model,
            threshold=args.threshold,
            max_attempts=args.max_attempts,
            timeout=args.timeout,
            augment=args.augment,
            verbose=not args.quiet,
            critic_samples=not args.no_critic_samples,
        )
        elapsed = time.time() - start

        print(f"\n{'=' * 60}")
        print(json.dumps(result, indent=2))

        if result["success"]:
            print(f"\nPDF:       {result['path']}")
            if result.get("augmented_path"):
                print(f"Augmented: {result['augmented_path']}")
            print(f"Verdict:   {result['verdict']}")

        usage = result.get("token_usage", {})
        in_tok = usage.get("inputTokens", 0)
        out_tok = usage.get("outputTokens", 0)
        cost = (in_tok * 3 + out_tok * 15) / 1_000_000
        print(f"Tokens:    {in_tok + out_tok:,}  Cost: ${cost:.4f}  Time: {elapsed:.1f}s")

        if not result["success"]:
            sys.exit(1)


if __name__ == "__main__":
    main()

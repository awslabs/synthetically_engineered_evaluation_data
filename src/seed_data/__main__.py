"""CLI entrypoint: python -m seed_data"""
import argparse
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


def _packet(argv):
    """Handle the `packet` subcommand — generate a coordinated multi-document packet."""
    load_dotenv()
    from seed_data import MODELS, Generator, ModelConfig

    model_choices = list(MODELS.keys())
    parser = argparse.ArgumentParser(
        prog="seed-data packet",
        description="Generate a coordinated multi-document packet (shared context, merged PDF).",
    )
    parser.add_argument("packet", help="Packet directory path, or a bundled packet name")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--scenario", default="", help="Scenario shared across the packet's documents")
    parser.add_argument("--count", type=int, default=1, help="Number of packets to generate")
    parser.add_argument("--doc-workers", type=int, default=3,
                        help="Parallel workers for sub-documents within a packet")
    parser.add_argument("--shuffle", action="store_true",
                        help="Randomize sub-document order in the merged PDF")
    parser.add_argument("--data-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--doc-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--critic-model", default="sonnet", choices=model_choices)
    parser.add_argument("--context-model", default="nova2-lite", choices=model_choices,
                        help="Model for shared-context resolution / planning")
    parser.add_argument("--aug-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--renderer", default="xhtml2pdf",
                        choices=["xhtml2pdf", "weasyprint", "reportlab"])
    parser.add_argument("--augment", action="store_true")
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)

    gen = Generator(
        models=ModelConfig(
            data=args.data_model, doc=args.doc_model, critic=args.critic_model,
            aug=args.aug_model, batch=args.context_model,
        ),
        threshold=args.threshold,
        renderer=args.renderer,
        output_dir=args.output,
        timeout=args.timeout,
        augment=args.augment,
    )
    result = gen.generate_packet(
        args.packet, count=args.count, scenario=args.scenario,
        shuffle=args.shuffle, doc_workers=args.doc_workers,
    )
    results = result if isinstance(result, list) else [result]
    print(f"\n{'=' * 60}")
    for r in results:
        status = "OK  " if r.success else "FAIL"
        print(f"{status} packet {r.packet_id}: {len(r.sections)} sections -> {r.merged_pdf or r.error}")
    if not any(r.success for r in results):
        sys.exit(1)


def _infer_schema(argv):
    """Handle the `infer-schema` subcommand — reverse-engineer a schema from docs.

    Reads real sample documents (PDF/PNG/JPEG, local or s3://), infers a schema +
    generation guidance with a vision model, and writes it to --output for review.
    With --then-generate it chains straight into single (--count 1) or batch
    (--count >1) generation from the inferred schema, mirroring the main CLI.
    """
    load_dotenv()
    from seed_data import MODELS, Generator, ModelConfig

    model_choices = list(MODELS.keys())
    parser = argparse.ArgumentParser(
        prog="seed-data infer-schema",
        description="Infer a document-type schema from real sample documents.",
    )
    parser.add_argument("inputs", nargs="+",
                        help="Sample document paths/globs/dirs and/or s3:// URIs (PDF/PNG/JPEG)")
    parser.add_argument("--name", required=True, help="Document-type name (schema title)")
    parser.add_argument("--output", required=True,
                        help="Directory to write the inferred schema.json + generation_guidance.md")
    parser.add_argument("--infer-model", default="sonnet", choices=model_choices,
                        help="Vision-capable model for inference (default: sonnet)")
    parser.add_argument("--max-docs", type=int, default=5,
                        help="Max example documents to feed the model (default: 5)")
    # Packet mode: input is ONE concatenated multi-document PDF. --name is the
    # packet name and --output is a packet directory (packet.json + schema dirs).
    parser.add_argument("--packet", action="store_true",
                        help="Treat the input as one concatenated multi-document PDF: "
                             "split it, infer a schema per segment, write a packet.json")
    parser.add_argument("--boundaries", default=None,
                        help="With --packet: fixed page ranges, e.g. '1-2,3,4-5' "
                             "(overrides model boundary detection)")
    parser.add_argument("--allow-questions", action="store_true",
                        help="Let the model ask you clarifying questions about the "
                             "document(s) during inference (interactive terminals only)")
    # One-shot generation tail (opt-in). Mirrors the main generate CLI semantics.
    parser.add_argument("--then-generate", action="store_true",
                        help="After inferring, generate from the schema (single, or batch if --count >1)")
    parser.add_argument("--count", type=int, default=1,
                        help="With --then-generate: number of docs (>1 = batch)")
    parser.add_argument("--scenario", default="", help="With --then-generate: scenario / diversity brief")
    parser.add_argument("--data-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--doc-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--critic-model", default="sonnet", choices=model_choices)
    parser.add_argument("--batch-model", default="nova2-lite", choices=model_choices)
    parser.add_argument("--aug-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--renderer", default="xhtml2pdf",
                        choices=["xhtml2pdf", "weasyprint", "reportlab"])
    parser.add_argument("--augment", action="store_true")
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)

    # --packet writes a packet dir for `seed-data packet`; it does not chain into
    # single/batch generation. Reject the combination rather than silently drop it.
    if args.packet and args.then_generate:
        parser.error(
            "--then-generate is not supported with --packet. "
            "Infer the packet, then run: seed-data packet <output_dir>"
        )

    # Wire the clarifying-dialogue callback to a terminal prompt — but ONLY when
    # stdin is a real TTY, so background/CI/piped runs never block on input().
    on_question = None
    if args.allow_questions:
        if sys.stdin.isatty():
            def on_question(question: str) -> str:
                print(f"\n\N{LEFTWARDS ARROW WITH HOOK} {question}")
                try:
                    return input("  your answer > ").strip()
                except (EOFError, KeyboardInterrupt):
                    return ""
        else:
            print("--allow-questions ignored: stdin is not an interactive terminal.",
                  file=sys.stderr)

    gen = Generator(
        models=ModelConfig(
            data=args.data_model, doc=args.doc_model, critic=args.critic_model,
            aug=args.aug_model, batch=args.batch_model,
        ),
        threshold=args.threshold,
        renderer=args.renderer,
        output_dir=args.output if not args.then_generate else "./output",
        augment=args.augment,
    )

    # --- Packet mode: one concatenated PDF -> packet.json + per-segment schemas ---
    if args.packet:
        try:
            out = gen.infer_packet(
                args.inputs, name=args.name, output_dir=args.output,
                model=args.infer_model, boundaries=args.boundaries,
                on_question=on_question,
            )
        except (FileNotFoundError, FileExistsError, ValueError) as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        print(f"\n{'=' * 60}")
        print(f"Inferred packet written to: {out}")
        print("Review packet.json + the per-segment schema dirs, then generate with:")
        print(f"  seed-data packet {out} --scenario \"...\"")
        return

    try:
        schema = gen.infer_schema(
            args.inputs, name=args.name, model=args.infer_model,
            max_docs=args.max_docs, output_dir=args.output,
            on_question=on_question,
        )
    except (FileNotFoundError, FileExistsError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    if not args.then_generate:
        print(f"\n{'=' * 60}")
        print(f"Inferred schema written to: {args.output}")
        print("Review schema.json + generation_guidance.md, then generate with:")
        print(f"  seed-data --schema-dir {args.output} --scenario \"...\"")
        return

    # One-shot: generate from the freshly inferred schema.
    print(f"\n{'=' * 60}\nGenerating from inferred schema...")
    if args.count > 1:
        batch = gen.generate_batch(schema, count=args.count, scenario=args.scenario, seed=args.seed)
        print(f"\nBatch: {batch.count_succeeded}/{batch.count_requested} succeeded")
        for doc in batch.documents:
            status = "OK  " if doc.success else "FAIL"
            print(f"  {status} {doc.doc_id[:8]}  {doc.verdict:9} {doc.pdf_path or doc.error}")
        if batch.count_succeeded == 0:
            sys.exit(1)
    else:
        doc = gen.generate(schema, scenario=args.scenario)
        print(f"\n{'=' * 60}")
        if doc.success:
            print(f"PDF:     {doc.pdf_path}")
            print(f"Data:    {doc.data_json_path}")
            print(f"Verdict: {doc.verdict} ({doc.score}/10)")
        else:
            print(f"FAILED: {doc.error}")
            sys.exit(1)


def main():
    # Subcommand dispatch (kept separate so the default generate flow is untouched).
    if len(sys.argv) > 1 and sys.argv[1] == "clone-schema-library":
        _clone_schema_library(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "packet":
        _packet(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "infer-schema":
        _infer_schema(sys.argv[2:])
        return

    load_dotenv()

    from seed_data import MODELS, Generator, ModelConfig

    model_choices = list(MODELS.keys())
    parser = argparse.ArgumentParser(
        prog="seed-data",
        description="AI-powered document generation pipeline",
    )
    parser.add_argument("--schema-dir", required=True,
                        help="Schema directory path, or a bundled schema name")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--scenario", default=None,
                        help="What to generate this run (>1 count: the theme to diversify)")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of docs (>1 plans diverse scenarios and fans out)")
    parser.add_argument("--data-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--doc-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--critic-model", default="sonnet", choices=model_choices)
    parser.add_argument("--batch-model", default="nova2-lite", choices=model_choices,
                        help="Model for planning batch scenarios")
    parser.add_argument("--aug-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--renderer", default="xhtml2pdf",
                        choices=["xhtml2pdf", "weasyprint", "reportlab"],
                        help="PDF rendering backend")
    parser.add_argument("--augment", action="store_true")
    parser.add_argument("--no-critic-samples", action="store_true",
                        help="Disable reference sample PDFs in doc critic")
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--seed", type=int, default=None,
                        help="Seed for batch scenario planning (regression-stable sets)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    gen = Generator(
        models=ModelConfig(
            data=args.data_model, doc=args.doc_model, critic=args.critic_model,
            aug=args.aug_model, batch=args.batch_model,
        ),
        threshold=args.threshold,
        renderer=args.renderer,
        output_dir=args.output,
        max_attempts=args.max_attempts,
        timeout=args.timeout,
        critic_samples=not args.no_critic_samples,
        augment=args.augment,
    )

    if args.count > 1:
        # Batch mode: plan diverse scenarios, fan out concurrent pipeline graphs.
        scenario = args.scenario or "Generate diverse, realistic documents"
        batch = gen.generate_batch(
            args.schema_dir, count=args.count, scenario=scenario,
            seed=args.seed, verbose=not args.quiet,
        )
        print(f"\n{'=' * 60}")
        print(f"Batch complete: {batch.count_succeeded}/{batch.count_requested} succeeded")
        print(f"Tokens: {batch.total_tokens:,}")
        for doc in batch.documents:
            status = "OK  " if doc.success else "FAIL"
            print(f"  {status} {doc.doc_id[:8]}  {doc.verdict:9} {doc.pdf_path or doc.error}")
        if batch.count_succeeded == 0:
            sys.exit(1)
    else:
        # Single-document mode.
        start = time.time()
        doc = gen.generate(args.schema_dir, scenario=args.scenario or "", verbose=not args.quiet)
        elapsed = time.time() - start

        print(f"\n{'=' * 60}")
        if doc.success:
            print(f"PDF:       {doc.pdf_path}")
            if doc.augmented_path:
                print(f"Augmented: {doc.augmented_path}")
            print(f"Data:      {doc.data_json_path}")
            print(f"Verdict:   {doc.verdict} ({doc.score}/10)")
        else:
            print(f"FAILED: {doc.error}")

        usage = doc.token_usage
        in_tok = usage.get("inputTokens", 0)
        out_tok = usage.get("outputTokens", 0)
        cost = (in_tok * 3 + out_tok * 15) / 1_000_000
        print(f"Tokens:    {in_tok + out_tok:,}  Cost: ${cost:.4f}  Time: {elapsed:.1f}s")

        if not doc.success:
            sys.exit(1)


if __name__ == "__main__":
    main()

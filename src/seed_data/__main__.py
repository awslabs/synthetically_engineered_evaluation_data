"""CLI entrypoint: python -m seed_data"""
import argparse
import os
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


def _plan(argv):
    """Handle the `plan` subcommand — inputs -> unified InferredSchema JSON.

    Auto-detects each input's type (free-text, CSV/Excel example data, JSON
    Schema, SQL DDL, ERD, or PDF/image documents) and writes the merged
    InferredSchema to --output as JSON.
    """

    load_dotenv()
    from seed_data import Generator

    parser = argparse.ArgumentParser(
        prog="seed-data plan",
        description="Ingest inputs (text, CSV, PDF, JSON Schema, SQL DDL, ERD) "
                    "into a unified InferredSchema JSON file.",
    )
    parser.add_argument("inputs", nargs="+",
                        help="Free-text description(s), file paths/globs, and/or s3:// URIs")
    parser.add_argument("--name", default="dataset",
                        help="Logical dataset name (default: dataset)")
    parser.add_argument("--output", default="./schema.json",
                        help="Path to write the InferredSchema JSON (default: ./schema.json)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    gen = Generator()
    try:
        schema = gen.plan(*args.inputs, name=args.name, verbose=not args.quiet)
    except (ValueError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w") as f:
        f.write(schema.model_dump_json(indent=2))

    entity_names = ", ".join(e.entity_name for e in schema.entities) or "(none)"
    print(f"\n{'=' * 60}")
    print(f"Wrote InferredSchema to: {args.output}")
    print(f"Entities: {entity_names}")
    print("Generate structured data with:")
    print(f"  seed-data generate-structured {args.output} --rows 100 --format csv")


def _generate_structured(argv):
    """Handle the `generate-structured` subcommand — schema -> CSV/Parquet/Excel."""
    load_dotenv()
    from seed_data import Generator

    parser = argparse.ArgumentParser(
        prog="seed-data generate-structured",
        description="Generate structured data from an InferredSchema.",
    )
    parser.add_argument("schema",
                        help="Bundled schema name, path to an InferredSchema JSON, "
                             "or a schema directory")
    parser.add_argument("--rows", type=int, default=100,
                        help="Target records per entity (default: 100)")
    parser.add_argument("--format", default="csv",
                        choices=["csv", "parquet", "excel", "json"],
                        help="Output format (default: csv)")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--seed", type=int, default=None,
                        help="Seed the programmatic columns (numeric, enum, date, ID, "
                             "pattern) for reproducible output; free-text fields come "
                             "from an LLM and stay unseeded")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    gen = Generator(output_dir=args.output)
    try:
        result = gen.generate_structured(
            args.schema, rows=args.rows, format=args.format, seed=args.seed,
            verbose=not args.quiet,
        )
    except (ImportError, FileNotFoundError, KeyError, ValueError, OSError) as e:
        # A missing [structured] extra, an unreadable schema path, or a schema that
        # does not parse are all setup mistakes the user can fix. Printed plainly
        # rather than left as a traceback, matching every other subcommand — before
        # this, `seed-data generate-structured typo.json` printed a raw
        # FileNotFoundError stack.
        print(e, file=sys.stderr)
        sys.exit(1)

    print(f"\n{'=' * 60}")
    if result.success:
        for entity, count in result.row_counts.items():
            print(f"  {entity}: {count} rows")
        print(f"Files: {', '.join(result.output_paths)}")
        if result.evaluation:
            scores = ", ".join(f"{k}={v:.2f}" for k, v in result.evaluation.items())
            print(f"Quality: {scores}")
    else:
        print(f"FAILED: {result.error}")
        sys.exit(1)


def _generate_documents(argv):
    """Handle the `generate-documents` subcommand — schema -> PDFs.

    Accepts either an InferredSchema JSON file (e.g. produced by `seed-data
    plan`) or a legacy schema directory / bundled schema name. The legacy dir
    path is unchanged from the default `--schema-dir` flow; the JSON path is
    adapted to the pipeline's schema triple via `schema/adapter.py`.
    """
    load_dotenv()
    from seed_data import MODELS, Generator, ModelConfig

    model_choices = list(MODELS.keys())
    parser = argparse.ArgumentParser(
        prog="seed-data generate-documents",
        description="Generate PDF documents from a schema (InferredSchema JSON, "
                    "schema directory, or bundled schema name).",
    )
    parser.add_argument("schema",
                        help="InferredSchema JSON path, schema directory, or bundled name")
    parser.add_argument("--entity", default=None,
                        help="For a multi-entity InferredSchema: which entity to render")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of docs (>1 plans diverse scenarios and fans out)")
    parser.add_argument("--scenario", default="",
                        help="What to generate this run (>1 count: the theme to diversify)")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--data-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--doc-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--critic-model", default="sonnet", choices=model_choices)
    parser.add_argument("--batch-model", default="nova2-lite", choices=model_choices,
                        help="Model for planning batch scenarios")
    parser.add_argument("--aug-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--renderer", default="xhtml2pdf",
                        choices=["xhtml2pdf", "weasyprint", "reportlab"])
    parser.add_argument("--augment", action="store_true")
    parser.add_argument("--no-critic-samples", action="store_true",
                        help="Disable reference sample PDFs in doc critic")
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--seed", type=int, default=None,
                        help="Seed for batch scenario planning (regression-stable sets)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

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

    # A directory (or bundled name) keeps the legacy path; a file is an
    # InferredSchema JSON that the adapter converts.
    schema_arg = args.schema
    if os.path.isfile(schema_arg):
        try:
            schema_arg = gen._resolve_inferred(schema_arg)
        except (ValueError, OSError) as e:
            print(f"Could not load schema from {args.schema}: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        if args.count > 1:
            scenario = args.scenario or "Generate diverse, realistic documents"
            batch = gen.generate_batch(
                schema_arg, count=args.count, scenario=scenario,
                entity=args.entity, seed=args.seed, verbose=not args.quiet,
            )
        else:
            batch = None
            doc = gen.generate(
                schema_arg, scenario=args.scenario,
                entity=args.entity, verbose=not args.quiet,
            )
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"{e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'=' * 60}")
    if batch is not None:
        print(f"Batch complete: {batch.count_succeeded}/{batch.count_requested} succeeded")
        print(f"Tokens: {batch.total_tokens:,}")
        for d in batch.documents:
            status = "OK  " if d.success else "FAIL"
            print(f"  {status} {d.doc_id[:8]}  {d.verdict:9} {d.pdf_path or d.error}")
        if batch.count_succeeded == 0:
            sys.exit(1)
    else:
        if doc.success:
            print(f"PDF:     {doc.pdf_path}")
            print(f"Data:    {doc.data_json_path}")
            print(f"Verdict: {doc.verdict} ({doc.score}/10)")
        else:
            print(f"FAILED: {doc.error}")
            sys.exit(1)


def _plan_and_generate(argv):
    """Handle the `plan-and-generate` subcommand — plan a schema, then generate,
    in one shot."""
    load_dotenv()
    from seed_data import MODELS, Generator, ModelConfig

    model_choices = list(MODELS.keys())
    parser = argparse.ArgumentParser(
        prog="seed-data plan-and-generate",
        description="End-to-end: plan a schema from the inputs, then generate "
                    "structured data or documents from it.",
    )
    parser.add_argument("inputs", nargs="+",
                        help="Free-text description(s), file paths/globs, and/or s3:// URIs")
    parser.add_argument("--output", default="structured",
                        choices=["structured", "documents"],
                        help="Which modality to generate (default: structured)")
    parser.add_argument("--output-dir", default="./output",
                        help="Directory to write artifacts to (default: ./output)")
    parser.add_argument("--name", default="dataset",
                        help="Logical dataset name (default: dataset)")
    parser.add_argument("--save-schema", default=None,
                        help="Also write the planned InferredSchema JSON to this path")
    # structured-only
    parser.add_argument("--rows", type=int, default=100,
                        help="structured only: target records per entity (default: 100)")
    parser.add_argument("--format", default="csv",
                        choices=["csv", "parquet", "excel", "json"],
                        help="structured only: output format (default: csv)")
    # documents-only
    parser.add_argument("--count", type=int, default=1,
                        help="documents only: how many to generate")
    parser.add_argument("--scenario", default="",
                        help="documents only: what to generate this run")
    parser.add_argument("--entity", default=None,
                        help="documents only: which entity of a multi-entity schema to render")
    parser.add_argument("--augment", action="store_true",
                        help="documents only: apply image augmentation")
    parser.add_argument("--data-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--doc-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--critic-model", default="sonnet", choices=model_choices)
    parser.add_argument("--batch-model", default="nova2-lite", choices=model_choices)
    parser.add_argument("--aug-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--renderer", default="xhtml2pdf",
                        choices=["xhtml2pdf", "weasyprint", "reportlab"])
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--seed", type=int, default=None,
                        help="structured: seed the programmatic columns; documents "
                             "(--count > 1): seed batch scenario planning. Schema "
                             "planning is an LLM step and is never seeded")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    gen = Generator(
        models=ModelConfig(
            data=args.data_model, doc=args.doc_model, critic=args.critic_model,
            aug=args.aug_model, batch=args.batch_model,
        ),
        threshold=args.threshold,
        renderer=args.renderer,
        output_dir=args.output_dir,
        timeout=args.timeout,
        augment=args.augment,
    )

    verbose = not args.quiet

    if args.output == "structured":
        # Checked before planning, which is a multi-agent LLM run: failing after it
        # would bill the user for the expensive half of the chain to report a
        # missing install that was knowable from the start.
        from seed_data.common.deps import require_structured

        try:
            require_structured("seed-data plan-and-generate --output structured")
        except ImportError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

    try:
        # Ingest first so --save-schema can persist it even when generation fails.
        schema = gen.plan(*args.inputs, name=args.name, verbose=verbose)
    except (ValueError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    if args.save_schema:
        with open(args.save_schema, "w") as f:
            f.write(schema.model_dump_json(indent=2))
        print(f"Wrote InferredSchema to: {args.save_schema}")

    if args.output == "structured":
        try:
            result = gen.generate_structured(
                schema, rows=args.rows, format=args.format, seed=args.seed,
                verbose=verbose,
            )
        except (ImportError, FileNotFoundError, KeyError, ValueError, OSError) as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        print(f"\n{'=' * 60}")
        if result.success:
            for entity, count in result.row_counts.items():
                print(f"  {entity}: {count} rows")
            print(f"Files: {', '.join(result.output_paths)}")
            if result.evaluation:
                scores = ", ".join(f"{k}={v:.2f}" for k, v in result.evaluation.items())
                print(f"Quality: {scores}")
        else:
            print(f"FAILED: {result.error}")
            sys.exit(1)
        return

    # documents. Wrapped for the same reason as the structured branch and
    # `generate-documents`: an `--entity` that is not in the schema surfaced as a
    # raw KeyError traceback.
    try:
        batch = None
        if args.count > 1:
            scenario = args.scenario or "Generate diverse, realistic documents"
            batch = gen.generate_batch(
                schema, count=args.count, scenario=scenario,
                entity=args.entity, seed=args.seed, verbose=verbose,
            )
        else:
            doc = gen.generate(
                schema, scenario=args.scenario, entity=args.entity, verbose=verbose,
            )
    except (FileNotFoundError, KeyError, ValueError, OSError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    if batch is not None:
        print(f"\n{'=' * 60}")
        print(f"Batch complete: {batch.count_succeeded}/{batch.count_requested} succeeded")
        for d in batch.documents:
            status = "OK  " if d.success else "FAIL"
            print(f"  {status} {d.doc_id[:8]}  {d.verdict:9} {d.pdf_path or d.error}")
        if batch.count_succeeded == 0:
            sys.exit(1)
    else:
        print(f"\n{'=' * 60}")
        if doc.success:
            print(f"PDF:     {doc.pdf_path}")
            print(f"Data:    {doc.data_json_path}")
            print(f"Verdict: {doc.verdict} ({doc.score}/10)")
        else:
            print(f"FAILED: {doc.error}")
            sys.exit(1)


# Subcommand name -> handler. Kept as a table so `--help` can list them and
# dispatch stays a single lookup.
SUBCOMMANDS = {
    "clone-schema-library": _clone_schema_library,
    "packet": _packet,
    "infer-schema": _infer_schema,
    "plan": _plan,
    "generate-structured": _generate_structured,
    "generate-documents": _generate_documents,
    "plan-and-generate": _plan_and_generate,
}

# Deprecated spellings, kept dispatchable for one release. Deliberately a separate
# table from SUBCOMMANDS: `--help` lists that one, and an alias listed there would
# advertise the name this rename is retiring. Neither spelling ever shipped in a
# release — both are new on this branch — so these are a courtesy to in-flight
# scripts, not a compatibility guarantee.
DEPRECATED_SUBCOMMANDS = {
    "ingest": ("plan", _plan),
    "run": ("plan-and-generate", _plan_and_generate),
}


def main():
    # Subcommand dispatch (kept separate so the default generate flow is untouched).
    if len(sys.argv) > 1 and sys.argv[1] in SUBCOMMANDS:
        SUBCOMMANDS[sys.argv[1]](sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] in DEPRECATED_SUBCOMMANDS:
        # Printed rather than warnings.warn: this is a CLI, so the user is a person
        # reading a terminal, and Python hides DeprecationWarning by default. stderr
        # so it cannot corrupt piped stdout.
        current, handler = DEPRECATED_SUBCOMMANDS[sys.argv[1]]
        print(
            f"warning: 'seed-data {sys.argv[1]}' is deprecated; "
            f"use 'seed-data {current}' instead.",
            file=sys.stderr,
        )
        handler(sys.argv[2:])
        return
    load_dotenv()

    from seed_data import MODELS, Generator, ModelConfig

    model_choices = list(MODELS.keys())
    parser = argparse.ArgumentParser(
        prog="seed-data",
        description="AI-powered synthetic data generation — documents and structured data",
        epilog=(
            "subcommands:\n"
            "  plan                  any input -> a unified schema JSON to review\n"
            "  generate-structured   schema -> CSV/Parquet/Excel/JSON\n"
            "  generate-documents    schema -> PDFs (InferredSchema JSON or schema dir)\n"
            "  plan-and-generate     end-to-end: plan + generate in one shot\n"
            "  infer-schema          infer a schema from real sample documents\n"
            "  packet                generate a coordinated multi-document packet\n"
            "  clone-schema-library  copy the bundled schemas somewhere editable\n"
            "\n"
            "Run `seed-data <subcommand> --help` for a subcommand's options.\n"
            "Without a subcommand, --schema-dir generates documents (below)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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

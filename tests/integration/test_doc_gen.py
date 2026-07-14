"""Isolated test: doc_generator ↔ doc_critic sub-graph loop.

Skips data generation — uses an existing JSON file.
Tests the full sub-graph: file_write → shell → editor → critic cycle.

Requires live AWS credentials, so it is excluded from the default pytest run
(see [tool.pytest.ini_options] addopts in pyproject.toml). Run it explicitly.

Usage:
  AWS_PROFILE=your-profile-name BYPASS_TOOL_CONSENT=true uv run python tests/integration/test_doc_gen.py
  AWS_PROFILE=your-profile-name BYPASS_TOOL_CONSENT=true uv run python tests/integration/test_doc_gen.py --model gpt-oss
  AWS_PROFILE=your-profile-name BYPASS_TOOL_CONSENT=true uv run python tests/integration/test_doc_gen.py --model deepseek-v3 --schema fcc-invoice
"""
import argparse
import json
import os
import sys
import time
import uuid

from dotenv import load_dotenv


def main():
    load_dotenv()

    from seed_data.orchestrate import _build_doc_loop
    from seed_data.utils import load_schema_dir

    # --- Args ---
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-oss", help="Doc generation model")
    parser.add_argument("--critic", default="haiku", help="Critic model")
    parser.add_argument("--schema", default="fcc-invoice", help="Schema dir name under schemas/")
    parser.add_argument("--data", default=None, help="Path to existing JSON data file (auto-detected if omitted)")
    parser.add_argument("--threshold", type=int, default=7)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--preview", action="store_true", help="Enable preview_pdf tool for visual self-inspection")
    parser.add_argument("--no-critic-samples", action="store_true", help="Disable reference sample PDFs in critic")
    parser.add_argument("--renderer", default="weasyprint", choices=["reportlab", "weasyprint"])
    args = parser.parse_args()

    # --- Resolve paths ---
    schema_dir = os.path.join("src/seed_data/schemas", args.schema)
    if not os.path.isdir(schema_dir):
        print(f"Schema dir not found: {schema_dir}")
        sys.exit(1)

    schema, steering, sample_pdfs = load_schema_dir(schema_dir)
    schema_json = json.dumps(schema, indent=2)
    doctype = schema.get("title", schema.get("document_type", "document")).lower()

    # Find or use data JSON
    if args.data:
        data_json_path = args.data
    else:
        # Auto-detect: check output/{doctype}/ (old layout) and output/{doctype}/data/ (new layout)
        candidates = []
        for search_dir in [
            os.path.join("output", doctype, "data"),
            os.path.join("output", doctype),
        ]:
            if os.path.isdir(search_dir):
                candidates.extend(
                    os.path.join(search_dir, f)
                    for f in sorted(os.listdir(search_dir)) if f.endswith(".json")
                )
        if not candidates:
            print(f"No JSON data files found for {doctype}. Pass --data explicitly.")
            sys.exit(1)
        data_json_path = candidates[0]

    if not os.path.exists(data_json_path):
        print(f"Data file not found: {data_json_path}")
        sys.exit(1)

    # --- Output paths ---
    doc_id = uuid.uuid4().hex[:12]
    output_dir = os.path.join("output", f"test-{args.schema}")
    pdfs_dir = os.path.join(output_dir, "pdfs")
    scripts_dir = os.path.join(output_dir, "generation_scripts")
    for d in (pdfs_dir, scripts_dir):
        os.makedirs(d, exist_ok=True)
    output_path = os.path.join(pdfs_dir, f"{doc_id}.pdf")
    script_ext = ".html" if args.renderer == "weasyprint" else ".py"
    script_path = os.path.join(scripts_dir, f"{doc_id}{script_ext}")

    # --- Build and run sub-graph ---
    print(f"Model:     {args.model}")
    print(f"Critic:    {args.critic}")
    print(f"Schema:    {schema_dir}")
    print(f"Data:      {data_json_path}")
    print(f"Output:    {output_path}")
    print(f"Script:    {script_path}")
    print(f"Threshold: {args.threshold}")
    print(f"Preview:   {args.preview}")
    print(f"Renderer:  {args.renderer}")
    print("=" * 60)

    doc_loop = _build_doc_loop(
        output_path=output_path,
        data_json_path=data_json_path,
        script_path=script_path,
        schema_json=schema_json,
        steering=steering,
        extra="",
        doc_model=args.model,
        critic_model=args.critic,
        threshold=args.threshold,
        timeout=args.timeout,
        sample_pdfs=sample_pdfs,
        enable_preview=args.preview,
        renderer=args.renderer,
    )

    start = time.time()
    try:
        result = doc_loop(
            f"Generate the PDF. Data is at {data_json_path}. Save PDF to {output_path}."
        )
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    elapsed = time.time() - start

    # --- Report ---
    print(f"\n{'=' * 60}")
    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        # Extract verdict from result
        verdict = "unknown"
        if hasattr(result, "results"):
            for key in ("doc_critic",):
                nr = result.results.get(key)
                if nr:
                    ct = str(nr.result).lower().replace("*", "").replace(" ", "")
                    if "verdict:accepted" in ct:
                        verdict = "accepted"
                    elif "verdict:rejected" in ct:
                        verdict = "rejected"
        print(f"PDF:     {output_path} ({size:,} bytes)")
        print(f"Script:  {script_path}")
        print(f"Verdict: {verdict}")
        print(f"Time:    {elapsed:.1f}s")
    else:
        print(f"FAILED: PDF not created at {output_path} ({elapsed:.1f}s)")
        sys.exit(1)


if __name__ == "__main__":
    main()

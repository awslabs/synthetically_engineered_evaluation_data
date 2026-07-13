"""Shared CLI argument parser for doc-gen-agent scripts."""
import argparse
from doc_gen_agent import MODELS


def base_parser(description="doc-gen-agent"):
    """Create the base argument parser with common options."""
    model_choices = list(MODELS.keys())
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--schema-dir", required=True, help="Schema directory")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--extra", default=None, help="Extra instructions / brief")
    parser.add_argument("--data-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--doc-model", default="nova2-lite", choices=model_choices)
    parser.add_argument("--critic-model", default="sonnet", choices=model_choices)
    parser.add_argument("--augment", action="store_true")
    parser.add_argument("--aug-model", default="gpt-oss", choices=model_choices)
    parser.add_argument("--no-critic-samples", action="store_true",
                        help="Disable reference sample PDFs in doc critic")
    parser.add_argument("--renderer", default="weasyprint", choices=["reportlab", "weasyprint"],
                        help="PDF rendering engine (default: weasyprint)")
    parser.add_argument("--preview", action="store_true",
                        help="Enable preview_pdf tool for visual self-inspection (requires VL model)")
    parser.add_argument("--threshold", type=int, default=5)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=3600)
    return parser

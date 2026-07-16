"""Strands @tool wrappers used by agents in the graph."""
import json
import os

from strands import tool


@tool
def random_roll(percent_chance: int) -> dict:
    """Roll a random decision with a given percent chance of returning true.

    Args:
        percent_chance: Integer from 1-100 representing the probability of returning true.
                        e.g. 70 means 70% chance of true, 50 means 50% chance of true.

    Returns:
        {"result": true} or {"result": false}

    Call this once per decision independently — never reuse the same result for multiple decisions.
    """
    import random
    result = random.randint(1, 100) <= percent_chance
    return {"status": "success", "content": [{"text": str(result).lower()}]}


@tool
def read_json_file(file_path: str) -> dict:
    """Read a JSON file and return its contents.

    Args:
        file_path: Path to the JSON file to read.
    """
    try:
        with open(file_path) as f:
            data = json.load(f)
        return {"status": "success", "content": [{"text": json.dumps(data, indent=2)}]}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"status": "error", "content": [{"text": f"Error reading {file_path}: {e}"}]}


@tool
def save_json_file(file_path: str, json_content: dict) -> dict:
    """Save JSON content to a file.

    Args:
        file_path: Path where the JSON file should be saved.
        json_content: The JSON object to save. A JSON-encoded string is also
            accepted and will be parsed before saving.
    """
    try:
        # Callers should pass a JSON object, but tolerate a JSON-encoded string.
        if isinstance(json_content, str):
            json_content = json.loads(json_content)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            json.dump(json_content, f, indent=2)
        return {"status": "success", "content": [{"text": f"Saved to: {file_path}"}]}
    except (OSError, json.JSONDecodeError, TypeError) as e:
        return {"status": "error", "content": [{"text": f"Error saving: {e}"}]}


@tool
def preview_pdf(pdf_path: str) -> dict:
    """Render a PDF to images so you can visually inspect the output.

    Call this after generating a PDF to see what it actually looks like.
    Returns page images you can examine for layout issues, truncation,
    font sizing, whitespace, and rendering artifacts.

    Args:
        pdf_path: Path to the PDF file to preview.
    """
    try:
        import io

        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf_path)
        content = []
        for page in doc:
            bitmap = page.render(scale=150 / 72)
            buf = io.BytesIO()
            bitmap.to_pil().save(buf, format="PNG")
            page.close()
            content.append({
                "image": {
                    "format": "png",
                    "source": {"bytes": buf.getvalue()}
                }
            })
        doc.close()
        content.append({"text": f"Rendered {len(content)} page(s) from {pdf_path}"})
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "content": [{"text": f"Preview failed: {e}"}]}


def _render_with_xhtml2pdf(html_path: str, pdf_path: str) -> None:
    """Render HTML to PDF with xhtml2pdf (pure Python, no system libraries)."""
    from xhtml2pdf import pisa
    with open(html_path, encoding="utf-8") as src, open(pdf_path, "wb") as dest:
        status = pisa.CreatePDF(src.read(), dest=dest, encoding="utf-8")
    if status.err:
        raise RuntimeError(f"xhtml2pdf reported {status.err} error(s) while rendering")


def _render_with_weasyprint(html_path: str, pdf_path: str) -> None:
    """Render HTML to PDF with WeasyPrint (requires Pango/Cairo system libraries)."""
    # Ensure system libraries are findable (macOS homebrew — Intel: /usr/local/lib, Apple Silicon: /opt/homebrew/lib)
    import platform
    if platform.system() == "Darwin":
        existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        paths = {p for p in existing.split(":") if p}
        paths.update(["/usr/local/lib", "/opt/homebrew/lib"])
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(paths)
    from weasyprint import HTML
    HTML(filename=html_path).write_pdf(pdf_path)


# Backend dispatch for the render tool. xhtml2pdf is the default because it is
# pure Python and needs no system libraries, so a fresh `pip install seed-data`
# renders out of the box.
_HTML_RENDERERS = {
    "xhtml2pdf": _render_with_xhtml2pdf,
    "weasyprint": _render_with_weasyprint,
}


def make_render_tool(backend: str = "xhtml2pdf"):
    """Build a ``render_html_to_pdf`` tool with its backend bound in.

    The backend is captured in the closure rather than read from a global env
    var, so each doc-generator gets its own correctly-configured render tool and
    concurrent workers with different renderers never collide. The tool keeps the
    name ``render_html_to_pdf`` so the generator prompt can reference it.
    """
    render = _HTML_RENDERERS.get(backend, _render_with_xhtml2pdf)

    @tool
    def render_html_to_pdf(html_path: str, pdf_path: str) -> dict:
        """Render an HTML file to PDF.

        Args:
            html_path: Path to the HTML file to render.
            pdf_path: Path where the PDF should be saved.
        """
        try:
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
            render(html_path, pdf_path)
            if os.path.exists(pdf_path):
                size = os.path.getsize(pdf_path)
                return {"status": "success", "content": [
                    {"text": f"PDF rendered: {pdf_path} ({size:,} bytes)"}
                ]}
            return {"status": "error", "content": [
                {"text": f"{backend} completed but PDF was not created."}
            ]}
        except Exception as e:
            # Surface the real traceback to stdout — otherwise only the LLM sees
            # the (paraphrased) error and the true cause never reaches the user.
            import traceback
            print(f"\n!!! render_html_to_pdf ({backend}) FAILED for {html_path}:")
            traceback.print_exc()
            return {"status": "error", "content": [
                {"text": f"Render failed ({backend}): {type(e).__name__}: {e}"}
            ]}

    return render_html_to_pdf

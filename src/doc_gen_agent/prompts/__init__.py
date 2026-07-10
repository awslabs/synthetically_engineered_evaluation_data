"""Jinja2 prompt template loader."""
import os
from jinja2 import Environment, FileSystemLoader, select_autoescape

_PROMPTS_DIR = os.path.dirname(__file__)
# select_autoescape escapes html/htm/xml by default and leaves .j2 prompt
# templates unescaped — preserving prompt text while satisfying Bandit B701.
_env = Environment(
    loader=FileSystemLoader(_PROMPTS_DIR),
    autoescape=select_autoescape(),
    keep_trailing_newline=True,
)


def render(template_name: str, **kwargs) -> str:
    """Render a prompt template by name (without .j2 extension)."""
    return _env.get_template(f"{template_name}.j2").render(**kwargs)

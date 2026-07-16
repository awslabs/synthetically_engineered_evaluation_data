"""Document Critic — Strands structured_output with multimodal PDF input.

Uses Pydantic models + structured_output_model for guaranteed valid responses.
"""
from typing import List

from pydantic import BaseModel, Field
from strands import Agent

from seed_data import prompts, MODELS
from seed_data.utils import make_model


class CritiqueIssue(BaseModel):
    """A single issue found during document critique."""
    category: str = Field(description="One of: layout, typography, content, math, completeness")
    severity: str = Field(description="One of: critical, major, minor")
    description: str = Field(description="Specific constructive feedback")
    fix_hint: str = Field(default="", description="Actionable code-level fix suggestion for the generator, e.g. 'increase colWidths[3] to 90*mm' or 'replace unicode U+2011 with ASCII hyphen'")


class CritiqueResult(BaseModel):
    """Structured critique result from the vision model."""
    score: int = Field(description="Quality score 1-10", ge=1, le=10)
    issues: List[CritiqueIssue] = Field(description="List of issues found")
    summary: str = Field(description="One sentence overall assessment")


def critique_document(
    pdf_path: str,
    model: str = "haiku",
    threshold: int = 7,
    steering: str = "",
    sample_pdfs: list[str] = None,
    data_json: str = None,
    session=None,
) -> dict:
    """Critique a PDF document using free-text output for natural language feedback.

    Returns dict with 'text' (full critique), 'score', and 'verdict'.
    The free-text format is easier for the doc generator to read and act on.
    """
    import re

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    system_prompt = prompts.render(
        "critic_vision", threshold=threshold, steering=steering,
        has_samples=bool(sample_pdfs), data_json=data_json or "",
    )
    agent = Agent(model=make_model(model, session=session), system_prompt=system_prompt)

    user_message = []

    # Include reference samples first so the critic sees them before the generated doc
    if sample_pdfs:
        for i, sp in enumerate(sample_pdfs):
            with open(sp, "rb") as f:
                user_message.append(
                    {"document": {"format": "pdf", "name": f"reference_sample_{i+1}",
                                  "source": {"bytes": f.read()}}}
                )
        user_message.append(
            {"text": f"Above are {len(sample_pdfs)} reference samples of real documents. "
                     "Use them to judge layout, density, and style of the generated document below."}
        )

    user_message.extend([
        {"document": {"format": "pdf", "name": "document_to_critique",
                       "source": {"bytes": pdf_bytes}}},
        {"text": f"Critique this generated document. Threshold: {threshold}/10."},
    ])

    result = agent(user_message)
    text = str(result)

    # Parse score and verdict from free-text response
    score = 5  # default if parsing fails
    score_match = re.search(r"Score:\s*(\d+)/10", text)
    if score_match:
        score = int(score_match.group(1))
    verdict = "accepted" if score >= threshold else "rejected"
    # Also check explicit verdict in text
    if "verdict:rejected" in text.lower().replace(" ", ""):
        verdict = "rejected"
    elif "verdict:accepted" in text.lower().replace(" ", ""):
        verdict = "accepted"

    print(f"\n--- Critique Result ({model}) ---")
    print(f"  Score:   {score}/10 → {verdict}")
    # Print a truncated preview of the critique
    lines = text.strip().split("\n")
    for line in lines[:20]:
        print(f"  {line}")
    if len(lines) > 20:
        print(f"  ... ({len(lines) - 20} more lines)")
    print("--- End Critique ---\n")

    return {
        "score": score,
        "verdict": verdict,
        "text": text,
        "pdf_path": pdf_path,
    }


def critique_data(
    data_json_path: str,
    schema: dict,
    steering: str = "",
    model: str = "haiku",
    threshold: int = 7,
) -> dict:
    """Critique generated data using structured_output with domain-aware LLM."""
    import json

    with open(data_json_path) as f:
        data = json.load(f)

    system_prompt = prompts.render(
        "data_critic",
        schema_json=json.dumps(schema, indent=2),
        steering=steering,
        data_json=json.dumps(data, indent=2),
    )
    from strands_tools.calculator import calculator
    agent = Agent(model=make_model(model), system_prompt=system_prompt, tools=[calculator])
    result = agent("Validate this data. Use the calculator tool to verify all arithmetic.",
                   structured_output_model=CritiqueResult)
    critique = result.structured_output

    verdict = "accepted" if critique.score >= threshold else "rejected"

    print(f"\n--- Data Critique ({model}) ---")
    print(f"  Score:   {critique.score}/10 → {verdict}")
    print(f"  Summary: {critique.summary}")
    for issue in critique.issues:
        print(f"  [{issue.severity}] ({issue.category}) {issue.description}")
    print("--- End Data Critique ---\n")

    return {
        "score": critique.score,
        "verdict": verdict,
        "issues": [issue.model_dump() for issue in critique.issues],
        "summary": critique.summary,
    }

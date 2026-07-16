"""Data stage — generate the document's structured data, then critique it.

Pairs:
- ``build_generator(ctx)`` — an Agent that invents schema-conforming JSON and
  saves it to ``ctx.data_json_path``.
- ``build_critic()`` — a FunctionNode that (1) checks the file exists, (2) runs
  deterministic JSON-Schema validation, and only then (3) asks an LLM to judge
  domain realism/arithmetic. It returns a structured ``Verdict``.

The deterministic guard (existence + JSON-Schema validation) runs in code, not
the LLM: it is exact, free, and faster. The LLM only judges what code cannot.
"""
from __future__ import annotations

import json

import jsonschema
from strands import Agent

from seed_data import prompts
from seed_data.utils import make_model
from seed_data.tools import save_json_file, random_roll
from seed_data.stages.base import (
    StageContext, Verdict, CritiqueIssue, FunctionNode,
)

GENERATOR_NAME = "data_generator"
CRITIC_NAME = "data_critic"


def build_generator(ctx: StageContext) -> Agent:
    """Build the data-generator agent for this document."""
    from strands_tools.calculator import calculator

    system_prompt = prompts.render(
        "data_generator",
        schema_json=json.dumps(ctx.schema_dict, indent=2),
        steering=ctx.steering,
        extra=ctx.extra,
        data_json_path=ctx.data_json_path,
    )
    return Agent(
        name=GENERATOR_NAME,
        model=make_model(ctx.models.data, thinking_budget=4096, role="data", session=ctx.session),
        system_prompt=system_prompt,
        tools=[save_json_file, calculator, random_roll],
    )


def _schema_errors(schema: dict, data: dict) -> list[CritiqueIssue]:
    """Deterministic JSON-Schema validation — exact, free, no LLM."""
    issues = []
    for e in jsonschema.Draft7Validator(schema).iter_errors(data):
        path = ".".join(str(p) for p in e.absolute_path) or "(root)"
        issues.append(CritiqueIssue(
            category="schema", severity="critical",
            description=f"{path}: {e.message}",
        ))
    return issues


def critique(ctx: StageContext) -> Verdict:
    """Guard (existence + schema) → LLM judgment → structured Verdict."""
    import os

    if not os.path.exists(ctx.data_json_path):
        return Verdict(
            accepted=False, score=0,
            summary="Data was not saved to disk.",
            feedback=f"Data file not found at {ctx.data_json_path}. "
                     "You must call save_json_file to save the JSON data.",
            issues=[CritiqueIssue(
                category="completeness", severity="critical",
                description=f"Data file not found at {ctx.data_json_path}.",
            )],
        )

    with open(ctx.data_json_path) as f:
        data = json.load(f)

    # Deterministic gate: fail fast on structural errors before spending tokens.
    schema_issues = _schema_errors(ctx.schema_dict, data)
    if schema_issues:
        print(f"\n--- Data Critic: Schema validation failed ({len(schema_issues)} error(s)) ---")
        for issue in schema_issues:
            print(f"  {issue.description}")
        return Verdict(
            accepted=False, score=0,
            summary=f"{len(schema_issues)} JSON Schema validation error(s) — fix before LLM critique.",
            feedback="\n".join(f"- [{i.severity}] {i.description}" for i in schema_issues),
            issues=schema_issues,
        )

    # LLM judgment: domain realism + arithmetic (with a calculator tool).
    from strands_tools.calculator import calculator

    system_prompt = prompts.render(
        "data_critic",
        schema_json=json.dumps(ctx.schema_dict, indent=2),
        steering=ctx.steering,
        data_json=json.dumps(data, indent=2),
    )
    agent = Agent(
        model=make_model(ctx.models.critic, session=ctx.session),
        system_prompt=system_prompt,
        tools=[calculator],
    )
    result = agent(
        "Validate this data. Use the calculator tool to verify all arithmetic.",
        structured_output_model=_LLMDataCritique,
    )
    llm: _LLMDataCritique = result.structured_output

    verdict = Verdict(
        accepted=llm.score >= ctx.threshold,
        score=llm.score,
        summary=llm.summary,
        feedback=_format_feedback(llm),
        issues=llm.issues,
    )

    print(f"\n--- Data Critique ({ctx.models.critic}) ---")
    print(f"  Score:   {verdict.score}/10 → {'accepted' if verdict.accepted else 'rejected'}")
    print(f"  Summary: {verdict.summary}")
    for issue in verdict.issues:
        print(f"  [{issue.severity}] ({issue.category}) {issue.description}")
    print("--- End Data Critique ---\n")

    return verdict


def _format_feedback(llm: "_LLMDataCritique") -> str:
    lines = [llm.summary]
    for i in llm.issues:
        hint = f" FIX: {i.fix_hint}" if i.fix_hint else ""
        lines.append(f"- [{i.severity}] ({i.category}) {i.description}{hint}")
    return "\n".join(lines)


def build_critic(ctx: StageContext) -> FunctionNode:
    """Build the data-critic graph node (guard + LLM judgment → Verdict)."""
    def _run(task_text: str, ctx: StageContext) -> str:
        return critique(ctx).as_node_text()

    return FunctionNode(func=_run, name=CRITIC_NAME, ctx=ctx)


# --- LLM-facing structured output (what the judge model fills in) -----------
# Kept separate from Verdict: this is the raw model output; Verdict is our
# control-flow object derived from it (accepted = score >= threshold).
from pydantic import BaseModel, Field  # noqa: E402


class _LLMDataCritique(BaseModel):
    """Structured output the data-critic model returns."""
    score: int = Field(description="Quality score 1-10", ge=1, le=10)
    issues: list[CritiqueIssue] = Field(default_factory=list, description="Issues found")
    summary: str = Field(description="One sentence overall assessment")

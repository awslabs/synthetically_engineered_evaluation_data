"""Augment stage — apply document aging/degradation, then critique legibility.

Pairs the augmentor agent (which picks an augraphy config and calls the
``apply_augmentation`` tool) with a critic that first relocates the tool's output
into the ``augmented/`` directory (deterministic file plumbing) and then judges
legibility with a vision model, returning a structured ``Verdict``.

Named ``augment_stage`` (not ``augment``) to avoid colliding with the top-level
``seed_data.augment`` module.
"""
from __future__ import annotations

import os
import shutil

from strands import Agent
from strands.multiagent import GraphBuilder

from seed_data import prompts
from seed_data.utils import make_model
from seed_data.stages.base import (
    StageContext, Verdict, CritiqueIssue, FunctionNode, rejected,
)

AUGMENTOR_NAME = "augmentor"
CRITIC_NAME = "aug_critic"
GATEWAY_NAME = "aug_gateway"


def _aug_output_path(ctx: StageContext) -> str:
    """Final resting path for the augmented PDF (in augmented/)."""
    doc_id = os.path.splitext(os.path.basename(ctx.output_path))[0]
    return os.path.join(ctx.output_dir, "augmented", f"{doc_id}_augmented.pdf")


def _tool_output_path(ctx: StageContext) -> str:
    """Where apply_augmentation writes by default (next to the clean PDF)."""
    return os.path.splitext(ctx.output_path)[0] + "_augmented.pdf"


def build_augmentor(ctx: StageContext) -> Agent:
    """Build the augmentor agent."""
    from seed_data.augment import apply_augmentation

    system_prompt = prompts.render(
        "augmentor", pdf_path=ctx.output_path, steering=ctx.steering, extra=ctx.extra,
    )
    return Agent(
        name=AUGMENTOR_NAME,
        model=make_model(ctx.models.aug, session=ctx.session),
        system_prompt=system_prompt,
        tools=[apply_augmentation],
    )


def build_gateway(ctx: StageContext) -> FunctionNode:
    """Rewrite the incoming task into an augmentation instruction."""
    def _run(task_text: str, ctx: StageContext) -> str:
        return (
            f"Apply realistic document aging/degradation effects to the PDF at: {ctx.output_path}\n"
            f'Call apply_augmentation with pdf_path="{ctx.output_path}" and your chosen config.'
        )
    return FunctionNode(func=_run, name=GATEWAY_NAME, ctx=ctx)


def build_critic(ctx: StageContext) -> FunctionNode:
    """Build the aug-critic node: relocate output (guard) → judge → Verdict."""
    def _run(task_text: str, ctx: StageContext) -> str:
        aug_path = _aug_output_path(ctx)
        tool_path = _tool_output_path(ctx)
        os.makedirs(os.path.dirname(aug_path), exist_ok=True)

        # Deterministic plumbing: move augmented PDF + config to final dirs.
        if os.path.exists(tool_path) and tool_path != aug_path:
            shutil.move(tool_path, aug_path)
        tool_config = tool_path.replace("_augmented.pdf", "_aug_config.json")
        if os.path.exists(tool_config):
            config_dir = os.path.join(ctx.output_dir, "config")
            os.makedirs(config_dir, exist_ok=True)
            doc_id = os.path.splitext(os.path.basename(ctx.output_path))[0]
            shutil.move(tool_config, os.path.join(config_dir, f"{doc_id}_aug_config.json"))

        if not os.path.exists(aug_path):
            return Verdict(
                accepted=False, score=0,
                summary="Augmented PDF was not generated.",
                feedback="Augmented PDF not found — re-run apply_augmentation.",
                issues=[CritiqueIssue(category="completeness", severity="critical",
                                      description="Augmented PDF not found")],
            ).as_node_text()

        from seed_data.augment import critique_augmented_document
        result = critique_augmented_document(
            pdf_path=aug_path, model=ctx.models.critic, threshold=ctx.threshold,
            session=ctx.session,
        )
        return Verdict(
            accepted=result["verdict"] == "accepted",
            score=int(result.get("score", 0)),
            summary=result.get("summary", ""),
            feedback=result.get("summary", ""),
            issues=[CritiqueIssue(**i) for i in result.get("issues", [])],
        ).as_node_text()

    return FunctionNode(func=_run, name=CRITIC_NAME, ctx=ctx)


def add_to_graph(builder: GraphBuilder, ctx: StageContext, after_node: str) -> None:
    """Wire the augment stage (gateway → augmentor → critic, loop on reject)
    into an existing outer-graph builder, downstream of ``after_node``."""
    builder.add_node(build_gateway(ctx), GATEWAY_NAME)
    builder.add_node(build_augmentor(ctx), AUGMENTOR_NAME)
    builder.add_node(build_critic(ctx), CRITIC_NAME)
    builder.add_edge(after_node, GATEWAY_NAME)
    builder.add_edge(GATEWAY_NAME, AUGMENTOR_NAME)
    builder.add_edge(AUGMENTOR_NAME, CRITIC_NAME)
    builder.add_edge(CRITIC_NAME, AUGMENTOR_NAME, condition=rejected(CRITIC_NAME))

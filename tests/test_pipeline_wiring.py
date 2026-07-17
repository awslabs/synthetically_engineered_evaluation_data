"""Pipeline-graph wiring smoke tests — build every graph shape, no Bedrock.

These catch the class of bug that crashes at *graph-build time*, before any LLM
call — e.g. a stage node constructed with the wrong arguments. That is exactly
how the augment stage broke (``FunctionNode`` built without its required
``ctx``): ``build_pipeline_graph(ctx, augment=True)`` raised ``TypeError`` on
every run, but nothing exercised that path.

Building a graph instantiates every stage's nodes (agents + FunctionNodes) and
wires every edge, so a successful build proves the wiring is intact for that
configuration. No models are invoked — ``GraphBuilder.build()`` does not call
the agents; it only assembles the graph.
"""
import os

from seed_data.stages.base import StageContext, ModelConfig
from seed_data.stages.pipeline import build_context, build_pipeline_graph


def _ctx(tmp_path) -> StageContext:
    return StageContext(
        schema_dict={"title": "invoice", "type": "object"},
        output_path=os.path.join(tmp_path, "pdfs", "doc.pdf"),
        data_json_path=os.path.join(tmp_path, "data", "doc.json"),
        script_path=os.path.join(tmp_path, "scripts", "doc.html"),
        models=ModelConfig(),
        output_dir=str(tmp_path),
    )


# --- the default (no-augment) pipeline builds -------------------------------

def test_build_pipeline_graph_default(tmp_path):
    graph = build_pipeline_graph(_ctx(str(tmp_path)))
    # data_generator, data_critic, doc_loop
    node_ids = set(graph.nodes)
    assert {"data_generator", "data_critic", "doc_loop"} <= node_ids


# --- the augment pipeline builds (regression guard for the ctx bug) ---------

def test_build_pipeline_graph_with_augment(tmp_path):
    """Regression: build_critic once omitted the required ctx, so this raised
    TypeError at build time for every augment run. Must build cleanly."""
    graph = build_pipeline_graph(_ctx(str(tmp_path)), augment=True)
    node_ids = set(graph.nodes)
    # augment adds gateway → augmentor → aug_critic downstream of doc_loop
    assert {"aug_gateway", "augmentor", "aug_critic"} <= node_ids


# --- build_context assembles a valid ctx from a resolved schema -------------

def test_build_context_from_resolved(tmp_path):
    ctx = build_context(
        resolved=({"title": "invoice", "type": "object"}, "steering text", []),
        output_dir=str(tmp_path),
    )
    assert ctx.doctype == "invoice"
    assert ctx.schema_dict["title"] == "invoice"
    # a graph builds from a real build_context, in both modes
    build_pipeline_graph(ctx)
    build_pipeline_graph(ctx, augment=True)

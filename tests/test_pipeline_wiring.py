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


def test_failed_result_names_the_halting_critic():
    """A terminal critic verdict must reach `GeneratedDoc.error`.

    A critic that could not judge sets `retryable=False`, halting the graph before
    the doc stage. `error` was a bare "PDF was not created", which is true but hides
    the only record of the real cause — the critic's own summary.
    """
    import os
    from seed_data.stages import pipeline as pipe
    from seed_data.stages import data as data_stage
    from seed_data.stages.base import StageContext, ModelConfig, Verdict

    refusal = Verdict(
        accepted=False, score=0, retryable=False,
        summary="The critic model returned no structured verdict.",
    )

    class _NodeResult:
        def get_agent_results(self):
            return [refusal.as_node_text()]

    class _Result:
        results = {data_stage.CRITIC_NAME: _NodeResult()}
        execution_order: list = []

    ctx = StageContext(
        schema_dict={"title": "widget"},
        output_path=os.path.join("/nonexistent", "doc.pdf"),
        data_json_path=os.path.join("/nonexistent", "doc.json"),
        script_path=os.path.join("/nonexistent", "doc.html"),
        models=ModelConfig(),
    )

    doc = pipe.result_from(ctx, _Result())
    assert doc.success is False
    assert "PDF was not created" in doc.error
    assert "no structured verdict" in doc.error


def test_failed_result_reads_the_doc_verdict_from_doc_loop():
    """The doc-stage verdict must be looked up under "doc_loop", not "doc_critic".

    `doc_critic` is a node of the *nested* loop graph, so it is never a key of the
    top-level result. Looking it up here always missed and fell through to the data
    critic's accepted verdict, which then failed the `not accepted` test — so a
    doc-stage halt reported a bare "PDF was not created" with no cause.
    """
    import os
    from seed_data.stages import pipeline as pipe
    from seed_data.stages import data as data_stage
    from seed_data.stages.base import StageContext, ModelConfig, Verdict

    def _node(verdict):
        class _NodeResult:
            def get_agent_results(self):
                return [verdict.as_node_text()]
        return _NodeResult()

    class _Result:
        # Exactly the top-level shape Strands produces: the nested loop appears as
        # "doc_loop" and `doc_critic` is nowhere to be found.
        results = {
            data_stage.CRITIC_NAME: _node(Verdict(accepted=True, score=8, summary="data ok")),
            "doc_loop": _node(Verdict(
                accepted=False, retryable=False, score=0,
                summary="The doc critic returned no structured verdict.",
            )),
        }
        execution_order: list = []

    ctx = StageContext(
        schema_dict={"title": "widget"},
        output_path=os.path.join("/nonexistent", "doc.pdf"),
        data_json_path=os.path.join("/nonexistent", "doc.json"),
        script_path=os.path.join("/nonexistent", "doc.html"),
        models=ModelConfig(),
    )

    doc = pipe.result_from(ctx, _Result())
    assert "doc critic returned no structured verdict" in doc.error
    # And it must not have reported the accepted data verdict instead.
    assert "data ok" not in doc.error


def test_collect_tokens_does_not_double_count_nested_graphs():
    """`get_agent_results()` already flattens sub-graphs, so also recursing doubled.

    Regression from main, which used an exclusive if/elif: a 500-token run reported
    800 once a nested loop graph was involved.
    """
    from seed_data.stages import pipeline as pipe

    class _Metrics:
        def __init__(self, n):
            self.accumulated_usage = {"inputTokens": n, "outputTokens": n}

    class _Agent:
        def __init__(self, n):
            self.metrics = _Metrics(n)

    class _Leaf:
        """A node result holding agents directly (no sub-graph)."""
        def __init__(self, *agents):
            self._agents = agents
        def get_agent_results(self):
            return list(self._agents)

    class _Nested:
        """A node result whose `.result` is itself a graph result."""
        def __init__(self, inner):
            self.result = inner
        def get_agent_results(self):
            # Strands flattens nested agents here too — this is the double-count trap.
            return [a for nr in inner_results(self.result) for a in nr.get_agent_results()]

    def inner_results(res):
        return list(res.results.values())

    class _Graph:
        def __init__(self, results):
            self.results = results
            self.execution_order: list = []

    inner = _Graph({"doc_generator": _Leaf(_Agent(100)), "doc_critic": _Leaf(_Agent(150))})
    outer = _Graph({"data_generator": _Leaf(_Agent(50)), "doc_loop": _Nested(inner)})

    usage = pipe._collect_tokens(outer)
    # 50 + 100 + 150 = 300 per direction; double-counting the nested pair gave 550.
    assert usage["inputTokens"] == 300, usage
    assert usage["outputTokens"] == 300, usage
    assert usage["totalTokens"] == 600, usage


def test_a_raise_after_rendering_does_not_discard_the_pdf(tmp_path):
    """The except path returned `success=False, pdf_path=None` unconditionally.

    The graph can render and accept a PDF and then fail in a later node (augment,
    say); discarding it threw away finished, paid-for work sitting on disk.
    """
    from unittest.mock import patch
    from seed_data.stages import pipeline as pipe

    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    (pdf_dir / "doc.pdf").write_bytes(b"%PDF-1.4 rendered")

    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "schema.json").write_text('{"title": "widget", "type": "object", "properties": {}}')

    def boom(*a, **k):
        raise RuntimeError("augment node exploded")

    with patch.object(pipe, "build_pipeline_graph", lambda *a, **k: boom), \
         patch.object(pipe, "build_context") as mk_ctx:
        from seed_data.stages.base import StageContext, ModelConfig
        mk_ctx.return_value = StageContext(
            schema_dict={"title": "widget"},
            output_path=str(pdf_dir / "doc.pdf"),
            data_json_path=str(tmp_path / "doc.json"),
            script_path=str(tmp_path / "doc.html"),
            models=ModelConfig(), output_dir=str(tmp_path),
        )
        doc = pipe.generate(schema_dir=str(schema_dir), verbose=False)

    # The finished PDF must still be reported so the work is discoverable...
    assert doc.pdf_path == str(pdf_dir / "doc.pdf"), "the rendered PDF must be reported"
    # ...but the run did not complete, and `success=True` here was itself a defect:
    # every CLI success branch prints the paths without ever printing `error` and
    # exits 0, so a crashed run was reported as a clean one. (This assertion
    # previously read `is True` — the test encoded the bug.)
    assert doc.success is False
    assert doc.verdict == "error"
    assert "augment node exploded" in (doc.error or "")

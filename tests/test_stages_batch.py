"""Tests for seed_data.stages.batch — the concurrent pipeline-graph fan-out.

LLM-free: the scenario planner and the pipeline-graph builder are stubbed, so we
verify the fan-out graph shape (one worker per scenario), that the batch pairs a
GeneratedDoc back to each scenario's context, and that plan_scenarios always
returns exactly `count` items — without any Bedrock calls.
"""
import os

import pytest

from seed_data.stages import batch as batch_mod
from seed_data.stages.base import StageContext, ModelConfig


def _ctx(tmp_path, i) -> StageContext:
    return StageContext(
        schema_dict={"title": "widget"},
        output_path=os.path.join(tmp_path, f"doc{i}.pdf"),
        data_json_path=os.path.join(tmp_path, f"doc{i}.json"),
        script_path=os.path.join(tmp_path, f"doc{i}.html"),
        models=ModelConfig(),
    )


def test_build_batch_graph_one_worker_per_context(tmp_path):
    contexts = [_ctx(str(tmp_path), i) for i in range(3)]
    graph, worker_names = batch_mod.build_batch_graph(contexts, timeout=60)
    assert worker_names == ["worker_0", "worker_1", "worker_2"]
    # coordinator + 3 workers = 4 nodes
    assert len(graph.nodes) == 4


def test_generate_batch_pairs_doc_per_scenario(tmp_path, monkeypatch):
    # Stub the planner (no LLM) to return N scenarios.
    monkeypatch.setattr(
        batch_mod, "plan_scenarios",
        lambda count, brief, model="sonnet", session=None: [f"scenario-{i}" for i in range(count)],
    )
    # Stub build_context (no schema-dir needed) so each worker gets a fake ctx.
    def fake_build_context(*, extra, output_dir, **kw):  # absorbs session/etc.
        i = extra.split("-")[-1]
        return _ctx(str(tmp_path), i)
    monkeypatch.setattr(batch_mod, "build_context", fake_build_context)

    # Stub the fan-out run: write a fake PDF per context (so result_from reports
    # success) and return a result whose worker nodes carry empty sub-results.
    def fake_build_batch_graph(contexts, **kw):
        for ctx in contexts:
            os.makedirs(os.path.dirname(ctx.output_path), exist_ok=True)
            with open(ctx.output_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")
        worker_names = [f"worker_{i}" for i in range(len(contexts))]

        class _EmptyNodeResult:
            class result:  # a MultiAgentResult-like object with no node results
                results: dict = {}
                execution_order: list = []

        class _Graph:
            def __call__(self, task):
                class _Res:
                    results = {n: _EmptyNodeResult() for n in worker_names}
                    execution_order = []
                return _Res()
        return _Graph(), worker_names

    monkeypatch.setattr(batch_mod, "build_batch_graph", fake_build_batch_graph)

    docs = batch_mod.generate_batch(
        schema_dir=str(tmp_path), count=3, brief="b",
        output_dir=str(tmp_path / "out"), verbose=False,
    )
    assert len(docs) == 3
    assert all(d.success for d in docs)  # PDFs exist → success
    assert len({d.doc_id for d in docs}) == 3  # distinct docs, own paths


def test_on_document_callback_fires_per_doc(tmp_path, monkeypatch):
    monkeypatch.setattr(
        batch_mod, "plan_scenarios",
        lambda count, brief, model="sonnet", session=None: [f"scenario-{i}" for i in range(count)],
    )
    monkeypatch.setattr(
        batch_mod, "build_context",
        lambda *, extra, output_dir, **kw: _ctx(str(tmp_path), extra.split("-")[-1]),
    )

    def fake_build_batch_graph(contexts, **kw):
        for ctx in contexts:
            os.makedirs(os.path.dirname(ctx.output_path), exist_ok=True)
            open(ctx.output_path, "wb").write(b"%PDF-1.4 fake")

        class _G:
            def __call__(self, task):
                class _R:
                    results = {}
                    execution_order = []
                return _R()
        return _G(), [f"worker_{i}" for i in range(len(contexts))]

    monkeypatch.setattr(batch_mod, "build_batch_graph", fake_build_batch_graph)

    seen = []
    batch_mod.generate_batch(
        schema_dir=str(tmp_path), count=3, brief="b",
        output_dir=str(tmp_path / "out"), verbose=False,
        on_document=lambda i, total, doc: seen.append((i, total, doc.success)),
    )
    assert seen == [(0, 3, True), (1, 3, True), (2, 3, True)]


def test_seeded_brief_appends_only_with_seed():
    assert batch_mod._seeded_brief("hello", None) == "hello"
    seeded = batch_mod._seeded_brief("hello", 42)
    assert "hello" in seeded and "42" in seeded


def test_plan_scenarios_pads_and_truncates(monkeypatch):
    class _Result:
        class structured_output:
            scenarios = ["only-one"]

    class _FakeAgent:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Result()

    monkeypatch.setattr(batch_mod, "Agent", _FakeAgent)
    monkeypatch.setattr(batch_mod, "make_model", lambda *a, **k: None)

    assert len(batch_mod.plan_scenarios(count=3, brief="b")) == 3

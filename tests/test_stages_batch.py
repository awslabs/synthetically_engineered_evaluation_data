"""Tests for seed_data.stages.batch — the concurrent pipeline-graph fan-out.

LLM-free: the scenario planner and the pipeline-graph builder are stubbed, so we
verify the fan-out graph shape (one worker per scenario), that the batch pairs a
GeneratedDoc back to each scenario's context, and that plan_scenarios always
returns exactly `count` items — without any Bedrock calls.
"""
import os


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
        lambda count, brief, **kw: [f"scenario-{i}" for i in range(count)],
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
        lambda count, brief, **kw: [f"scenario-{i}" for i in range(count)],
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


def _stub_planner(monkeypatch, structured_output):
    """Point plan_scenarios at a fake agent returning `structured_output`."""
    class _Result:
        pass
    _Result.structured_output = structured_output

    class _FakeAgent:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k):
            _FakeAgent.last_prompt = a[0] if a else ""
            return _Result()

    monkeypatch.setattr(batch_mod, "Agent", _FakeAgent)
    monkeypatch.setattr(batch_mod, "make_model", lambda *a, **k: None)
    return _FakeAgent


def test_plan_scenarios_falls_back_to_brief_on_refusal(monkeypatch):
    """A guardrail refusal yields `count` copies of the brief, not an AttributeError.

    `structured_output` is None when the model refuses. Unguarded, `.scenarios` raised
    `AttributeError: 'NoneType' object has no attribute 'scenarios'` and took down the
    whole batch before any document was generated.
    """
    _stub_planner(monkeypatch, None)
    assert batch_mod.plan_scenarios(count=3, brief="a widget invoice") == ["a widget invoice"] * 3


def test_plan_scenarios_padding_excludes_the_seed_instruction(monkeypatch):
    """The seed must reach the planner prompt but never the padded scenarios.

    The caller used to pre-seed the brief, so a refusal under `--seed 42` wrote
    "[Deterministic seed: 42 ...]" into every document's `ctx.extra`, which the data
    generator reads as content guidance.
    """
    agent = _stub_planner(monkeypatch, None)

    scenarios = batch_mod.plan_scenarios(count=2, brief="a widget invoice", seed=42)

    assert scenarios == ["a widget invoice"] * 2
    for s in scenarios:
        assert "seed" not in s.lower(), f"seed instruction leaked into a scenario: {s!r}"
    # ...but the planner itself was still told about the seed.
    assert "42" in agent.last_prompt


def test_plan_scenarios_fallback_is_silent_when_not_verbose(monkeypatch, capsys):
    """`--quiet` must suppress the fallback notice; the warning still logs."""
    _stub_planner(monkeypatch, None)

    batch_mod.plan_scenarios(count=2, brief="b", verbose=False)
    assert capsys.readouterr().out == ""

    batch_mod.plan_scenarios(count=2, brief="b", verbose=True)
    assert "padding" in capsys.readouterr().out.lower()


def test_plan_scenarios_fallback_warns_for_programmatic_callers(monkeypatch, caplog):
    """The degradation must be detectable without reading stdout.

    `BatchResult` reports N/N succeeded either way, so a caller that only inspects
    the results cannot tell the documents collapsed to one unvaried brief.
    """
    import logging

    _stub_planner(monkeypatch, None)
    with caplog.at_level(logging.WARNING, logger=batch_mod.logger.name):
        batch_mod.plan_scenarios(count=3, brief="b", verbose=False)

    assert any(r.levelno == logging.WARNING and "padding" in r.getMessage().lower()
               for r in caplog.records)


def test_plan_scenarios_short_response_also_warns(monkeypatch, caplog):
    """A short response is the same degradation as a refusal, partially."""
    import logging

    class _Plan:
        scenarios = ["only-one"]

    _stub_planner(monkeypatch, _Plan())
    with caplog.at_level(logging.WARNING, logger=batch_mod.logger.name):
        out = batch_mod.plan_scenarios(count=3, brief="b", verbose=False)

    assert out == ["only-one", "b", "b"]
    assert any("1 of 3" in r.getMessage() for r in caplog.records)

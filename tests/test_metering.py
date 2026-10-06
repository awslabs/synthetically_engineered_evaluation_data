"""Tests for seed_data.metering — token usage from every model call.

A fake Strands-style model (async ``stream`` yielding a ``metadata`` usage event)
stands in for BedrockModel, so binding, nesting, threading and the structured
facade's ``token_usage`` are checked without Bedrock.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from seed_data.metering import current_meter, metered, submit_in_context, token_meter


class _FakeModel:
    def __init__(self, usage=None, **kwargs):
        self._usage = usage or {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120}

    async def stream(self, *args, **kwargs):
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockDelta": {"delta": {"text": "hi"}}}
        yield {"metadata": {"usage": self._usage, "metrics": {"latencyMs": 5}}}


Metered = metered(_FakeModel)


def _call(model):
    async def drain():
        return [e async for e in model.stream([])]
    return asyncio.run(drain())


def test_usage_is_recorded_and_events_pass_through():
    with token_meter() as meter:
        model = Metered()
        events = _call(model)
        _call(model)
    assert len(events) == 3 and events[-1]["metadata"]["metrics"] == {"latencyMs": 5}
    assert meter.usage == {"inputTokens": 200, "outputTokens": 40, "totalTokens": 240}
    assert meter.calls == 2


def test_meter_binds_at_model_creation_not_at_call_time():
    with token_meter() as meter:
        model = Metered()
    _call(model)                       # called after the block: still this run's spend
    assert meter.usage["totalTokens"] == 120

    unmetered = Metered()              # built outside any meter: counts nowhere
    with token_meter() as other:
        _call(unmetered)
    assert other.usage["totalTokens"] == 0


def test_concurrent_runs_do_not_count_into_each_other():
    def run(usage):
        with token_meter() as meter:
            model = Metered(usage={"inputTokens": usage, "outputTokens": 0})
            for _ in range(5):
                _call(model)
        return meter.usage["totalTokens"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(run, 10), pool.submit(run, 1000)
        assert (a.result(), b.result()) == (50, 5000)


def test_nested_meters_roll_up():
    with token_meter() as outer:
        _call(Metered())
        with token_meter() as inner:
            _call(Metered())
    assert inner.usage["totalTokens"] == 120
    assert outer.usage["totalTokens"] == 240


def test_submit_in_context_carries_the_meter_into_pool_workers():
    def build_and_call():
        _call(Metered())                # model created inside the worker thread
        return current_meter()

    with token_meter() as meter, ThreadPoolExecutor(max_workers=2) as pool:
        plain = pool.submit(build_and_call).result()
        carried = [submit_in_context(pool, build_and_call).result() for _ in range(2)]
    assert plain is None                # a bare submit loses the context ...
    assert all(m is meter for m in carried)
    assert meter.usage["totalTokens"] == 240   # ... so only the carried calls count


def test_make_model_returns_a_metered_bedrock_model():
    from strands.models import BedrockModel
    from seed_data.utils import make_model

    with token_meter() as meter:
        model = make_model("haiku")
    assert isinstance(model, BedrockModel)
    assert model._seed_meter is meter


def test_structured_result_reports_token_usage(monkeypatch, tmp_path):
    pytest.importorskip("pandas", reason="requires the [structured] optional dependencies")
    import json
    import types

    import seed_data.structured.pipeline as pipeline_mod
    from seed_data.structured import run_structured

    out = tmp_path / "customer.csv"
    out.write_text("id\n1\n")

    def fake_pipeline(schema, **kw):
        # Stands in for the graph + fill agents: each model call reports usage.
        current_meter().add({"inputTokens": 700, "outputTokens": 300})
        current_meter().add({"inputTokens": 50, "outputTokens": 10})
        ps = types.SimpleNamespace(
            export_json=json.dumps({"files": [str(out)], "record_counts": {"Customer": 1}}),
            evaluation_scores={}, evaluation_issues=[],
        )
        return None, ps

    monkeypatch.setattr(pipeline_mod, "run_graph_pipeline", fake_pipeline)
    from seed_data.schema.models import InferredSchema
    schema = InferredSchema.model_validate({"entities": [{"entity_name": "Customer", "fields": []}]})
    result = run_structured(schema, output_dir=str(tmp_path), verbose=False)
    assert result.success
    assert result.token_usage == {"inputTokens": 750, "outputTokens": 310, "totalTokens": 1060}


def test_token_meter_is_exported():
    import seed_data
    assert seed_data.token_meter is token_meter

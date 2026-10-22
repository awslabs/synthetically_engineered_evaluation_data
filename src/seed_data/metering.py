"""Token metering for every model call SEED makes.

Per-document results already carry ``token_usage`` (summed from the pipeline
graph), but much of SEED calls models outside any graph: schema planning, the
structured pipeline's distribution/sample/fill agents, scenario planning. Those
calls were invisible, so ``StructuredResult.token_usage`` was always zero and a
host enforcing a budget could not see what a plan or a table run cost.

Usage is recorded at the model, so nothing escapes::

    from seed_data import token_meter

    with token_meter() as meter:
        schema = gen.plan("Customers and their orders")
    meter.usage   # {"inputTokens": ..., "outputTokens": ..., "totalTokens": ...}

Every model built by :func:`seed_data.utils.make_model` binds the meter that is
active *when the model is created* and adds each call's Bedrock ``usage`` to it
(both the streaming and non-streaming paths end in a ``metadata`` event). Binding
at creation, rather than looking the meter up per call, keeps counting right when
the call later runs on another thread, and keeps two concurrent runs in one
process from counting into each other. Meters nest: usage recorded in an inner
meter also reaches the enclosing ones.

Thread pools that create models in their workers must carry the context across
— use :func:`submit_in_context` instead of ``pool.submit``. ``asyncio.to_thread``
and Strands' own threads already copy it.
"""
from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from typing import Iterator

_current: contextvars.ContextVar["TokenMeter | None"] = contextvars.ContextVar(
    "seed_token_meter", default=None,
)


class TokenMeter:
    """Thread-safe running total of Bedrock token usage."""

    def __init__(self, parent: "TokenMeter | None" = None):
        self._parent = parent
        self._lock = threading.Lock()
        self._input = 0
        self._output = 0
        self.calls = 0

    def add(self, usage: dict | None) -> None:
        if not usage:
            return
        with self._lock:
            self._input += int(usage.get("inputTokens", 0) or 0)
            self._output += int(usage.get("outputTokens", 0) or 0)
            self.calls += 1
        if self._parent is not None:
            self._parent.add(usage)

    @property
    def usage(self) -> dict:
        with self._lock:
            return {"inputTokens": self._input, "outputTokens": self._output,
                    "totalTokens": self._input + self._output}


@contextmanager
def token_meter() -> Iterator[TokenMeter]:
    """Meter every model created inside the ``with`` block."""
    meter = TokenMeter(parent=_current.get())
    token = _current.set(meter)
    try:
        yield meter
    finally:
        _current.reset(token)


def current_meter() -> TokenMeter | None:
    return _current.get()


def submit_in_context(pool, fn, *args, **kwargs):
    """``pool.submit`` that runs ``fn`` in a copy of the caller's context.

    A fresh copy per task: one ``Context`` cannot be entered by two threads at once.
    """
    return pool.submit(contextvars.copy_context().run, fn, *args, **kwargs)


def metered(model_cls):
    """Subclass a Strands model class so its calls report usage to a bound meter."""

    class Metered(model_cls):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._seed_meter = _current.get()

        async def stream(self, *args, **kwargs):
            async for event in super().stream(*args, **kwargs):
                if self._seed_meter is not None and isinstance(event, dict):
                    meta = event.get("metadata")
                    if isinstance(meta, dict):
                        self._seed_meter.add(meta.get("usage"))
                yield event

    Metered.__name__ = f"Metered{model_cls.__name__}"
    Metered.__qualname__ = Metered.__name__
    return Metered

"""Ingest subsystem — turn any input into a unified :class:`InferredSchema`.

Internal engine. The supported public surface is ``Generator.ingest`` (see
:mod:`seed_data.api`); ``run_ingest`` here is called by that facade verb.
"""

from seed_data.ingest.detect import InputType, detect_input_type
from seed_data.ingest.pipeline import run_ingest

__all__ = ["run_ingest", "detect_input_type", "InputType"]

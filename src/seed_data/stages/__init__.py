"""Pipeline stages — one module per generate+critique pair.

Each stage module pairs a generator (an LLM `Agent`) with its critic (a
deterministic guard + an LLM judgment), sharing a single `StageContext`. Stages
are wired into the orchestration graph by `seed_data.orchestrate`.
"""

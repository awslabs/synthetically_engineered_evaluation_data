# PR #15 Review Response Plan

**PR:** [#15 — SEED unification (M1–M5)](https://github.com/awslabs/synthetically_engineered_evaluation_data/pull/15)
**Reviewer:** @sromoam — `CHANGES_REQUESTED` (2026-08-05)
**PR head:** `hp/seed-unification` @ `d106cde`
**Local branch:** `hp/structured-hardening` @ `e025792` (one commit ahead, not yet pushed)

The review has two halves: five inline comments about **naming** (the part @sromoam
flagged as needing discussion) and a detailed Claude-assisted audit in a PR comment
listing **one must-fix bug, one should-fix, and a set of correctness gaps**.

Two of the audit's findings are already fixed by the unpushed `e025792` — see
[§0](#0-already-fixed-by-the-unpushed-commit). Everything else was re-verified as
still reproducing on current `HEAD` before being planned.

---

## 0. Already fixed by the unpushed commit

`e025792` ("Harden the structured path") landed locally after the PR was pushed and
independently covers two audit items. Pushing it resolves them with no new work.

| Audit item | Status on `e025792` | Evidence |
|---|---|---|
| Base-install UX doesn't match docs (README promises a clear `ImportError`, delivers a raw `ModuleNotFoundError`) | **Fixed** | New `common/deps.py` `require_structured()` raises a message naming the extra; wired into `api.py`, `__main__.py`, `evaluation/__init__.py`. Covered by `tests/test_deps_guard.py` (219 lines). |
| Pydantic `UserWarning: Field name "schema_json" ... shadows an attribute in parent "BaseModel"` | **Fixed** | Parameter renamed to `schema_input`. Verified: `python -W error::UserWarning -c "import seed_data.api"` imports clean. |

`e025792` also independently addresses the PR's own self-declared "known limitation"
(the row-count quality gate), which the audit endorsed as worth a follow-up. That
strengthens the response to §4 below.

**Action:** push `e025792` as the first step, then note in the reply that these three
were already in flight.

---

## 1. Naming — the discussion @sromoam asked for

Five inline comments, all on docs, all about framing. These need a **decision from the
user before any code moves**, because two of the three names are constrained by the
published PyPI package.

### 1a. `Generator` → something more descriptive

> "We might want to consider a slightly more descriptive name than 'Generator' since
> this may confuse with the concept of a generator in core python."

**Worth stating plainly in the reply: this name is not from the unification work.**
`class Generator` was introduced by @sromoam himself in `5fdd7c3` (2026-07-15,
"Refactor pipeline architecture into composable stages with typed API"), well before
this PR. `git blame` attributes the class line and its docstring — *"Configure once,
generate many. The main entry point for seed-data."* — to him. It then shipped in
**published v0.0.6**. So this is a question about the existing public API, not about
anything #15 renamed or introduced.

**The constraint that decides this:** `from seed_data import Generator` is the
documented entry point of the published package, and the PR's central promise is that
it keeps working. Renaming it outright breaks every existing user.

**Recommendation — decline the rename here, offer an alias.** Keep `Generator` as the
canonical name and, if @sromoam wants a clearer primary name, add a descriptive alias
(e.g. `SeedGenerator` or `DataGenerator`) pointing at the same class, with `Generator`
retained indefinitely as the documented compatible name. Cost is ~1 line plus a docs
note; a true rename costs a breaking major version.

Since it's his own naming under discussion, the call on whether to add an alias — or to
take the rename in a separate, deliberate breaking-change PR — is his to make. It
should not be bundled into #15 either way: renaming the published entry point is
exactly the kind of change that deserves its own PR rather than riding along in a
90-file unification.

The Python-builtin-confusion concern is real but weak in practice: the name is only
ever reached as `seed_data.Generator`, never bare, and `Generator` is a well-worn
class name in data tooling (e.g. Faker's `Generator`).

### 1b. `ingest` → `fit` or `plan`

> "I'm not in love with the function name 'ingest'. I think your function is really
> more of a 'fit' or a 'plan' than an 'ingest'."

**This one is genuinely open** — `Generator.ingest` is **new in this PR** (absent from
v0.0.6), so there is no compatibility constraint and renaming now costs nothing later.
This is the right moment to settle it.

Note the ownership split across these three comments: `Generator` (1a) is @sromoam's own
pre-existing name and is constrained by the published package, whereas `ingest` (1b),
`generate_structured`, and `run` (1c) are the verbs #15 adds. The two comments about
*new* names are the ones actually actionable in this PR.

The reviewer's read is defensible: the method infers structure *from* inputs and returns
a schema you can inspect and edit — closer to scikit-learn's `fit` (learn parameters
from data, store them) than to a data-loading "ingest".

Counter-consideration: `fit` implies the fitted state lives *on the object*
(`estimator.fit(X)` mutates `self`), whereas this returns an `InferredSchema` the caller
owns and the `Generator` stays stateless. `plan` avoids that mismatch and reads honestly
for "produce the schema we're going to generate from."

**Recommendation:** rename to **`plan`**, keeping `ingest` as a deprecated alias for one
minor version. `plan` fits the return-a-value shape, pairs naturally with the
`plan_and_generate` suggestion in 1c, and sidesteps `fit`'s state implication. Ask the
user to confirm `plan` vs `fit` before touching code — this is a taste call the repo
owners should make together.

### 1c. `run` → `fit_and_generate` / `plan_and_generate`

> "to match the pattern from other libraries like scikit-learn, maybe we could use
> 'fit_and_generate' or 'plan_and_generate' here instead of 'run'."

`Generator.run` is also **new in this PR** — no constraint. The sklearn analogy is apt:
`run` says nothing about what happens, while the method demonstrably does two things
(ingest, then generate).

**Recommendation:** rename to **`plan_and_generate`** to match whatever 1b resolves to.
Keep the pair consistent — `plan` / `plan_and_generate`, or `fit` / `fit_and_generate`.
Do **not** mix (`ingest` + `plan_and_generate` would be worse than either).

### 1d. Blast radius if the renames are approved

Mechanical but not trivial — worth knowing the size before agreeing:

| Surface | `Generator` | `ingest` |
|---|---|---|
| Code (`src/`, `tests/`) | 19 files | 68 occurrences |
| Docs (`docs/`, `README.md`) | 52 files | 367 occurrences |

The docs number dominates. Note that many `ingest` doc hits are the **CLI subcommand**
`seed-data ingest`, which is a separate naming decision from the Python method — the CLI
verb can stay `ingest` (it *is* a load-from-inputs command there) even if the method
becomes `plan`. **Flag this to the user:** renaming both in lockstep is more churn and
arguably less accurate.

### 1e. "Is there an open standard for this schema?"

> "In this schema...I'm wondering if there's an open standard we can use here; This isn't
> quite JSON schema specification is it? Might be worth investigating?"

**Answer: JSON Schema is already the interchange format; `InferredSchema` is
deliberately a superset.** `schema/io.py` ships both directions —
`from_json_schema()` and `to_json_schema()` — plus `from_schema_dir()`. So the repo
already reads and writes the standard.

`InferredSchema` carries things JSON Schema has no vocabulary for and that generation
requires: `DistributionSpec` (statistical shape per field), `RelationshipDefinition`
(FK cardinality across entities), `generation_guidance`, and `reference_samples`.
JSON Schema validates one document; this describes how to *synthesize a correlated
multi-entity dataset*.

**Recommendation:** no code change — this is a **documentation gap, not a design gap**.
Add a short "Relationship to JSON Schema" section to `docs/docs/Guides/ingest.md`
stating: JSON Schema in/out is supported via `schema/io.py`; the extra fields are
enumerated with why each can't be expressed in JSON Schema; and where custom extensions
use the `x-` convention (`x-probability` already does). Optionally note that
distribution metadata could later be aligned with an existing vocabulary if one emerges.
This turns a "did you consider the standard?" question into a documented answer.

---

## 2. Must fix — anchored regex patterns emit literal `^` and `$`

**Verified reproducing on `HEAD`:**

```
_generate_from_pattern('^[A-Z]{3}-[0-9]{4}$', 2, set())
  -> ['^YNL-6770$', '^ODF-2484$']      # matches own pattern: False
```

`_generate_from_pattern` (`src/seed_data/structured/generation.py:161`) walks the pattern
character by character and treats anything not `[` or `\` as a literal — so the anchors
become output characters. JSON Schema `pattern` values are conventionally anchored, so
this is the common case, not an edge case.

It compounds: `_correct_pattern` (`postprocessing/corrector.py:140`) calls the same
helper, so correcting a pattern violation produces another invalid value. Every record
burns correction budget and still fails re-validation.

**Fix:** strip a leading `^` and trailing `$` before segment parsing. Roughly one line
at the top of the function. Note the anchors are *semantically* correct to drop here —
the helper generates a whole value, so it's implicitly fullmatch.

**Tests:** anchored pattern produces self-matching values; anchored and unanchored forms
of the same pattern agree; `_correct_pattern` on an anchored field yields a value that
survives re-validation (this is the regression that proves the compounding is gone).

---

## 3. Should fix — unmapped character classes silently emit `-`

**Verified reproducing:**

```
_generate_from_pattern('[0-9A-F]{6}', 3, set()) -> ['009F99', '90---A', 'A--A9A']
_generate_from_pattern('[B-D]{4}',   3, set()) -> ['-B-B', 'B-DB', 'B-B-']
```

`_REGEX_CHAR_CLASSES` is an exact-string lookup table. A class not literally in the table
falls through to `chars = inner`, so `0-9A-F` is treated as the literal character set
`{0,-,9,A,F}` and `-` gets sampled as a value character. `[0-9A-F]` (hex) is common.

**Fix:** parse ranges properly — expand `X-Y` spans inside a class, handle a literal `-`
at the start/end position, and support a leading `^` negation or explicitly reject it.
~10 lines, and it makes the lookup table redundant (keep the table only if benchmarking
shows it matters; otherwise delete it, which removes a whole class of "class not in
table" bugs).

**Also in scope (lower severity, same function):** the uniqueness fallback at line ~227
cascades when the pattern space is exhausted. Verified:

```
_generate_from_pattern('[0-9]{1}', 14, set())[-4:]
  -> ['6_10', '6_10_11', '6_10_11_12', '6_10_11_12_13']
```

It suffixes the *previous* generated value, so values grow without bound and stop
matching the pattern. Fix: suffix a stable base (or the pattern's own prefix) with a
counter, and cap length; if the space is genuinely exhausted, log once and return what
exists rather than fabricating ever-longer strings.

**Tests:** hex and letter-range classes produce only in-class characters; a literal `-`
inside a class is still honored; exhausted space returns bounded, pattern-shaped values
without unbounded growth.

---

## 4. Correctness gaps — validator

All five verified reproducing on `HEAD`:

```
duplicate unique=True ids [1,1,1] -> 0 violations, 3/3 valid
3.7 in an integer field           -> 0 violations
'GARBAGE' in uuid field w/ pattern-> 0 violations
'ABC-1234-GARBAGE' vs [A-Z]{3}-[0-9]{4} -> 0 violations
```

| Gap | Fix | Notes |
|---|---|---|
| **`RecordValidator` never checks uniqueness** | Add a `unique=True` duplicate scan emitting `uniqueness_violation` (fixable — regenerate the value) | The audit's deeper point: `StructuralMetrics.uniqueness_violation_count` *does* count these, but its penalty caps at `min(n*0.05, 0.5)` weighted `0.2`, so worst-case uniqueness still scores `0.9` against a `0.7` threshold — **duplicate primary keys can never fail the gate**. Fixing the validator is what actually closes this, since violations feed the correct/filter path. |
| **`_check_type` accepts floats in integer fields** | Reject a non-integral value for `type == "integer"` (`float(v).is_integer()`) rather than relying on `int(v)` truncating | `int(3.7)` succeeding is why this passes today. |
| **`pattern` only enforced for `string`/`email`/`phone`/`enum`** (`validator.py:173`) | Enforce `pattern` whenever it is set, regardless of declared type | Currently inconsistent with `_needs_llm`, which deliberately routes `uuid`/`url` to the LLM — so those get a pattern that is never checked. |
| **`_check_constraints` uses `re.match`, not `re.fullmatch`** | Switch to `fullmatch` | `_samples_match_pattern` in `generation.py` already uses `fullmatch`; the two should agree. Do this **together with §2** — anchored patterns plus `fullmatch` interact, and fixing one without the other shifts which values pass. |
| **`_parse_json_lenient`'s suffix heuristic doesn't work** | Delete the suffix-repair branch, keep the plain-parse path | It appends `}` after stripping, over-closing: `'{"data": {"E": [1]}}]}'` → `None`. Harmless (callers handle `None`) but it is dead complexity presenting as a safety net. Low risk, real cleanup. |

**Sequencing note:** these change what the quality gate rejects, so expect existing
structured tests to shift. Fix the validator, then re-run the full suite and reconcile
— do not adjust assertions before seeing which ones legitimately move.

---

## 5. Minor items

| Item | Plan |
|---|---|
| `common/config.py` does `from seed_data import MODELS` while `seed_data/__init__.py` pulls the structured stack — circular-import-adjacent | **Fix.** Read the model registry from a module that doesn't import the world, or inline the two constants. It works today only via lazy `__getattr__`; the reviewer is right that it's fragile. Cheap to de-risk. |
| `DistributionGenerator(seed=None)` always; CLI `--seed` never reaches the structured path | **Fix — thread `--seed` through.** Verified: `generation.py:320` constructs `DistributionGenerator()` with no seed, so structured output is unreproducible despite the flag existing. Reproducibility is a headline property for eval-data tooling; this is worth more than "minor". |
| `schema_json` Pydantic warning | **Already fixed** in `e025792` (§0). |
| `docs/planning/*.md` adds ~2,000 lines | **Ask the user.** They were intentional as a historical record. Options: keep as-is (reply explaining intent), or move under a clearly-labelled `docs/planning/archive/`. Recommend keeping and replying — they document *why* decisions were made, which is exactly what's lost otherwise. Note this doc adds to that total. |

---

## 6. Deferred to a follow-up issue

Per the audit's own suggestion, open **one issue** covering the "gate is structurally
unable to fail" class of problem:

- The **uniqueness-penalty ceiling** (§4, first row) — even with validator uniqueness
  checks added, the *structural score* still can't fail on duplicate keys alone.
- The **row-count gate** — the PR's declared known limitation. Note `e025792` already
  adds a completeness dimension at 0.75 of target; the issue should record what remains
  rather than restating a fixed problem.

Also record the reviewer's process note (M1 should have been split from M2–M5, since M1's
schema refactor is the part that could break the published offering) as a lesson for the
next multi-milestone PR. Not actionable on #15.

---

## Execution order

1. ~~**Push `e025792`**~~ — **done**, resolves §0 (three items).
2. ~~**Get the user's naming decision** (§1a–1c)~~ — **done**: `plan` / `plan_and_generate`,
   CLI renamed too, deprecated aliases kept.
3. ~~**§2 must-fix** (anchored patterns) **+ §4 `fullmatch`**~~ — **done**.
4. ~~**§3** character-class ranges + cascade fallback~~ — **done**.
5. ~~**§4** remaining validator gaps~~ — **done** (uniqueness scan + corrector branch,
   non-integral integers, `pattern` enforced whenever set).
6. ~~**§5** circular import, `--seed` plumbing~~ — **done** (`model_registry.py` leaf module;
   `--seed` on `generate-structured` and `plan-and-generate`).
7. ~~**§1e** JSON Schema docs section~~ — **done**: "Relationship to JSON Schema" in
   `docs/docs/Guides/plan.md`. Round-trip limits were measured, not assumed — export is
   single-entity and loses `distribution`, `generation_guidance`, `reference_samples`,
   `unique`, `default`, and `structured_relationships`.
8. ~~**§1a–1c renames**~~ — **done** (code → tests → docs; `ingest` / `run` kept as
   deprecated aliases on both the Python and CLI surfaces; `docs/docs/Guides/ingest.md`
   renamed to `plan.md`).
9. ~~**§6** open the follow-up issue~~ — **done**:
   [#21](https://github.com/awslabs/synthetically_engineered_evaluation_data/issues/21).
10. Full verification: **done** — `ruff check .` clean, 501 tests passing, docs build
    `--strict` clean, wheel smoke on a clean Python 3.13 venv (base install confirmed
    lean: no pandas), and the three CLI surfaces that shipped in v0.0.6
    (`clone-schema-library`, `packet`, `infer-schema`) verified **byte-identical** to the
    `v0.0.6` tag. Note the original checklist said "all seven `--help` surfaces vs
    `main`" — only three existed in v0.0.6; the other four are new on this branch, and
    two of those (`generate-structured`, `plan-and-generate`) legitimately differ by the
    added `--seed` line.

**Nothing is pushed until the user approves.**

---

## Open questions for the user

1. ~~**Naming (§1a–1c)**~~ — **resolved.** `plan` + `plan_and_generate` for the two new
   verbs, and the **CLI** renamed in lockstep (`seed-data plan`,
   `seed-data plan-and-generate`), with `ingest` / `run` dispatchable as deprecated
   aliases on both surfaces. `Generator` keeps its name; the reply notes it is @sromoam's
   own pre-v0.0.6 name and proposes any rename as a separate breaking-change PR.
2. **Where do the fixes land** — new commits on `hp/structured-hardening` pushed into
   this PR, or a separate stacked PR so @sromoam can review the fixes independently of
   the 90-file original? **Still open** — nothing is pushed.
3. **Planning docs (§5)** — keep in-repo as the historical record, or archive them?
   **Still open**; current state keeps them, including this doc.

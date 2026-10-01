# Dynamic Call Target Resolution (Unit 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the target of a dynamic `CALL` / `EXEC CICS XCTL` / `EXEC CICS LINK` inside one COBOL program by carrying literal values through cobble's existing byte-extent dataflow fixpoint, and publish the result as real, candidate, or explicitly-unresolved edges in the whole-corpus knowledge graph.

**Architecture:** `cobble/dataflow/fixpoint` already runs a monotone worklist over source-CFG nodes whose lattice maps a `FieldExtent` to the set of `Source`s reaching it. This adds a second component to that same lattice — extent to `ValueSet` — joined by the same `join` and killed by the same `must_cover` rule, seeded from an initial byte image built out of `VALUE` clauses. A new pass reads the settled state at each call site and writes one row per site to a `targets.jsonl` artifact; `cobble-build` reads that artifact and emits the edges. No new traversal, no second resolver.

**Tech Stack:** Python 3.13, `uv`, pytest, Pyright strict, Black (88 cols), `import-linter`, `python-fp-lint`, `ast-grep`. The corpus is the vendored public AWS CardDemo sample at `vendor/carddemo`.

**Spec:** `docs/superpowers/specs/2026-09-30-cobble-dynamic-call-resolution-design.md` — read it before Task 1. Sections 2a, 4.1–4.7 and 12 are the ones tasks argue from.

## Global Constraints

- **Frozen dataclasses only.** Every new dataclass is `@dataclass(frozen=True)`. No exceptions (`guidelines/lang/python/programming-patterns.md`).
- **No `Any`, no `object`, no unparameterised generic.** The one pre-existing `object` at the JSONL boundary is confined to `cobble/cobble/dataflow/fixpoint/rows.py`; new readers use that module's helpers rather than adding a second boundary.
- **The Pyright gate is per-file, not repo-wide.** `uv run pyright` reports **762 pre-existing errors** on `main` (342 in `jackal`, 420 in `cobble`, of which 363 are in one file, `cobble/tests/dataflow/srccfg/test_statement_index.py`). This is the project's own policy, at `.pre-commit-config.yaml:46` — *"Blocking on staged files: touching a file obliges fixing its errors, while untouched files' backlog does not block unrelated commits."* So each task's gate is: **zero Pyright errors in the files that task creates or modifies.** Every one of the 22 files this plan touches is at zero today, verified, so no task inherits a backlog. Do **not** attempt to fix the repo-wide baseline; it is out of scope. Measure with `uv run pyright --outputjson` filtered to your task's files, not the summary count.
- **No inline comments** beyond a one-line class or module header. Docstrings are a separate matter and are **expected**: every module, class and non-trivial function in `cobble/dataflow` carries one explaining *why*, often at length, and this plan's code blocks follow that convention deliberately. `guardrails.md` reads as prohibiting per-function doc comments; the codebase's pervasive practice is the governing convention here, and a task that stripped docstrings to satisfy the literal rule would produce a large unrelated diff and lose the rationale these modules depend on. Do not flag a docstring as a defect.
- **`Sequence` / `Mapping` from `collections.abc`** for parameters that are not mutated. Never `list` / `dict` in a signature.
- **No `for` loops that mutate.** Comprehensions, `map`, `filter`, `reduce`. Enforced by `python-fp-lint`.
- **No mocking, no monkeypatching.** Inject fakes. `guidelines/lang/python/testing.md`.
- **Fully qualified imports.** `from cobble.dataflow.fields.values import ValueSet`, never a relative import.
- **One behaviour per test, with a concrete equality assertion.** Not one test per assertion, and never a non-empty or containment check where a value was available.
- **Values are `bytes`, of exactly the holding extent's length.** Alphanumeric content is left-justified and space-filled. A candidate program name is that value with trailing spaces stripped.
- **`MAX_VALUES = 32`**, a module constant, not an option or a parameter.
- **Black before every commit**: `make fmt` from the forge root, never `black .` — `BLACK_PATHS` excludes `vendor/` and the generated ANTLR grammar.
- **Commands run from `cobble/`** with `uv run --no-sync`, and **never with `bridge-env.sh` sourced.** `guidelines/project/workflow.md` is explicit: cobble is run without it, because sourcing it switches on acceptance tests that "are currently failing for reasons that predate this note", so a green run proves nothing either way. Every baseline count in this plan — 882 passed, 13 skipped — was measured without it, and a run that sources it is not comparable in either direction. `cobble-parse-corpus` does, and the cache it writes already exists at `cobble/out-parsed`.
- **Never `--no-verify`.** A failing hook is fixed, not bypassed.

## Review Focus

Five conditions the spec implies that no task's happy path exercises. Each has its test assigned to the task that owns the code.

1. **A member whose walk did not settle must not yield a proven edge.** `COACTUPC` trips the dequeue cap, so its value sets are a subset; a site resolving to exactly one program there is a *candidate*, not a fact. Test in Task 7.
2. **A `VALUE` literal wider than its `PIC` is truncated, not padded.** `PIC X(4) VALUE 'ABCDEFGH'` holds `ABCD`. Padding blindly would invent a program name no `PIC X(8)` field can hold. Test in Task 3.
3. **A `REDEFINES` whose views do not tile identically.** The `COMEN02Y` case works because both views lay out the same widths. Where they differ, a read extent can straddle two `FILLER`s and compose bytes from two unrelated literals into one plausible-looking name. That must yield no candidate rather than a wrong one. Test in Task 5.
4. **A program with no WORKING-STORAGE, and a `VALUE` on a group item.** The image builder must return an empty image for the first and ignore the second, not raise. Test in Task 3.
5. **Two members whose dynamic sites name the same field.** `CDEMO-TO-PROGRAM` appears in 15 members; the `DYNAMIC_TARGET` ids must stay distinct and the graph writer's keep-first dedupe must not merge them. Test in Task 9.

## File Structure

| file | responsibility |
|---|---|
| `cobble/dataflow/fields/values.py` | **new** — `ValueSet`, `UnresolvedReason`, `MAX_VALUES`, and the join/truncate rules. Pure; no imports from cobble. |
| `cobble/dataflow/fields/image.py` | **new** — the initial byte image: records plus a `CellIndex` to `Mapping[FieldExtent, ValueSet]`. |
| `cobble/dataflow/fixpoint/targets.py` | **new** — the occurrence-exact value read at a call site, and `ResolvedTarget`. |
| `cobble/dataflow/layout.py` | `Cell` carries its declared `VALUE`. |
| `cobble/dataflow/fields/state.py` | `State` becomes a two-component frozen dataclass. |
| `cobble/dataflow/fields/transfer.py` | writes carry a `ValueSet` alongside their `Source`s. |
| `cobble/dataflow/fixpoint/fixpoint.py` | the walk starts from the image; `INCOMPLETE_WALK` propagates. |
| `cobble/dataflow/fields/side_tables.py` | `target_row`. |
| `cobble/dataflow/fixpoint/build_corpus.py` | the fifth sink. |
| `cobble/knowledge_graph/graph_types.py` | `DYNAMIC_TARGET`, three `*_CANDIDATE` edge kinds. |
| `cobble/build_graph.py` | reads `targets.jsonl`, applies the three-way edge rule. |
| `cobble/cics/verb_source_asg.py` | stops resolving the program operand. |
| `cobble/config/carddemo-fields-tests.toml` | **new, tracked** — the acceptance config for a public corpus. |

---
### Task 1: Turn on the corpus-level acceptance gate

Spec §2a. Nothing has ever exercised this fixpoint against a parsed corpus, so this task establishes the gate **before** the lattice is touched. It ends with a recorded baseline you can regress against.

**Files:**
- Create: `cobble/config/carddemo-fields-tests.toml`
- Modify: `cobble/.gitignore` (after line 31, `!config/parse-carddemo.toml`)
- Modify: `cobble/tests/dataflow/fields/conftest.py:25-37`
- Modify: `cobble/tests/dataflow/fields/test_fields_acceptance.py:28` and `:88-113`

**Interfaces:**
- Consumes: nothing.
- Produces: a `corpus_config` fixture that resolves without a private config; `COVERAGE_FLOOR` at its real value; `oracle.cfg_nodes` as a list rather than `oracle.cfg_node` as a string.

- [ ] **Step 1: Confirm the cache exists**

Run from `cobble/`:

```bash
ls out-parsed | wc -l
```

Expected: `29`. If it is 0, build it first — this needs the JARs and takes about two minutes:

```bash
. ./bridge-env.sh \
  && uv run --no-sync --directory cobble cobble-parse-corpus --config config/carddemo.toml
```

- [ ] **Step 2: Write the tracked acceptance config**

`cobble/config/carddemo-fields-tests.toml`. Paths are relative because this file is tracked and must name no machine; the suite is run from `cobble/`.

```toml
cache_dir = "out-parsed"

members = [
  "COMEN01C", "COACTUPC", "COCRDLIC", "COCRDUPC", "COTRN02C",
  "COUSR00C", "COSGN00C", "CBTRN02C", "CBACT04C", "CORPT00C",
]

[oracle]
member = "COMEN01C"
source_field = "WS-PGMNAME"
target_field = "CDEMO-FROM-PROGRAM"
cfg_nodes = []

[performance]
member = "COACTUPC"
seconds = 60.0
```

`cfg_nodes` is filled in at Step 7, from an observed run that you then verify against the source. Leaving it empty here is deliberate: an invented node id would pass nothing and teach nobody.

- [ ] **Step 3: Un-ignore only the public filename**

`cobble/.gitignore` already ignores all of `config/*.toml` and negates the examples plus `carddemo.toml`. Add one line beside those negations:

```
!config/carddemo-fields-tests.toml
```

Do **not** un-ignore `config/fields-tests.toml`. That is the fixed filename `conftest.py` resolves first, and it is where someone points the suite at a corpus under analysis; tracking it would commit that corpus's member names. `guidelines/data-security.md`.

- [ ] **Step 4: Make the fixture fall back to the public config**

Replace `conftest.py:25-37` with:

```python
CORPUS_CONFIG = Path(__file__).resolve().parents[3] / "config" / "fields-tests.toml"
PUBLIC_CONFIG = (
    Path(__file__).resolve().parents[3] / "config" / "carddemo-fields-tests.toml"
)


@pytest.fixture
def corpus_config() -> Mapping[str, object]:
    """A local config naming real members, else the tracked public-corpus one.

    The local name stays gitignored because it is where a corpus under analysis
    gets pointed at; the public one is tracked so the acceptance tests are a gate
    rather than a permanent skip.
    """
    chosen = CORPUS_CONFIG if CORPUS_CONFIG.is_file() else PUBLIC_CONFIG
    if not chosen.is_file():
        pytest.skip(f"no {CORPUS_CONFIG.name} and no {PUBLIC_CONFIG.name}")
    return tomllib.loads(chosen.read_text(encoding="utf-8"))
```

`Mapping[str, object]` rather than a bare `Mapping`: the bare form is an unparameterised generic and Pyright strict rejects it. `object` is permitted here for the same reason `rows.py` permits it — this is a TOML boundary and the values are genuinely heterogeneous. Do not widen that precedent beyond these two modules.

- [ ] **Step 5: Run the acceptance tests and record what happens**

```bash
uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_acceptance.py -v
```

Expected, and this is the point of the task:
- `test_most_resolvable_writes_produce_at_least_one_edge` — **PASS**
- `test_no_analysed_member_is_silently_skipped` — **FAIL**, `{'COACTUPC': 'dequeue cap 103200 reached', ...}`
- `test_the_pinned_derivation_holds_end_to_end` — **FAIL**, `cfg_nodes` is empty
- `test_the_worst_member_completes_within_its_bound` — PASS or FAIL on timing

Two of these are real findings, not setup errors. Do not adjust a threshold to make them pass.

- [ ] **Step 6: Raise the coverage floor to just under the measured figure**

Measured over all 29 members: 3426 of 3863 write operands covered, 88.7%. The floor of 0.60 would not notice a regression halving coverage.

`test_fields_acceptance.py:28`:

```python
COVERAGE_FLOOR = 0.85
```

0.85 and not 0.887, because the floor is over the ten members in the config rather than all 29 and must not fail on a member mix it was not measured against. Re-run Step 5's first test and confirm it still passes.

- [ ] **Step 7: Pin the oracle from an observed run, then verify it by reading the source**

`COMEN01C.cbl:154` and `:179` both hold `MOVE WS-PGMNAME TO CDEMO-FROM-PROGRAM`, so this derivation is two statements and the expected node set has two members. Get the ids:

```bash
uv run --no-sync python - <<'PY'
import json, pathlib
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.emit import graph_records
from cobble.dataflow.fixpoint.fixpoint import analysed
from cobble.corpus_index import CorpusIndex
from cobol_asg.asg_types import CobolASG

with cached_asg_dialect_parsers_registered():
    asg = CobolASG.from_dict(
        json.loads(pathlib.Path("out-parsed/COMEN01C.json").read_text())
    )
flow, index = analysed(asg)
for edge in flow.edges:
    if edge.target.field_name == "CDEMO-FROM-PROGRAM":
        print(edge.node, edge.origin or edge.source.field_name)
PY
```

Read each printed node id and confirm it corresponds to one of those two `MOVE` statements before pinning it. Then put the verified ids in `cfg_nodes`.

- [ ] **Step 8: Replace the non-empty assertion with set equality**

`test_fields_acceptance.py:88-113`. The current body asserts `assert carried` and then `assert any(...)`; the first is the weak assertion `guidelines/testing.md` prohibits, and together they permit an extra unexplained carrier. Replace the two asserts with one:

```python
    assert {one.node for one in carried} == set(oracle["cfg_nodes"]), sorted(
        one.node for one in carried
    )
```

and change `oracle["cfg_node"]` to `oracle["cfg_nodes"]` where the config is read.

- [ ] **Step 9: Mutation-check the strengthened oracle**

Delete one id from `cfg_nodes` and re-run: the test must fail naming the extra carrier. Add a fabricated id and re-run: it must fail naming the missing one. Restore the correct list.

- [ ] **Step 10: Raise the dequeue factor to the measured figure**

The cap is `factor * nodes`, and `COACTUPC` needs more than 50 dequeues per node. Measured on it directly:

| factor | cap | settled | covered | time |
|---|---|---|---|---|
| 50 | 103200 | no | 660/834 | 27.0s |
| 150 | 309600 | **yes** | 660/834 | 28.6s |

So this is a mistuned default, not a limitation of the analysis: 1.6s more and the walk is provably the fixpoint rather than a subset. Coverage is identical, which is the expected shape — the extra dequeues confirm the state instead of growing it.

`cobble/cobble/dataflow/fixpoint/options.py`, the `ITERATION_FACTOR` constant:

```python
ITERATION_FACTOR = 150
```

Raising the cap can only help a member that previously settled, since the cap is an upper bound and not a target, so no other member can regress. The cost it does raise is the worst case for a genuinely pathological member, which now spends up to three times as long before giving up — acceptable at 28.6s for the corpus's largest member, and the reason the cap still exists.

- [ ] **Step 11: Confirm the skipped-member test now passes for the right reason**

```bash
uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_acceptance.py -v
```

Expected: all four pass, with no `xfail` and no member reported as skipped. Then mutation-check the change — set `ITERATION_FACTOR = 50` again, confirm `test_no_analysed_member_is_silently_skipped` fails naming `COACTUPC`, and restore 150. A default that passes only because nothing exercises it is what this whole task exists to stop.

Also confirm `test_a_raised_factor_lifts_the_cap_for_a_member_that_tripped_it` and `test_reaching_the_dequeue_cap_records_a_reason` in `tests/dataflow/fields/test_fixpoint.py` still pass — both construct their own `AnalysisOptions`, so neither should be sensitive to the default, and if either is, it was asserting the constant rather than the behaviour.

- [ ] **Step 12: Run the whole dataflow suite and the gate**

```bash
uv run --no-sync python -m pytest tests/dataflow/ -q
```

Expected: the previous 871 passing still pass, and the four fields acceptance tests now run and pass instead of skipping. The 13 `srccfg` and `closure` acceptance skips remain — they need their own tracked configs, which is a follow-up and not this task. From the forge root:

```bash
make fmt && uv run pyright && uv run lint-imports
```

- [ ] **Step 13: Commit**

```bash
git add cobble/config/carddemo-fields-tests.toml cobble/.gitignore \
        cobble/cobble/dataflow/fixpoint/options.py \
        cobble/tests/dataflow/fields/conftest.py \
        cobble/tests/dataflow/fields/test_fields_acceptance.py
git commit -m "test(cobble): run the fields acceptance suite against CardDemo

The four corpus-level tests were gated on a gitignored config that has never
existed, so they have always skipped -- including the one written to stop a
suite passing while explaining nothing. Tracks a CardDemo config under a
public-corpus filename, leaving the private filename ignored, raises the
coverage floor from 0.60 to 0.85 against a measured 88.7%, and strengthens the
end-to-end oracle from a non-empty check to set equality.

Running it found COACTUPC exhausting the dequeue cap and returning a subset. It
settles at factor 150 for 1.6s more with identical coverage, so the default rises
from 50 -- a mistuned constant nothing had ever reached.

```

---
### Task 2: `ValueSet` — the value domain

Spec §4.1. Pure module, no cobble imports, so it is testable in isolation and nothing else in this plan can proceed without it.

**Files:**
- Create: `cobble/cobble/dataflow/fields/values.py`
- Test: `cobble/tests/dataflow/fields/test_values.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MAX_VALUES: int`, `UnresolvedReason(Enum)`, `ValueSet(values: frozenset[bytes], reasons: frozenset[UnresolvedReason])` with a `complete` property, `EMPTY: ValueSet`, and the free functions `bounded(values, reasons) -> ValueSet`, `merged(left, right) -> ValueSet`, `of_value(value: bytes) -> ValueSet`, `because(reason) -> ValueSet`, `fitted(value: bytes, width: int) -> bytes`, `refitted(source: ValueSet, width: int) -> ValueSet`.

- [ ] **Step 1: Write the failing tests**

`cobble/tests/dataflow/fields/test_values.py`:

```python
"""The value domain: what an extent can hold, and why the set may be short."""

from __future__ import annotations

from cobble.dataflow.fields.values import (
    MAX_VALUES,
    EMPTY,
    UnresolvedReason,
    ValueSet,
    because,
    bounded,
    fitted,
    merged,
    of_value,
    refitted,
)


def test_a_set_over_the_budget_keeps_the_lowest_sorted_and_records_the_overflow():
    values = frozenset(f"PGM{n:05d}".encode() for n in range(MAX_VALUES + 8))
    result = bounded(values, frozenset())

    assert result.values == frozenset(sorted(values)[:MAX_VALUES])
    assert result.reasons == frozenset({UnresolvedReason.OVER_BUDGET})
    assert result.complete is False
    assert bounded(frozenset({b"PGMA"}), frozenset()) == of_value(b"PGMA")


def test_merging_unions_both_components_and_re_applies_the_budget():
    left = ValueSet(frozenset({b"PGMA"}), frozenset({UnresolvedReason.FROM_FILE}))
    right = ValueSet(frozenset({b"PGMB"}), frozenset({UnresolvedReason.NO_EXTENT}))
    big = bounded(frozenset(f"A{n:07d}".encode() for n in range(MAX_VALUES - 2)), frozenset())
    other = bounded(frozenset(f"B{n:07d}".encode() for n in range(MAX_VALUES - 2)), frozenset())

    assert merged(left, right) == ValueSet(
        frozenset({b"PGMA", b"PGMB"}),
        frozenset({UnresolvedReason.FROM_FILE, UnresolvedReason.NO_EXTENT}),
    )
    assert merged(of_value(b"PGMA"), EMPTY) == of_value(b"PGMA")
    assert merged(EMPTY, EMPTY).complete is True
    assert big.complete is True and other.complete is True
    assert len(merged(big, other).values) == MAX_VALUES
    assert merged(big, other).reasons == frozenset({UnresolvedReason.OVER_BUDGET})


def test_a_value_is_truncated_or_space_filled_to_the_field_width():
    assert fitted(b"ABCDEFGH", 4) == b"ABCD"
    assert fitted(b"CO", 8) == b"CO      "
    assert fitted(b"COSGN00C", 8) == b"COSGN00C"
    assert refitted(
        ValueSet(frozenset({b"CO", b"ABCDEFGHIJ"}), frozenset()), 8
    ) == ValueSet(frozenset({b"CO      ", b"ABCDEFGH"}), frozenset())
    assert refitted(because(UnresolvedReason.FROM_FILE), 8) == because(
        UnresolvedReason.FROM_FILE
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_values.py -v
```

Expected: collection error, `ModuleNotFoundError: No module named 'cobble.dataflow.fields.values'`.

- [ ] **Step 3: Write the module**

`cobble/cobble/dataflow/fields/values.py`:

```python
"""A set of concrete byte values an extent can hold, and why it may be incomplete."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MAX_VALUES = 32


class UnresolvedReason(Enum):
    """Why a value set is a subset of what its extent can really hold."""

    NOT_A_LITERAL = "not-a-literal"
    INBOUND_LINKAGE = "inbound-linkage"
    FROM_FILE = "from-file"
    FROM_CALLEE = "from-callee"
    NO_EXTENT = "no-extent"
    UNINITIALISED = "uninitialised"
    OVER_BUDGET = "over-budget"
    INCOMPLETE_WALK = "incomplete-walk"


@dataclass(frozen=True)
class ValueSet:
    """Every byte value reaching one extent, and why the set may be short.

    ``reasons`` empty means the set is complete -- these values and no others.
    Non-empty means at least these and possibly more, which is ``Reaching``'s
    truncated/abandoned distinction rather than a top element: collapsing to top
    would discard values already proven, and a caller that wants to know whether a
    site resolved needs the values *and* the doubt, not one or the other.
    """

    values: frozenset[bytes] = frozenset()
    reasons: frozenset[UnresolvedReason] = frozenset()

    @property
    def complete(self) -> bool:
        return not self.reasons


EMPTY = ValueSet()


def bounded(
    values: frozenset[bytes], reasons: frozenset[UnresolvedReason]
) -> ValueSet:
    """``values`` capped at ``MAX_VALUES``, the overflow named rather than hidden.

    Sorted before truncation so a corpus run writes the same artefact on every
    machine; an arbitrary 32 of a frozenset would not.
    """
    if len(values) <= MAX_VALUES:
        return ValueSet(values=values, reasons=reasons)
    return ValueSet(
        values=frozenset(sorted(values)[:MAX_VALUES]),
        reasons=reasons | {UnresolvedReason.OVER_BUDGET},
    )


def merged(left: ValueSet, right: ValueSet) -> ValueSet:
    return bounded(left.values | right.values, left.reasons | right.reasons)


def of_value(value: bytes) -> ValueSet:
    return ValueSet(values=frozenset({value}))


def because(reason: UnresolvedReason) -> ValueSet:
    return ValueSet(reasons=frozenset({reason}))


def fitted(value: bytes, width: int) -> bytes:
    """One value as it lands in a ``width``-byte alphanumeric field.

    Truncated on the right when longer and space-filled when shorter, which is what
    an alphanumeric MOVE does: PIC X(4) VALUE 'ABCDEFGH' holds ABCD, and MOVE 'CO'
    into a PIC X(8) leaves six spaces. A value of any other length would claim bytes
    its extent does not own.
    """
    return value[:width].ljust(width, b" ")


def refitted(source: ValueSet, width: int) -> ValueSet:
    return bounded(
        frozenset(fitted(value, width) for value in source.values), source.reasons
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run --no-sync python -m pytest tests/dataflow/fields/test_values.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Mutation-check the budget rule**

Change `sorted(values)[:MAX_VALUES]` to `list(values)[:MAX_VALUES]` and re-run: the first test must fail, because a frozenset's iteration order is not the sorted order. Change `value[:width].ljust(width, b" ")` to `value.ljust(width, b" ")` and re-run: the third test must fail on the truncation case. Restore both.

- [ ] **Step 6: Gate and commit**

```bash
cd .. && make fmt && uv run pyright && cd cobble
uv run --no-sync python -m pytest tests/dataflow/fields/test_values.py -q
cd .. && git add cobble/cobble/dataflow/fields/values.py cobble/tests/dataflow/fields/test_values.py
git commit -m "feat(cobble): a value domain for what an extent can hold

The lattice records where a value came from but not what it is, so a literal
collapses to the origin LITERAL and its text is lost. ValueSet is the missing
half: concrete bytes of the extent's own width, bounded at 32 and carrying the
reason a set is short rather than a top element that would discard what was
already proven.

```

---

### Task 3: `Cell` carries its `VALUE`, and the initial byte image

Spec §4.3. Owns Review Focus items 2 and 4.

**Files:**
- Modify: `cobble/cobble/dataflow/layout.py` — the `Cell` dataclass and `_occurrence`
- Create: `cobble/cobble/dataflow/fields/image.py`
- Test: `cobble/tests/dataflow/fields/test_image.py`

**Interfaces:**
- Consumes: `ValueSet`, `bounded`, `fitted` from Task 2.
- Produces: `Cell.value: str`, `Cell.value_is_figurative: bool`; `initial_image(records: Sequence[Record], index: CellIndex) -> Mapping[FieldExtent, ValueSet]`.

- [ ] **Step 1: Write the failing tests**

`VALUE` text in these fixtures carries no quotes, because the ProLeap bridge strips them before the cache is written — verified against `out-parsed/COMEN01C.json`, where `WS-PGMNAME` reads `value='COMEN01C'`.

`cobble/tests/dataflow/fields/test_image.py`:

```python
"""What a program's WORKING-STORAGE holds before any statement runs."""

from __future__ import annotations

from cobble.dataflow.fields.extent import cell_index
from cobble.dataflow.fields.image import initial_image
from cobble.dataflow.fields.values import of_value
from cobble.dataflow.layout import program_records


def test_every_occurrence_of_a_table_entry_carries_its_declaration_value(
    program_of, field
):
    asg = program_of(
        [],
        paragraphs=[],
        data_fields=[
            field(
                1,
                "TAB-REC",
                children=[
                    field(
                        5,
                        "TAB-ENTRY",
                        offset=0,
                        occurs=3,
                        children=[
                            field(10, "TAB-PGM", "X(8)", offset=0, value="COPGM01")
                        ],
                    )
                ],
            )
        ],
    )
    records = program_records(asg)
    index = cell_index(records)
    image = initial_image(records, index)

    named = {
        index.extent_of(cell).start: image[index.extent_of(cell)]
        for record in records
        for cell in record.cells
        if cell.name == "TAB-PGM"
    }

    assert named == {0: of_value(b"COPGM01 "), 8: of_value(b"COPGM01 "), 16: of_value(b"COPGM01 ")}


def test_the_image_holds_elementary_working_storage_values_only(program_of, field):
    asg = program_of(
        [],
        paragraphs=[],
        data_fields=[
            field(
                1,
                "WS-REC",
                children=[
                    field(5, "WS-PGM", "X(8)", offset=0, value="COSGN00C"),
                    field(5, "WS-NARROW", "X(4)", offset=8, value="ABCDEFGH"),
                    field(
                        5,
                        "WS-BLANK",
                        "X(8)",
                        offset=12,
                        value="SPACES",
                        value_is_figurative=True,
                    ),
                    field(5, "WS-PLAIN", "X(8)", offset=20),
                ],
            )
        ],
        linkage_fields=[
            field(
                1,
                "LK-REC",
                children=[field(5, "LK-PGM", "X(8)", offset=0, value="IGNORED ")],
            )
        ],
    )
    records = program_records(asg)
    index = cell_index(records)
    image = initial_image(records, index)

    by_name = {
        cell.name: image.get(index.extent_of(cell))
        for record in records
        for cell in record.cells
    }

    assert by_name["WS-PGM"] == of_value(b"COSGN00C")
    assert by_name["WS-NARROW"] == of_value(b"ABCD")
    assert by_name["WS-BLANK"] == of_value(b"        ")
    assert by_name["WS-PLAIN"] is None
    assert by_name["WS-REC"] is None
    assert by_name["LK-PGM"] is None


def test_a_program_with_no_working_storage_has_an_empty_image(program_of, field):
    asg = program_of([], paragraphs=[], data_fields=[])
    records = program_records(asg)

    assert initial_image(records, cell_index(records)) == {}
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run --no-sync python -m pytest tests/dataflow/fields/test_image.py -v
```

Expected: `ModuleNotFoundError` for `cobble.dataflow.fields.image`.

- [ ] **Step 3: Carry the `VALUE` onto `Cell`**

In `cobble/cobble/dataflow/layout.py`, add two fields to `Cell` after `redefines` and before `occurs` — anywhere among the defaulted fields is fine, but keep them adjacent:

```python
    value: str = ""
    value_is_figurative: bool = False
```

and in `_occurrence`, in the `Cell(...)` construction, after `redefines=node.field.redefines,`:

```python
            value=node.field.value,
            value_is_figurative=node.field.value_is_figurative,
```

`_Sized` needs no change: it already holds the whole `CobolField`, so every occurrence of a declaration reads the same literal from the same place.

- [ ] **Step 4: Write the image builder**

`cobble/cobble/dataflow/fields/image.py`:

```python
"""The bytes a program's WORKING-STORAGE holds before any statement runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import groupby
from operator import itemgetter
from types import MappingProxyType

from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.values import ValueSet, bounded, fitted
from cobble.dataflow.layout import Cell, Record
from cobol_memory.field_extent import FieldExtent

WORKING_STORAGE = "WORKING-STORAGE"

_FIGURATIVE = MappingProxyType(
    {
        "SPACE": b" ",
        "SPACES": b" ",
        "ZERO": b"0",
        "ZEROS": b"0",
        "ZEROES": b"0",
        "LOW-VALUE": b"\x00",
        "LOW-VALUES": b"\x00",
        "HIGH-VALUE": b"\xff",
        "HIGH-VALUES": b"\xff",
        "QUOTE": b'"',
        "QUOTES": b'"',
        "NULL": b"\x00",
        "NULLS": b"\x00",
    }
)


def _unquoted(text: str) -> str:
    """A literal without its surrounding quotes, its own spaces untouched.

    The bridge already strips them, so this is for a value that arrived any other
    way. Stripping whitespace instead would corrupt a declared value whose content
    is spaces -- VALUE \'USRSEC  \' is eight bytes and six of them matter.
    """
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\'\"":
        return text[1:-1]
    return text


def _literal_bytes(cell: Cell) -> bytes:
    """One cell's declared content as bytes, figurative constants included.

    A figurative constant is concrete storage -- SPACES is X'40' repeated to the
    field's width -- so excluding it would make the image claim a field holds
    nothing when the program can read eight spaces out of it and branch on them,
    which COMEN01C.cbl:198 does.
    """
    if cell.value_is_figurative:
        return _FIGURATIVE.get(cell.value.strip().upper(), b" ") * cell.length
    return _unquoted(cell.value).encode("utf-8", errors="replace")


def initial_image(
    records: Sequence[Record], index: CellIndex
) -> Mapping[FieldExtent, ValueSet]:
    """One value per elementary WORKING-STORAGE cell that declares a VALUE.

    WORKING-STORAGE only: LINKAGE and the FILE section have no initial content, and
    an extent in either with no writer in this member is exactly what
    INBOUND_LINKAGE and FROM_FILE report.

    Groups are excluded. A group's extent contains its children's, so an entry on
    the group would also be returned by ``may_alias`` for a read of any child --
    handing a caller the whole record's bytes where it asked for eight.
    """
    pairs = sorted(
        (
            (index.extent_of(cell), fitted(_literal_bytes(cell), cell.length))
            for record in records
            if record.origin == WORKING_STORAGE
            for cell in record.cells
            if cell.value and not cell.is_group
        ),
        key=lambda pair: str(pair[0]),
    )
    return MappingProxyType(
        {
            extent: bounded(frozenset(value for _, value in group), frozenset())
            for extent, group in groupby(pairs, key=itemgetter(0))
        }
    )
```

- [ ] **Step 5: Run to verify they pass**

```bash
uv run --no-sync python -m pytest tests/dataflow/fields/test_image.py -v
uv run --no-sync python -m pytest tests/dataflow/ -q
```

Expected: 3 passed in the new file, and the existing suite still green — `Cell` gained two defaulted fields, so every existing construction still type-checks.

- [ ] **Step 6: Mutation-check**

Remove `and not cell.is_group` and re-run: the second test must fail on `by_name["WS-REC"]`. Change `record.origin == WORKING_STORAGE` to always true and re-run: it must fail on `by_name["LK-PGM"]`. Restore both.

- [ ] **Step 7: Gate and commit**

```bash
cd .. && make fmt && uv run pyright && uv run lint-imports && cd cobble
cd .. && git add cobble/cobble/dataflow/layout.py cobble/cobble/dataflow/fields/image.py \
        cobble/tests/dataflow/fields/test_image.py
git commit -m "feat(cobble): an initial byte image from VALUE clauses

layout dropped CobolField.value, so the declared content of WORKING-STORAGE was
invisible to every later stage -- which is the dominant route by which a dynamic
call target is knowable: 132 of 161 non-static sites in the vendored corpora are
a field with a VALUE clause.

Elementary cells only, WORKING-STORAGE only. A group entry would be returned by
may_alias for a read of any child, and LINKAGE has no initial content.

```

---
### Task 4: `State` becomes two components

Spec §4.2. The riskiest task: every user of the lattice changes. Owns Review Focus item 3.

`FieldExtent` equality includes `field_name`, and the image keys an entry under the cell that declares the `VALUE` — `FILLER_3` — while a read names the redefining view, `CDEMO-MENU-OPT-PGMNAME`. Verified on `out-parsed/COMEN01C.json`: both are record bytes `(39, 8)`. So a value lookup **must match on the byte range, not on extent identity**, and a read contained in a wider valued extent is sliced out of it. A read contained in no valued extent — one straddling two of them — yields no value rather than a composed, wrong one.

**Files:**
- Modify: `cobble/cobble/dataflow/fields/state.py` (whole module)
- Modify: `cobble/cobble/dataflow/fields/transfer.py:76-79` (`_applied`)
- Modify: `cobble/cobble/dataflow/fixpoint/fixpoint.py:350`, `:440`, `:253`, `:412` (every `EMPTY` and `join` site)
- Modify: whatever else Pyright names in Step 4 — those edits belong to this commit, not the next task's
- Test: `cobble/tests/dataflow/fields/test_state.py` (extend)

**Interfaces:**
- Consumes: `ValueSet`, `merged`, `because`, `UnresolvedReason` from Task 2.
- Produces: `State(sources: Mapping[FieldExtent, frozenset[Source]], values: Mapping[FieldExtent, ValueSet])`; `EMPTY: State`; `join(left, right) -> State`; `write(state, target, sources, values) -> State`; `reaching(state, read) -> frozenset[Source]` (unchanged signature); `values_at(state, read) -> ValueSet`.

- [ ] **Step 1: Write the failing tests**

Append to `cobble/tests/dataflow/fields/test_state.py`:

```python
def test_a_strong_write_kills_both_components_and_a_clamped_one_kills_neither():
    exact = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.EXACT, "WS-A")
    clamped = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.CLAMPED, "WS-A")
    first = write(EMPTY, exact, frozenset(), of_value(b"PGMOLD  "))

    assert values_at(write(first, exact, frozenset(), of_value(b"PGMNEW  ")), exact) == (
        of_value(b"PGMNEW  ")
    )
    assert values_at(
        write(first, clamped, frozenset(), of_value(b"PGMNEW  ")), exact
    ) == ValueSet(frozenset({b"PGMOLD  ", b"PGMNEW  "}), frozenset())


def test_a_value_is_found_by_byte_range_not_by_extent_identity():
    declared = FieldExtent(RegionId.WORKING_STORAGE, 39, 8, Precision.EXACT, "FILLER_3")
    read_as = FieldExtent(
        RegionId.WORKING_STORAGE, 39, 8, Precision.EXACT, "CDEMO-MENU-OPT-PGMNAME"
    )
    state = write(EMPTY, declared, frozenset(), of_value(b"COACTVWC"))

    assert declared != read_as
    assert values_at(state, read_as) == of_value(b"COACTVWC")


def test_a_read_inside_a_valued_extent_is_sliced_and_one_that_straddles_two_is_not():
    left = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.EXACT, "WS-L")
    right = FieldExtent(RegionId.WORKING_STORAGE, 8, 8, Precision.EXACT, "WS-R")
    state = write(
        write(EMPTY, left, frozenset(), of_value(b"COACTVWC")),
        right,
        frozenset(),
        of_value(b"COCRDLIC"),
    )
    inside = FieldExtent(RegionId.WORKING_STORAGE, 2, 4, Precision.EXACT, "SLICE")
    straddling = FieldExtent(RegionId.WORKING_STORAGE, 4, 8, Precision.EXACT, "STRADDLE")

    assert values_at(state, inside) == of_value(b"ACTV")
    assert values_at(state, straddling) == because(UnresolvedReason.UNINITIALISED)


def test_an_extent_nothing_has_written_reports_uninitialised():
    unwritten = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.EXACT, "WS-A")

    assert values_at(EMPTY, unwritten) == because(UnresolvedReason.UNINITIALISED)
```

Add to that file's imports: `from cobble.dataflow.fields.state import EMPTY, State, join, reaching, values_at, write` and `from cobble.dataflow.fields.values import UnresolvedReason, ValueSet, because, of_value`.

- [ ] **Step 2: Run to verify they fail**

```bash
cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_state.py -v
```

Expected: `ImportError: cannot import name 'values_at'`.

- [ ] **Step 3: Rewrite `state.py`**

Keep the existing module docstring and `Source`, `LITERAL`, `CICS_STATE`, `NOWHERE` unchanged. Replace the `State` alias, `EMPTY`, `join`, `write` and `reaching` with:

```python
_NO_SOURCES: Mapping[FieldExtent, frozenset[Source]] = MappingProxyType({})
_NO_VALUES: Mapping[FieldExtent, ValueSet] = MappingProxyType({})


@dataclass(frozen=True)
class State:
    """What reaches each extent, and what each extent can hold.

    One object rather than two maps threaded side by side, because both are killed
    by the same ``must_cover`` rule and a value that outlived the provenance of the
    write that placed it would be a value the program cannot hold. Joining one and
    forgetting the other has to be impossible, not merely discouraged.
    """

    sources: Mapping[FieldExtent, frozenset[Source]] = _NO_SOURCES
    values: Mapping[FieldExtent, ValueSet] = _NO_VALUES


EMPTY = State()


def _joined_sources(
    left: Mapping[FieldExtent, frozenset[Source]],
    right: Mapping[FieldExtent, frozenset[Source]],
) -> Mapping[FieldExtent, frozenset[Source]]:
    keys = (*left, *(extent for extent in right if extent not in left))
    return MappingProxyType(
        {
            extent: left.get(extent, frozenset()) | right.get(extent, frozenset())
            for extent in keys
        }
    )


def _joined_values(
    left: Mapping[FieldExtent, ValueSet], right: Mapping[FieldExtent, ValueSet]
) -> Mapping[FieldExtent, ValueSet]:
    keys = (*left, *(extent for extent in right if extent not in left))
    return MappingProxyType(
        {
            extent: merged(left.get(extent, VALUES_EMPTY), right.get(extent, VALUES_EMPTY))
            for extent in keys
        }
    )


def join(left: State, right: State) -> State:
    """Union of both components, extent by extent. Order does not matter."""
    return State(
        sources=_joined_sources(left.sources, right.sources),
        values=_joined_values(left.values, right.values),
    )


def write(
    state: State,
    target: FieldExtent,
    sources: frozenset[Source],
    values: ValueSet = VALUES_EMPTY,
) -> State:
    """``sources`` and ``values`` reach ``target``; whatever it must_covers stops.

    An EXACT target must_covers itself, so it drops its own prior entry in both maps
    -- a strong update. A CLAMPED one covers nothing, so both are kept and this is a
    weak update. The two components are filtered by one predicate on purpose.
    """
    kept_sources = {
        extent: held
        for extent, held in state.sources.items()
        if not target.must_cover(extent)
    }
    kept_values = {
        extent: held
        for extent, held in state.values.items()
        if not target.must_cover(extent)
    }
    return State(
        sources=MappingProxyType(
            {
                **kept_sources,
                target: kept_sources.get(target, frozenset()) | sources,
            }
        ),
        values=MappingProxyType(
            {
                **kept_values,
                target: merged(kept_values.get(target, VALUES_EMPTY), values),
            }
        ),
    )


def reaching(state: State, read: FieldExtent) -> frozenset[Source]:
    """Every source held at an extent this read might overlap."""
    return frozenset(
        source
        for extent, sources in state.sources.items()
        if read.may_alias(extent)
        for source in sources
    )


def _sliced(held: ValueSet, extent: FieldExtent, read: FieldExtent) -> ValueSet:
    at = read.start - extent.start
    return ValueSet(
        values=frozenset(value[at : at + read.length] for value in held.values),
        reasons=held.reasons,
    )


def values_at(state: State, read: FieldExtent) -> ValueSet:
    """Every value the bytes at ``read`` can hold, sliced out of what holds them.

    Matched by byte range and not by extent identity, because two names over one
    piece of storage are two extents differing only in ``field_name`` -- the image
    files a value under the FILLER that declares it and a program reads it through
    the REDEFINES, and those are not equal extents.

    A read wholly inside a wider valued extent is sliced out of it, which is what
    makes a reference-modified read resolvable. A read straddling two valued extents
    is inside neither and yields no value at all: composing bytes from two unrelated
    literals would produce a plausible name the program can never hold, and a wrong
    answer here becomes a wrong edge in the graph.
    """
    found = tuple(
        _sliced(held, extent, read)
        for extent, held in state.values.items()
        if extent.region is read.region
        and extent.start <= read.start
        and read.end <= extent.end
    )
    if not found:
        return because(UnresolvedReason.UNINITIALISED)
    return reduce(merged, found, VALUES_EMPTY)
```

Imports to add at the top of `state.py`:

```python
from dataclasses import dataclass
from functools import reduce

from cobble.dataflow.fields.values import (
    EMPTY as VALUES_EMPTY,
    UnresolvedReason,
    ValueSet,
    because,
    merged,
)
```

`EMPTY as VALUES_EMPTY` because this module already exports its own `EMPTY`, and two names for two different empties in one file is how the wrong one gets used.

- [ ] **Step 4: Fix every caller the type change breaks**

Run Pyright first and let it enumerate them rather than guessing:

```bash
cd .. && uv run pyright 2>&1 | grep -E "state\.py|transfer\.py|fixpoint\.py" | head -40
```

The known sites:
- `transfer.py:76-79` `_applied` — `write(held, entry.target, entry.sources)` still type-checks because `values` is defaulted. Leave it until Task 5.
- `fixpoint.py:253` and `:412` — `join(states.get(edge.target, EMPTY), after)` needs no change; `EMPTY` is now a `State` instance rather than a mapping and `join` still takes two.
- `fixpoint.py:350` and `:440` — `MappingProxyType({entry: EMPTY})` is a map of node id to `State`; unchanged.
- Anywhere iterating a `State` directly as a mapping (`for extent in state`) must become `state.sources` or `state.values`. Pyright reports each as "not iterable".

- [ ] **Step 5: Run the full suite**

Scope note: the walk still starts from `EMPTY` after this task. Seeding it from the image is **Task 6**, deliberately, so that this task's diff is the type change alone and the 871 existing tests are a clean control. Leaving `_settled` and `_swept` at `EMPTY` here is correct and is not an omission.

```bash
cd cobble && uv run --no-sync python -m pytest tests/dataflow/ -q
```

Expected: the 4 new state tests pass and every previously-passing test still passes. This is the task's real assertion: the provenance behaviour is unchanged by construction, and 871 existing tests are the proof.

- [ ] **Step 6: Mutation-check the shared kill rule**

In `write`, make `kept_values` keep everything (drop the `must_cover` filter) and re-run: `test_a_strong_write_kills_both_components_and_a_clamped_one_kills_neither` must fail with both the old and new value present. Then change `values_at`'s containment test to `read.may_alias(extent)` and re-run: the straddling case must fail, returning composed bytes. Restore both.

- [ ] **Step 7: Gate and commit**

```bash
cd .. && make fmt && uv run pyright && uv run lint-imports
git add cobble/cobble/dataflow/fields/state.py cobble/tests/dataflow/fields/test_state.py \
        cobble/cobble/dataflow/fields/transfer.py cobble/cobble/dataflow/fixpoint/fixpoint.py
git commit -m "refactor(cobble): the lattice carries values beside provenance

State was a mapping from extent to the sources reaching it. It becomes a pair of
maps joined by one join and killed by one must_cover filter, so a value cannot
outlive the provenance of the write that placed it.

values_at matches on byte range rather than extent identity: FieldExtent equality
includes field_name, and the declared value of a redefined table lives under the
FILLER that declares it while the program reads it through the REDEFINES. A read
inside a valued extent is sliced out of it; one straddling two is not resolved at
all, because composing two unrelated literals yields a name no field can hold.

```

---

### Task 5: Transfer functions carry values

Spec §4.4.

**Files:**
- Modify: `cobble/cobble/dataflow/fields/transfer.py` — `Write`, `_applied`, `_one_move`, `_initialize_writes`, `_union_writes`, `_origin_writes`
- Test: `cobble/tests/dataflow/fields/test_transfer.py` (extend)

**Interfaces:**
- Consumes: Task 2's `values`, Task 4's `write`.
- Produces: `Write(target: FieldExtent, sources: frozenset[Source], values: ValueSet)`.

- [ ] **Step 1: Write the failing tests**

Append to `cobble/tests/dataflow/fields/test_transfer.py`:

```python
def test_a_literal_move_carries_its_text_fitted_to_the_target(index_of, program_of, field):
    asg = program_of(
        [],
        paragraphs=[
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "MOVE",
                        "operands": [{"name": "'COSGN00C'"}, {"name": "WS-PGM"}],
                    }
                ],
            }
        ],
        data_fields=[field(1, "WS-PGM", "X(8)")],
    )
    index = index_of(asg)
    statement = statement_index(asg)[next(iter(statement_index(asg)))]
    after = transfer(statement, "n1", EMPTY, index)
    target = index.extent_of(index.cells_named("WS-PGM", (), 0)[0])

    assert values_at(after, target) == of_value(b"COSGN00C")


```

Only one test here, and deliberately: a field-to-field move's *result* is only observable once a settled state can be read, which is Task 7's subject. Asserting it now would need an accessor on `ProgramFlow` that exists for a test's convenience, and the refit itself is already pinned by Task 2's `refitted` test.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run --no-sync python -m pytest tests/dataflow/fields/test_transfer.py -k "literal_move or refits" -v
```

Expected: FAIL — `values_at` returns `because(UNINITIALISED)` because no transfer produces a value yet.

- [ ] **Step 3: Give `Write` a value component**

```python
@dataclass(frozen=True)
class Write:
    """One extent, and everything reaching it after this statement."""

    target: FieldExtent
    sources: frozenset[Source]
    values: ValueSet = VALUES_EMPTY
```

and `_applied`:

```python
def _applied(state: State, writes: Iterator[Write]) -> State:
    return reduce(
        lambda held, entry: write(held, entry.target, entry.sources, entry.values),
        writes,
        state,
    )
```

- [ ] **Step 4: Produce values in `_one_move`**

The literal's text is on the operand. Replace `_one_move`:

```python
def _one_move(
    operand: RefModOperand,
    sources: OperandExtents,
    target: FieldExtent,
    node: str,
    state: State,
) -> Iterator[Write]:
    """The whole target from the whole source, or from a named origin."""
    if not sources.extents:
        origin = _unresolved_origin(operand, sources.reason)
        return iter(
            (
                Write(
                    target,
                    _synthetic(origin, node),
                    _literal_value(operand, target.length),
                ),
            )
        )
    return iter(
        (
            Write(
                target,
                _from_extents(sources.extents, node),
                _carried(state, sources.extents, target.length),
            ),
        )
    )


def _literal_value(operand: RefModOperand, width: int) -> ValueSet:
    """A quoted literal's own bytes; anything else is not a literal."""
    if not is_literal(operand.name):
        return because(UnresolvedReason.NOT_A_LITERAL)
    text = operand.name.strip()
    if not (text[:1] in "'\"" and text[-1:] == text[:1]):
        return because(UnresolvedReason.NOT_A_LITERAL)
    return of_value(fitted(text[1:-1].encode("utf-8", errors="replace"), width))


def _carried(
    state: State, extents: tuple[FieldExtent, ...], width: int
) -> ValueSet:
    return refitted(
        reduce(merged, (values_at(state, extent) for extent in extents), VALUES_EMPTY),
        width,
    )
```

`_one_move` now needs the in-state, so `_move_writes` and `writes_of` thread `state` through. Change `writes_of(statement, node, index)` to `writes_of(statement, node, index, state)` and update `transfer` to pass its own `state`. Every handler in `_WRITES_BY_KIND` takes the same four arguments; handlers that produce no values accept `state` and ignore it, which keeps one dispatch signature rather than two.

A figurative constant source (`MOVE SPACES TO X`) reaches `_literal_value` with `operand.name == "SPACES"`, which is not quoted, so it yields `NOT_A_LITERAL`. That is deliberate for Unit 1: a figurative constant as a *statement* source is not a program name, and the image already covers the declared-`VALUE` case where it matters.

- [ ] **Step 5: Give the other producers a value**

- `_initialize_writes` — `_origin_writes(..., LITERAL, ...)` gains `because(UnresolvedReason.NOT_A_LITERAL)`; `INITIALIZE` sets a category default this unit does not model.
- `_union_writes` — `because(UnresolvedReason.NOT_A_LITERAL)`; a `STRING`/arithmetic result is not a literal.
- A `READ`/`RECEIVE` target — `because(UnresolvedReason.FROM_FILE)`.
- A `CALL`'s `BY REFERENCE` argument — `because(UnresolvedReason.FROM_CALLEE)`.

Find each by grepping for `Write(` in the file and give every construction an explicit `values=`; leaving one defaulted means it silently claims `EMPTY`, which reads as "complete and holding nothing" rather than "unknown".

- [ ] **Step 6: Run, mutation-check, gate, commit**

```bash
uv run --no-sync python -m pytest tests/dataflow/ -q
cd .. && make fmt && uv run pyright && uv run lint-imports
```

Mutation check: make `_literal_value` return `VALUES_EMPTY` for a non-literal and re-run — a site whose operand is arithmetic would then look resolved-and-empty rather than unresolved, so Task 7's tests must fail once they exist; for now confirm `test_a_literal_move_carries_its_text_fitted_to_the_target` still passes and that removing the `fitted` call fails it.

```bash
git add cobble/cobble/dataflow/fields/transfer.py cobble/tests/dataflow/fields/test_transfer.py
git commit -m "feat(cobble): transfers carry the literal they move

A literal collapsed to the origin LITERAL and its text was discarded, so the
lattice knew a field had been assigned a constant but not which one. Every Write
now carries a ValueSet, fitted to the target's width, and every producer states
its reason explicitly rather than defaulting to an empty set that would read as
complete.

```

---
### Task 6: The walk starts from the image

Spec §4.3, §4.4. Small task, but it is what connects Tasks 3 and 5.

**Files:**
- Modify: `cobble/cobble/dataflow/fixpoint/fixpoint.py` — `analysed`, `analyse`, `_walked`, `_worked`, `_swept`, `_settled`
- Test: `cobble/tests/dataflow/fields/test_fixpoint.py` (extend)

**Interfaces:**
- Consumes: `initial_image` (Task 3), `State` (Task 4).
- Produces: `analyse(asg, index, options, entry_state: State = EMPTY) -> ProgramFlow`; `ProgramFlow.settled` already exists and is now meaningful for the value component too.

- [ ] **Step 1: Write the failing test**

The seeding's *observable* effect is a resolved call site, which is Task 7. What this task can assert is that seeding is wired in and changes nothing else — so the test pins the coverage counters, and `writes > 0` so a program that analysed nothing cannot satisfy it.

```python
def test_seeding_the_entry_state_leaves_the_coverage_counters_alone(
    program_of, field, index_of
):
    asg = program_of(
        [],
        paragraphs=[{"name": "MAIN", "statements": [_move("WS-PGM", "WS-COPY")]}],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-PGM", "X(8)", offset=0, value="COSGN00C"),
                    field(5, "WS-COPY", "X(8)", offset=8),
                ],
            )
        ],
    )
    index = index_of(asg)
    bare = analyse(asg, index, DEFAULT_OPTIONS)
    seeded = analysed(asg)[0]

    assert seeded.writes > 0
    assert (seeded.writes, seeded.covered, seeded.settled) == (
        bare.writes,
        bare.covered,
        bare.settled,
    )
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run --no-sync python -m pytest tests/dataflow/fields/test_fixpoint.py -k seeding -v
```

Expected: FAIL — `analyse` does not yet take a fourth argument, so the call in the test is a `TypeError`. If it passes instead, the signature change has already been made and the test is asserting nothing; check before continuing.

- [ ] **Step 3: Thread the entry state**

`analyse` gains a parameter and hands it to `_walked`:

```python
def analyse(
    asg,
    index: CellIndex,
    options: AnalysisOptions = DEFAULT_OPTIONS,
    entry_state: State = EMPTY,
) -> ProgramFlow:
```

`_walked`, `_worked`, `_swept` and `_settled` each take `entry_state: State` and use it where they currently write `EMPTY`:

- `_settled`: `states=MappingProxyType({entry: entry_state})` (was `{entry: EMPTY}`)
- `_swept`: `states: Mapping[str, State] = MappingProxyType({entry: entry_state})`

Nothing else changes. `join` with a seeded state is the same join.

- [ ] **Step 4: Build the image in `analysed`**

`analysed` currently discards the records after building the index. Keep them:

```python
    try:
        records = program_records(asg)
        index = cell_index(records)
    except UnsizeableFieldError as error:
        ...
    return analyse(asg, index, options, State(values=initial_image(records, index))), index
```

Match the existing return shape — `analysed` returns `tuple[ProgramFlow, CellIndex]`, so keep that and only add the third argument to the inner `analyse` call.

- [ ] **Step 5: Run the suite, gate, commit**

```bash
uv run --no-sync python -m pytest tests/dataflow/ -q
uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_acceptance.py -q
cd .. && make fmt && uv run pyright && uv run lint-imports
```

The acceptance run matters here: seeding adds an entry per valued cell to every member's entry state, so this is the first task that could move the coverage figure or the worst-member timing. If `test_the_worst_member_completes_within_its_bound` fails, report the new figure — do not raise `seconds` without saying why.

```bash
git add cobble/cobble/dataflow/fixpoint/fixpoint.py cobble/tests/dataflow/fields/test_fixpoint.py
git commit -m "feat(cobble): the walk starts from WORKING-STORAGE's declared content

Both walks began at EMPTY, so a field whose only assignment is its VALUE clause
reached its readers as nothing. The entry state is now the initial image, which
is the dominant route by which a dynamic call target is knowable.

```

---

### Task 7: Resolve the call sites

Spec §4.5. The core of the unit. Owns Review Focus item 1.

**Files:**
- Modify: `cobble/cobble/dataflow/fields/extent.py` — add `operand_occurrence_extents`
- Create: `cobble/cobble/dataflow/fixpoint/targets.py`
- Modify: `cobble/cobble/dataflow/fixpoint/fixpoint.py` — `ProgramFlow.targets`
- Modify: `cobble/cobble/dataflow/srccfg/cfg.py` — `Node.target_operand`
- Modify: `cobble/cobble/dataflow/srccfg/desugar.py` — `_with_call` and `_cobol_call` set it
- Test: `cobble/tests/dataflow/fixpoint/test_targets.py`

**Interfaces:**
- Consumes: everything from Tasks 2–6; `Cfg`, `Node`, `CALL_TRANSFERS` from `cobble.dataflow.srccfg.desugar`; `call_sites` from `cobble.dataflow.srccfg.link`.
- Produces: `operand_occurrence_extents(operand, index) -> tuple[FieldExtent, ...]`; `ResolvedTarget(caller, node, transfer, expression, candidates, reasons, dropped)`; `resolved_targets(cfg, index, states, settled) -> tuple[ResolvedTarget, ...]`; `ProgramFlow.targets: tuple[ResolvedTarget, ...]`.

- [ ] **Step 1: Add the occurrence-exact read to `extent.py`**

Beside `operand_extents`, reusing the private helpers already in that module:

```python
def operand_occurrence_extents(
    operand: RefModOperand, index: CellIndex
) -> tuple[FieldExtent, ...]:
    """One EXACT extent per occurrence an operand could denote.

    Deliberately not ``operand_extents``. A computed subscript there yields one
    CLAMPED extent spanning every occurrence -- ``_spanning``'s min(start) to
    max(end) -- which for CDEMO-MENU-OPT-PGMNAME(WS-OPTION) is 11*46+8 bytes and
    covers every row's 35-byte caption and 1-byte user type as well. That span
    exists so a computed subscript can never *kill* a definition, which is a
    write-side concern; reading a value through it would answer 'Account View'
    where a program name was asked for.

    Constant subscripts still select their one occurrence, via the same ``_selected``
    the clamped path falls back from, so a literal index loses no precision here.
    """
    candidates = index.cells_named(
        operand.name, operand.qualifiers, len(operand.subscripts)
    )
    if not candidates:
        return ()
    if not operand.subscripts:
        return _sliced(tuple(index.extent_of(cell) for cell in candidates), operand)
    selected = _selected(operand.subscripts, candidates, index)
    if selected:
        return _sliced(selected, operand)
    return _sliced(
        tuple(
            index.extent_of(occurrence)
            for cell in _one_per_declaration(candidates)
            for occurrence in index.occurrences_of(cell)
        ),
        operand,
    )
```

- [ ] **Step 2: Write the failing tests**

`cobble/tests/dataflow/fixpoint/test_targets.py` — create `tests/dataflow/fixpoint/` with no `__init__.py`, matching the rest of the tree.

```python
"""Which program a dynamic call site can reach, and why it may be unknown."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.fixpoint import analysed
from cobble.dataflow.fixpoint.options import AnalysisOptions
from cobol_asg.asg_types import CobolASG

CACHE = Path(__file__).resolve().parents[3] / "out-parsed"

MENU_PROGRAMS = (
    "COACTUPC",
    "COACTVWC",
    "COBIL00C",
    "COCRDLIC",
    "COCRDSLC",
    "COCRDUPC",
    "COPAUS0C",
    "CORPT00C",
    "COTRN00C",
    "COTRN01C",
    "COTRN02C",
)


def _targets(member: str, **options):
    if not (CACHE / f"{member}.json").is_file():
        pytest.skip(f"no parsed cache for {member}; run cobble-parse-corpus")
    with cached_asg_dialect_parsers_registered():
        asg = CobolASG.from_dict(
            json.loads((CACHE / f"{member}.json").read_text(encoding="utf-8"))
        )
    flow, _ = analysed(asg, AnalysisOptions(**options)) if options else analysed(asg)
    return {(t.node, t.expression): t for t in flow.targets}


def test_a_value_table_read_at_a_computed_subscript_yields_every_declared_program():
    found = _targets("COMEN01C")
    menu = [
        target
        for (_, expression), target in found.items()
        if expression.startswith("CDEMO-MENU-OPT-PGMNAME")
    ]

    assert menu, sorted(expression for _, expression in found)
    assert {tuple(sorted(t.candidates)) for t in menu} == {MENU_PROGRAMS}
    assert {UnresolvedReason.UNINITIALISED} <= set(menu[0].reasons)


def test_a_local_literal_move_resolves_each_site_to_its_own_program():
    found = _targets("COUSR00C")
    per_site = {
        target.node: tuple(sorted(target.candidates))
        for target in found.values()
        if target.expression == "CDEMO-TO-PROGRAM"
    }

    assert sorted(per_site.values()) == [("COSGN00C",), ("COUSR02C",), ("COUSR03C",)]


def test_an_unsettled_walk_marks_every_site_incomplete():
    found = _targets("COACTUPC", factor=1)

    assert found
    assert all(
        UnresolvedReason.INCOMPLETE_WALK in target.reasons for target in found.values()
    )
    assert not any(target.complete for target in found.values())
```

The second test's expected value comes from reading `COUSR00C.cbl`: it holds three `XCTL PROGRAM(CDEMO-TO-PROGRAM)` sites, at lines 197, 207 and 515, each immediately preceded by its own `MOVE` — `'COUSR02C'` at 192, `'COUSR03C'` at 202, `'COSGN00C'` at 509. Each site is therefore a singleton, and the test is really an assertion that the strong-update kill works: `CDEMO-TO-PROGRAM` is also assigned `'COSGN00C'` at 111 and `'COADM01C'` at 126, and neither may survive to a site a later write dominates.

Two things to check rather than assume when you first run it. If a site reports more than one candidate, the CFG has a path reaching that `XCTL` without passing its `MOVE` — read the paragraph before changing the expectation, because that may be true of the program. If a site carries `UNINITIALISED`, some path reaches it with the field never written in this member, which is correct for a `LINKAGE` field and means the expected `reasons` are non-empty rather than that the test is wrong. Record which you found in the commit message; do not adjust the assertion to match output without reading the source that explains it.

- [ ] **Step 3: Run to verify they fail**

```bash
uv run --no-sync python -m pytest tests/dataflow/fixpoint/test_targets.py -v
```

Expected: `AttributeError: 'ProgramFlow' object has no attribute 'targets'`.

- [ ] **Step 4: Write `targets.py`**

```python
"""Which programs one dynamic call site can reach, read off the settled state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce

from cobble.dataflow.fields.extent import CellIndex, operand_occurrence_extents
from cobble.dataflow.fields.state import State, values_at
from cobble.dataflow.fields.values import (
    EMPTY as VALUES_EMPTY,
    UnresolvedReason,
    ValueSet,
    because,
    merged,
)
from cobble.dataflow.srccfg.cfg import Cfg, Node
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS
from cobol_asg.ref_mod import RefModOperand
from cobol_memory.field_extent import FieldExtent


@dataclass(frozen=True)
class ResolvedTarget:
    """One dynamic call site, the programs it can reach, and the doubt attached.

    ``candidates`` is sorted, so the artefact and every edge derived from it are the
    same on any machine. ``dropped`` holds values that resolved but are not program
    names -- spaces, low-values -- which is a fact about the site and not an absence:
    a site provably holding spaces is answered, just not with a program.
    """

    caller: str
    node: str
    transfer: str
    expression: str
    candidates: tuple[str, ...] = ()
    reasons: tuple[UnresolvedReason, ...] = ()
    dropped: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.reasons


def _is_program_name(name: str) -> bool:
    """A resolved value that could name a load module.

    Not a pattern standing in for a type: every candidate here is already known to
    be the content of a program-name operand, and this only rejects content that
    cannot name anything at all.
    """
    return bool(name) and name.isprintable() and not name.isspace()


def _decoded(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").rstrip()


def _held(state: State, extents: Sequence[FieldExtent]) -> ValueSet:
    if not extents:
        return because(UnresolvedReason.NO_EXTENT)
    return reduce(merged, (values_at(state, extent) for extent in extents), VALUES_EMPTY)


def _resolved(
    cfg: Cfg, node: Node, index: CellIndex, state: State, settled: bool
) -> ResolvedTarget:
    operand = RefModOperand(name=node.target)
    held = _held(state, operand_occurrence_extents(operand, index))
    names = tuple(sorted({_decoded(value) for value in held.values}))
    reasons = held.reasons if settled else held.reasons | {
        UnresolvedReason.INCOMPLETE_WALK
    }
    return ResolvedTarget(
        caller=cfg.program,
        node=node.id,
        transfer=node.transfer,
        expression=node.target,
        candidates=tuple(name for name in names if _is_program_name(name)),
        reasons=tuple(sorted(reasons, key=lambda reason: reason.value)),
        dropped=tuple(name for name in names if not _is_program_name(name)),
    )


def resolved_targets(
    cfg: Cfg,
    index: CellIndex,
    states: Mapping[str, State],
    settled: bool,
) -> tuple[ResolvedTarget, ...]:
    """One row per dynamic call site, whether or not anything resolved.

    A site whose target is a literal is not here: it is already an edge. A site the
    walk never reached has no state, so it resolves to nothing with a reason, which
    is the answer and not an omission.
    """
    return tuple(
        _resolved(cfg, node, index, states.get(node.id, State()), settled)
        for node in cfg.nodes
        if node.transfer in CALL_TRANSFERS and node.target and not node.target_resolved
    )
```

`RefModOperand(name=node.target)` loses the subscripts, because `Node.target` is the text `_callee` rendered — `CDEMO-MENU-OPT-PGMNAME(WS-OPTION)`. **That is a defect you must fix in this step, not work around**: change `srccfg/desugar.py` to keep the structured operand on the node rather than its rendering, or add a field carrying it. Parsing the subscript back out of the text would be exactly the "information encoded in a string representation" that `guidelines/design-principles.md` forbids. Prefer adding `Node.target_operand: RefModOperand | None = None` set by `_with_call` and `_cobol_call` from the operand each already has in hand, and use it here; fall back to `RefModOperand(name=node.target)` only when it is absent, which is the literal case this function already filters out.

- [ ] **Step 5: Hang the targets off `ProgramFlow`**

In `fixpoint.py`, `ProgramFlow` gains `targets: tuple[ResolvedTarget, ...] = ()`, and `analyse` fills it from `resolved_targets(cfg, index, walk.states, walk.settled)`. The states stay internal to `analyse`, matching how `edges` and `defs` are already derived rather than exposed.

- [ ] **Step 6: Run, and pin the second test's expected value**

```bash
uv run --no-sync python -m pytest tests/dataflow/fixpoint/test_targets.py -v
```

Follow Step 2's instruction on the placeholder before treating a pass as real.

- [ ] **Step 7: Mutation-check the two claims that matter**

1. Replace `operand_occurrence_extents` with `operand_extents(...).extents` in `_held` and re-run: the menu test must fail with captions and user types among the candidates. This is the assertion that the CLAMPED span is not reused.
2. Make `reasons` ignore `settled` and re-run: `test_an_unsettled_walk_marks_every_site_incomplete` must fail. This is the assertion that an unsettled walk cannot publish a fact.

Restore both.

- [ ] **Step 8: Gate and commit**

```bash
cd .. && make fmt && uv run pyright && uv run lint-imports
git add cobble/cobble/dataflow/fields/extent.py cobble/cobble/dataflow/fixpoint/targets.py \
        cobble/cobble/dataflow/fixpoint/fixpoint.py cobble/cobble/dataflow/srccfg/desugar.py \
        cobble/cobble/dataflow/srccfg/cfg.py \
        cobble/tests/dataflow/fixpoint/test_targets.py
git commit -m "feat(cobble): resolve a dynamic call site from the settled state

One row per site whose target is a data item, carrying the programs it can reach,
the reasons the set may be short, and the values that resolved but name no
program.

The read is occurrence-exact rather than operand_extents: a computed subscript
yields one CLAMPED extent spanning the whole table, which exists so it can never
kill a definition, and reading values through it returns a menu caption where a
program name was asked for. An unsettled walk marks every site incomplete, so a
subset can never be published as a fact.

```

---
### Task 8: The artifact table

Spec §4.6.

**Files:**
- Modify: `cobble/cobble/dataflow/fields/side_tables.py` — add `target_row`
- Modify: `cobble/cobble/dataflow/fixpoint/build_corpus.py` — `_Sinks`, `_tables`, `MemberResult`, the run report
- Modify: `cobble/cobble/dataflow/fixpoint/config.py` if the output paths are named there
- Test: `cobble/tests/dataflow/fields/test_fields_build_corpus.py` (extend)

**Interfaces:**
- Consumes: `ResolvedTarget` (Task 7).
- Produces: `target_row(target: ResolvedTarget) -> tuple[str, str]`; a `targets.jsonl` beside `extents.jsonl`, `defs.jsonl` and `aliases.jsonl`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_dynamic_site_is_one_row_whether_or_not_it_resolved():
    resolved = ResolvedTarget(
        caller="PROGA",
        node="MAIN/3",
        transfer="CICS_XCTL",
        expression="WS-PGM",
        candidates=("COSGN00C",),
    )
    unresolved = ResolvedTarget(
        caller="PROGA",
        node="MAIN/7",
        transfer="CICS_XCTL",
        expression="CDEMO-TO-PROGRAM",
        reasons=(UnresolvedReason.INBOUND_LINKAGE,),
        dropped=("",),
    )

    assert target_row(resolved) == (
        "PROGA\x00MAIN/3",
        json.dumps(
            {
                "caller": "PROGA",
                "node": "MAIN/3",
                "transfer": "CICS_XCTL",
                "expression": "WS-PGM",
                "candidates": ["COSGN00C"],
                "reasons": [],
                "dropped": [],
            }
        ),
    )
    assert json.loads(target_row(unresolved)[1])["reasons"] == ["inbound-linkage"]
```

- [ ] **Step 2: Run to verify it fails**, then write `target_row`

```python
def target_row(target: ResolvedTarget) -> _Row:
    """One dynamic call site, keyed by the site: a caller and a node name it once.

    Every site is a row, including one that resolved to nothing -- a reader can then
    tell "we looked and could not say" from "there is no such site", which an absent
    row cannot express. Reasons serialise as their enum values; the enum is the type
    and the string is the wire.
    """
    return (
        f"{target.caller}\x00{target.node}",
        json.dumps(
            {
                "caller": target.caller,
                "node": target.node,
                "transfer": target.transfer,
                "expression": target.expression,
                "candidates": list(target.candidates),
                "reasons": [reason.value for reason in target.reasons],
                "dropped": list(target.dropped),
            }
        ),
    )
```

- [ ] **Step 3: Add the fifth sink**

`_Sinks` gains `targets: JsonlWriter` and `add_result` gains `self.targets.add_rows(map(target_row, result.targets))`. `MemberResult` gains `targets: tuple[ResolvedTarget, ...] = ()`, filled in `_tables` from `flow.targets`. Update the `_Sinks` docstring: it says "All five artefacts" and now means six, and the reason `targets` is its own file is the same reason `aliases` is — a call site's possible callees are not a fact about either program's field graph.

- [ ] **Step 4: Report the counts**

Add to the run report, beside `_report_aliases`, a line stating how many dynamic sites were seen, how many resolved to exactly one program, how many to several, and how many to none with a breakdown by reason. This is the completeness metric the README needs in place of a test count.

- [ ] **Step 5: Run the corpus stage end to end**

```bash
cd cobble && uv run --no-sync cobble-dataflow-fixpoint --config config/fields.toml --all
```

`config/fields.toml` does not exist — copy `config/fields.example.toml` to it and point `asg_dir` at `out-parsed`. It is gitignored; that is correct and it stays untracked. Confirm `targets.jsonl` appears in the configured output directory and spot-check `COMEN01C`'s rows against Task 7's expected program list.

- [ ] **Step 6: Gate and commit**

```bash
cd .. && make fmt && uv run pyright && uv run lint-imports && cd cobble
uv run --no-sync python -m pytest tests/dataflow/ -q
cd .. && git add cobble/cobble/dataflow/fields/side_tables.py \
        cobble/cobble/dataflow/fixpoint/build_corpus.py \
        cobble/tests/dataflow/fields/test_fields_build_corpus.py
git commit -m "feat(cobble): publish resolved call targets as a corpus table

One row per dynamic call site, keyed by caller and node, carrying the candidate
programs, the typed reasons the set may be short, and the values that resolved
but name no program. A site that resolved to nothing is still a row, so a reader
can tell 'we looked and could not say' from 'there is no such site'.

```

---

### Task 9: The graph reads the table

Spec §4.7. Owns Review Focus item 5.

**Files:**
- Modify: `cobble/cobble/knowledge_graph/graph_types.py` — `NodeKind.DYNAMIC_TARGET`, three `*_CANDIDATE` edge kinds
- Modify: `cobble/cobble/build_graph.py` — read the table, apply the three-way rule
- Modify: `cobble/cobble/knowledge_graph/palette.py` — a colour for the new node kind, if it enumerates kinds exhaustively
- Test: `cobble/tests/knowledge_graph/test_dynamic_targets.py`

**Interfaces:**
- Consumes: `targets.jsonl` via `cobble.dataflow.fixpoint.rows`.
- Produces: `dynamic_target_graph(rows, corpus_index) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_three_edge_forms_and_ids_that_do_not_fuse_across_members():
    rows = (
        {"caller": "PROGA", "node": "MAIN/1", "transfer": "CICS_XCTL",
         "expression": "WS-PGM", "candidates": ["COSGN00C"], "reasons": [], "dropped": []},
        {"caller": "PROGB", "node": "MAIN/2", "transfer": "CICS_XCTL",
         "expression": "WS-TAB", "candidates": ["COACTVWC", "COCRDLIC"],
         "reasons": ["uninitialised"], "dropped": []},
        {"caller": "PROGC", "node": "MAIN/3", "transfer": "CICS_LINK",
         "expression": "CDEMO-TO-PROGRAM", "candidates": [],
         "reasons": ["inbound-linkage"], "dropped": []},
        {"caller": "PROGD", "node": "MAIN/4", "transfer": "CICS_LINK",
         "expression": "CDEMO-TO-PROGRAM", "candidates": [],
         "reasons": ["inbound-linkage"], "dropped": []},
    )
    nodes, edges = dynamic_target_graph(rows, CorpusIndex())

    assert [(e.source, e.kind, e.target, e.target_kind) for e in edges] == [
        ("PROGA", EdgeKind.XCTL, "COSGN00C", NodeKind.PROGRAM),
        ("PROGB", EdgeKind.XCTL_CANDIDATE, "COACTVWC", NodeKind.PROGRAM),
        ("PROGB", EdgeKind.XCTL_CANDIDATE, "COCRDLIC", NodeKind.PROGRAM),
        ("PROGC", EdgeKind.LINK, "PROGC.CDEMO-TO-PROGRAM", NodeKind.DYNAMIC_TARGET),
        ("PROGD", EdgeKind.LINK, "PROGD.CDEMO-TO-PROGRAM", NodeKind.DYNAMIC_TARGET),
    ]
    assert {n.id for n in nodes if n.kind is NodeKind.DYNAMIC_TARGET} == {
        "PROGC.CDEMO-TO-PROGRAM",
        "PROGD.CDEMO-TO-PROGRAM",
    }


def test_a_single_candidate_with_any_reason_is_a_candidate_not_a_fact():
    rows = (
        {"caller": "PROGA", "node": "MAIN/1", "transfer": "CICS_XCTL",
         "expression": "WS-PGM", "candidates": ["COSGN00C"],
         "reasons": ["incomplete-walk"], "dropped": []},
    )
    _, edges = dynamic_target_graph(rows, CorpusIndex())

    assert [e.kind for e in edges] == [EdgeKind.XCTL_CANDIDATE]
```

The second test is Review Focus item 1 reaching the graph, and the first is item 5: `PROGC` and `PROGD` both name `CDEMO-TO-PROGRAM`, and the writer dedupes nodes on `(kind, id)`, so a shared id would fuse two members into one hub — the failure `dataflow/depgraph/flows.py:319` documents.

- [ ] **Step 2: Run to verify it fails**, then add the kinds

`graph_types.py`, in `NodeKind`, with a comment in the style of its neighbours:

```python
    # A dynamic call site whose target the dataflow could not pin to a program.
    # id is "<program>.<expression>" -- scoped like FIELD, because the expression
    # is a data name unique only within its program, and a corpus-wide node per
    # expression would fuse every member that names it into one hub.
    DYNAMIC_TARGET = "DYNAMIC_TARGET"
```

and in `EdgeKind`:

```python
    XCTL_CANDIDATE = "XCTL_CANDIDATE"
    LINK_CANDIDATE = "LINK_CANDIDATE"
    CALL_CANDIDATE = "CALL_CANDIDATE"
```

- [ ] **Step 3: Write the emitter**

In `build_graph.py`, beside `_ref_graph`:

```python
_ORDINARY = MappingProxyType(
    {
        "CICS_XCTL": EdgeKind.XCTL,
        "CICS_LINK": EdgeKind.LINK,
        "CALL": EdgeKind.CALL,
    }
)

_CANDIDATE = MappingProxyType(
    {
        "CICS_XCTL": EdgeKind.XCTL_CANDIDATE,
        "CICS_LINK": EdgeKind.LINK_CANDIDATE,
        "CALL": EdgeKind.CALL_CANDIDATE,
    }
)
```

and a function applying the rule: one ordinary edge when there is exactly one candidate and no reason; one candidate edge per candidate otherwise; and, when there are no candidates at all, one ordinary edge to a `DYNAMIC_TARGET` node whose `attrs` carry `reason` (the reasons joined, or `not-attempted` when the table has no row for a site the CICS walk saw) and `dropped`.

Read the rows with `cobble.dataflow.fixpoint.rows.read`, `text` and `strings` — not `json.loads` directly. That module exists to keep the untyped boundary in one place.

- [ ] **Step 4: Wire it into `main` and make the table optional**

The graph build must still work with no `targets.jsonl`. Where it is absent, every dynamic site the CICS walk saw yields a `DYNAMIC_TARGET` node with `reason = "not-attempted"`, and no `CALL` site appears at all — the import scanner is literal-only, so cobble has no other knowledge of one. Record which inputs the build had, so a changed node count is explained by a named missing artifact rather than looking like drift.

- [ ] **Step 5: Run, gate, commit**

```bash
cd cobble && uv run --no-sync python -m pytest tests/knowledge_graph/ -q
cd .. && make fmt && uv run pyright && uv run lint-imports
git add cobble/cobble/knowledge_graph/graph_types.py cobble/cobble/build_graph.py \
        cobble/tests/knowledge_graph/test_dynamic_targets.py
git commit -m "feat(cobble): dynamic call edges, candidate or explicitly unresolved

A site resolving to one program with no doubt is an ordinary XCTL/LINK/CALL edge.
Two or more, or one with any reason attached, are *_CANDIDATE edges -- so a
consumer filtering on EdgeKind, which every renderer does, cannot mistake a
possible call for a proven one. None at all is an edge to a DYNAMIC_TARGET node
named '<program>.<expression>', which keeps the site visible without fusing the
fifteen members that name CDEMO-TO-PROGRAM into one hub.

```

---

### Task 10: Stop the CICS extractor inventing programs

Spec §1, §4.7.

**Files:**
- Modify: `cobble/cobble/cics/flow_observer.py` — `CicsVerb.program_operand`
- Modify: `cobble/cobble/cics/verb_source_asg.py` — `_transfer_verb`
- Test: `cobble/tests/cics/test_verb_source_asg.py` (extend)

**Interfaces:**
- Consumes: nothing new.
- Produces: `CicsVerb.program_operand: str` — the operand as written, empty for a literal.

- [ ] **Step 1: Write the failing test**

```python
def test_a_data_name_program_operand_is_recorded_not_resolved():
    verbs = _verbs_of(
        """
           EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) END-EXEC.
           EXEC CICS XCTL PROGRAM('COSGN00C') END-EXEC.
        """
    )

    assert [(v.xctl_target, v.program_operand) for v in verbs] == [
        (None, "CDEMO-TO-PROGRAM"),
        ("COSGN00C", ""),
    ]
```

Use whatever helper that file already has for building verbs from source; do not add a second one. A `VALUE`-carrying field must also yield `(None, "WS-ABEND-PGM")` rather than the old `("ABNDPROC", ...)` — add that case to the same test, because the old behaviour was right by accident and its removal is the point.

- [ ] **Step 2: Run to verify it fails**, then change `_transfer_verb`

```python
def _transfer_verb(stmt: ExecCicsStatement, program: str, data_fields):
    """XCTL and LINK: both name the program they transfer to in PROGRAM(...).

    A literal resolves here; a data name does not. The declared VALUE of the field
    is not the program's content at the moment of the transfer -- any later MOVE
    overwrites it -- and falling back to the operand's own text emits an edge to a
    program no corpus contains. Resolution belongs to the dataflow, which reads the
    state at this site rather than the declaration.
    """
    operand = stmt.options.get(PROGRAM_OPTION)
    literal = operand.text if operand is not None and operand.is_literal else None
    return _verb(
        stmt.verb,
        program,
        xctl_target=literal,
        program_operand="" if literal else _operand_text(operand),
    )
```

`_resolve_operand`, `_field_value` and `_static_value` stay — `TRANSID`, `MAP`, `MAPSET` and `FILE` still use them, and changing those is explicitly out of scope (spec §3). `flow_graph_core._verb_edge` needs no change: line 97 already returns early on an empty `xctl_target`, so the fabricated edges stop being produced rather than produced and filtered.

- [ ] **Step 3: Confirm the fabricated nodes are gone**

```bash
cd cobble && uv run --no-sync cobble-build --config config/carddemo.toml
python3 -c "
import json
bad = {'CDEMO-TO-PROGRAM','CCARD-NEXT-PROG','CDEMO-MENU-OPT-PGMNAME','CDEMO-ADMIN-OPT-PGMNAME'}
nodes = [json.loads(l) for l in open('out/nodes.jsonl')]
print('fabricated PROGRAM nodes:', [n['id'] for n in nodes if n['kind']=='PROGRAM' and n['id'] in bad])
"
```

Expected: an empty list.

- [ ] **Step 4: Gate and commit**

```bash
cd .. && make fmt && uv run pyright && uv run lint-imports && cd cobble
uv run --no-sync python -m pytest tests/cics/ tests/knowledge_graph/ -q
cd .. && git add cobble/cobble/cics/flow_observer.py cobble/cobble/cics/verb_source_asg.py \
        cobble/tests/cics/test_verb_source_asg.py
git commit -m "fix(cobble): a dynamic PROGRAM operand is not a program name

_resolve_operand took a field's declared VALUE and, failing that, the operand's
own text -- so 18 of the reference graph's 36 program-transfer edges pointed at
variable names and four PROGRAM nodes were variables. The fallback is a
mis-ported runtime behaviour: cicada resolves the operand by emitting a runtime
decode, whose 'unresolved bare name' case is a name that is not a field at all,
a precondition a static pass cannot check.

The transfer verbs now record the operand and resolve only literals. The other
operands keep _resolve_operand; extending the dataflow to them is a follow-up.

```

---

### Task 11: Regenerate the reference graph and update the docs

Spec §6.

**Files:**
- Modify: `cobble/reference/nodes.jsonl`, `cobble/reference/edges.jsonl`
- Modify: `cobble/README.md`
- Modify: `cobble/tests/test_compare.py` if it names counts

- [ ] **Step 1: Rebuild and diff before replacing**

```bash
cd cobble && uv run --no-sync cobble-build --config config/carddemo.toml
diff <(sort reference/nodes.jsonl) <(sort out/nodes.jsonl) | head -40
diff <(sort reference/edges.jsonl) <(sort out/edges.jsonl) | head -60
```

Read the whole diff before copying anything. Every removed line must be one of the four fabricated `PROGRAM` nodes or one of the 18 edges pointing at them; every added line must be a `DYNAMIC_TARGET` node, a `*_CANDIDATE` edge, or a resolved edge to a program that is really in the corpus. **An unexplained line in that diff is a defect in Tasks 7–10, not a new baseline.** Reviewing this diff is the task.

- [ ] **Step 2: Replace the reference and record the counts**

```bash
cp out/nodes.jsonl reference/nodes.jsonl && cp out/edges.jsonl reference/edges.jsonl
wc -l reference/nodes.jsonl reference/edges.jsonl
```

- [ ] **Step 3: Update the README**

- The 449/803 claim, in the opening paragraph and wherever else it appears, becomes the new counts.
- The stage table gains `targets.jsonl` and says what a row means.
- A short subsection on the three edge forms and the `DYNAMIC_TARGET` node, with the `<program>.<expression>` id rule and why it is scoped that way.
- Correct the cost claim: the README says a whole-cache pass is "minutes of fixpoint per member"; measured over the 29-member CardDemo cache it is 72.5s in total, 2.5s typical and 29.1s worst.
- No test counts anywhere (`guidelines/project/workflow.md`).

- [ ] **Step 4: Full gate**

```bash
cd .. && make fmt && uv run pyright && uv run lint-imports
pre-commit run python-fp-lint-check --hook-stage manual --all-files
make test-all
```

`make test-all` and not `make test`: this changed a runtime-adjacent package and the graph.

- [ ] **Step 5: Commit**

```bash
git add cobble/reference/nodes.jsonl cobble/reference/edges.jsonl cobble/README.md
git commit -m "docs(cobble): regenerate the reference graph for resolved call targets

Four fabricated PROGRAM nodes and the 18 edges pointing at them are gone;
candidate and DYNAMIC_TARGET edges take their place, and dynamic COBOL CALL
sites appear for the first time. Corrects the README's cost claim: a whole-cache
fixpoint pass over the 29-member CardDemo cache is 72.5s, not minutes per member.

```

---

## Follow-ups to file as issues

Not part of this plan. File each with `bd create` when Task 11 lands.

- Unit 2: interprocedural propagation through the `COMMAREA`, resolving the 10 sites that stay `INBOUND_LINKAGE`. Spec §11.
- Extend the value analysis to `TRANSID`, `MAP`, `MAPSET` and `FILE` operands, and retire `_resolve_operand`; the fabricated `BMS_MAP` node `CCARD-NEXT-MAPSET.CCARD-NEXT-MAP` goes with it.
- Guard-sensitive refinement of a candidate set: `WHEN CDEMO-MENU-OPT-PGMNAME(WS-OPTION) = 'COPAUS0C'` pins the value at the site, and `state.py` carries no guards by design.
- Track CardDemo configs for the `srccfg` and `closure` acceptance suites, which account for 13 of the 17 skips Task 1 does not address.
- Soundness check against an interpreted run: every target a real execution took must be in the candidate set. An artifact comparison, since `.importlinter` forbids cobble importing the interpreter.

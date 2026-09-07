# Path-Sampling Byte Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `cobble-fields-trace` CLI that interprets one concrete CFG path at a time over a real byte-provenance store, steps into `LINK`/`XCTL` callees by binding the shared commarea window, and samples paths until a branch-coverage target is met.

**Architecture:** Two new modules in `cobble/cobble/dataflow/fields/`. `trace.py` holds the walk: a per-program store slice, a stack of open invocations, and a per-node cursor that makes each path take a different arm. `trace_report.py` holds the rendering and the argparse CLI. Nothing existing changes — the walk reuses `transfer.writes_of`, `state.write`, `state.reaching` and `aliases.commarea_aliases` exactly as they are, and never calls `state.join`.

**Tech Stack:** Python 3.11+, stdlib only (`argparse`, `dataclasses`, `functools`, `itertools`, `types.MappingProxyType`), pytest. Existing in-repo: `cobble.dataflow.fields.*`, `cobble.dataflow.srccfg.*`, `cobble.dataflow.layout`, vendored `cobol_asg` / `cobol_memory`.

**Spec:** `docs/superpowers/specs/2026-09-07-path-sampling-trace-design.md` — read it before Task 1. Bead: `red-dragon-forge-nxy`.

## Global Constraints

- **Nothing existing changes.** `fixpoint.py`, `transfer.py`, `state.py`, `aliases.py`, `build_corpus.py`, `query.py` and everything under `srccfg/` are read-only for this plan. `vendor/red-dragon` is never modified. The only edit to an existing file is one line in `cobble/pyproject.toml` (Task 4).
- **`state.join` is never called.** A path has one store; joining is what the fixpoint does and what this walk exists to avoid. If you reach for `join`, the design has been misread.
- **fp-lint must be at zero for both new modules.** No `Optional`, no `X | None`, no `None` defaults, no `is None` / `is not None`, no `Any`, no unfrozen dataclass, no `list.append`/`extend`/`insert`/`pop`/`remove`, no `set.add`/`discard`, no `dict.update`/`setdefault`/`clear`, no subscript assignment or deletion, no augmented assignment, no mutation inside a loop, no deep nesting, no static method, no `list[...]`/`dict[...]` parameter annotations (use `Sequence`/`Mapping`), no variable reassignment, no inline suppression comments. Check with `uv run --no-sync python -m python_fp_lint check cobble/cobble/dataflow/fields/`.
- **Black, line length 88. Ruff clean.** `uv run --no-sync python -m black cobble/cobble cobble/tests` then `uv run --no-sync python -m ruff check --output-format=concise cobble/cobble/dataflow/fields cobble/tests/dataflow/fields`.
- **`lint-imports` stays at 11 kept / 0 broken.** The new modules may import `cobble.dataflow.*`, `cobol_asg`, `cobol_memory`. Nothing from `cicada`, `squall` or `jackal`. Nothing may import the new modules except each other and the test.
- **Never run `make lint`.** It fails with 433 pre-existing pyright errors, tracked as bead `kvs`. It is not a gate for this work.
- **No corpus identifier in any tracked file, commit messages included.** Test fixtures use `TPROGA`, `TPROGB`, `WS-*`, `SUB-*`. `DFHCOMMAREA` is a standard CICS name and is fine. A pre-commit terminology guard enforces this; if it fires, rename the token, do not whitelist it.
- **Comments are a smell.** A comment survives only by carrying an external constraint, a non-obvious why, or a reference to an issue or standard. Docstrings carry the reasoning; inline comments almost never do.
- **No test counts in living documentation.** The README section in Task 4 describes what the tool does, never how many tests cover it.
- **Baselines to compare against, not to "get to green" against.** Before Task 1, record them: the full cobble suite is **1196 passed, 12 skipped**; fp-lint has **9 pre-existing** findings (`rows.py` 2, `fixpoint.py` 7); ruff's one known pre-existing finding is a `PLW1510` in `test_fields_build_corpus.py:201`, which the default rule set the root `pyproject.toml` leaves in force does not report. The gate is **nothing in the new files**, not a total — a new finding is a regression even though the totals look small either way.
- **Environment.** No bare `python` — always `uv run --no-sync python`. `uv`, `git` and `pre-commit` need `dangerouslyDisableSandbox: true`. macOS has no `timeout`. `git commit` can exceed a 120 s Bash timeout; allow 400 s.

---

## File Structure

| File | Responsibility |
|---|---|
| `cobble/cobble/dataflow/fields/trace.py` | **New.** The walk. Value objects (`Budget`, `Window`, `Frame`, `Dep`, `DeadEnd`, `Coverage`, `Trace`, `Loaded`), the per-program store, window rebasing, one path's stepping rules, call crossing, and the sampler. Knows nothing about text. |
| `cobble/cobble/dataflow/fields/trace_report.py` | **New.** `Trace` to text, and the argparse CLI. Knows nothing about paths. Separate because `query.py` in this same directory is the counter-example: it reached a thousand lines by holding a walk and its output format together. |
| `cobble/pyproject.toml` | **Modify.** One `[project.scripts]` line: `cobble-fields-trace`. |
| `cobble/README.md` | **Modify.** One short section under the field-dataflow material. |
| `cobble/tests/dataflow/fields/test_fields_trace.py` | **New.** Hand-built CFGs for the stack rules (no JVM), plus one real two-member parse for the crossing (skips without the bridge JAR). |

The seam that makes the stack rules testable without a parse is a **loader function**: `traced(program, loader, budget)` walks against any `Callable[[str], Loaded]`, and `sampled(program, asg_dir, budget)` is the thin wrapper that supplies the memoised on-disk one. No monkeypatching of private names anywhere in the test.

---

### Task 1: Value objects, the per-program store, and window rebasing

The arithmetic that makes a commarea a byte identity rather than a flow. Pure functions over `FieldExtent` and `State` — no CFG, no ASG, no I/O — so it is testable on its own and everything later builds on it.

**Files:**
- Create: `cobble/cobble/dataflow/fields/trace.py`
- Test: `cobble/tests/dataflow/fields/test_fields_trace.py`

**Interfaces:**
- Consumes: `cobble.dataflow.fields.state.{State, Source, EMPTY, write}`, `cobble.dataflow.fields.extent_text.byte_range`, `cobble.dataflow.fields.side_tables.CommareaAlias`, `cobble.dataflow.fields.aliases.NO_EXTENT`, `cobol_memory.field_extent.{FieldExtent, Precision}`, `cobol_memory.region_id.RegionId`.
- Produces, for Tasks 2–4:
  - `Budget(paths: int = 200, coverage: float = 1.0, max_depth: int = 5000)`, and `DEFAULT_BUDGET: Budget`
  - `DEFAULT_PATHS: int`, `DEFAULT_COVERAGE: float`, `DEFAULT_MAX_DEPTH: int`
  - `Window(caller: str, caller_extent: FieldExtent, callee_extent: FieldExtent, known: bool)`, and `NO_WINDOW: Window`
  - `Dep(program: str, node: str, target: FieldExtent, origin: str, source: FieldExtent, definers: tuple[str, ...], via: str)`
  - `DeadEnd(program: str, node: str, transfer: str, callee: str, reason: str)`
  - `Coverage(taken: frozenset[tuple[str, str, str]], total: int, programs: frozenset[str])` with a `fraction: float` property
  - `Trace(deps: frozenset[Dep], dead_ends: frozenset[DeadEnd], paths: int, coverage: Coverage)`
  - `_extent_at(text: str, program: str) -> FieldExtent`
  - `_window(row: CommareaAlias, callee: str) -> Window`
  - `_rebased(extent: FieldExtent, source: FieldExtent, target: FieldExtent) -> FieldExtent`
  - `_seeded(held: State, source: FieldExtent, target: FieldExtent) -> State`

- [ ] **Step 1: Write the failing tests**

Create `cobble/tests/dataflow/fields/test_fields_trace.py` with exactly this content:

```python
"""The path walk: its stack rules on graphs built here, its crossing on a real parse.

Two halves, because they fail for different reasons. The stack rules -- unroll a
loop once, let a paragraph PERFORMed twice run twice, take only your own RETURN
edge -- are decided by the walk alone, so they are asserted against CFGs written
out in this file where every node id is chosen here. The crossing is decided by
the bridge's layout arithmetic, which no hand-built extent can stand in for: a
rebase that is off by a byte agrees with a fixture and disagrees with COBOL.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from cobble.dataflow.fields.side_tables import CommareaAlias
from cobble.dataflow.fields.state import Source, write
from cobble.dataflow.fields.trace import (
    NO_WINDOW,
    _extent_at,
    _rebased,
    _seeded,
    _window,
)
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"


def _extent(region: RegionId, start: int, length: int, name: str) -> FieldExtent:
    return FieldExtent(
        region=region,
        start=start,
        length=length,
        precision=Precision.EXACT,
        field_name=name,
    )


def _sourced(name: str, node: str) -> frozenset[Source]:
    return frozenset(
        {
            Source(
                origin="",
                extent=_extent(RegionId.WORKING_STORAGE, 0, 4, name),
                node=node,
            )
        }
    )


def test_the_region_text_round_trips_through_the_enum_that_wrote_it():
    """``FieldExtent.__str__`` spells the region as the enum's own value, so
    ``RegionId(text)`` is the way back and no mapping table is needed."""
    found = _extent_at("WS-AREA@working_storage[8:20]", "TPROGA")

    assert found.region is RegionId.WORKING_STORAGE
    assert (found.start, found.length) == (8, 12)
    assert found.field_name == "WS-AREA"
    assert found.precision is Precision.EXACT


def test_a_text_that_is_not_an_extent_parses_to_a_length_of_nothing():
    """A dead-end alias row carries a reason where the extents would be. Zero
    length is what makes that safe to carry in an extent-shaped slot: may_alias
    and must_cover both reject a non-positive length."""
    assert not _extent_at("", "TPROGA").length
    assert not _extent_at("callee-not-in-cache", "TPROGA").length


def test_a_row_carrying_a_reason_yields_no_window():
    row = CommareaAlias(
        caller="TPROGA", node="MAIN-PARA/2", transfer="LINK", reason="dynamic-target"
    )

    assert _window(row, "") == NO_WINDOW


def test_a_row_carrying_both_layouts_yields_the_window_they_share():
    row = CommareaAlias(
        caller="TPROGA",
        node="MAIN-PARA/2",
        transfer="LINK",
        callee="TPROGB",
        caller_extent="WS-AREA@working_storage[8:20]",
        callee_extent="DFHCOMMAREA@linkage[0:12]",
        returns=True,
    )
    found = _window(row, "TPROGB")

    assert found.known
    assert found.caller == "TPROGA"
    assert found.caller_extent.start == 8
    assert found.callee_extent.region is RegionId.LINKAGE
    assert found.caller_extent.length == found.callee_extent.length


def test_a_rebase_shifts_by_the_two_windows_offsets_and_renames_the_bytes():
    """Caller byte ``source.start + k`` IS callee byte ``target.start + k``. The
    rebased extent takes the target record's name, because spelling the caller's
    field name inside the callee's region names a field that is not there."""
    window_in = _extent(RegionId.WORKING_STORAGE, 8, 12, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 12, "DFHCOMMAREA")
    found = _rebased(_extent(RegionId.WORKING_STORAGE, 12, 4, "WS-B"), window_in, window_out)

    assert found.region is RegionId.LINKAGE
    assert (found.start, found.length) == (4, 4)
    assert found.field_name == "DFHCOMMAREA"


def test_a_rebase_clips_to_the_window_rather_than_claiming_past_it():
    """Bytes outside the shared window are not shared storage. A rebase that kept
    them would report the callee as addressing the caller's whole record."""
    window_in = _extent(RegionId.WORKING_STORAGE, 8, 8, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 8, "DFHCOMMAREA")
    found = _rebased(_extent(RegionId.WORKING_STORAGE, 4, 12, "WS-WIDE"), window_in, window_out)

    assert (found.start, found.length) == (0, 8)


def test_seeding_carries_provenance_across_unchanged_and_credits_no_node():
    """A binding, not a flow: nothing converts and nothing pads, so the sources
    cross intact and no node is recorded as having written them."""
    window_in = _extent(RegionId.WORKING_STORAGE, 0, 8, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 8, "DFHCOMMAREA")
    held = write(
        {},
        _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-KEY"),
        _sourced("WS-SEED", "TPROGA/MAIN-PARA/0"),
    )
    found = _seeded(held, window_in, window_out)

    ((extent, sources),) = tuple(found.items())
    assert extent.region is RegionId.LINKAGE
    assert (extent.start, extent.length) == (0, 4)
    assert tuple(one.node for one in sources) == ("TPROGA/MAIN-PARA/0",)


def test_seeding_leaves_behind_whatever_the_window_does_not_reach():
    """Only the shared bytes are bound. Storage outside the commarea is the
    caller's alone and has no address in the callee at all."""
    window_in = _extent(RegionId.WORKING_STORAGE, 0, 8, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 8, "DFHCOMMAREA")
    held = write(
        {},
        _extent(RegionId.WORKING_STORAGE, 40, 4, "WS-PRIVATE"),
        _sourced("WS-SEED", "TPROGA/MAIN-PARA/0"),
    )

    assert not _seeded(held, window_in, window_out)


def test_two_caller_extents_clipping_to_one_window_range_keep_both_provenances():
    """A union, not a dict comprehension. Two extents can clip to the same shared
    range -- a record and a redefinition of it -- and keying a comprehension on the
    rebased extent would drop one of them silently."""
    window_in = _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 4, "DFHCOMMAREA")
    first = write(
        {},
        _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-KEY"),
        _sourced("WS-SEED", "TPROGA/MAIN-PARA/0"),
    )
    both = {
        **first,
        replace(_extent(RegionId.WORKING_STORAGE, 0, 4, "WS-ALIAS")): _sourced(
            "WS-OTHER", "TPROGA/MAIN-PARA/1"
        ),
    }
    found = _seeded(both, window_in, window_out)

    ((_extent_out, sources),) = tuple(found.items())
    assert {one.node for one in sources} == {
        "TPROGA/MAIN-PARA/0",
        "TPROGA/MAIN-PARA/1",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_trace.py -q`

Expected: collection error — `ModuleNotFoundError: No module named 'cobble.dataflow.fields.trace'`.

- [ ] **Step 3: Write the implementation**

Create `cobble/cobble/dataflow/fields/trace.py`:

```python
"""One concrete path at a time, with a real byte store and no join anywhere.

The fixpoint next door answers "could these bytes flow" over every path at once,
which costs it two things a path gets for free. A PERFORMed paragraph returns to
every caller, because ``srccfg/build.py`` lowers it once and gives it one RETURN
edge per site; on a path the stack says which site is yours. And a call is a
wall, because ``transfer`` credits a commarea to ``%CALL:<name>`` and knows
nothing of the callee; on a path a LINK is a step into the callee, and the
write-back needs no mechanism at all -- in a byte-addressable model the two sides
are the same storage.

What it gives up is soundness in the other direction. Every dependency here was
witnessed by an actual path, and absence means "not sampled", never "does not
exist". The two walks answer different questions and this one replaces nothing.

The store is keyed by program OUTSIDE the extent, because ``RegionId`` is an enum
of six DATA DIVISION sections and carries no program: two members'
``WORKING_STORAGE@100`` are the same ``FieldExtent``, and ``may_alias`` would
conflate them. Slicing by program keeps every may_alias/must_cover comparison
inside one program's storage, where those predicates are sound, and needs no
change to ``cobol_memory``, which is vendored.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from cobble.dataflow.fields.aliases import NO_EXTENT
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fields.side_tables import CommareaAlias
from cobble.dataflow.fields.state import State
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

DEFAULT_PATHS = 200
DEFAULT_COVERAGE = 1.0
DEFAULT_MAX_DEPTH = 5000


@dataclass(frozen=True)
class Budget:
    """When to stop sampling, and how long one path may be.

    ``max_depth`` is a cost bound, not a correctness one: the re-entry rule
    already makes every path finite, but a program with thousands of paragraphs
    reachable in sequence can still make one path long enough to be useless.
    """

    paths: int = DEFAULT_PATHS
    coverage: float = DEFAULT_COVERAGE
    max_depth: int = DEFAULT_MAX_DEPTH


DEFAULT_BUDGET = Budget()


@dataclass(frozen=True)
class Window:
    """A commarea's two ends: the caller's bytes and the callee's, same length.

    ``known`` False is a call site with no window to bind -- a dynamic target, a
    callee absent from the cache, an operand naming no field. A sentinel rather
    than an absent value, so a caller compares windows the same way everywhere.
    """

    caller: str = ""
    caller_extent: FieldExtent = NO_EXTENT
    callee_extent: FieldExtent = NO_EXTENT
    known: bool = False


NO_WINDOW = Window()


@dataclass(frozen=True)
class Dep:
    """One statement's write, one source of it, and where that source was defined.

    ``origin`` is non-empty exactly when the source is not storage, and
    ``definers`` is then empty -- nothing in any program wrote a literal or a file
    record. ``definers`` are program-qualified node ids, which is what lets a
    definer that crossed a call name the member it is in. ``via`` is the call site
    this program was entered through, innermost when nested, and empty in the
    program the trace started from.
    """

    program: str
    node: str
    target: FieldExtent
    origin: str
    source: FieldExtent
    definers: tuple[str, ...]
    via: str


@dataclass(frozen=True)
class DeadEnd:
    """A call site a sampled path arrived at and could not cross.

    Its own stream rather than a field on ``Dep``, because there is no write to
    hang it on: the path did not enter the callee, so nothing was witnessed there.
    """

    program: str
    node: str
    transfer: str
    callee: str
    reason: str


@dataclass(frozen=True)
class Coverage:
    """Branch edges taken, against every branch edge in the programs entered.

    The denominator comes from the ``Cfg``s, never from what the walk produced:
    the 3ao post-mortem found an acceptance suite passing while its walk reached
    18% of nodes, because the denominator was derived from the answer.
    """

    taken: frozenset[tuple[str, str, str]] = frozenset()
    total: int = 0
    programs: frozenset[str] = frozenset()

    @property
    def fraction(self) -> float:
        """One, not zero, for a program with no branches: there is nothing left to
        sample, so a target of 1.0 is met rather than unreachable."""
        return len(self.taken) / self.total if self.total else 1.0


@dataclass(frozen=True)
class Trace:
    """Everything the sampled paths witnessed, deduplicated.

    No path ids. The report is the union over paths, and an id would only label a
    route the report does not print.
    """

    deps: frozenset[Dep] = frozenset()
    dead_ends: frozenset[DeadEnd] = frozenset()
    paths: int = 0
    coverage: Coverage = Coverage()


def _extent_at(text: str, program: str) -> FieldExtent:
    """The artefact's wire form back to an extent, or a length of nothing.

    ``FieldExtent.__str__`` spells the region as ``RegionId``'s own value, so the
    enum constructor is the way back and there is no mapping to keep in step.
    """
    found = byte_range(text, program)
    if not found.known:
        return NO_EXTENT
    return FieldExtent(
        region=RegionId(found.region),
        start=found.start,
        length=found.length,
        precision=Precision.EXACT if found.exact else Precision.CLAMPED,
        field_name=found.name,
    )


def _window(row: CommareaAlias, callee: str) -> Window:
    """The two ends of one site's shared storage, or NO_WINDOW.

    A zero-length end is not a narrow window, it is no window: overlap needs
    ``start < other.end``, so nothing can ever be bound through ``[n:n]``.
    """
    caller = _extent_at(row.caller_extent, row.caller)
    landed = _extent_at(row.callee_extent, callee)
    if not caller.length or not landed.length:
        return NO_WINDOW
    return Window(
        caller=row.caller, caller_extent=caller, callee_extent=landed, known=True
    )


def _rebased(
    extent: FieldExtent, source: FieldExtent, target: FieldExtent
) -> FieldExtent:
    """``extent``'s overlap with ``source``, at the same offset inside ``target``.

    Clipped to the window, because the bytes outside it are not shared storage and
    a rebase that kept them would claim the callee addresses the caller's whole
    record. Named for ``target``: spelling the caller's field name inside the
    callee's region names a field that is not declared there.
    """
    start = max(extent.start, source.start)
    end = min(extent.end, source.end)
    return replace(
        extent,
        region=target.region,
        start=target.start + start - source.start,
        length=end - start,
        field_name=target.field_name,
    )


def _seeded(held: State, source: FieldExtent, target: FieldExtent) -> State:
    """Every extent overlapping ``source``, rebased onto ``target``, provenance kept.

    A binding, not a flow: caller byte ``source.start + k`` *is* callee byte
    ``target.start + k``, so the sources carry across unchanged and no node is
    credited with a write.

    Unioned by rebased extent rather than built as a comprehension over it, because
    two distinct extents can clip to the same shared range -- a record and a
    redefinition of it -- and a comprehension keyed on the result would drop one of
    them silently.
    """
    bound = tuple(
        (_rebased(extent, source, target), sources)
        for extent, sources in held.items()
        if extent.may_alias(source)
    )
    keys = tuple(dict.fromkeys(extent for extent, _ in bound))
    return {
        key: frozenset(
            one for extent, sources in bound if extent == key for one in sources
        )
        for key in keys
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_trace.py -q`

Expected: PASS, 9 tests.

- [ ] **Step 5: Run the gates**

```bash
cd cobble
uv run --no-sync python -m black cobble/dataflow/fields/trace.py tests/dataflow/fields/test_fields_trace.py
uv run --no-sync python -m python_fp_lint check cobble/dataflow/fields/
uv run --no-sync python -m ruff check --output-format=concise cobble/dataflow/fields tests/dataflow/fields
cd .. && uv run --no-sync lint-imports
```

Expected: black reformats or reports unchanged; fp-lint reports exactly the 9 pre-existing findings in `rows.py` and `fixpoint.py` and none in `trace.py`; ruff reports exactly the 1 pre-existing `PLW1510`; lint-imports reports 11 kept / 0 broken.

- [ ] **Step 6: Commit**

```bash
git add cobble/cobble/dataflow/fields/trace.py cobble/tests/dataflow/fields/test_fields_trace.py
git commit -m "feat(cobble): bind a commarea window by rebasing bytes, not by naming fields"
```

---

### Task 2: One path — the stepping rules, the stack, and the cursor

The walk proper, against an injected loader so the stack rules can be asserted on graphs written in the test. No ASG reading and no crossing yet: a `Loaded` with no alias rows makes every node an ordinary edge choice.

**Files:**
- Modify: `cobble/cobble/dataflow/fields/trace.py` (append; the Task 1 definitions stay as they are)
- Test: `cobble/tests/dataflow/fields/test_fields_trace.py` (append)

**Interfaces:**
- Consumes from Task 1: `Budget`, `DEFAULT_BUDGET`, `Window`, `NO_WINDOW`, `Dep`, `DeadEnd`, `Coverage`, `Trace`.
- Consumes existing: `cobble.dataflow.fields.state.{EMPTY, Source, State, reaching, write}`, `cobble.dataflow.fields.transfer.{Statement, Write, writes_of}`, `cobble.dataflow.fields.extent.{CellIndex, cell_index}`, `cobble.dataflow.srccfg.cfg.{Cfg, Edge, EdgeKind, NodeKind}`.
- Produces, for Tasks 3–4:
  - `Loaded(program: str, cfg: Cfg, statements: Mapping[str, Statement], index: CellIndex, entry: str, aliases: Mapping[str, tuple[CommareaAlias, ...]], reason: str)`
  - `NO_CFG: Cfg`, `NO_INDEX: CellIndex`, `NO_STATEMENTS`, `NO_ALIASES`, `NO_STORE`, `NO_CURSORS`
  - `Loader = Callable[[str], Loaded]`
  - `Frame(program: str, site: str, resume: str, crossing: bool, returns: bool, window: Window, visited: frozenset[str])`
  - `traced(program: str, loader: Loader, budget: Budget = DEFAULT_BUDGET) -> Trace`

- [ ] **Step 1: Write the failing tests**

Append to `cobble/tests/dataflow/fields/test_fields_trace.py`. Also add these names to the existing `from cobble.dataflow.fields.trace import (...)` block: `Budget`, `Loaded`, `traced`, `visited_order`. And add this import line: `from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind`.

```python
def _node(node_id: str, kind: NodeKind = NodeKind.NOP) -> Node:
    return Node(id=node_id, kind=kind, paragraph=node_id.split("/")[0])


def _edge(source: str, target: str, kind: EdgeKind = EdgeKind.FLOW) -> Edge:
    return Edge(source=source, target=target, kind=kind)


def _loader(*programs: Loaded):
    """A loader over programs written out here, which is the seam that lets the
    stack rules be asserted without a parse."""
    held = {one.program: one for one in programs}
    return lambda program: held[program]


def _only(program: str, nodes, edges, entry: str) -> Loaded:
    return Loaded(
        program=program,
        cfg=Cfg(program=program, nodes=tuple(nodes), edges=tuple(edges)),
        entry=entry,
    )


LOOP = _only(
    "TPROGA",
    (
        _node("P/0"),
        _node("P/1", NodeKind.TEST),
        _node("P/2"),
        _node("P/3"),
    ),
    (
        _edge("P/0", "P/1"),
        _edge("P/1", "P/2", EdgeKind.TRUE),
        _edge("P/1", "P/3", EdgeKind.FALSE),
        _edge("P/2", "P/1"),
    ),
    "P/0",
)
"""A test with a body that loops back to it and an exit that does not."""


def test_a_loop_body_runs_once_and_then_the_walk_leaves():
    """The back edge targets a node the open frame has already run, so it is
    refused: the body runs once and the exit edge is taken. That is the
    unroll-once decision, and it is the same rule that stops a recursive PERFORM.
    """
    found = traced("TPROGA", _loader(LOOP), Budget(paths=1, coverage=1.0))

    assert found.paths == 1
    assert found.coverage.total == 2


def test_sampling_takes_a_different_arm_on_the_next_path_and_reaches_full_coverage():
    """The cursor is per (program, node) and global to the run, so path 1 takes a
    test's first arm and path 2 its second. Deterministic and reproducible, which
    is why no random seed appears anywhere in this walk.
    """
    found = traced("TPROGA", _loader(LOOP), Budget(paths=8))

    assert found.coverage.taken == {
        ("TPROGA", "P/1", "TRUE"),
        ("TPROGA", "P/1", "FALSE"),
    }
    assert found.coverage.fraction == 1.0


def test_sampling_stops_as_soon_as_the_coverage_target_is_met():
    """Both arms of the one test are taken by the second path, so a target of 1.0
    is met there and the remaining budget goes unspent."""
    found = traced("TPROGA", _loader(LOOP), Budget(paths=50, coverage=1.0))

    assert found.paths == 2


def test_a_lower_coverage_target_stops_earlier_still():
    found = traced("TPROGA", _loader(LOOP), Budget(paths=50, coverage=0.5))

    assert found.paths == 1


TWICE = _only(
    "TPROGA",
    (
        _node("M/0", NodeKind.CALL),
        _node("M/1", NodeKind.CALL),
        _node("M/2"),
        _node("S/0"),
        _node("S/end"),
    ),
    (
        _edge("M/0", "M/1"),
        _edge("M/0", "S/0", EdgeKind.PERFORM),
        _edge("M/1", "M/2"),
        _edge("M/1", "S/0", EdgeKind.PERFORM),
        _edge("S/0", "S/end"),
        _edge("S/end", "M/1", EdgeKind.RETURN),
        _edge("S/end", "M/2", EdgeKind.RETURN),
    ),
    "M/0",
)
"""Two PERFORMs of one paragraph, so ``build.py`` gave it two RETURN edges."""


def test_a_paragraph_performed_twice_in_one_path_runs_both_times():
    """Its frame took its visited nodes with it when it returned, so the second
    PERFORM starts clean. Two arms of one paragraph in one trace is real: the two
    sites genuinely can behave differently.
    """
    found = traced("TPROGA", _loader(TWICE), Budget(paths=1))

    assert found.paths == 1
    assert not found.dead_ends


def test_only_the_return_edge_back_to_your_own_caller_is_taken():
    """The precision the fixpoint cannot have. ``build.py`` calls two RETURN edges
    from one paragraph "the deliberate imprecision"; a stack knows which is yours.

    Asserted by the node order, which ``Trace`` cannot give: it is the union over
    paths, so the route is exactly what it discards. Taking the wrong RETURN edge
    from the first PERFORM would skip M/1, and the second PERFORM's own return
    would never run.
    """
    assert visited_order("TPROGA", _loader(TWICE), Budget(paths=1)) == (
        "M/0",
        "S/0",
        "S/end",
        "M/1",
        "S/0",
        "S/end",
        "M/2",
    )


FALLEN = _only(
    "TPROGA",
    (_node("M/0"), _node("M/end"), _node("S/0"), _node("S/end")),
    (
        _edge("M/0", "M/end"),
        _edge("M/0", "S/0", EdgeKind.PERFORM),
        _edge("M/end", "S/0", EdgeKind.FALLTHRU),
        _edge("S/0", "S/end"),
        _edge("S/end", "M/end", EdgeKind.RETURN),
    ),
    "M/0",
)
"""A paragraph both PERFORMed and fallen into, which is the shape that makes a
RETURN edge wrong: reached by falling through, its caller's resume point is none
of its business."""


def test_a_paragraph_fallen_into_rather_than_performed_takes_no_return_edge():
    """No frame's resume point matches, so every RETURN edge is dropped and the
    path ends where the paragraph does -- rather than jumping to a caller that is
    not on the stack."""
    assert visited_order("TPROGA", _loader(FALLEN), Budget(paths=1)) == (
        "M/0",
        "S/0",
        "S/end",
        "M/end",
        "S/0",
        "S/end",
    )


def test_coverage_counts_branch_edges_and_not_every_edge_walked():
    """A TEST has exactly two out-edges and everything else has one route through
    it, so counting the rest would make the percentage a node count wearing a
    branch's name."""
    found = traced("TPROGA", _loader(TWICE), Budget(paths=1))

    assert found.coverage.total == 0
    assert found.coverage.programs == {"TPROGA"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_trace.py -q`

Expected: collection error — `ImportError: cannot import name 'traced'`.

- [ ] **Step 3: Write the implementation**

Append to `cobble/cobble/dataflow/fields/trace.py`. Extend the import block at the top with:

```python
from collections.abc import Callable, Mapping, Sequence
from functools import reduce
from itertools import repeat

from cobble.dataflow.fields.extent import CellIndex, cell_index
from cobble.dataflow.fields.state import EMPTY, Source, reaching, write
from cobble.dataflow.fields.transfer import Statement, Write, writes_of
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, NodeKind
```

(`State` is already imported from Task 1; `dataclass` and `replace` likewise.)

Then append:

```python
NO_CFG = Cfg(program="", nodes=(), edges=())
NO_INDEX = cell_index(())
NO_STATEMENTS: Mapping[str, Statement] = {}
NO_ALIASES: Mapping[str, tuple[CommareaAlias, ...]] = {}
NO_STORE: Mapping[str, State] = {}
NO_CURSORS: Mapping[tuple[str, str], int] = {}


@dataclass(frozen=True)
class Loaded:
    """One program's compiled artefacts, or the reason it cannot be entered.

    Built once per program per process and reused across every path, because a
    parse and a layout cost far more than a walk over them.
    """

    program: str
    cfg: Cfg = NO_CFG
    statements: Mapping[str, Statement] = NO_STATEMENTS
    index: CellIndex = NO_INDEX
    entry: str = ""
    aliases: Mapping[str, tuple[CommareaAlias, ...]] = NO_ALIASES
    reason: str = ""


Loader = Callable[[str], Loaded]


@dataclass(frozen=True)
class Frame:
    """One open invocation: where it resumes, and which nodes it has already run.

    Popped whole on return, which is what makes the re-entry rule right in all
    three of its cases. A paragraph's visited nodes leave with its frame, so a
    second PERFORM of the same paragraph starts clean; a frame still open still
    forbids re-entry, which covers a loop's back edge, a recursive PERFORM and a
    LINK cycle with one rule.
    """

    program: str
    site: str = ""
    resume: str = ""
    crossing: bool = False
    returns: bool = False
    window: Window = NO_WINDOW
    visited: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _Walk:
    """One path, mid-flight. Threaded, never mutated."""

    node: str
    stack: tuple[Frame, ...]
    store: Mapping[str, State] = NO_STORE
    cursors: Mapping[tuple[str, str], int] = NO_CURSORS
    deps: frozenset[Dep] = frozenset()
    dead_ends: frozenset[DeadEnd] = frozenset()
    taken: frozenset[tuple[str, str, str]] = frozenset()
    entered: frozenset[str] = frozenset()
    order: tuple[str, ...] = ()
    running: bool = True

    @property
    def frame(self) -> Frame:
        """The innermost open invocation. The stack is never empty while running:
        the root of a path is a frame like any other."""
        return self.stack[-1]

    @property
    def program(self) -> str:
        return self.frame.program

    @property
    def via(self) -> str:
        """The call site this program was entered through, innermost when nested."""
        crossings = tuple(one for one in self.stack if one.crossing)
        if not crossings:
            return ""
        return f"{crossings[-1].window.caller}/{crossings[-1].site}"


@dataclass(frozen=True)
class _Run:
    """The sampler's accumulator: the trace so far, and the cursors that make the
    next path differ from the last one."""

    trace: Trace = Trace()
    cursors: Mapping[tuple[str, str], int] = NO_CURSORS


def _open(stack: Sequence[Frame], program: str, node: str) -> bool:
    """The re-entry rule: an edge back to a node an open frame has already run."""
    return any(one.program == program and node in one.visited for one in stack)


def _marked(stack: tuple[Frame, ...], node: str) -> tuple[Frame, ...]:
    return (*stack[:-1], replace(stack[-1], visited=stack[-1].visited | {node}))


def _qualified(writes: Sequence[Write], program: str) -> tuple[Write, ...]:
    """``state.Source`` carries a bare node id, and a definer that crossed a call
    is in another member -- so every id going into the store is program-qualified.
    """
    return tuple(
        replace(
            entry,
            sources=frozenset(
                replace(one, node=f"{program}/{one.node}") for one in entry.sources
            ),
        )
        for entry in writes
    )


def _writes(walk: _Walk, loaded: Loaded) -> tuple[Write, ...]:
    """Whatever this node's statement writes, or nothing where there is no statement.

    Membership rather than a ``get`` that may come back empty-handed: a LABEL or a
    NOP has no statement at all, which is not the same fact as a statement that
    writes nothing.
    """
    if walk.node not in loaded.statements:
        return ()
    return _qualified(
        writes_of(loaded.statements[walk.node], walk.node, loaded.index), walk.program
    )


def _definers(held: State, source: Source) -> tuple[str, ...]:
    """Where the source's bytes were last written on this path.

    Empty for a synthetic origin: nothing in any program wrote a literal or a file
    record, and naming a definer for one would invent a flow.
    """
    if source.origin:
        return ()
    return tuple(sorted({one.node for one in reaching(held, source.extent)}))


def _witnessed(
    walk: _Walk, held: State, writes: Sequence[Write]
) -> frozenset[Dep]:
    """One dependency per (target, source) pair, definers read out of the slice as
    it stood BEFORE the statement.

    ``reaching`` here is the whole reason the store exists. ``writes_of`` builds a
    ``Source`` from the source operand's own extents and never consults the state,
    so without this read the walk would only restate the statement it just ran.
    """
    return frozenset(
        Dep(
            program=walk.program,
            node=walk.node,
            target=entry.target,
            origin=one.origin,
            source=one.extent,
            definers=_definers(held, one),
            via=walk.via,
        )
        for entry in writes
        for one in entry.sources
    )


def _applied(held: State, writes: Sequence[Write]) -> State:
    return reduce(
        lambda state, entry: write(state, entry.target, entry.sources), writes, held
    )


def _ran(walk: _Walk, loaded: Loaded) -> _Walk:
    """This node's statement against this program's slice, and what it witnessed."""
    held = walk.store.get(walk.program, EMPTY)
    writes = _writes(walk, loaded)
    return replace(
        walk,
        stack=_marked(walk.stack, walk.node),
        store={**walk.store, walk.program: _applied(held, writes)},
        deps=walk.deps | _witnessed(walk, held, writes),
        entered=walk.entered | {walk.program},
        order=(*walk.order, walk.node),
    )


def _sequel(cfg: Cfg, node: str) -> str:
    """Where a call or a PERFORM continues once it comes back.

    This node's own FLOW edge, which ``build.py`` keeps even on a PERFORM node --
    purely so the paragraph's RETURN targets can be computed from it.
    """
    return next(
        (edge.target for edge in cfg.successors(node) if edge.kind is EdgeKind.FLOW),
        "",
    )


def _return_edge(walk: _Walk, edges: Sequence[Edge]) -> tuple[Edge, ...]:
    """The one RETURN edge going back to the innermost frame's own resume point.

    The first path-insensitivity cost paid off: ``build.py`` gives a paragraph one
    RETURN edge per PERFORM site and the fixpoint takes them all, because only a
    stack knows which site is yours. A crossing frame is excluded because a RETURN
    edge belongs to a PERFORM, and matching one against a callee's resume point
    would be a node-id coincidence rather than a return.
    """
    if walk.frame.crossing:
        return ()
    return tuple(
        one
        for one in edges
        if one.kind is EdgeKind.RETURN and one.target == walk.frame.resume
    )[:1]


def _admissible(walk: _Walk, edges: Sequence[Edge]) -> tuple[Edge, ...]:
    """Everything left once the stack has had its say.

    PERFORM edges are gone because a refused one means the paragraph is skipped and
    this node's own FLOW edge is the continuation. RETURN edges are gone because
    the path reached this node without performing it -- by falling through -- and
    its callers' resume points are none of its business.
    """
    return tuple(
        one
        for one in edges
        if one.kind is not EdgeKind.PERFORM
        and one.kind is not EdgeKind.RETURN
        and not _open(walk.stack, walk.program, one.target)
    )


def _branch(
    loaded: Loaded, node: str, edge: Edge
) -> frozenset[tuple[str, str, str]]:
    """Coverage counts branch edges only.

    A TEST has exactly two out-edges and everything else has one route through it,
    so counting the rest would make the percentage a node count wearing a branch's
    name.
    """
    if loaded.cfg.node(node).kind is not NodeKind.TEST:
        return frozenset()
    return frozenset({(loaded.program, node, edge.kind.value)})


def _sampled(walk: _Walk, loaded: Loaded, edges: Sequence[Edge]) -> _Walk:
    """One branch, chosen by this node's cursor, which advances across paths.

    The cursor is per (program, node) and global to the run, so path 1 takes a
    node's first arm and path 2 its second. Deterministic and reproducible, which
    is why no random seed appears anywhere here.
    """
    if not edges:
        return _ended(walk)
    key = (walk.program, walk.node)
    seen = walk.cursors.get(key, 0)
    chosen = edges[seen % len(edges)]
    return replace(
        walk,
        node=chosen.target,
        cursors={**walk.cursors, key: seen + 1},
        taken=walk.taken | _branch(loaded, walk.node, chosen),
    )


def _performed(walk: _Walk, loaded: Loaded, edge: Edge) -> _Walk:
    return replace(
        walk,
        node=edge.target,
        stack=(
            *walk.stack,
            Frame(
                program=walk.program,
                site=walk.node,
                resume=_sequel(loaded.cfg, walk.node),
            ),
        ),
    )


def _returned(walk: _Walk, edge: Edge) -> _Walk:
    """Pop the frame and continue at the resume point the edge just confirmed."""
    return replace(walk, node=edge.target, stack=walk.stack[:-1])


def _ended(walk: _Walk) -> _Walk:
    """Nowhere left to go, unless a crossing frame owes its caller a return."""
    return replace(walk, running=False)


def _followed(walk: _Walk, loaded: Loaded) -> _Walk:
    """Along an edge. PERFORM and RETURN are decided by the stack; the rest sampled.

    A PERFORM edge is always taken rather than sampled: the FLOW edge beside it is
    a bookkeeping artefact of ``build.py``, and taking it would skip the paragraph.
    A refused PERFORM -- its target is on the stack -- falls through to the FLOW
    edge, which skips the paragraph rather than abandoning the path.
    """
    edges = loaded.cfg.successors(walk.node)
    performed = tuple(one for one in edges if one.kind is EdgeKind.PERFORM)
    if performed and not _open(walk.stack, walk.program, performed[0].target):
        return _performed(walk, loaded, performed[0])
    returned = _return_edge(walk, edges)
    if returned:
        return _returned(walk, returned[0])
    return _sampled(walk, loaded, _admissible(walk, edges))


def _moved(walk: _Walk, loaded: Loaded, loader: Loader) -> _Walk:
    """Where the path goes from here. Task 3 puts call crossing in front of this."""
    return _followed(walk, loaded)


def _stepped(walk: _Walk, loader: Loader) -> _Walk:
    """Run the node the walk stands on, then choose where it goes next."""
    if not walk.running:
        return walk
    loaded = loader(walk.program)
    return _moved(_ran(walk, loaded), loaded, loader)


def _walked(start: _Walk, limit: int, loader: Loader) -> _Walk:
    """Steps until the path ends or ``limit`` nodes have run.

    ``reduce`` over a fixed count rather than a loop with a reassigned accumulator:
    the walk is threaded, and ``_stepped`` returns a finished walk unchanged, so
    the remaining iterations cost one comparison each.
    """
    return reduce(lambda walk, _: _stepped(walk, loader), repeat(None, limit), start)


def _started(program: str, loader: Loader, cursors) -> _Walk:
    return _Walk(
        node=loader(program).entry,
        stack=(Frame(program=program),),
        cursors=cursors,
    )


def _branches(cfg: Cfg) -> int:
    tests = frozenset(node.id for node in cfg.nodes if node.kind is NodeKind.TEST)
    return sum(1 for edge in cfg.edges if edge.source in tests)


def _coverage(before: Coverage, walk: _Walk, loader: Loader) -> Coverage:
    """Taken accumulates; the denominator is recomputed over the programs entered
    so far, so entering a new one raises it rather than flattering the percentage.
    """
    programs = before.programs | walk.entered
    return Coverage(
        taken=before.taken | walk.taken,
        total=sum(_branches(loader(one).cfg) for one in sorted(programs)),
        programs=programs,
    )


def _round(run: _Run, program: str, loader: Loader, budget: Budget) -> _Run:
    """One path, unless the coverage target is already met."""
    if run.trace.paths and run.trace.coverage.fraction >= budget.coverage:
        return run
    walk = _walked(_started(program, loader, run.cursors), budget.max_depth, loader)
    return _Run(
        trace=Trace(
            deps=run.trace.deps | walk.deps,
            dead_ends=run.trace.dead_ends | walk.dead_ends,
            paths=run.trace.paths + 1,
            coverage=_coverage(run.trace.coverage, walk, loader),
        ),
        cursors=walk.cursors,
    )


def traced(program: str, loader: Loader, budget: Budget = DEFAULT_BUDGET) -> Trace:
    """Sample paths from ``program``'s entry until the budget or the coverage target.

    Under-approximate by construction: every dependency here was witnessed by an
    actual path, and absence means "not sampled", never "does not exist".

    Public, and taking a loader rather than a directory, so a caller can hand it
    graphs it built itself. That is the seam the stack rules are asserted through.
    """
    return reduce(
        lambda run, _: _round(run, program, loader, budget),
        repeat(None, budget.paths),
        _Run(),
    ).trace


def visited_order(
    program: str, loader: Loader, budget: Budget = DEFAULT_BUDGET
) -> tuple[str, ...]:
    """The nodes one path ran, in order. ``Trace`` cannot say: it is the union over
    paths, so the route is exactly what it discards."""
    return _walked(
        _started(program, loader, NO_CURSORS), budget.max_depth, loader
    ).order
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_trace.py -q`

Expected: PASS, 17 tests.

- [ ] **Step 5: Run the gates**

```bash
cd cobble
uv run --no-sync python -m black cobble/dataflow/fields/trace.py tests/dataflow/fields/test_fields_trace.py
uv run --no-sync python -m python_fp_lint check cobble/dataflow/fields/
uv run --no-sync python -m ruff check --output-format=concise cobble/dataflow/fields tests/dataflow/fields
```

Expected: fp-lint reports exactly the 9 pre-existing findings and none in `trace.py`; ruff reports nothing in the new files. `_moved` carries a `loader` parameter it does not use until Task 3, which is deliberate — the signature is the seam Task 3 fills in. The root `pyproject.toml` sets no ruff `select`, so the default rule set (`E4`/`E7`/`E9`/`F`) is in force and `ARG001` is not among it. If a future rule set does flag it, fold Task 3's crossing branch in early rather than adding a suppression.

- [ ] **Step 6: Commit**

```bash
git add cobble/cobble/dataflow/fields/trace.py cobble/tests/dataflow/fields/test_fields_trace.py
git commit -m "feat(cobble): interpret one concrete path, taking only your own return edge"
```

---

### Task 3: Crossing a call, and reading programs off the ASG cache

The payoff. A `LINK` becomes a step into the callee with the shared window bound; the callee's write-back needs no mechanism because the two sides were the same bytes. Plus the on-disk loader, so `sampled` works against a real parse.

**Files:**
- Modify: `cobble/cobble/dataflow/fields/trace.py` (append, and replace the `_moved` stub from Task 2)
- Test: `cobble/tests/dataflow/fields/test_fields_trace.py` (append)

**Interfaces:**
- Consumes from Tasks 1–2: `Window`, `NO_WINDOW`, `_window`, `_seeded`, `Loaded`, `Loader`, `Frame`, `_Walk`, `_followed`, `_ended`, `_open`, `_sequel`, `traced`, `Budget`, `Trace`, `DeadEnd`.
- Consumes existing: `cobble.dataflow.fields.aliases.{UNSIZEABLE, commarea_aliases}`, `cobble.dataflow.depgraph.cics_cache.cached_asg_dialect_parsers_registered`, `cobble.dataflow.layout.{UnsizeableFieldError, program_records}`, `cobble.dataflow.srccfg.build.{build_program, label_id, paragraph_order}`, `cobble.dataflow.srccfg.statements.statement_index`, `cobble.dataflow.srccfg.desugar.{LINK_TRANSFER, XCTL_TRANSFER}`, `cobol_asg.asg_types.CobolASG`.
- Produces, for Task 4:
  - `sampled(program: str, asg_dir: Path, budget: Budget = DEFAULT_BUDGET) -> Trace`
  - `loadable(asg_dir: Path, program: str) -> str` — empty when traceable, else the reason
  - `NO_PROCEDURE: str`, `RE_ENTRY: str`, `CROSSING_VERBS: tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

Append to `cobble/tests/dataflow/fields/test_fields_trace.py`. Add `RE_ENTRY`, `sampled` and `loadable` to the trace import block, and add `from cobble.parsing.parse_corpus import Job, parse_one` inside the fixture (not at module scope — it is only needed when the JVM is available).

First, the hand-built half — crossing and dead ends without a parse:

```python
CALLER = _only(
    "TPROGA",
    (_node("M/0"), _node("M/1", NodeKind.CALL), _node("M/2")),
    (_edge("M/0", "M/1"), _edge("M/1", "M/2")),
    "M/0",
)

CALLEE = _only("TPROGB", (_node("S/0"),), (), "S/0")


def _linked(reason: str = "", returns: bool = True) -> CommareaAlias:
    if reason:
        return CommareaAlias(
            caller="TPROGA", node="M/1", transfer="LINK", callee="TPROGB", reason=reason
        )
    return CommareaAlias(
        caller="TPROGA",
        node="M/1",
        transfer="LINK",
        callee="TPROGB",
        caller_extent="WS-AREA@working_storage[0:8]",
        callee_extent="DFHCOMMAREA@linkage[0:8]",
        returns=returns,
    )


def _pair(row: CommareaAlias):
    return _loader(replace(CALLER, aliases={"M/1": (row,)}), CALLEE)


def test_a_link_with_a_window_is_a_step_into_the_callee_and_back():
    """Not a wall. The callee's entry runs, then the caller resumes at the call
    node's own sequel, because ``returns`` is true for LINK."""
    assert visited_order("TPROGA", _pair(_linked()), Budget(paths=1)) == (
        "M/0",
        "M/1",
        "S/0",
        "M/2",
    )


def test_an_xctl_does_not_come_back_so_the_path_ends_in_the_callee():
    assert visited_order(
        "TPROGA", _pair(_linked(returns=False)), Budget(paths=1)
    ) == ("M/0", "M/1", "S/0")


def test_a_site_with_no_window_is_a_dead_end_and_the_callers_path_goes_on():
    """The caller's own path is not over. ``transfer`` has already credited the
    commarea to ``%CALL:<program>`` exactly as the fixpoint does, so ending the
    path here would lose the caller's remaining statements for nothing."""
    found = traced("TPROGA", _pair(_linked(reason="dynamic-target")), Budget(paths=1))

    assert found.dead_ends == {
        DeadEnd(
            program="TPROGA",
            node="M/1",
            transfer="LINK",
            callee="TPROGB",
            reason="dynamic-target",
        )
    }
    assert visited_order(
        "TPROGA", _pair(_linked(reason="dynamic-target")), Budget(paths=1)
    ) == ("M/0", "M/1", "M/2")


def test_a_program_already_on_the_stack_is_not_re_entered():
    """A LINK cycle is the re-entry rule's third case, with no extra machinery: the
    callee's entry node is one an open frame has already run."""
    cyclic = _loader(
        replace(CALLER, aliases={"M/1": (_linked(),)}),
        replace(
            _only(
                "TPROGB",
                (_node("S/0", NodeKind.CALL),),
                (),
                "S/0",
            ),
            aliases={
                "S/0": (
                    CommareaAlias(
                        caller="TPROGB",
                        node="S/0",
                        transfer="LINK",
                        callee="TPROGA",
                        caller_extent="DFHCOMMAREA@linkage[0:8]",
                        callee_extent="WS-AREA@working_storage[0:8]",
                        returns=True,
                    ),
                )
            },
        ),
    )
    found = traced("TPROGA", cyclic, Budget(paths=1))

    assert {one.reason for one in found.dead_ends} == {RE_ENTRY}
    assert visited_order("TPROGA", cyclic, Budget(paths=1)) == (
        "M/0",
        "M/1",
        "S/0",
        "M/2",
    )
```

Then the real-parse half:

```python
TRACE_CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPROGA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-OUT-KEY           PIC X(4).
           05  WS-IN-RESULT         PIC X(4).
       01  WS-SEED                  PIC X(4).
       01  WS-SINK                  PIC X(4).
       01  WS-FLAG                  PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'KKKK' TO WS-SEED.
           IF WS-FLAG = 'Y'
               MOVE WS-SEED TO WS-OUT-KEY
           ELSE
               MOVE 'ZZZZ' TO WS-OUT-KEY
           END-IF.
           PERFORM LINK-PARA.
           MOVE WS-IN-RESULT TO WS-SINK.
           STOP RUN.
       LINK-PARA.
           EXEC CICS LINK PROGRAM('TPROGB')
                          COMMAREA(WS-AREA)
                          LENGTH(8)
           END-EXEC.
"""

TRACE_CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPROGB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  SUB-REC.
           05  SUB-KEY              PIC X(4).
           05  SUB-RESULT           PIC X(4).
       LINKAGE SECTION.
       01  DFHCOMMAREA              PIC X(8).
       PROCEDURE DIVISION.
       SUB-PARA.
           MOVE DFHCOMMAREA TO SUB-REC.
           MOVE SUB-KEY TO SUB-RESULT.
           MOVE SUB-RESULT TO DFHCOMMAREA(5:4).
           EXEC CICS RETURN END-EXEC.
"""


def _bridge_jar() -> Path:
    """The parse is the only thing here that needs a JVM, so it is the only thing
    that can make this half unrunnable. A missing JAR is an unbuilt workspace, not
    a failing analysis: ``make jar`` at the root builds it."""
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


@pytest.fixture(scope="module")
def parsed(tmp_path_factory) -> Path:
    """Both members parsed for real. One JVM start, because that is the cost being
    amortised -- every test below asks a question of the same cache."""
    from cobble.parsing.parse_corpus import Job, parse_one

    root = tmp_path_factory.mktemp("trace")
    cache = root / "asg"
    cache.mkdir()
    for program, source in (("TPROGA", TRACE_CALLER), ("TPROGB", TRACE_CALLEE)):
        path = root / f"{program}.cbl"
        path.write_text(source, encoding="utf-8")
        result = parse_one(
            Job(path, cache / f"{program}.json"), str(_bridge_jar()), (), ("cpy",)
        )
        assert result.ok, result.error
    return cache


@pytest.fixture(scope="module")
def crossed(parsed: Path) -> Trace:
    return sampled("TPROGA", parsed, Budget(paths=8))


def test_the_walk_enters_the_callee_and_witnesses_writes_in_both_members(crossed):
    assert {one.program for one in crossed.deps} == {"TPROGA", "TPROGB"}


def test_the_callees_writes_are_credited_to_the_call_site_they_were_reached_through(
    crossed,
):
    """``via`` is how a reader reconstructs the route without the walk printing
    every node it passed through."""
    inside = {one.via for one in crossed.deps if one.program == "TPROGB"}

    assert len(inside) == 1
    assert next(iter(inside)).startswith("TPROGA/LINK-PARA/")


def test_the_callee_reads_bytes_the_caller_defined(crossed):
    """The inbound direction, and the whole point. SUB-REC is written from
    DFHCOMMAREA, whose bytes the caller's own MOVE put there -- so the definer is
    a node in a different member, which no intra-program walk can name."""
    (dep,) = [
        one
        for one in crossed.deps
        if one.program == "TPROGB" and one.target.field_name == "SUB-REC"
    ]

    assert str(dep.source).startswith("DFHCOMMAREA@linkage[0:8]")
    assert [one for one in dep.definers if one.startswith("TPROGA/")]


def test_the_callers_sink_reads_bytes_the_callee_defined(crossed):
    """The return direction, which needs no mechanism at all: the callee's write
    through DFHCOMMAREA(5:4) landed on the caller's own WS-IN-RESULT, because in a
    byte-addressable model the two were never separate storage."""
    (dep,) = [
        one
        for one in crossed.deps
        if one.program == "TPROGA" and one.target.field_name == "WS-SINK"
    ]

    assert str(dep.source) == "WS-IN-RESULT@working_storage[4:8]"
    assert [one for one in dep.definers if one.startswith("TPROGB/")]


def test_both_arms_of_the_branch_are_witnessed_across_the_sampled_paths(crossed):
    """One path sees one arm. Sampling is what gets the other, and it is why a
    single path's answer would be a narrower claim than this tool makes."""
    origins = {
        one.origin
        for one in crossed.deps
        if one.program == "TPROGA" and one.target.field_name == "WS-OUT-KEY"
    }
    sources = {
        str(one.source)
        for one in crossed.deps
        if one.program == "TPROGA" and one.target.field_name == "WS-OUT-KEY"
    }

    assert "LITERAL" in origins
    assert any(text.startswith("WS-SEED@") for text in sources)


def test_the_coverage_denominator_comes_from_the_graphs_and_not_from_the_answer(
    crossed,
):
    """The 3ao post-mortem's lesson. Both programs are counted once entered, and
    the caller's one IF is the only branch either of them has."""
    assert crossed.coverage.programs == {"TPROGA", "TPROGB"}
    assert crossed.coverage.total == 2
    assert crossed.coverage.fraction == 1.0


def test_a_member_absent_from_the_cache_is_refused_before_any_path_runs(parsed: Path):
    """A wrong ``--asg-dir`` is a mistake about the invocation, not a finding about
    the corpus, so it never reaches the sampler."""
    assert loadable(parsed, "TPROGA") == ""
    assert "no ASG cache" in loadable(parsed, "TPROGZ")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_trace.py -q`

Expected: collection error — `ImportError: cannot import name 'sampled'`.

- [ ] **Step 3: Write the implementation**

Extend `trace.py`'s import block with:

```python
import json
from functools import cache
from pathlib import Path

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.aliases import UNSIZEABLE, commarea_aliases
from cobble.dataflow.layout import UnsizeableFieldError, program_records
from cobble.dataflow.srccfg.build import build_program, label_id, paragraph_order
from cobble.dataflow.srccfg.desugar import LINK_TRANSFER, XCTL_TRANSFER
from cobble.dataflow.srccfg.statements import statement_index
from cobol_asg.asg_types import CobolASG
```

Add these constants beside the Task 2 ones:

```python
CROSSING_VERBS = (LINK_TRANSFER, XCTL_TRANSFER)

NO_PROCEDURE = "callee-has-no-procedure"
RE_ENTRY = "re-entry"
```

Replace the Task 2 `_moved` stub with:

```python
def _moved(walk: _Walk, loaded: Loaded, loader: Loader) -> _Walk:
    """Where the path goes from here: into a callee, or along an edge.

    A crossing site is one the alias table has a row for, rather than one this
    module re-recognises by verb. Deriving it from the rows is what makes it
    impossible for the two to disagree about which nodes are call sites.
    """
    rows = loaded.aliases.get(walk.node, ())
    if not rows:
        return _followed(walk, loaded)
    return _called(walk, loaded, loader, rows[0])
```

And append the crossing itself, plus the loader:

```python
def _dead_end(walk: _Walk, row: CommareaAlias, reason: str) -> _Walk:
    return replace(
        walk,
        dead_ends=walk.dead_ends
        | {
            DeadEnd(
                program=walk.program,
                node=walk.node,
                transfer=row.transfer,
                callee=row.callee,
                reason=reason,
            )
        },
    )


def _entered(
    walk: _Walk,
    loaded: Loaded,
    row: CommareaAlias,
    window: Window,
    callee: Loaded,
) -> _Walk:
    """Step into the callee with the shared window bound, and nothing else.

    The callee's slice starts empty because CICS gives a LINKed program fresh
    WORKING-STORAGE, so a program entered twice on one path does not inherit its
    own earlier run's memory. The resume point is read off the CALLER's graph:
    that is where the path comes back to.
    """
    return replace(
        walk,
        node=callee.entry,
        stack=(
            *walk.stack,
            Frame(
                program=row.callee,
                site=walk.node,
                resume=_sequel(loaded.cfg, walk.node),
                crossing=True,
                returns=row.returns,
                window=window,
            ),
        ),
        store={
            **walk.store,
            row.callee: _seeded(
                walk.store.get(walk.program, EMPTY),
                window.caller_extent,
                window.callee_extent,
            ),
        },
    )


def _refusal(walk: _Walk, row: CommareaAlias, window: Window, callee: Loaded) -> str:
    """Why this site cannot be crossed, or empty. First reason wins.

    A CALL ... USING row is refused by its transfer: the caller's parameters bind
    positionally onto the callee's PROCEDURE DIVISION USING, which is a different
    relation from a commarea window and is deliberately out of scope. Its own row
    already carries ``call-using-unsupported``, so nothing here has to invent a
    reason for it.
    """
    if row.transfer not in CROSSING_VERBS or not window.known:
        return row.reason or f"transfer-not-crossable: {row.transfer}"
    if callee.reason:
        return callee.reason
    if not callee.entry:
        return NO_PROCEDURE
    if _open(walk.stack, row.callee, callee.entry):
        return RE_ENTRY
    return ""


def _called(
    walk: _Walk, loaded: Loaded, loader: Loader, row: CommareaAlias
) -> _Walk:
    """A LINK or an XCTL: bind the shared window and step in, or say why not.

    A refusal does not end the caller's path. ``transfer`` has already credited the
    commarea to ``%CALL:<program>`` exactly as the fixpoint does, so stopping here
    would lose the caller's remaining statements and gain nothing.
    """
    window = _window(row, row.callee)
    callee = loader(row.callee) if row.callee else Loaded(program="")
    refused = _refusal(walk, row, window, callee)
    if refused:
        return _followed(_dead_end(walk, row, refused), loaded)
    return _entered(walk, loaded, row, window, callee)
```

`Loaded(program="")` for a blank callee has `entry == ""`, so `_refusal` returns `NO_PROCEDURE` — but the truthful reason is the row's own, which a blank callee always carries (`dynamic-target` or `call-using-unsupported`). The `row.transfer not in CROSSING_VERBS or not window.known` clause fires first for every such row, because a row with a blank callee never has extents. So the order of the clauses is load-bearing; keep it.

Now the return direction. Replace the Task 2 `_ended` with:

```python
def _restored(caller: State, callee: State, window: Window) -> State:
    """The caller's slice with the shared window written back from the callee's.

    ``state.write`` rather than a union: the callee's write to those bytes really
    did kill what the caller held there, and ``must_cover`` is what says so. Not
    ``state.join``, which is the fixpoint's operation and is never called here.
    """
    back = _seeded(callee, window.callee_extent, window.caller_extent)
    return reduce(
        lambda held, pair: write(held, pair[0], pair[1]), tuple(back.items()), caller
    )


def _ended(walk: _Walk) -> _Walk:
    """Nowhere left to go, unless a crossing frame owes its caller a return.

    Seeding the caller's window back needs no conversion and no flow edge: the two
    sides were the same bytes all along. An empty resume point is a call that was
    the last thing its caller did, so there is nothing to come back to.
    """
    frame = walk.frame
    if not (frame.crossing and frame.returns and frame.resume):
        return replace(walk, running=False)
    return replace(
        walk,
        node=frame.resume,
        stack=walk.stack[:-1],
        store={
            **walk.store,
            frame.window.caller: _restored(
                walk.store.get(frame.window.caller, EMPTY),
                walk.store.get(frame.program, EMPTY),
                frame.window,
            ),
        },
    )
```

Finally the on-disk loader and the two public entry points:

```python
@cache
def _loaded(asg_dir: Path, program: str) -> Loaded:
    """Everything a path needs from one member, built once per process.

    Memoised on the directory as well as the name, so a run against a different
    parse never reads another one's answer -- the same reason ``aliases.py`` keys
    its callee reads that way.

    A member whose storage cannot be laid out cannot be entered even when its
    LINKAGE laid out fine, which is what let its call site be aliased in the first
    place: the window says the bytes are shared, not that the callee is analysable.
    """
    asg = _asg_at(asg_dir / f"{program}.json")
    try:
        index = cell_index(program_records(asg))
    except UnsizeableFieldError as error:
        return Loaded(program=program, reason=f"{UNSIZEABLE}: {error}")
    return Loaded(
        program=program,
        cfg=build_program(asg),
        statements=statement_index(asg),
        index=index,
        entry=_entry_node(asg),
        aliases=_by_node(commarea_aliases(asg, index, asg_dir)),
    )


def _asg_at(path: Path) -> CobolASG:
    """Spelled out here rather than reused: ``aliases.py``'s own reader is private
    to it, and this design's one hard constraint is that nothing existing changes.
    """
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _entry_node(asg: CobolASG) -> str:
    order = paragraph_order(asg)
    return label_id(order[0].name) if order else ""


def _by_node(
    rows: Sequence[CommareaAlias],
) -> Mapping[str, tuple[CommareaAlias, ...]]:
    """``commarea_aliases`` returns a whole member's sites at once; a path wants one."""
    keys = tuple(dict.fromkeys(row.node for row in rows))
    return {key: tuple(row for row in rows if row.node == key) for key in keys}


def loadable(asg_dir: Path, program: str) -> str:
    """Empty when ``program`` can be traced, or the reason it cannot.

    The CLI's check, not the walk's: a wrong ``--asg-dir`` is a mistake about the
    invocation rather than a finding about the corpus, and a member with no
    PROCEDURE DIVISION has no path to sample.
    """
    path = asg_dir / f"{program}.json"
    if not path.is_file():
        return f"no ASG cache at {path}"
    loaded = _loaded(asg_dir, program)
    if loaded.reason:
        return loaded.reason
    if not loaded.entry:
        return NO_PROCEDURE
    return ""


def sampled(program: str, asg_dir: Path, budget: Budget = DEFAULT_BUDGET) -> Trace:
    """``traced`` against the one ASG cache every other stage reads.

    No artefact directory: reading the cache directly is what lets a path enter a
    callee ``aliases.jsonl`` has no rows for, which is any member a single-member
    build did not select.
    """
    return traced(program, lambda member: _loaded(asg_dir, member), budget)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_trace.py -q`

Expected: PASS. Without the bridge JAR the eight real-parse tests skip; run `make jar` at the root first so they do not.

- [ ] **Step 5: Run the gates**

```bash
cd cobble
uv run --no-sync python -m black cobble/dataflow/fields/trace.py tests/dataflow/fields/test_fields_trace.py
uv run --no-sync python -m python_fp_lint check cobble/dataflow/fields/
uv run --no-sync python -m ruff check --output-format=concise cobble/dataflow/fields tests/dataflow/fields
cd .. && uv run --no-sync lint-imports
```

Expected: fp-lint 9 pre-existing, none in `trace.py`; ruff 1 pre-existing; lint-imports 11 kept / 0 broken.

- [ ] **Step 6: Commit**

```bash
git add cobble/cobble/dataflow/fields/trace.py cobble/tests/dataflow/fields/test_fields_trace.py
git commit -m "feat(cobble): step a path into a LINK callee through the shared commarea bytes"
```

---

### Task 4: The report, the CLI, and the entry point

The walk becomes a tool. Rendering lives in its own module so the walk never learns about text.

**Files:**
- Create: `cobble/cobble/dataflow/fields/trace_report.py`
- Modify: `cobble/pyproject.toml` (one line under `[project.scripts]`, after `cobble-fields-query`)
- Modify: `cobble/README.md` (one section)
- Test: `cobble/tests/dataflow/fields/test_fields_trace.py` (append)

**Interfaces:**
- Consumes from Tasks 1–3: `Budget`, `DEFAULT_COVERAGE`, `DEFAULT_MAX_DEPTH`, `DEFAULT_PATHS`, `Dep`, `Trace`, `loadable`, `sampled`.
- Consumes existing: `cobble.dataflow.fields.extent_text.extent_text`.
- Produces: `lines(trace: Trace) -> tuple[str, ...]`, `cli(argv: Sequence[str] = ()) -> int`, `main() -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `cobble/tests/dataflow/fields/test_fields_trace.py`:

```python
def test_the_report_groups_by_program_and_names_the_site_each_was_entered_through(
    parsed: Path, tmp_path: Path
):
    from cobble.dataflow.fields.trace_report import cli

    out = tmp_path / "trace.txt"
    assert (
        cli(
            [
                "TPROGA",
                "--asg-dir",
                str(parsed),
                "--out",
                str(out),
                "--paths",
                "8",
            ]
        )
        == 0
    )
    written = out.read_text(encoding="utf-8")

    assert "TPROGA\n" in written
    assert "TPROGB   via TPROGA/LINK-PARA/" in written
    assert "branch coverage: 2/2 (100%) over " in written
    assert "programs entered" in written


def test_the_report_states_its_limits_where_a_reader_will_see_them(
    parsed: Path, tmp_path: Path
):
    """In the output, not only in the design doc. The query-time stop layer was
    deleted for being unreadable, and a number a reader can act on is what replaced
    it."""
    from cobble.dataflow.fields.trace_report import cli

    out = tmp_path / "trace.txt"
    assert cli(["TPROGA", "--asg-dir", str(parsed), "--out", str(out)]) == 0
    written = out.read_text(encoding="utf-8")

    assert "limits:" in written
    assert 'absence means "not sampled"' in written


def test_a_definer_that_crossed_a_call_is_spelled_with_the_member_it_is_in(
    parsed: Path, tmp_path: Path
):
    """The payload no existing artefact can carry: the caller's sink names a node
    in the callee as the last writer of its bytes."""
    from cobble.dataflow.fields.trace_report import cli

    out = tmp_path / "trace.txt"
    assert cli(["TPROGA", "--asg-dir", str(parsed), "--out", str(out)]) == 0
    written = out.read_text(encoding="utf-8")

    assert "defined at TPROGB/SUB-PARA/" in written


def test_a_missing_cache_directory_is_refused_with_a_status_and_not_a_traceback(
    tmp_path: Path,
):
    from cobble.dataflow.fields.trace_report import cli

    assert (
        cli(
            [
                "TPROGA",
                "--asg-dir",
                str(tmp_path / "absent"),
                "--out",
                str(tmp_path / "trace.txt"),
            ]
        )
        == 2
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_trace.py -q -k "report or limits or definer or refused"`

Expected: FAIL with `ModuleNotFoundError: No module named 'cobble.dataflow.fields.trace_report'`.

- [ ] **Step 3: Write the implementation**

Create `cobble/cobble/dataflow/fields/trace_report.py`:

```python
"""The trace as text, and the CLI that writes it.

Separate from ``trace.py`` because ``query.py`` in this same directory is the
counter-example: it reached a thousand lines by holding a walk and its output
format together. The walk knows nothing about text; this knows nothing about
paths.

The limits are printed, not only documented. The query-time stop layer was
deleted on 2026-09-07 for being unreadable, and what replaced it is a number a
reader can act on -- so a coverage percentage and four sentences go in the file,
where someone reading an answer will actually meet them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.trace import (
    DEFAULT_COVERAGE,
    DEFAULT_MAX_DEPTH,
    DEFAULT_PATHS,
    Budget,
    Dep,
    Trace,
    loadable,
    sampled,
)

LIMITS = (
    "",
    "limits:",
    "  - unsampled paths' flows are missing; the coverage percentage is the disclosure",
    "  - a loop body runs once, so a dependency needing a second iteration is missed",
    "  - conditions are not evaluated, so some sampled paths cannot happen at run time",
    '  - sound one way only: absence means "not sampled", never "does not exist"',
)


def _group_of(dep: Dep) -> tuple[str, str]:
    return (dep.program, dep.via)


def _came_from(dep: Dep) -> str:
    """An origin where the source is not storage, so an external value reads as
    itself rather than as an absence."""
    return dep.origin if dep.origin else extent_text(dep.source)


def _dep_line(dep: Dep, width: int) -> str:
    """Where these bytes came from, at which statement, and who last wrote them.

    ``defined at`` is the payload. The node is program-qualified, so a definer that
    crossed a call names the member it is in -- the interprocedural chain that a
    query over the intra-program artefacts has to rebuild.
    """
    said = f"    <- {_came_from(dep).ljust(width)}   at {dep.program}/{dep.node}"
    if not dep.definers:
        return said
    return f"{said}   defined at {', '.join(dep.definers)}"


def _target_lines(target: str, deps: Sequence[Dep]) -> tuple[str, ...]:
    width = max(len(_came_from(one)) for one in deps)
    return (f"  {target}", *sorted(_dep_line(one, width) for one in deps))


def _group_lines(group: tuple[str, str], deps: Sequence[Dep]) -> tuple[str, ...]:
    program, via = group
    targets = tuple(dict.fromkeys(sorted(extent_text(one.target) for one in deps)))
    return (
        f"{program}   via {via}" if via else program,
        *(
            line
            for target in targets
            for line in _target_lines(
                target, tuple(one for one in deps if extent_text(one.target) == target)
            )
        ),
        "",
    )


def _dependency_lines(trace: Trace) -> tuple[str, ...]:
    groups = tuple(dict.fromkeys(sorted(_group_of(one) for one in trace.deps)))
    return tuple(
        line
        for group in groups
        for line in _group_lines(
            group, tuple(one for one in trace.deps if _group_of(one) == group)
        )
    )


def _dead_end_lines(trace: Trace) -> tuple[str, ...]:
    """Their own section. A site the path could not cross is not a dependency, and
    mixing the two would make an absence read like a finding."""
    if not trace.dead_ends:
        return ()
    return (
        "dead ends:",
        *sorted(
            f"  {one.program}/{one.node}   {one.transfer}   "
            f"{one.callee if one.callee else '(unresolved)'}   {one.reason}"
            for one in trace.dead_ends
        ),
        "",
    )


def _summary_lines(trace: Trace) -> tuple[str, ...]:
    found = trace.coverage
    return (
        f"branch coverage: {len(found.taken)}/{found.total} "
        f"({round(100 * found.fraction)}%) over {trace.paths} paths, "
        f"{len(found.programs)} programs entered",
    )


def lines(trace: Trace) -> tuple[str, ...]:
    return (
        *_dependency_lines(trace),
        *_dead_end_lines(trace),
        *_summary_lines(trace),
        *LIMITS,
    )


def _positive(given: str) -> int:
    count = int(given)
    if count < 1:
        raise argparse.ArgumentTypeError(f"needs at least one, got {count}")
    return count


def _fraction(given: str) -> float:
    found = float(given)
    if found <= 0 or found > 1:
        raise argparse.ArgumentTypeError(f"needs a fraction in (0, 1], got {found}")
    return found


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sample concrete paths through one program and the callees it LINKs, "
            "reporting the byte provenance each path witnessed."
        )
    )
    parser.add_argument("program", help="the ASG cache stem to start from")
    parser.add_argument(
        "--asg-dir", required=True, type=Path, help="the parse every stage reads"
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="where to write the report; a whole-memory answer is a file, not a terminal",
    )
    parser.add_argument(
        "--paths", type=_positive, default=DEFAULT_PATHS, metavar="N"
    )
    parser.add_argument(
        "--coverage",
        type=_fraction,
        default=DEFAULT_COVERAGE,
        metavar="F",
        help="stop once this fraction of branch edges has been taken",
    )
    parser.add_argument(
        "--max-depth",
        type=_positive,
        default=DEFAULT_MAX_DEPTH,
        metavar="N",
        help="nodes one path may run before it is cut short",
    )
    return parser


def cli(argv: Sequence[str] = ()) -> int:
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    if not arguments.asg_dir.is_dir():
        sys.stderr.write(f"trace: !! no ASG cache at {arguments.asg_dir}\n")
        return 2
    refused = loadable(arguments.asg_dir, arguments.program)
    if refused:
        sys.stderr.write(f"trace: !! cannot trace {arguments.program}: {refused}\n")
        return 2
    trace = sampled(
        arguments.program,
        arguments.asg_dir,
        Budget(
            paths=arguments.paths,
            coverage=arguments.coverage,
            max_depth=arguments.max_depth,
        ),
    )
    arguments.out.write_text(
        "\n".join(lines(trace)) + "\n", encoding="utf-8"
    )
    return 0


def main() -> int:
    sys.exit(cli())
```

- [ ] **Step 4: Add the entry point**

In `cobble/pyproject.toml`, immediately after the `cobble-fields-query` line under `[project.scripts]`:

```toml
cobble-fields-trace = "cobble.dataflow.fields.trace_report:main"
```

Then re-install so the script exists: `uv sync --all-packages` at the root.

- [ ] **Step 5: Document it**

In `cobble/README.md`, in the field-dataflow material, after the description of the query surface, add:

```markdown
### Path sampling, across calls

`cobble-fields-trace PROGRAM --asg-dir DIR --out FILE` answers a different
question from the artefact tables. It interprets **one concrete path at a time**
over the same byte-provenance model, threads a single store with no join, and
steps into a `LINK`ed callee by binding the callee's `DFHCOMMAREA` onto the
caller's commarea window — so a write-back needs no mechanism, because the two
sides are the same storage. Because a path has a stack, it also takes only the
`RETURN` edge back to the site that actually performed the paragraph.

The report names, for every extent written on a sampled path, where its bytes
came from and **which node in which member last wrote them**. That crossing
chain is what the intra-program tables cannot carry.

It under-approximates, deliberately: a flow it does not report was not sampled,
never "does not exist", and a loop body runs once. `--paths` and `--coverage`
bound the sampling and the branch-coverage figure is printed with the answer, as
are those limits. The fixpoint behind `cobble-fields` keeps the other guarantee —
over-approximate, every real flow present — and neither replaces the other.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_trace.py -q`

Expected: PASS, all tests.

- [ ] **Step 7: Run every gate**

```bash
cd cobble
uv run --no-sync python -m black cobble tests
uv run --no-sync python -m python_fp_lint check cobble/dataflow/fields/
uv run --no-sync python -m ruff check --output-format=concise cobble/dataflow/fields tests/dataflow/fields
uv run --no-sync python -m pytest -q
cd .. && uv run --no-sync lint-imports
```

Expected: black reports files unchanged; fp-lint reports exactly the 9 pre-existing findings, none in either new module; ruff reports exactly the 1 pre-existing `PLW1510`; the cobble suite is at its 1196-passed baseline plus the new tests, with no failures; lint-imports 11 kept / 0 broken.

- [ ] **Step 8: Smoke-test the CLI end to end**

Against a real parse. Use `cobble/config/parse.local.toml`'s `asg_dir` if it is present on this machine, otherwise any directory `cobble-parse-corpus` has written:

```bash
cd cobble && uv run --no-sync cobble-fields-trace <PROGRAM> --asg-dir <ASG_DIR> --out /tmp/trace.txt --paths 20
```

Read the file. Confirm at least one `defined at` names a node in another member, and that the coverage line and the limits block are present. Do not commit the output, and do not put the program or directory name in a commit message — that is a corpus identifier.

- [ ] **Step 9: Close the bead and export the snapshot**

```bash
bd close red-dragon-forge-nxy --reason="path-sampling trace shipped: trace.py, trace_report.py, cobble-fields-trace"
bd export -o issues/issues.jsonl && git add issues/issues.jsonl
```

- [ ] **Step 10: Commit**

```bash
git add cobble/cobble/dataflow/fields/trace_report.py cobble/pyproject.toml cobble/README.md cobble/tests/dataflow/fields/test_fields_trace.py issues/issues.jsonl
git commit -m "feat(cobble): report a sampled path trace, with its coverage and its limits"
```

---

## Self-Review

**Spec coverage.** Every section maps to a task. *The problem* and *What this builds* are the motivation, carried in `trace.py`'s docstring (Task 1) and the README (Task 4). *Not a replacement* is the Global Constraint that nothing existing changes, plus the printed limits (Task 4). *Interface* is Task 4's `_parser`. *Provenance, not values* is `Dep` carrying `origin`/`source`/`definers` and never a value (Task 1), and there is no task anywhere that evaluates a condition or a literal. *Mechanism → One path* is Task 2 (`_ran`, `_witnessed`, `_qualified`, `_sampled`). *The re-entry rule* is `_open` plus `Frame.visited` (Task 2), tested in all three cases — loop (Task 2), twice-performed paragraph (Task 2), LINK cycle (Task 3). *Crossing a call* is Task 3. *Coverage* is `_branch`/`_branches`/`_coverage` (Task 2), with the denominator asserted against the graphs in Task 3. *Stated limits* is Task 4's `LIMITS`. *Constraints* is the Global Constraints section.

**One gap, deliberately left.** The spec says a site's several rows mean a layout ambiguity and the first row is used. `_moved` takes `rows[0]` and there is no test for a two-row site, because constructing one needs an operand name resolving to cells in two records — a fixture that would cost more to build than the branch is worth. If a reviewer wants it covered, the hand-built loader in Task 3 can carry two rows for `M/1` and assert only the first is crossed; add it there rather than filing it.

**Type consistency.** `Loaded`, `Loader`, `Frame`, `Window`, `Dep`, `DeadEnd`, `Coverage`, `Trace`, `Budget` keep the same field names and types from the task that defines them through every later use. `_seeded(held, source, target)` and `_rebased(extent, source, target)` keep their argument order everywhere. `_entered` takes the **caller's** `Loaded` as well as the callee's, because the resume point is read off the caller's graph, not the callee's. `store` is `Mapping[str, State]` throughout and is never keyed by anything but a program name.

**One watch-out for the implementer.** `_refusal`'s clause order is load-bearing: the transfer/window check must come before the entry check, or a row with a blank callee reports `callee-has-no-procedure` instead of its own true reason — a dead end that names the wrong cause is worse than one that names none.

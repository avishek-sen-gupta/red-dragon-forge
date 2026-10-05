# Cross-program Dataflow Combine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve dynamic jump targets (and byte provenance) whose values arrive from other programs, by linking the per-program fixpoint results instead of re-analysing programs.

**Architecture:** `cobble-dataflow-fixpoint` stays single-program and writes one extra table, `jumps.jsonl`: per jump, exit, `RETRIEVE` and program entry, the kind, target, memory areas handed over, and what each field in them held — read off the settled state. A new command, `cobble-dataflow-combine`, loads each linked program's `defs.jsonl`, flow rows and `jumps.jsonl` into small byte-range indexes; a resolve step walks values back within a program to received / returned / retrieved bytes; linking follows those across programs over a call graph it grows in rounds. Outputs: a combined `targets.jsonl` and a `links.jsonl` the provenance query can follow.

**Tech Stack:** Python 3.13, pytest, Pydantic (JSON boundary), uv workspace (`cobble` member), the ProLeap bridge JAR for synthetic-COBOL integration tests.

**Spec:** `docs/superpowers/specs/2026-10-05-cross-program-dataflow-combine-design.md` (commit `07d5684`, amended 2026-10-06 with the `ENTRY` row). Read it before starting; this plan argues from it.

## Global Constraints

- Python 3.13+; Black line length 88 (`make fmt`); Pyright strict, zero errors; `python-fp-lint` per `fp.json`: no `Any`, no `object` outside `fixpoint/rows.py`, frozen dataclasses, no `is None` / `is not None`, no `x or None`, no mutation in loops, `Sequence` / `Mapping` parameters, no comments beyond a one-line module/class header.
- One class per file. Tests use synthetic COBOL only — no corpus member names (`guidelines/data-security.md`).
- `cobble-dataflow-fixpoint`'s existing tables (`defs.jsonl`, `graph.jsonl`, `targets.jsonl`, `aliases.jsonl`, `extents.jsonl`) must stay byte-identical for every program.
- The combine step never loads `extents.jsonl` and never re-runs a program's analysis.
- `uv run --no-sync lint-imports` must pass; `cobble` adds no new import of `cicada`/`squall`/`jackal` beyond `cics.csd_parse` and `cics.statements`, which it already uses.
- Commands run from `cobble/` unless stated; always `uv run --no-sync`. Tests that need the bridge JAR use the existing `fixpoint_corpus` fixture (`tests/dataflow/fixpoint/conftest.py`), which finds the JAR itself; build it first with `make jar` at the forge root if absent.
- Gate before every commit: `make fmt` (forge root), `uv run --no-sync pyright`, `uv run --no-sync lint-imports`, `pre-commit run python-fp-lint-check --hook-stage manual --files <changed files>`, `uv run --no-sync python -m pytest -q` in `cobble/`.
- Each new test is mutation-checked: break the code it covers in the two most obvious ways, confirm it fails, restore (`guidelines/testing.md`).

## Review Focus

1. **A jump whose area operand resolves to no field** (subscripted name, unknown field): the row is still written, with `areas: []` and its target — test in Task 4.
2. **A received byte range only partly covered by every caller's area** (caller's area shorter than the callee's): the uncovered bytes keep `inbound-linkage` beside the values the callers did supply — test in Task 7.
3. **A cycle of programs that adds nothing** (A XCTLs to B's received target, B to A's): linking terminates and reports no invented candidates — test in Task 7.
4. **`--member` naming a program twice, or naming one with no results**: duplicates ignored; missing ones refused, nothing written — test in Task 9.
5. **A literal-sourced write inside the walk** (`MOVE 'X' TO F` — a flow row with an empty `source_extent` at an ordinary node): contributes its value, never an `unknown` stop — test in Task 6.

---

## File structure

```
cobble/cobble/dataflow/jumps/
  __init__.py      # one-line header
  jump_kind.py     # JumpKind
  fact.py          # Fact: extent text, values, writers, reasons at one point
  jump_area.py   # JumpArea: param, area extent text, field facts
  jump.py          # Jump: one jumps.jsonl row
  facts.py         # fact_at(state, extent), merged(facts)
  discover.py      # jumps_of(...): every Jump in one program
  rows.py          # jump_row / jump_from_row / jump_identity
cobble/cobble/dataflow/combine/
  __init__.py
  flow.py          # Flow: one flow row, as byte ranges
  target_site.py   # TargetSite: a dynamic site's transfer and expression
  program_tables.py# ProgramTables: one program's facts / flows / jumps / received / sites
  load.py          # load_tables(fixpoint_dir, program)
  stop_kind.py     # StopKind
  stop.py          # Stop
  resolution.py    # Resolution + joined
  resolve.py       # resolve(tables, node, at)
  callee_areas.py  # CalleeAreas protocol
  asg_callee_areas.py # CalleeAreas over the parse cache (aliases helpers)
  edge.py          # Edge
  held.py          # Held: values + reasons + outside callers, + join
  linked_target.py # LinkedTarget: ResolvedTarget + outside callers
  outside_jumps.py # OutsideJumps
  run_report.py    # RunReport
  linked.py        # Linked: targets + edges + report
  link.py          # link(...): rounds over edges, depth-first values
  outside.py       # outside_jumps(fixpoint_dir, asg_dir, inside, transactions)
  outputs.py       # write targets.jsonl / links.jsonl
  cli.py           # cobble-dataflow-combine
Modified:
  cobble/cobble/dataflow/fields/values.py        # two UnresolvedReason members
  cobble/cobble/dataflow/fields/aliases.py       # three public helpers
  cobble/cobble/dataflow/fixpoint/targets.py     # is_program_name public
  cobble/cobble/dataflow/fixpoint/fixpoint.py    # ProgramFlow.jumps
  cobble/cobble/dataflow/fixpoint/build_corpus.py# write jumps.jsonl
  cobble/cobble/dataflow/fixpoint/query.py       # --links
  cobble/pyproject.toml, cobble/README.md
```

---

### Task 1: Jump types and the `jumps.jsonl` wire format

**Files:**
- Create: `cobble/cobble/dataflow/jumps/{__init__,jump_kind,fact,jump_area,jump,rows}.py`
- Test: `cobble/tests/dataflow/jumps/__init__.py` (empty), `cobble/tests/dataflow/jumps/test_rows.py`

**Interfaces:**
- Produces: `JumpKind`, `Fact`, `JumpArea`, `Jump`, `jump_row(jump: Jump) -> str`, `jump_from_row(text: str) -> Jump`, `jump_identity(jump: Jump) -> str`.

- [ ] **Step 1: Write the failing round-trip test**

```python
"""A jumps.jsonl row is a lossless spelling of one Jump."""

import json

from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.rows import jump_from_row, jump_identity, jump_row

JUMP = Jump(
    program="PROGA",
    node="MAIN/3",
    line=12,
    kind=JumpKind.XCTL,
    returns=False,
    target=Fact(
        extent="WS-NEXT@working_storage[20:28]",
        values=("PROGB   ",),
        writers=("MAIN/1",),
    ),
    areas=(
        JumpArea(
            param=0,
            extent="WS-AREA@working_storage[0:20]",
            fields=(
                Fact(
                    extent="WS-FROM@working_storage[0:8]",
                    values=("PROGA   ",),
                    writers=("MAIN/2",),
                ),
                Fact(
                    extent="WS-REST@working_storage[8:20]",
                    reasons=(UnresolvedReason.UNINITIALISED,),
                ),
            ),
        ),
    ),
)


def test_a_jump_round_trips_through_its_row() -> None:
    row = jump_row(JUMP)

    assert json.loads(row) == {
        "program": "PROGA",
        "node": "MAIN/3",
        "line": 12,
        "kind": "XCTL",
        "returns": False,
        "target": {
            "extent": "WS-NEXT@working_storage[20:28]",
            "values": ["PROGB   "],
            "writers": ["MAIN/1"],
            "reasons": [],
        },
        "transid": {"extent": "", "values": [], "writers": [], "reasons": []},
        "areas": [
            {
                "param": 0,
                "extent": "WS-AREA@working_storage[0:20]",
                "fields": [
                    {
                        "extent": "WS-FROM@working_storage[0:8]",
                        "values": ["PROGA   "],
                        "writers": ["MAIN/2"],
                        "reasons": [],
                    },
                    {
                        "extent": "WS-REST@working_storage[8:20]",
                        "values": [],
                        "writers": [],
                        "reasons": ["uninitialised"],
                    },
                ],
            }
        ],
    }
    assert jump_from_row(row) == JUMP
    assert jump_identity(JUMP) == "PROGA\x00MAIN/3\x00XCTL"
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run --no-sync python -m pytest tests/dataflow/jumps/test_rows.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.jumps'`.

- [ ] **Step 3: Implement**

`jumps/__init__.py`:
```python
"""Jumps: what each jump in one program hands over, read off its settled state."""
```

`jumps/jump_kind.py`:
```python
"""JumpKind — the statements that move control or data between programs."""

from enum import Enum


class JumpKind(Enum):
    XCTL = "XCTL"
    LINK = "LINK"
    CALL = "CALL"
    RETURN_TRANSID = "RETURN_TRANSID"
    START = "START"
    EXIT = "EXIT"
    RETRIEVE = "RETRIEVE"
    ENTRY = "ENTRY"
```

`jumps/fact.py`:
```python
"""Fact — what the settled state says about some bytes at one node."""

from dataclasses import dataclass

from cobble.dataflow.fields.values import UnresolvedReason


@dataclass(frozen=True)
class Fact:
    extent: str = ""
    values: tuple[str, ...] = ()
    writers: tuple[str, ...] = ()
    reasons: tuple[UnresolvedReason, ...] = ()
```

`jumps/jump_area.py`:
```python
"""JumpArea — one block of memory a jump hands over, field by field."""

from dataclasses import dataclass

from cobble.dataflow.jumps.fact import Fact


@dataclass(frozen=True)
class JumpArea:
    param: int
    extent: str
    fields: tuple[Fact, ...] = ()
```

`jumps/jump.py`:
```python
"""Jump — one jumps.jsonl row: where control goes and what it hands over."""

from dataclasses import dataclass

from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.jump_area import JumpArea


@dataclass(frozen=True)
class Jump:
    program: str
    node: str
    line: int
    kind: JumpKind
    returns: bool
    target: Fact = Fact()
    transid: Fact = Fact()
    areas: tuple[JumpArea, ...] = ()
```

`jumps/rows.py`:
```python
"""The jumps.jsonl wire form: one Jump per line, validated back into a Jump on read."""

import json

from pydantic import BaseModel, ConfigDict

from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.jump_area import JumpArea


class _FactRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    extent: str = ""
    values: tuple[str, ...] = ()
    writers: tuple[str, ...] = ()
    reasons: tuple[UnresolvedReason, ...] = ()


class _AreaRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    param: int
    extent: str
    fields: tuple[_FactRow, ...] = ()


class _JumpRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    program: str
    node: str
    line: int
    kind: JumpKind
    returns: bool
    target: _FactRow = _FactRow()
    transid: _FactRow = _FactRow()
    areas: tuple[_AreaRow, ...] = ()


def _fact_dict(fact: Fact) -> dict[str, str | list[str]]:
    return {
        "extent": fact.extent,
        "values": list(fact.values),
        "writers": list(fact.writers),
        "reasons": [reason.value for reason in fact.reasons],
    }


def _area_dict(area: JumpArea) -> dict[str, int | str | list[dict[str, str | list[str]]]]:
    return {
        "param": area.param,
        "extent": area.extent,
        "fields": [_fact_dict(field) for field in area.fields],
    }


def jump_row(jump: Jump) -> str:
    return json.dumps(
        {
            "program": jump.program,
            "node": jump.node,
            "line": jump.line,
            "kind": jump.kind.value,
            "returns": jump.returns,
            "target": _fact_dict(jump.target),
            "transid": _fact_dict(jump.transid),
            "areas": [_area_dict(area) for area in jump.areas],
        }
    )


def _fact(row: _FactRow) -> Fact:
    return Fact(row.extent, row.values, row.writers, row.reasons)


def jump_from_row(text: str) -> Jump:
    row = _JumpRow.model_validate_json(text)
    return Jump(
        program=row.program,
        node=row.node,
        line=row.line,
        kind=row.kind,
        returns=row.returns,
        target=_fact(row.target),
        transid=_fact(row.transid),
        areas=tuple(
            JumpArea(area.param, area.extent, tuple(map(_fact, area.fields)))
            for area in row.areas
        ),
    )


def jump_identity(jump: Jump) -> str:
    return f"{jump.program}\0{jump.node}\0{jump.kind.value}"
```

Check `rg -n pydantic cobble/pyproject.toml`; if cobble does not declare it (it imports it in `cobble/corpus_file.py`, so it should), add `"pydantic>=2.12.5,<3.0.0"` to `dependencies` and run `uv lock` at the forge root.

- [ ] **Step 4: Run the test** — Expected: PASS. Mutation-check: drop `"transid"` from `jump_row`; make `jump_from_row` ignore `areas`. Each must fail. Restore.

- [ ] **Step 5: Gate and commit**

```bash
git add cobble/cobble/dataflow/jumps cobble/tests/dataflow/jumps
git commit -m "feat(cobble): jump rows — what a jump hands over, as a lossless JSONL row"
```

---

### Task 2: Reading facts off a settled state

**Files:**
- Create: `cobble/cobble/dataflow/jumps/facts.py`
- Modify: `cobble/cobble/dataflow/fields/values.py` — add two `UnresolvedReason` members
- Test: `cobble/tests/dataflow/jumps/test_facts.py`

**Interfaces:**
- Produces: `fact_at(state: State, extent: FieldExtent) -> Fact` (values decoded, **not** stripped, sorted; writers = sorted nodes of `reaching(state, extent)` whose `origin` is empty; reasons sorted by value); `merged(facts: Sequence[Fact]) -> Fact` (first extent, unions of the rest, sorted); `UnresolvedReason.OUTSIDE_ANALYSED_SET = "outside-analysed-set"`, `UnresolvedReason.NOT_RECORDED = "not-recorded"`.

- [ ] **Step 1: Write the failing test**

```python
"""A Fact is the settled state's answer for some bytes at one node."""

from cobble.dataflow.fields.state import EMPTY, Source, write
from cobble.dataflow.fields.values import UnresolvedReason, ValueSet
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.facts import fact_at, merged
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

WS = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.EXACT, "WS-FROM")
LK = FieldExtent(RegionId.LINKAGE, 0, 8, Precision.EXACT, "LK-FROM")
STATE = write(
    EMPTY,
    WS,
    frozenset({Source(origin="", extent=LK, node="MAIN/2")}),
    ValueSet(values=frozenset({b"PROGA   "})),
)


def test_a_fact_carries_unstripped_values_writers_and_reasons() -> None:
    assert (fact_at(STATE, WS), fact_at(STATE, LK)) == (
        Fact(
            extent="WS-FROM@working_storage[0:8]",
            values=("PROGA   ",),
            writers=("MAIN/2",),
        ),
        Fact(
            extent="LK-FROM@linkage[0:8]",
            reasons=(UnresolvedReason.INBOUND_LINKAGE,),
        ),
    )


def test_facts_merge_by_union_keeping_the_first_extent() -> None:
    assert merged(
        (
            Fact("A@working_storage[0:8]", ("X",), ("N/1",)),
            Fact("A@working_storage[8:16]", ("Y",), ("N/2",), (UnresolvedReason.FROM_FILE,)),
        )
    ) == Fact(
        "A@working_storage[0:8]",
        ("X", "Y"),
        ("N/1", "N/2"),
        (UnresolvedReason.FROM_FILE,),
    )
```

- [ ] **Step 2: Run** — Expected: FAIL, `No module named 'cobble.dataflow.jumps.facts'`.

- [ ] **Step 3: Implement**

In `fields/values.py`, inside `class UnresolvedReason(Enum)` after `UNMODELLED`:
```python
    OUTSIDE_ANALYSED_SET = "outside-analysed-set"
    NOT_RECORDED = "not-recorded"
```

`jumps/facts.py`:
```python
"""Read Facts — values, writers, reasons — for some bytes off a settled state."""

from collections.abc import Sequence

from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.state import State, reaching, values_at
from cobble.dataflow.jumps.fact import Fact
from cobol_memory.field_extent import FieldExtent


def fact_at(state: State, extent: FieldExtent) -> Fact:
    held = values_at(state, extent)
    return Fact(
        extent=extent_text(extent),
        values=tuple(sorted(v.decode("utf-8", errors="replace") for v in held.values)),
        writers=tuple(
            sorted({s.node for s in reaching(state, extent) if not s.origin})
        ),
        reasons=tuple(sorted(held.reasons, key=lambda reason: reason.value)),
    )


def merged(facts: Sequence[Fact]) -> Fact:
    if not facts:
        return Fact()
    return Fact(
        extent=facts[0].extent,
        values=tuple(sorted({v for fact in facts for v in fact.values})),
        writers=tuple(sorted({w for fact in facts for w in fact.writers})),
        reasons=tuple(
            sorted(
                {r for fact in facts for r in fact.reasons},
                key=lambda reason: reason.value,
            )
        ),
    )
```

- [ ] **Step 4: Run** — Expected: PASS. Mutation-check: remove the `not s.origin` filter; strip values. Each must fail. Restore.
- [ ] **Step 5: Gate and commit** — `feat(cobble): read a jump's facts off the settled state`.

---

### Task 3: Public line-up helpers in `aliases.py`

**Files:**
- Modify: `cobble/cobble/dataflow/fields/aliases.py` (add three public functions; no change to existing behaviour)
- Test: `cobble/tests/dataflow/fixpoint/test_line_up_helpers.py` (real bridge)

**Interfaces:**
- Produces:
  - `area_extents(operand: str, index: CellIndex) -> tuple[FieldExtent, ...]` — the extents a commarea/argument/option operand names, by the same rule `_windows` uses (`_reference` + `cells_named(name, qualifiers, 0)`); `()` when it names nothing.
  - `received_areas(asg: CobolASG, index: CellIndex) -> tuple[tuple[int, FieldExtent], ...]` — `((0, DFHCOMMAREA),)` when the program declares one; else `(i, record)` for each `procedure_using` parameter *i* found as a level-01 LINKAGE record (positions preserved, unfound ones omitted).
  - `callee_received_area(asg_dir: Path, callee: str, by_position: bool, param: int) -> FieldExtent` — the callee's `DFHCOMMAREA` (`by_position` False) or its `USING` parameter `param` (`by_position` True); `NO_EXTENT` when there is none.

- [ ] **Step 1: Write the failing test**

```python
"""The callee and caller sides of a line-up, read the way the alias table reads them."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.aliases import (
    NO_EXTENT,
    area_extents,
    callee_received_area,
    received_areas,
)
from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fixpoint.fixpoint import analysed
from cobol_asg.asg_types import CobolASG

CICS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-A             PIC X(4).
           05  WS-B             PIC X(6).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS RETURN END-EXEC.
"""

SUBP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBP.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-B                 PIC X(8).
       01  LK-A                 PIC X(6).
       PROCEDURE DIVISION USING LK-A LK-B.
       MAIN-PARA.
           GOBACK.
"""


def _asg(cache: Path, name: str) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads((cache / f"{name}.json").read_text()))


def test_both_sides_of_a_line_up_are_found(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path],
) -> None:
    cache = fixpoint_corpus({"CICSP": CICS, "SUBP": SUBP}).parent / "parsed"
    cics, subp = _asg(cache, "CICSP"), _asg(cache, "SUBP")
    _, cics_index = analysed(cics)
    _, subp_index = analysed(subp)

    assert tuple(map(extent_text, area_extents("WS-AREA", cics_index))) == (
        "WS-AREA@working_storage[0:10]",
    )
    assert area_extents("NO-SUCH-FIELD", cics_index) == ()
    assert tuple(
        (param, extent_text(extent)) for param, extent in received_areas(cics, cics_index)
    ) == ((0, "DFHCOMMAREA@linkage[0:10]"),)
    assert tuple(
        (param, extent.field_name) for param, extent in received_areas(subp, subp_index)
    ) == ((0, "LK-A"), (1, "LK-B"))
    assert callee_received_area(cache, "CICSP", False, 0).length == 10
    assert callee_received_area(cache, "SUBP", True, 1).field_name == "LK-B"
    assert callee_received_area(cache, "SUBP", True, 5) == NO_EXTENT
    assert callee_received_area(cache, "MISSING", False, 0) == NO_EXTENT
```

(The LINKAGE offsets in the `SUBP` assertion are by name rather than by number because the bridge lays LINKAGE out in `USING` order — red-dragon `415d7c64` — and the test pins the binding, not the layout.)

- [ ] **Step 2: Run** — `uv run --no-sync python -m pytest tests/dataflow/fixpoint/test_line_up_helpers.py -q` — Expected: FAIL, `ImportError: cannot import name 'area_extents'`.

- [ ] **Step 3: Implement** — append to `fields/aliases.py`:

```python
def area_extents(operand: str, index: CellIndex) -> tuple[FieldExtent, ...]:
    reference = _reference(operand)
    return tuple(
        index.extent_of(cell)
        for cell in index.cells_named(reference.name, reference.qualifiers, 0)
    )


def received_areas(asg: CobolASG, index: CellIndex) -> tuple[tuple[int, FieldExtent], ...]:
    commarea = _linkage_commarea(index)
    if not commarea.reason:
        return ((0, commarea.extent),)
    found = tuple(
        (position, _record_named(index, param.name))
        for position, param in enumerate(asg.procedure_using)
    )
    return tuple((position, callee.extent) for position, callee in found if not callee.reason)


def callee_received_area(
    asg_dir: Path, callee: str, by_position: bool, param: int
) -> FieldExtent:
    linkage = _callee_linkage(asg_dir, callee)
    if linkage.reason:
        return NO_EXTENT
    found = (
        _parameter(linkage, param) if by_position else _linkage_commarea(linkage.index)
    )
    return NO_EXTENT if found.reason else found.extent
```

- [ ] **Step 4: Run** the new test and `tests/dataflow/fixpoint/test_call_using_aliases.py` — Expected: both PASS (the existing one unchanged).
- [ ] **Step 5: Gate and commit** — `refactor(cobble): expose the callee-area and operand line-up rules`.

---

### Task 4: The fixpoint finds every jump and writes `jumps.jsonl`

**Files:**
- Create: `cobble/cobble/dataflow/jumps/discover.py`
- Modify: `cobble/cobble/dataflow/fixpoint/fixpoint.py` (`ProgramFlow.jumps`, set in `analyse`)
- Modify: `cobble/cobble/dataflow/fixpoint/build_corpus.py` (`JUMPS_FILE`, `MemberResult.jumps`, `_tables`, `_Sinks`, `_member_directory`, the corpus merge)
- Modify: `cobble/README.md` (fixpoint outputs list)
- Test: `cobble/tests/dataflow/fixpoint/test_jumps_synthetic.py`; baseline data `cobble/tests/dataflow/fixpoint/data/jumps_baseline/` (created in Step 1)

**Interfaces:**
- Consumes: `fact_at`, `merged` (Task 2); `area_extents`, `received_areas` (Task 3); `Cfg`, `Node` (`srccfg/cfg.py`); `CALL_TRANSFERS`, `commarea_field` (`srccfg/desugar.py`); `operand_occurrence_extents`, `CellIndex` (`fields/extent.py`); `Statement` (`fields/transfer.py`); `ExecCicsStatement`, `CicsOperand` (`cics.statements`); `GobackStatement`, `ExitProgramStatement`, `StopRunStatement` (`cobol_asg.cobol_statements`).
- Produces: `jumps_of(asg: CobolASG, cfg: Cfg, statements: Mapping[str, Statement], index: CellIndex, states: Mapping[str, State]) -> tuple[Jump, ...]`; `ProgramFlow.jumps`; `members/<P>/jumps.jsonl` and corpus `jumps.jsonl`.

- [ ] **Step 1: Capture the baseline of the existing tables, before any change**

Create `tests/dataflow/fixpoint/test_jumps_synthetic.py` with the sources and a temporary test that copies the four tables out, run it once on the current code, then delete the temporary test:

```python
"""jumps.jsonl, compiled by the real bridge: one row per jump, exit, RETRIEVE and entry."""

import json
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

BASELINE = Path(__file__).parent / "data" / "jumps_baseline"

CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-FROM          PIC X(8).
           05  WS-REST          PIC X(12).
       01  WS-NEXT              PIC X(8) VALUE 'PROGB'.
       01  WS-ONE               PIC X(4).
       01  WS-TWO               PIC X(4).
       01  WS-THREE             PIC X(4).
       01  WS-TBL.
           05  WS-ROW           PIC X(4) OCCURS 3.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGA' TO WS-FROM.
           CALL 'SUBP' USING WS-ONE WS-TWO WS-THREE.
           EXEC CICS LINK PROGRAM('PROGB') COMMAREA(WS-ROW(1)) END-EXEC.
           EXEC CICS XCTL PROGRAM(WS-NEXT) COMMAREA(WS-AREA) END-EXEC.
"""

CICSB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                 PIC X(6) VALUE 'HELLO'.
       01  WS-Y                 PIC X(6).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS RETRIEVE INTO(WS-Y) END-EXEC.
           EXEC CICS START TRANSID('TRNC') FROM(WS-X) END-EXEC.
           EXEC CICS RETURN TRANSID('TRNB') COMMAREA(DFHCOMMAREA) END-EXEC.
"""

SUBP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBP.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-1                 PIC X(4).
       01  LK-2                 PIC X(4).
       01  LK-3                 PIC X(4).
       PROCEDURE DIVISION USING LK-1 LK-2 LK-3.
       MAIN-PARA.
           MOVE 'ABCD' TO LK-1.
           GOBACK.
"""

SOURCES = {"PROGA": CALLER, "PROGB": CICSB, "SUBP": SUBP}
EXISTING = ("defs.jsonl", "graph.jsonl", "targets.jsonl", "aliases.jsonl")


def test_capture_baseline(fixpoint_corpus: Callable[[Mapping[str, str]], Path]) -> None:
    out = fixpoint_corpus(SOURCES)
    BASELINE.mkdir(parents=True, exist_ok=True)
    tuple(shutil.copy(out / name, BASELINE / name) for name in EXISTING)
```

Run: `uv run --no-sync python -m pytest tests/dataflow/fixpoint/test_jumps_synthetic.py::test_capture_baseline -q` — Expected: PASS, four files under `data/jumps_baseline/`. Then delete `test_capture_baseline` (keep `shutil` out of the file).

- [ ] **Step 2: Write the failing tests** (replace the deleted function with these)

```python
@pytest.fixture(scope="module")
def out(fixpoint_corpus: Callable[[Mapping[str, str]], Path]) -> Path:
    return fixpoint_corpus(SOURCES)


def _jumps(out: Path, program: str) -> list[dict[str, object]]:
    lines = (out / "members" / program / "jumps.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def _by_kind(rows: list[dict[str, object]], kind: str) -> list[dict[str, object]]:
    return [row for row in rows if row["kind"] == kind]


def _shape(row: dict[str, object]) -> tuple[object, ...]:
    areas = row["areas"]
    assert isinstance(areas, list)
    return (
        row["kind"],
        row["returns"],
        row["target"],
        row["transid"],
        [(a["param"], a["extent"], [f["extent"] for f in a["fields"]]) for a in areas],
    )


def test_an_xctl_hands_over_its_commarea_field_by_field(out: Path) -> None:
    (xctl,) = _by_kind(_jumps(out, "PROGA"), "XCTL")
    area = xctl["areas"][0]
    assert (xctl["target"]["values"], area["param"], area["extent"]) == (
        ["PROGB   "],
        0,
        "WS-AREA@working_storage[0:20]",
    )
    assert [(f["extent"], f["values"], f["reasons"]) for f in area["fields"]] == [
        ("WS-FROM@working_storage[0:8]", ["PROGA   "], []),
        ("WS-REST@working_storage[8:20]", [], ["uninitialised"]),
    ]
    assert len(area["fields"][0]["writers"]) == 1


def test_a_call_hands_over_one_area_per_using_argument(out: Path) -> None:
    (call,) = _by_kind(_jumps(out, "PROGA"), "CALL")
    assert (call["returns"], call["target"]["values"]) == (True, ["SUBP"])
    assert [(a["param"], a["extent"]) for a in call["areas"]] == [
        (0, "WS-ONE@working_storage[28:32]"),
        (1, "WS-TWO@working_storage[32:36]"),
        (2, "WS-THREE@working_storage[36:40]"),
    ]


def test_an_area_naming_no_field_still_writes_the_jump(out: Path) -> None:
    (link,) = _by_kind(_jumps(out, "PROGA"), "LINK")
    assert (link["returns"], link["target"]["values"], link["areas"]) == (
        True,
        ["PROGB"],
        [],
    )


def test_cics_return_start_and_retrieve_are_found_from_their_options(out: Path) -> None:
    rows = _jumps(out, "PROGB")
    (retrieve,) = _by_kind(rows, "RETRIEVE")
    (start,) = _by_kind(rows, "START")
    (back,) = _by_kind(rows, "RETURN_TRANSID")
    assert [a["extent"] for a in retrieve["areas"]] == ["WS-Y@working_storage[6:12]"]
    assert (start["transid"]["values"], [a["extent"] for a in start["areas"]]) == (
        ["TRNC"],
        ["WS-X@working_storage[0:6]"],
    )
    assert (back["transid"]["values"], [a["extent"] for a in back["areas"]]) == (
        ["TRNB"],
        ["DFHCOMMAREA@linkage[0:20]"],
    )


def test_every_program_has_an_entry_row_and_exits_list_received_areas(out: Path) -> None:
    rows = _jumps(out, "SUBP")
    (entry,) = _by_kind(rows, "ENTRY")
    (goback,) = _by_kind(rows, "EXIT")
    assert (entry["node"], [(a["param"], a["fields"]) for a in entry["areas"]]) == (
        "",
        [(0, []), (1, []), (2, []), ],
    )
    assert [(a["param"], [f["values"] for f in a["fields"]]) for a in goback["areas"]] == [
        (0, [["ABCD"]]),
        (1, [[]]),
        (2, [[]]),
    ]


def test_the_existing_tables_are_unchanged(out: Path) -> None:
    assert {
        name: (out / name).read_text() for name in EXISTING
    } == {name: (BASELINE / name).read_text() for name in EXISTING}
```

Before running, check the WORKING-STORAGE offsets in the assertions against `out.parent / "extents.jsonl"` (`WS-AREA` 0–20, `WS-NEXT` 20–28, `WS-ONE` 28–32 …; `PROGB` `WS-X` 0–6, `WS-Y` 6–12). If the layout differs, correct the expected offsets from the extents table — never from the jump rows under test.

- [ ] **Step 3: Run** — Expected: every test except `test_the_existing_tables_are_unchanged` FAILS with `FileNotFoundError: …/jumps.jsonl`.

- [ ] **Step 4: Implement `jumps/discover.py`**

```python
"""Every jump, exit, RETRIEVE and entry in one program, and what each hands over."""

from collections.abc import Mapping

from cics.statements import CicsOperand, ExecCicsStatement
from cobble.dataflow.fields.aliases import area_extents, received_areas
from cobble.dataflow.fields.extent import CellIndex, operand_occurrence_extents
from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.state import State
from cobble.dataflow.fields.transfer import Statement
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.facts import fact_at, merged
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.srccfg.cfg import Cfg, Node
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS, commarea_field
from cobol_asg.asg_types import CobolASG
from cobol_asg.cobol_statements import (
    ExitProgramStatement,
    GobackStatement,
    StopRunStatement,
)
from cobol_memory.field_extent import FieldExtent

_KINDS = {"LINK": JumpKind.LINK, "XCTL": JumpKind.XCTL, "CALL": JumpKind.CALL}
_RETURNS = frozenset({JumpKind.LINK, JumpKind.CALL})
_CICS_OPTION = {
    JumpKind.RETURN_TRANSID: "COMMAREA",
    JumpKind.START: "FROM",
    JumpKind.RETRIEVE: "INTO",
}
_NO_TARGET = Fact(reasons=(UnresolvedReason.NO_EXTENT,))


def jumps_of(
    asg: CobolASG,
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    states: Mapping[str, State],
) -> tuple[Jump, ...]:
    return (
        _entry(asg, cfg, index),
        *(
            jump
            for node in cfg.nodes
            if node.id in states and node.id in statements
            for jump in _at(asg, cfg.program, node, statements[node.id], index, states[node.id])
        ),
    )


def _entry(asg: CobolASG, cfg: Cfg, index: CellIndex) -> Jump:
    return Jump(
        program=cfg.program,
        node="",
        line=0,
        kind=JumpKind.ENTRY,
        returns=False,
        areas=tuple(
            JumpArea(param, extent_text(extent))
            for param, extent in received_areas(asg, index)
        ),
    )


def _cics_kind(statement: ExecCicsStatement) -> tuple[JumpKind, ...]:
    verb = statement.verb.upper()
    if verb == "RETURN":
        return (
            (JumpKind.RETURN_TRANSID,) if "TRANSID" in statement.options else (JumpKind.EXIT,)
        )
    if verb == "START":
        return (JumpKind.START,)
    if verb == "RETRIEVE":
        return (JumpKind.RETRIEVE,)
    return ()


def _at(
    asg: CobolASG,
    program: str,
    node: Node,
    statement: Statement,
    index: CellIndex,
    state: State,
) -> tuple[Jump, ...]:
    if node.transfer in CALL_TRANSFERS:
        return (_cfg_jump(program, node, index, state),)
    match statement:
        case ExecCicsStatement():
            return tuple(
                _cics_jump(asg, program, node, statement, kind, index, state)
                for kind in _cics_kind(statement)
            )
        case GobackStatement() | ExitProgramStatement() | StopRunStatement():
            return (_exit(asg, program, node, index, state),)
        case _:
            return ()


def _base(program: str, node: Node, kind: JumpKind) -> Jump:
    return Jump(
        program=program,
        node=node.id,
        line=node.span.line_start,
        kind=kind,
        returns=kind in _RETURNS,
    )


def _cfg_jump(program: str, node: Node, index: CellIndex, state: State) -> Jump:
    kind = _KINDS[CALL_TRANSFERS[node.transfer]]
    base = _base(program, node, kind)
    return Jump(
        base.program,
        base.node,
        base.line,
        base.kind,
        base.returns,
        target=_target(node, index, state),
        areas=_cfg_areas(node, kind, index, state),
    )


def _target(node: Node, index: CellIndex, state: State) -> Fact:
    if node.target_resolved:
        return Fact(values=(node.target,))
    extents = operand_occurrence_extents(node.target_operand, index)
    if not extents:
        return _NO_TARGET
    return merged(tuple(fact_at(state, extent) for extent in extents))


def _cfg_areas(
    node: Node, kind: JumpKind, index: CellIndex, state: State
) -> tuple[JumpArea, ...]:
    if kind is JumpKind.CALL:
        return tuple(
            area
            for position, argument in enumerate(node.using)
            for area in _areas(position, argument.name, index, state)
        )
    return _areas(0, commarea_field(node), index, state)


def _areas(
    param: int, operand: str, index: CellIndex, state: State
) -> tuple[JumpArea, ...]:
    if not operand:
        return ()
    return tuple(
        dict.fromkeys(
            JumpArea(param, extent_text(extent), _fields(extent, index, state))
            for extent in area_extents(operand, index)
        )
    )


def _fields(extent: FieldExtent, index: CellIndex, state: State) -> tuple[Fact, ...]:
    cells = index.elementary_within(extent)
    if not cells:
        return (fact_at(state, extent),)
    return tuple(fact_at(state, index.extent_of(cell)) for cell in cells)


def _option(statement: ExecCicsStatement, name: str) -> CicsOperand:
    value = statement.options.get(name, CicsOperand(text="", is_literal=False))
    return value if isinstance(value, CicsOperand) else CicsOperand(text="", is_literal=False)


def _transid(statement: ExecCicsStatement, index: CellIndex, state: State) -> Fact:
    operand = _option(statement, "TRANSID")
    if operand.is_literal:
        return Fact(values=(operand.text,))
    extents = area_extents(operand.text, index)
    if not extents:
        return _NO_TARGET
    return merged(tuple(fact_at(state, extent) for extent in extents))


def _cics_jump(
    asg: CobolASG,
    program: str,
    node: Node,
    statement: ExecCicsStatement,
    kind: JumpKind,
    index: CellIndex,
    state: State,
) -> Jump:
    if kind is JumpKind.EXIT:
        return _exit(asg, program, node, index, state)
    base = _base(program, node, kind)
    return Jump(
        base.program,
        base.node,
        base.line,
        base.kind,
        base.returns,
        transid=(
            _transid(statement, index, state)
            if kind is not JumpKind.RETRIEVE
            else Fact()
        ),
        areas=_areas(0, _option(statement, _CICS_OPTION[kind]).text, index, state),
    )


def _exit(
    asg: CobolASG, program: str, node: Node, index: CellIndex, state: State
) -> Jump:
    base = _base(program, node, JumpKind.EXIT)
    return Jump(
        base.program,
        base.node,
        base.line,
        base.kind,
        base.returns,
        areas=tuple(
            JumpArea(param, extent_text(extent), _fields(extent, index, state))
            for param, extent in received_areas(asg, index)
        ),
    )
```

Notes for the implementer, checked against the code:
- `CALL_TRANSFERS` maps a node's transfer to `"LINK"` / `"XCTL"` / `"CALL"` (`srccfg/desugar.py:96`), which `_KINDS` turns into a `JumpKind`.
- `ExecCicsStatement.options` is `dict[str, CicsOperand | None]` (`cicada/cics/statements.py`); `_option` turns an absent or flag-only option into an empty operand so nothing reads `None`.
- A `LINK` with `COMMAREA(WS-ROW(1))`: a subscripted name matches no cell at arity 0 (the same rule `aliases.py` applies, which reports it as `caller-field-unknown`), so `area_extents` returns `()`, `areas` is empty and the row is still written (Review Focus 1).

- [ ] **Step 5: Wire it into the fixpoint**

In `fixpoint/fixpoint.py`: import `Jump` and `jumps_of`; add `jumps: tuple[Jump, ...] = ()` to `ProgramFlow` after `targets`; in `analyse()` add to the `ProgramFlow(...)` call:
```python
        jumps=jumps_of(asg, cfg, statements, index, walk.states),
```

In `fixpoint/build_corpus.py`:
- `JUMPS_FILE = "jumps.jsonl"` next to `TARGETS_FILE`; import `Jump`, `jump_row`, `jump_identity`.
- `MemberResult`: add `jumps: tuple[Jump, ...] = ()` after `targets`.
- `_tables`: add `jumps=flow.jumps,` after `targets=flow.targets,`.
- `_Sinks`: add field `jumps: JsonlWriter`; in `add_result` add `self.jumps.add_rows((jump_identity(j), jump_row(j)) for j in result.jumps)`; in `add_member` add `self.jumps.add_rows(_identified(directory / JUMPS_FILE, _jump_identity))`.
- Add:
```python
def _jump_identity(row: Row) -> str:
    return "\0".join(
        (rows.text(row, "program"), rows.text(row, "node"), rows.text(row, "kind"))
    )
```
- `_member_directory`: add `jsonl_writer(staging / JUMPS_FILE) as jumps,` to the `with`, and pass `jumps` as the fifth `_Sinks` argument.
- The corpus merge (the `with` around `_side_writer(arguments, TARGETS_FILE) as targets`): add `_side_writer(arguments, JUMPS_FILE) as jumps,` and pass it as the fifth `_Sinks` argument.
- Module docstring's table list (line ~30): add `jumps.jsonl  per jump, exit, RETRIEVE and entry, what it hands over`.

`cobble/README.md`: in the `cobble-dataflow-fixpoint` row, list `jumps` among the artefacts.

- [ ] **Step 6: Run** — `uv run --no-sync python -m pytest tests/dataflow/fixpoint -q` — Expected: PASS, including `test_the_existing_tables_are_unchanged` and every pre-existing fixpoint test.
- [ ] **Step 7: Runtime check on CardDemo** (forge root): `. ./bridge-env.sh && cd cobble && time uv run --no-sync cobble-dataflow-fixpoint --asg-dir demo/carddemo/out-parsed --out-dir /tmp/fx-after --extents demo/carddemo/out-fixpoint/extents.jsonl --all --force`. Compare with the same command on `git stash` of this task's changes into `/tmp/fx-before`. The after time must be within 10 % of before; record both in the commit message. Also `diff /tmp/fx-before/defs.jsonl /tmp/fx-after/defs.jsonl` and the same for `graph.jsonl`, `targets.jsonl`, `aliases.jsonl` — all empty.
- [ ] **Step 8: Gate and commit** — `feat(cobble): cobble-dataflow-fixpoint writes jumps.jsonl` (include the two runtimes).

---

### Task 5: Loading one program's tables for linking

**Files:**
- Modify: `cobble/cobble/dataflow/fixpoint/targets.py` — rename `_is_program_name` to `is_program_name` (update its one caller)
- Create: `combine/{__init__,flow,target_site,program_tables,load}.py`
- Test: `cobble/tests/dataflow/combine/__init__.py` (empty), `cobble/tests/dataflow/combine/test_load.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Flow:
    node: str
    source: ByteRange      # known=False: a synthetic write (a literal, a call, a file)
    target: ByteRange

@dataclass(frozen=True)
class TargetSite:
    transfer: str          # the fixpoint's targets row 'transfer'
    expression: str

@dataclass(frozen=True)
class ProgramTables:
    program: str
    facts: Mapping[str, tuple[tuple[ByteRange, Fact], ...]]   # node -> facts recorded there
    flows: Mapping[str, tuple[Flow, ...]]                      # node -> flows written there
    jumps: Mapping[str, Jump]                                  # node -> jump at that node
    received: tuple[tuple[int, ByteRange], ...]               # from the ENTRY row
    sites: Mapping[str, TargetSite]                            # node -> dynamic site

    def facts_at(self, node: str, at: ByteRange) -> tuple[tuple[ByteRange, Fact], ...]: ...
    def received_param(self, at: ByteRange) -> tuple[int, ...]: ...   # () when no area covers it

def load_tables(fixpoint_dir: Path, program: str) -> ProgramTables
```

`facts` merges two sources: every `defs.jsonl` row (keyed by its node, range from its `extent`), and every jump row's `target` and `fields` (keyed by the jump node). `jumps` excludes the `ENTRY` row (node `""`).

- [ ] **Step 1: Write the failing test**

```python
"""One program's fixpoint tables, indexed by node and byte range for linking."""

import json
from pathlib import Path

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.load import load_tables
from cobble.dataflow.combine.target_site import TargetSite
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.rows import jump_row

P = "PROGB"


def _write(directory: Path, name: str, rows: list[str]) -> None:
    (directory / name).write_text("".join(row + "\n" for row in rows))


def test_tables_index_facts_flows_jumps_received_and_sites(tmp_path: Path) -> None:
    member = tmp_path / "members" / P
    member.mkdir(parents=True)
    _write(member, "defs.jsonl", [json.dumps({
        "program": P, "node": "MAIN/2", "extent": "LK-FROM@linkage[0:8]",
        "definers": [], "values": [], "reasons": ["inbound-linkage"]})])
    _write(member, "graph.jsonl", [
        json.dumps({"type": "node", "id": "PROGB.WS-NEXT", "kind": "FIELD"}),
        json.dumps({"type": "edge", "source": "PROGB.LK-FROM", "source_kind": "FIELD",
                    "target": "PROGB.WS-NEXT", "target_kind": "FIELD", "kind": "FLOWS_TO",
                    "attrs": {"node": "MAIN/2", "source_extent": "LK-FROM@linkage[0:8]",
                              "target_extent": "WS-NEXT@working_storage[0:8]"}}),
        json.dumps({"type": "edge", "source": "PROGB.LITERAL", "source_kind": "FIELD",
                    "target": "PROGB.WS-NEXT", "target_kind": "FIELD", "kind": "FLOWS_TO",
                    "attrs": {"node": "MAIN/1", "source_extent": "",
                              "target_extent": "WS-NEXT@working_storage[0:8]"}}),
    ])
    jump = Jump(P, "MAIN/3", 9, JumpKind.XCTL, False,
                target=Fact("WS-NEXT@working_storage[0:8]", ("PROGM   ",), ("MAIN/1", "MAIN/2")))
    entry = Jump(P, "", 0, JumpKind.ENTRY, False,
                 areas=(JumpArea(0, "DFHCOMMAREA@linkage[0:20]"),))
    _write(member, "jumps.jsonl", [jump_row(entry), jump_row(jump)])
    _write(member, "targets.jsonl", [json.dumps({
        "caller": P, "node": "MAIN/3", "transfer": "CICS_XCTL", "expression": "WS-NEXT",
        "candidates": ["PROGM"], "reasons": ["inbound-linkage"], "dropped": []})])

    tables = load_tables(tmp_path, P)

    lk = byte_range("LK-FROM@linkage[0:8]", P)
    ws = byte_range("WS-NEXT@working_storage[0:8]", P)
    assert tables.facts == {
        "MAIN/2": ((lk, Fact("LK-FROM@linkage[0:8]", reasons=(UnresolvedReason.INBOUND_LINKAGE,))),),
        "MAIN/3": ((ws, jump.target),),
    }
    assert tables.flows == {
        "MAIN/2": (Flow("MAIN/2", lk, ws),),
        "MAIN/1": (Flow("MAIN/1", byte_range("", P), ws),),
    }
    assert tables.jumps == {"MAIN/3": jump}
    assert tables.received == ((0, byte_range("DFHCOMMAREA@linkage[0:20]", P)),)
    assert tables.sites == {"MAIN/3": TargetSite("CICS_XCTL", "WS-NEXT")}
    assert tables.received_param(byte_range("X@linkage[4:8]", P)) == (0,)
    assert tables.received_param(byte_range("X@linkage[30:34]", P)) == ()
    assert tables.facts_at("MAIN/2", byte_range("X@linkage[2:4]", P)) == tables.facts["MAIN/2"]
```

(`definers` in the defs row become the Fact's `writers`; values/reasons as written.)

- [ ] **Step 2: Run** — Expected: FAIL, `No module named 'cobble.dataflow.combine'`.

- [ ] **Step 3: Implement**

`combine/__init__.py`:
```python
"""Combine: link the per-program fixpoint results across programs."""
```

`combine/flow.py`:
```python
"""Flow — one flow row: bytes copied (or synthetically written) at one node."""

from dataclasses import dataclass

from cobble.dataflow.fields.extent_text import ByteRange


@dataclass(frozen=True)
class Flow:
    node: str
    source: ByteRange
    target: ByteRange
```

`combine/target_site.py`:
```python
"""TargetSite — a dynamic call site as the fixpoint's targets table names it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetSite:
    transfer: str
    expression: str
```

`combine/program_tables.py`:
```python
"""ProgramTables — one program's facts, flows, jumps and received areas, indexed."""

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.target_site import TargetSite
from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump


@dataclass(frozen=True)
class ProgramTables:
    program: str
    facts: Mapping[str, tuple[tuple[ByteRange, Fact], ...]]
    flows: Mapping[str, tuple[Flow, ...]]
    jumps: Mapping[str, Jump]
    received: tuple[tuple[int, ByteRange], ...]
    sites: Mapping[str, TargetSite]

    def facts_at(self, node: str, at: ByteRange) -> tuple[tuple[ByteRange, Fact], ...]:
        return tuple(
            (where, fact) for where, fact in self.facts.get(node, ()) if where.overlaps(at)
        )

    def received_param(self, at: ByteRange) -> tuple[int, ...]:
        return tuple(param for param, area in self.received if area.covers(at))[:1]
```

`combine/load.py`:
```python
"""Load one program's fixpoint tables from its member directory."""

from collections.abc import Iterable, Mapping
from itertools import groupby
from pathlib import Path
from types import MappingProxyType

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.target_site import TargetSite
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint import rows
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_from_row

_FLOWS_TO = "FLOWS_TO"


def _grouped[T](pairs: Iterable[tuple[str, T]]) -> Mapping[str, tuple[T, ...]]:
    ordered = sorted(pairs, key=lambda pair: pair[0])
    return MappingProxyType(
        {key: tuple(value for _, value in group) for key, group in groupby(ordered, key=lambda pair: pair[0])}
    )


def _def_fact(row: rows.Row) -> Fact:
    return Fact(
        extent=rows.text(row, "extent"),
        values=rows.strings(row, "values"),
        writers=rows.strings(row, "definers"),
        reasons=tuple(UnresolvedReason(r) for r in rows.strings(row, "reasons")),
    )


def _def_facts(member: Path, program: str) -> tuple[tuple[str, tuple[ByteRange, Fact]], ...]:
    return tuple(
        (rows.text(row, "node"), (byte_range(rows.text(row, "extent"), program), _def_fact(row)))
        for row in rows.read(member / "defs.jsonl")
    )


def _jump_facts(jump: Jump) -> tuple[tuple[str, tuple[ByteRange, Fact]], ...]:
    facts = (jump.target, *(field for area in jump.areas for field in area.fields))
    return tuple(
        (jump.node, (byte_range(fact.extent, jump.program), fact))
        for fact in facts
        if fact.extent
    )


def _flows(member: Path, program: str) -> tuple[tuple[str, Flow], ...]:
    return tuple(
        (
            rows.text(attrs, "node"),
            Flow(
                rows.text(attrs, "node"),
                byte_range(rows.text(attrs, "source_extent"), program),
                byte_range(rows.text(attrs, "target_extent"), program),
            ),
        )
        for row in rows.read(member / "graph.jsonl")
        if rows.text(row, "type") == "edge" and rows.text(row, "kind") == _FLOWS_TO
        for attrs in (rows.nested(row, "attrs"),)
    )


def _jumps(member: Path) -> tuple[Jump, ...]:
    path = member / "jumps.jsonl"
    if not path.is_file():
        return ()
    return tuple(jump_from_row(line) for line in path.read_text().splitlines() if line.strip())


def load_tables(fixpoint_dir: Path, program: str) -> ProgramTables:
    member = fixpoint_dir / "members" / program
    jumps = _jumps(member)
    entries = tuple(jump for jump in jumps if jump.kind is JumpKind.ENTRY)
    real = tuple(jump for jump in jumps if jump.kind is not JumpKind.ENTRY)
    return ProgramTables(
        program=program,
        facts=_grouped(
            (*_def_facts(member, program), *(f for jump in real for f in _jump_facts(jump)))
        ),
        flows=_grouped(_flows(member, program)),
        jumps=MappingProxyType({jump.node: jump for jump in real}),
        received=tuple(
            (area.param, byte_range(area.extent, program))
            for entry in entries[:1]
            for area in entry.areas
        ),
        sites=MappingProxyType(
            {
                rows.text(row, "node"): TargetSite(
                    rows.text(row, "transfer"), rows.text(row, "expression")
                )
                for row in rows.read(member / "targets.jsonl")
            }
        ),
    )
```

(`_grouped` keeps rows within a node in file order because `sorted` is stable.)

- [ ] **Step 4: Run** — Expected: PASS. Mutation-check: drop the `_jump_facts` contribution; drop the `kind == FLOWS_TO` filter. Each must fail.
- [ ] **Step 5: Gate and commit** — `feat(cobble): load one program's fixpoint tables for linking`.

---

### Task 6: The resolve step

**Files:**
- Create: `combine/{stop_kind,stop,resolution,resolve}.py`
- Test: `cobble/tests/dataflow/combine/test_resolve.py`

**Interfaces:**

```python
class StopKind(Enum):
    RECEIVED = "received"     # this program's received area `param`, bytes `at`
    RETURNED = "returned"     # bytes left by the LINK/CALL at `node`, area `param`
    RETRIEVED = "retrieved"   # bytes written by the RETRIEVE at `node`
    UNKNOWN = "unknown"       # `reasons`

@dataclass(frozen=True)
class Stop:
    kind: StopKind
    at: ByteRange = NO_RANGE
    node: str = ""
    param: int = 0
    reasons: tuple[UnresolvedReason, ...] = ()

@dataclass(frozen=True)
class Resolution:
    values: frozenset[str] = frozenset()
    stops: frozenset[Stop] = frozenset()

def joined(left: Resolution, right: Resolution) -> Resolution
def resolve(tables: ProgramTables, node: str, at: ByteRange) -> Resolution
```

Values are sliced to the requested bytes (`at` inside a fact's range), so a reference-modified read gets the right bytes; stripping happens only when values become program names (Task 7).

- [ ] **Step 1: Write the failing tests**

```python
"""resolve: what some bytes hold at a node, back to the stops linking follows."""

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolution import Resolution
from cobble.dataflow.combine.resolve import resolve
from cobble.dataflow.combine.stop import Stop
from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.jump_area import JumpArea

P = "PROGB"


def r(text: str) -> ByteRange:
    return byte_range(text, P)


def tables(
    facts: dict[str, tuple[tuple[ByteRange, Fact], ...]],
    flows: dict[str, tuple[Flow, ...]],
    jumps: dict[str, Jump] = {},
) -> ProgramTables:
    return ProgramTables(
        program=P,
        facts=facts,
        flows=flows,
        jumps=jumps,
        received=((0, r("DFHCOMMAREA@linkage[0:20]")),),
        sites={},
    )


LK = r("LK-FROM@linkage[0:8]")
WS = r("WS-NEXT@working_storage[0:8]")
TMP = r("WS-TMP@working_storage[8:20]")


def test_received_bytes_are_found_through_several_copies_of_different_widths() -> None:
    t = tables(
        facts={
            "J": ((WS, Fact("WS-NEXT@working_storage[0:8]", writers=("M2",))),),
            "M2": ((TMP, Fact("WS-TMP@working_storage[8:20]", writers=("M1",))),),
            "M1": ((LK, Fact("LK-FROM@linkage[0:8]", reasons=(UnresolvedReason.INBOUND_LINKAGE,))),),
        },
        flows={
            "M2": (Flow("M2", r("WS-TMP@working_storage[8:16]"), WS),),
            "M1": (Flow("M1", LK, r("WS-TMP@working_storage[8:16]")),),
        },
    )
    assert resolve(t, "J", WS) == Resolution(
        stops=frozenset({Stop(StopKind.RECEIVED, at=r("LK-FROM@linkage[0:8]"), param=0)})
    )


def test_a_reference_modified_copy_rebases_onto_the_right_source_bytes() -> None:
    t = tables(
        facts={
            "J": ((WS, Fact("WS-NEXT@working_storage[0:8]", writers=("M1",))),),
            "M1": ((r("LK-AREA@linkage[0:20]"), Fact("LK-AREA@linkage[0:20]")),),
        },
        flows={"M1": (Flow("M1", r("LK-AREA@linkage[12:20]"), WS),)},
    )
    (stop,) = resolve(t, "J", r("WS-NEXT@working_storage[2:6]")).stops
    assert (stop.kind, stop.at.start, stop.at.end) == (StopKind.RECEIVED, 14, 18)


def test_bytes_left_by_a_link_and_a_call_stop_as_returned_in_the_right_area() -> None:
    call = Jump(P, "C", 5, JumpKind.CALL, True, areas=(
        JumpArea(0, "WS-A@working_storage[0:4]"),
        JumpArea(1, "WS-B@working_storage[4:12]"),
    ))
    b = r("WS-B@working_storage[4:12]")
    t = tables(
        facts={"J": ((b, Fact("WS-B@working_storage[4:12]", writers=("C",))),)},
        flows={"C": (Flow("C", NO_RANGE, b),)},
        jumps={"C": call},
    )
    assert resolve(t, "J", b).stops == frozenset(
        {Stop(StopKind.RETURNED, at=b, node="C", param=1)}
    )


def test_a_retrieve_stop_is_decided_by_its_node_not_its_reason() -> None:
    y = r("WS-Y@working_storage[0:6]")
    retrieve = Jump(P, "R", 3, JumpKind.RETRIEVE, False, areas=(JumpArea(0, "WS-Y@working_storage[0:6]"),))
    t = tables(
        facts={"J": ((y, Fact("WS-Y@working_storage[0:6]", writers=("R",), reasons=(UnresolvedReason.NOT_A_LITERAL,))),)},
        flows={"R": (Flow("R", NO_RANGE, y),)},
        jumps={"R": retrieve},
    )
    assert resolve(t, "J", y).stops == frozenset({Stop(StopKind.RETRIEVED, at=y, node="R")})


def test_a_literal_write_inside_the_walk_contributes_its_value_only() -> None:
    t = tables(
        facts={"J": ((WS, Fact("WS-NEXT@working_storage[0:8]", values=("PROGM   ",), writers=("M1",))),)},
        flows={"M1": (Flow("M1", NO_RANGE, WS),)},
    )
    assert resolve(t, "J", WS) == Resolution(values=frozenset({"PROGM   "}))


def test_a_computed_value_stops_as_unknown_with_its_reason() -> None:
    n = r("WS-N@working_storage[0:4]")
    t = tables(facts={"J": ((n, Fact("WS-N@working_storage[0:4]", reasons=(UnresolvedReason.UNINITIALISED,))),)}, flows={})
    assert resolve(t, "J", n) == Resolution(
        stops=frozenset({Stop(StopKind.UNKNOWN, reasons=(UnresolvedReason.UNINITIALISED,))})
    )


def test_no_facts_at_a_point_is_reported_not_guessed() -> None:
    assert resolve(tables(facts={}, flows={}), "J", WS) == Resolution(
        stops=frozenset({Stop(StopKind.UNKNOWN, reasons=(UnresolvedReason.NOT_RECORDED,))})
    )


def test_a_copy_loop_inside_one_program_terminates() -> None:
    a, b = r("WS-A@working_storage[0:4]"), r("WS-B@working_storage[4:8]")
    t = tables(
        facts={
            "J": ((a, Fact("WS-A@working_storage[0:4]", writers=("M1",))),),
            "M1": ((b, Fact("WS-B@working_storage[4:8]", writers=("M2",))),),
            "M2": ((a, Fact("WS-A@working_storage[0:4]", writers=("M1",))),),
        },
        flows={"M1": (Flow("M1", b, a),), "M2": (Flow("M2", a, b),)},
    )
    assert resolve(t, "J", a) == Resolution()
```

- [ ] **Step 2: Run** — Expected: FAIL, missing modules.

- [ ] **Step 3: Implement**

`combine/stop_kind.py`:
```python
"""StopKind — where a backwards walk inside one program can end."""

from enum import Enum


class StopKind(Enum):
    RECEIVED = "received"
    RETURNED = "returned"
    RETRIEVED = "retrieved"
    UNKNOWN = "unknown"
```

`combine/stop.py`:
```python
"""Stop — one place a value's bytes come from that this program cannot see past."""

from dataclasses import dataclass

from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange
from cobble.dataflow.fields.values import UnresolvedReason


@dataclass(frozen=True)
class Stop:
    kind: StopKind
    at: ByteRange = NO_RANGE
    node: str = ""
    param: int = 0
    reasons: tuple[UnresolvedReason, ...] = ()
```

`combine/resolution.py`:
```python
"""Resolution — the values some bytes hold here, and the stops still to follow."""

from dataclasses import dataclass

from cobble.dataflow.combine.stop import Stop


@dataclass(frozen=True)
class Resolution:
    values: frozenset[str] = frozenset()
    stops: frozenset[Stop] = frozenset()


def joined(left: Resolution, right: Resolution) -> Resolution:
    return Resolution(left.values | right.values, left.stops | right.stops)
```

`combine/resolve.py`:
```python
"""Resolve what some bytes hold at one node, walking back to received, returned and retrieved bytes."""

from dataclasses import replace
from functools import reduce

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolution import Resolution, joined
from cobble.dataflow.combine.stop import Stop
from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind

_LINKAGE = "linkage"
_CALLS = frozenset({JumpKind.LINK, JumpKind.CALL})
_STRUCTURAL = frozenset({UnresolvedReason.INBOUND_LINKAGE, UnresolvedReason.FROM_CALLEE})
_Seen = frozenset[tuple[str, str, int, int]]


def resolve(tables: ProgramTables, node: str, at: ByteRange) -> Resolution:
    facts = tables.facts_at(node, at)
    if not facts:
        return Resolution(stops=frozenset({Stop(StopKind.UNKNOWN, reasons=(UnresolvedReason.NOT_RECORDED,))}))
    return _from_facts(tables, node, at, facts, frozenset())


def _key(node: str, at: ByteRange) -> tuple[str, str, int, int]:
    return (node, at.region, at.start, at.end)


def _overlap(a: ByteRange, b: ByteRange) -> ByteRange:
    return replace(a, start=max(a.start, b.start), end=min(a.end, b.end))


def _from_facts(
    tables: ProgramTables,
    node: str,
    at: ByteRange,
    facts: tuple[tuple[ByteRange, Fact], ...],
    seen: _Seen,
) -> Resolution:
    if _key(node, at) in seen:
        return Resolution()
    inner = seen | {_key(node, at)}
    return reduce(
        joined,
        (_from_fact(tables, at, where, fact, inner) for where, fact in facts),
        Resolution(),
    )


def _sliced(fact: Fact, where: ByteRange, part: ByteRange) -> frozenset[str]:
    lo, hi = part.start - where.start, part.end - where.start
    return frozenset(value[lo:hi] for value in fact.values)


def _from_fact(
    tables: ProgramTables, at: ByteRange, where: ByteRange, fact: Fact, seen: _Seen
) -> Resolution:
    part = _overlap(at, where)
    values = Resolution(values=_sliced(fact, where, part))
    if fact.writers:
        return reduce(
            joined,
            (
                _through(tables, writer, flow, part, fact, seen)
                for writer in fact.writers
                for flow in tables.flows.get(writer, ())
                if flow.target.overlaps(part)
            ),
            values,
        )
    if part.region == _LINKAGE and not fact.values:
        return joined(values, _received(tables, part))
    return joined(values, _unknown(fact))


def _received(tables: ProgramTables, part: ByteRange) -> Resolution:
    params = tables.received_param(part)
    if not params:
        return Resolution(stops=frozenset({Stop(StopKind.UNKNOWN, reasons=(UnresolvedReason.INBOUND_LINKAGE,))}))
    return Resolution(stops=frozenset({Stop(StopKind.RECEIVED, at=part, param=params[0])}))


def _unknown(fact: Fact) -> Resolution:
    reasons = tuple(r for r in fact.reasons if r not in _STRUCTURAL)
    if fact.values or not reasons:
        return Resolution()
    return Resolution(stops=frozenset({Stop(StopKind.UNKNOWN, reasons=reasons)}))


def _through(
    tables: ProgramTables,
    writer: str,
    flow: Flow,
    part: ByteRange,
    fact: Fact,
    seen: _Seen,
) -> Resolution:
    written = _overlap(part, flow.target)
    if not flow.source.known:
        return _synthetic(tables, writer, written, fact)
    offset = flow.source.start - flow.target.start
    source = replace(
        flow.source,
        start=written.start + offset,
        end=min(flow.source.end, written.end + offset),
    )
    if source.start >= source.end:
        return Resolution()
    return _from_facts(tables, writer, source, tables.facts_at(writer, source), seen)


def _synthetic(
    tables: ProgramTables, writer: str, written: ByteRange, fact: Fact
) -> Resolution:
    if writer not in tables.jumps:
        return _unknown(fact)
    jump = tables.jumps[writer]
    if jump.kind in _CALLS:
        return _returned(tables, jump, written, fact)
    if jump.kind is JumpKind.RETRIEVE:
        return Resolution(
            stops=frozenset({Stop(StopKind.RETRIEVED, at=written, node=writer)})
        )
    return _unknown(fact)


def _returned(
    tables: ProgramTables, jump: Jump, written: ByteRange, fact: Fact
) -> Resolution:
    params = tuple(
        area.param
        for area in jump.areas
        if byte_range(area.extent, tables.program).covers(written)
    )[:1]
    if not params:
        return _unknown(fact)
    return Resolution(
        stops=frozenset(
            {Stop(StopKind.RETURNED, at=written, node=jump.node, param=params[0])}
        )
    )
```

When a fact has writers but none of their flows overlap `part` (a write the flow table did not record, e.g. an unmodelled one), the result is the fact's own values only — `reduce` over an empty generator returns `values`. That matches today's fixpoint, which already folded such writes into the fact's reasons.

- [ ] **Step 4: Run** — Expected: PASS. Mutation-check: (a) remove the rebase `offset` (use `written` as `source`) → `test_a_reference_modified_copy…` fails; (b) drop the `seen` guard → `test_a_copy_loop…` recurses forever (pytest timeout / RecursionError). Restore.
- [ ] **Step 5: Gate and commit** — `feat(cobble): resolve a value back to received, returned and retrieved bytes`.

---

### Task 7: Linking in rounds

**Files:**
- Create: `combine/{callee_areas,edge,held,linked_target,outside_jumps,run_report,linked,link}.py`
- Test: `cobble/tests/dataflow/combine/test_link.py`

**Interfaces:**

```python
class CalleeAreas(Protocol):
    def area(self, callee: str, kind: JumpKind, param: int) -> ByteRange: ...   # NO_RANGE if none

@dataclass(frozen=True)
class Edge:
    caller: str
    node: str
    kind: JumpKind
    callee: str
    param: int
    caller_window: ByteRange
    callee_window: ByteRange
    callee_node: str = ""      # START: the callee's RETRIEVE node
    discovered: bool = False

@dataclass(frozen=True)
class Held:
    values: frozenset[str] = frozenset()
    reasons: frozenset[UnresolvedReason] = frozenset()
    outside: frozenset[str] = frozenset()

@dataclass(frozen=True)
class OutsideJumps:
    known_into: Mapping[str, tuple[str, ...]] = {}   # inside program -> outside programs jumping in
    unresolved: int = 0
    without_results: tuple[str, ...] = ()

@dataclass(frozen=True)
class LinkedTarget:
    target: ResolvedTarget
    outside: tuple[str, ...] = ()

@dataclass(frozen=True)
class Linked:
    targets: tuple[LinkedTarget, ...]
    edges: tuple[Edge, ...]
    report: RunReport

def link(tables: Mapping[str, ProgramTables], areas: CalleeAreas,
         transactions: Mapping[str, str], outside: OutsideJumps) -> Linked
```

Rounds recompute the edge set from the current values until no new edge appears; values within a round are a depth-first walk with a `visiting` guard (sound for "may hold" — every reachable value is collected exactly once per path).

- [ ] **Step 1: Write the failing tests** — hand-built tables per program and a fake areas map.

```python
"""Linking: values cross programs over a call graph that grows from those values."""

from collections.abc import Mapping

from cobble.dataflow.combine.callee_areas import CalleeAreas
from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.link import link
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.target_site import TargetSite
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.jump_area import JumpArea


class FakeAreas(CalleeAreas):
    def __init__(self, areas: Mapping[tuple[str, int], str]) -> None:
        self._areas = areas

    def area(self, callee: str, kind: JumpKind, param: int) -> ByteRange:
        text = self._areas.get((callee, param), "")
        return byte_range(text, callee) if text else NO_RANGE


def _facts(program: str, facts: tuple[Fact, ...]) -> tuple[tuple[ByteRange, Fact], ...]:
    return tuple((byte_range(fact.extent, program), fact) for fact in facts)


def caller(name: str, stamp: str, to: str) -> ProgramTables:
    fields = (
        Fact("WS-FROM@working_storage[0:8]", values=(stamp.ljust(8),), writers=("S",)),
        Fact("WS-REST@working_storage[8:20]", reasons=(UnresolvedReason.UNINITIALISED,)),
    )
    jump = Jump(
        name, "X", 9, JumpKind.XCTL, False,
        target=Fact(values=(to,)),
        areas=(JumpArea(0, "WS-AREA@working_storage[0:20]", fields),),
    )
    return ProgramTables(
        name,
        facts={"X": _facts(name, fields)},
        flows={},
        jumps={"X": jump},
        received=((0, byte_range("DFHCOMMAREA@linkage[0:20]", name)),),
        sites={},
    )


def returner(name: str, fallback: str) -> ProgramTables:
    ws = byte_range("WS-NEXT@working_storage[0:8]", name)
    lk = byte_range("LK-FROM@linkage[0:8]", name)
    inbound = Fact("LK-FROM@linkage[0:8]", reasons=(UnresolvedReason.INBOUND_LINKAGE,))
    target = Fact(
        "WS-NEXT@working_storage[0:8]", values=(fallback.ljust(8),), writers=("M1", "M2")
    )
    jump = Jump(
        name, "X", 9, JumpKind.XCTL, False,
        target=target,
        areas=(JumpArea(0, "DFHCOMMAREA@linkage[0:20]", (inbound,)),),
    )
    return ProgramTables(
        name,
        facts={"X": _facts(name, (target, inbound)), "M2": ((lk, inbound),)},
        flows={"M1": (Flow("M1", NO_RANGE, ws),), "M2": (Flow("M2", lk, ws),)},
        jumps={"X": jump},
        received=((0, byte_range("DFHCOMMAREA@linkage[0:20]", name)),),
        sites={"X": TargetSite("CICS_XCTL", "WS-NEXT")},
    )


def areas(*names: str) -> FakeAreas:
    return FakeAreas({(n, 0): "DFHCOMMAREA@linkage[0:20]" for n in names})


def _row(
    linked: Linked, program: str
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    (found,) = [t for t in linked.targets if t.target.caller == program]
    return (
        found.target.candidates,
        tuple(r.value for r in found.target.reasons),
        found.outside,
    )


def test_return_to_caller_resolves_to_every_program_that_jumps_in() -> None:
    linked = link(
        {"A": caller("A", "A", "B"), "B": returner("B", "M")}, areas("A", "B"), {}, OutsideJumps()
    )
    assert _row(linked, "B") == (("A", "M"), (), ())
    assert {(e.caller, e.callee, e.discovered) for e in linked.edges} == {
        ("A", "B", False),
        ("B", "A", True),
    }


def test_a_target_found_only_across_programs_grows_the_call_graph() -> None:
    tables = {"C": caller("C", "R", "P"), "P": returner("P", "M"), "R": returner("R", "Q")}
    linked = link(tables, areas("C", "P", "R"), {}, OutsideJumps())
    assert _row(linked, "P") == (("M", "R"), (), ())
    assert ("P", "R", True) in {(e.caller, e.callee, e.discovered) for e in linked.edges}
    assert _row(linked, "R") == (("Q", "R"), (), ())


def test_a_cycle_that_adds_nothing_terminates_with_no_invented_candidates() -> None:
    linked = link(
        {"A": returner("A", "B"), "B": returner("B", "A")}, areas("A", "B"), {}, OutsideJumps()
    )
    assert (_row(linked, "A"), _row(linked, "B")) == ((("B",), (), ()), (("A",), (), ()))


def test_a_window_narrower_than_the_bytes_contributes_nothing() -> None:
    linked = link(
        {"A": caller("A", "A", "B"), "B": returner("B", "M")},
        FakeAreas({("B", 0): "DFHCOMMAREA@linkage[0:4]"}),
        {},
        OutsideJumps(),
    )
    assert _row(linked, "B") == (("M",), ("inbound-linkage",), ())


def test_an_outside_caller_with_a_known_target_is_named() -> None:
    linked = link(
        {"B": returner("B", "M")}, areas("B"), {}, OutsideJumps(known_into={"B": ("OUT1",)})
    )
    assert _row(linked, "B") == (
        ("M",),
        ("inbound-linkage", "outside-analysed-set"),
        ("OUT1",),
    )
```

Add three more in the same style, each asserting exact candidates:
- `test_return_transid_re_enters_the_programs_own_entry` — `B` with a `RETURN_TRANSID` jump `transid=Fact(values=("TRNB",))`, `areas=(JumpArea(0, "DFHCOMMAREA@linkage[0:20]", (Fact("LK-FROM@linkage[0:8]", values=("A       ",)),)),)`, `transactions={"TRNB": "B"}` → `B`'s XCTL candidates include `A`.
- `test_start_from_reaches_the_started_programs_retrieve` — `S` with `START` (`transid TRNR`, `FROM` field holding `"PROGZ   "`), `R` whose XCTL target was written at its `RETRIEVE` node (flow with `NO_RANGE` source at the `RETRIEVE` node) → `R`'s candidates `("PROGZ",)`.
- `test_a_link_write_back_reaches_the_callers_later_jump` — `A` `LINK`s `W` passing `WS-AREA`; `W`'s `EXIT` row field `LK-FROM` holds `"Q       "`; `A`'s later XCTL target was written at the `LINK` node (flow with `NO_RANGE` source at the `LINK` node) → candidates `("Q",)`.

- [ ] **Step 2: Run** — Expected: FAIL, missing modules.

- [ ] **Step 3: Implement**

`combine/callee_areas.py`:
```python
"""CalleeAreas — where a callee receives the bytes a jump hands it."""

from typing import Protocol

from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.jumps.jump_kind import JumpKind


class CalleeAreas(Protocol):
    def area(self, callee: str, kind: JumpKind, param: int) -> ByteRange: ...
```

`combine/edge.py`:
```python
"""Edge — one program-to-program link linking used, with its lined-up bytes."""

from dataclasses import dataclass

from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.jumps.jump_kind import JumpKind


@dataclass(frozen=True)
class Edge:
    caller: str
    node: str
    kind: JumpKind
    callee: str
    param: int
    caller_window: ByteRange
    callee_window: ByteRange
    callee_node: str = ""
    discovered: bool = False
```

`combine/held.py`:
```python
"""Held — the values some bytes can hold across programs, and why there may be more."""

from dataclasses import dataclass

from cobble.dataflow.fields.values import UnresolvedReason


@dataclass(frozen=True)
class Held:
    values: frozenset[str] = frozenset()
    reasons: frozenset[UnresolvedReason] = frozenset()
    outside: frozenset[str] = frozenset()


def held_join(left: Held, right: Held) -> Held:
    return Held(left.values | right.values, left.reasons | right.reasons, left.outside | right.outside)
```

`combine/outside_jumps.py`:
```python
"""OutsideJumps — what programs outside a linked set say about jumping into it."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True)
class OutsideJumps:
    known_into: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))
    unresolved: int = 0
    without_results: tuple[str, ...] = ()
```

`combine/run_report.py`:
```python
"""RunReport — the facts about a run stated once, not on every value."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RunReport:
    rounds: int = 0
    discovered: int = 0
    unresolved_outside_jumps: int = 0
    without_results: tuple[str, ...] = ()
```

`combine/linked_target.py`:
```python
"""LinkedTarget — a dynamic site after linking, with the outside callers it may miss."""

from dataclasses import dataclass

from cobble.dataflow.fixpoint.targets import ResolvedTarget


@dataclass(frozen=True)
class LinkedTarget:
    target: ResolvedTarget
    outside: tuple[str, ...] = ()
```

`combine/linked.py`:
```python
"""Linked — the result of linking: targets, the edges used, and the run report."""

from dataclasses import dataclass

from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.linked_target import LinkedTarget
from cobble.dataflow.combine.run_report import RunReport


@dataclass(frozen=True)
class Linked:
    targets: tuple[LinkedTarget, ...]
    edges: tuple[Edge, ...]
    report: RunReport
```

`combine/link.py`:
```python
"""Link programs: values cross programs over a call graph grown from those values, in rounds."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import reduce

from cobble.dataflow.combine.callee_areas import CalleeAreas
from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.held import Held, held_join
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.linked_target import LinkedTarget
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolve import resolve
from cobble.dataflow.combine.run_report import RunReport
from cobble.dataflow.combine.stop import Stop
from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.targets import ResolvedTarget, is_program_name
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind

_ENTERING = frozenset({JumpKind.XCTL, JumpKind.LINK, JumpKind.CALL, JumpKind.RETURN_TRANSID})
_PROGRAM_JUMPS = frozenset({JumpKind.XCTL, JumpKind.LINK, JumpKind.CALL})
_Visiting = frozenset[tuple[str, str, str, int, int]]


@dataclass(frozen=True)
class _World:
    tables: Mapping[str, ProgramTables]
    edges: frozenset[Edge]
    outside: OutsideJumps


def link(
    tables: Mapping[str, ProgramTables],
    areas: CalleeAreas,
    transactions: Mapping[str, str],
    outside: OutsideJumps,
) -> Linked:
    return _rounds(tables, areas, transactions, outside, frozenset(), 1)


def _rounds(
    tables: Mapping[str, ProgramTables],
    areas: CalleeAreas,
    transactions: Mapping[str, str],
    outside: OutsideJumps,
    edges: frozenset[Edge],
    round_: int,
) -> Linked:
    world = _World(tables, edges, outside)
    found = frozenset(_edges(world, areas, transactions))
    if found <= edges:
        return _linked(world, round_)
    return _rounds(tables, areas, transactions, outside, edges | found, round_ + 1)


def _names(values: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted({v.rstrip() for v in values if is_program_name(v.rstrip())}))


def _fact_held(world: _World, program: str, node: str, fact: Fact) -> Held:
    if not fact.extent:
        return Held(values=frozenset(fact.values))
    return _held(world, program, node, byte_range(fact.extent, program), frozenset())


def _shifted(at: ByteRange, src: ByteRange, dst: ByteRange, program: str) -> ByteRange:
    start = max(at.start, src.start)
    end = min(at.end, src.end)
    return replace(dst, program=program, start=dst.start + start - src.start, end=dst.start + end - src.start)


def _held(world: _World, program: str, node: str, at: ByteRange, visiting: _Visiting) -> Held:
    if program not in world.tables:
        return Held(reasons=frozenset({UnresolvedReason.OUTSIDE_ANALYSED_SET}))
    key = (program, node, at.region, at.start, at.end)
    if key in visiting:
        return Held()
    found = resolve(world.tables[program], node, at)
    inner = visiting | {key}
    return reduce(
        held_join,
        (_stop(world, program, stop, inner) for stop in found.stops),
        Held(values=found.values),
    )


def _stop(world: _World, program: str, stop: Stop, visiting: _Visiting) -> Held:
    match stop.kind:
        case StopKind.UNKNOWN:
            return Held(reasons=frozenset(stop.reasons))
        case StopKind.RECEIVED:
            return _received(world, program, stop, visiting)
        case StopKind.RETURNED:
            return _returned(world, program, stop, visiting)
        case StopKind.RETRIEVED:
            return _retrieved(world, program, stop, visiting)


def _outside_callers(world: _World, program: str) -> Held:
    callers = world.outside.known_into.get(program, ())
    if not callers:
        return Held()
    return Held(
        reasons=frozenset({UnresolvedReason.OUTSIDE_ANALYSED_SET}),
        outside=frozenset(callers),
    )


def _received(world: _World, program: str, stop: Stop, visiting: _Visiting) -> Held:
    into = tuple(
        e
        for e in world.edges
        if e.callee == program
        and e.kind in _ENTERING
        and e.param == stop.param
        and e.callee_window.covers(stop.at)
    )
    from_callers = reduce(
        held_join,
        (
            _held(
                world,
                e.caller,
                e.node,
                _shifted(stop.at, e.callee_window, e.caller_window, e.caller),
                visiting,
            )
            for e in into
        ),
        Held(),
    )
    gaps = Held() if into else Held(reasons=frozenset({UnresolvedReason.INBOUND_LINKAGE}))
    return held_join(held_join(from_callers, gaps), _outside_callers(world, program))


def _returned(world: _World, program: str, stop: Stop, visiting: _Visiting) -> Held:
    out = tuple(e for e in world.edges if e.caller == program and e.node == stop.node and e.param == stop.param)
    if not out:
        return Held(reasons=frozenset({UnresolvedReason.FROM_CALLEE}))
    return reduce(
        held_join,
        (
            _held(world, e.callee, exit_.node, _shifted(stop.at, e.caller_window, e.callee_window, e.callee), visiting)
            for e in out
            for exit_ in _exits(world, e.callee)
        ),
        Held(),
    )


def _exits(world: _World, program: str) -> tuple[Jump, ...]:
    if program not in world.tables:
        return ()
    return tuple(j for j in world.tables[program].jumps.values() if j.kind is JumpKind.EXIT)


def _retrieved(world: _World, program: str, stop: Stop, visiting: _Visiting) -> Held:
    starts = tuple(e for e in world.edges if e.kind is JumpKind.START and e.callee == program and e.callee_node == stop.node)
    if not starts:
        return Held(reasons=frozenset({UnresolvedReason.NOT_A_LITERAL}))
    return reduce(
        held_join,
        (
            _held(world, e.caller, e.node, _shifted(stop.at, e.callee_window, e.caller_window, e.caller), visiting)
            for e in starts
        ),
        Held(),
    )


def _lined_up(caller: ByteRange, callee: ByteRange) -> tuple[ByteRange, ByteRange]:
    shared = min(caller.length, callee.length)
    return (replace(caller, end=caller.start + shared), replace(callee, end=callee.start + shared))


def _edges(world: _World, areas: CalleeAreas, transactions: Mapping[str, str]) -> tuple[Edge, ...]:
    return tuple(
        edge
        for program, tables in world.tables.items()
        for jump in tables.jumps.values()
        for edge in _jump_edges(world, areas, transactions, program, jump)
    )


def _callees(world: _World, areas: CalleeAreas, transactions: Mapping[str, str], program: str, jump: Jump) -> tuple[tuple[str, bool], ...]:
    if jump.kind in _PROGRAM_JUMPS:
        own = set(_names(frozenset(jump.target.values)))
        found = _names(_fact_held(world, program, jump.node, jump.target).values)
        return tuple((name, name not in own) for name in found)
    if jump.kind in (JumpKind.RETURN_TRANSID, JumpKind.START):
        own = set(_names(frozenset(jump.transid.values)))
        found = _names(_fact_held(world, program, jump.node, jump.transid).values)
        return tuple((transactions[t], t not in own) for t in found if t in transactions)
    return ()


def _jump_edges(world: _World, areas: CalleeAreas, transactions: Mapping[str, str], program: str, jump: Jump) -> tuple[Edge, ...]:
    return tuple(
        edge
        for callee, discovered in _callees(world, areas, transactions, program, jump)
        for area in jump.areas
        for edge in _area_edges(world, areas, program, jump, callee, discovered, area.param, byte_range(area.extent, program))
    )


def _area_edges(world: _World, areas: CalleeAreas, program: str, jump: Jump, callee: str, discovered: bool, param: int, mine: ByteRange) -> tuple[Edge, ...]:
    if jump.kind is JumpKind.START:
        return tuple(
            Edge(program, jump.node, jump.kind, callee, param, *_lined_up(mine, byte_range(r.areas[0].extent, callee)), callee_node=r.node, discovered=discovered)
            for r in (world.tables[callee].jumps.values() if callee in world.tables else ())
            if r.kind is JumpKind.RETRIEVE and r.areas
        )
    kind = JumpKind.XCTL if jump.kind is JumpKind.RETURN_TRANSID else jump.kind
    theirs = areas.area(callee, kind, param)
    if not theirs.known:
        return ()
    return (Edge(program, jump.node, jump.kind, callee, param, *_lined_up(mine, theirs), discovered=discovered),)


def _target(world: _World, program: str, node: str) -> LinkedTarget:
    tables = world.tables[program]
    jump = tables.jumps[node]
    site = tables.sites[node]
    held = _fact_held(world, program, node, jump.target)
    names = _names(held.values)
    return LinkedTarget(
        ResolvedTarget(
            caller=program,
            node=node,
            transfer=site.transfer,
            expression=site.expression,
            candidates=names,
            reasons=tuple(sorted(held.reasons, key=lambda r: r.value)),
            dropped=tuple(sorted({v.rstrip() for v in held.values} - set(names))),
        ),
        tuple(sorted(held.outside)),
    )


def _linked(world: _World, rounds: int) -> Linked:
    return Linked(
        targets=tuple(
            _target(world, program, node)
            for program in sorted(world.tables)
            for node in sorted(world.tables[program].sites)
            if node in world.tables[program].jumps
        ),
        edges=tuple(sorted(world.edges, key=lambda e: (e.caller, e.node, e.callee, e.param))),
        report=RunReport(
            rounds=rounds,
            discovered=sum(1 for e in world.edges if e.discovered),
            unresolved_outside_jumps=world.outside.unresolved,
            without_results=world.outside.without_results,
        ),
    )
```

Implementation notes the tests pin down:
- `_held` returns `OUTSIDE_ANALYSED_SET` for a program not in the set, so a `RETURNED` stop into an outside callee is honest rather than empty.
- `_received` uses only callers whose window **covers** the requested bytes, and adds `INBOUND_LINKAGE` when none does (Review Focus 2). A window covering part of the bytes contributes nothing: four bytes of an eight-byte name would be read as a different, shorter name.
- A program reached by nothing keeps `INBOUND_LINKAGE` (`test_an_outside_caller…`). The cycle test (Review Focus 3) terminates because each round's edge set is a subset of the finite set of (jump, callee, area) triples and `visiting` stops value recursion; the values circulating in the cycle add nothing new, so each program keeps only its own fallback.
- Long lines: let Black wrap them; split any function the fp-lint complexity ceiling rejects into named helpers without changing behaviour.

`fixpoint/targets.py`: rename `_is_program_name` → `is_program_name` and update its caller in that file.

- [ ] **Step 4: Run** — Expected: PASS. Mutation-check: (a) make `_rounds` return after the first round → `test_a_target_found_only_across_programs…` fails; (b) use `overlaps` instead of `covers` in `_received` → `test_a_window_narrower…` fails. Restore.
- [ ] **Step 5: Gate and commit** — `feat(cobble): link programs in rounds, growing the call graph with the values`.

---

### Task 8: Edges of the set

**Files:**
- Create: `combine/outside.py`
- Test: `cobble/tests/dataflow/combine/test_outside.py`

**Interfaces:**
- Produces: `outside_jumps(fixpoint_dir: Path, asg_dir: Path, inside: frozenset[str], transactions: Mapping[str, str]) -> OutsideJumps`.

- [ ] **Step 1: Write the failing test** — a `tmp_path` fixpoint dir with `members/OUT1/jumps.jsonl` (an XCTL with `target.values == ["B"]`), `members/OUT2/jumps.jsonl` (an XCTL with `target.extent` set and no values), and an `asg_dir` containing `B.json`, `OUT1.json`, `OUT2.json`, `NORES.json` (empty `{}` files are enough — only names are read):

```python
def test_outside_programs_are_named_counted_or_listed(tmp_path: Path) -> None:
    fixpoint, asg = tmp_path / "fx", tmp_path / "asg"
    for name, jump in (
        ("OUT1", Jump("OUT1", "X", 1, JumpKind.XCTL, False, target=Fact(values=("B",)))),
        ("OUT2", Jump("OUT2", "X", 1, JumpKind.XCTL, False, target=Fact("WS-N@working_storage[0:8]"))),
    ):
        (fixpoint / "members" / name).mkdir(parents=True)
        (fixpoint / "members" / name / "jumps.jsonl").write_text(jump_row(jump) + "\n")
    asg.mkdir()
    for name in ("B", "OUT1", "OUT2", "NORES"):
        (asg / f"{name}.json").write_text("{}")

    assert outside_jumps(fixpoint, asg, frozenset({"B"}), {}) == OutsideJumps(
        known_into={"B": ("OUT1",)}, unresolved=1, without_results=("NORES",)
    )
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**

```python
"""What programs outside a linked set say about jumping into it — read, never analysed."""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_from_row

_PROGRAM_JUMPS = frozenset({JumpKind.XCTL, JumpKind.LINK, JumpKind.CALL})
_TRANSACTION_JUMPS = frozenset({JumpKind.RETURN_TRANSID, JumpKind.START})


def _jumps(directory: Path) -> tuple[Jump, ...]:
    path = directory / "jumps.jsonl"
    if not path.is_file():
        return ()
    return tuple(jump_from_row(line) for line in path.read_text().splitlines() if line.strip())


def _targets(jump: Jump, transactions: Mapping[str, str]) -> tuple[str, ...]:
    if jump.kind in _PROGRAM_JUMPS:
        return tuple(v.rstrip() for v in jump.target.values)
    if jump.kind in _TRANSACTION_JUMPS:
        return tuple(transactions[v.rstrip()] for v in jump.transid.values if v.rstrip() in transactions)
    return ()


def _unresolved(jump: Jump) -> bool:
    return jump.kind in _PROGRAM_JUMPS and bool(jump.target.extent) and not jump.target.values


def outside_jumps(
    fixpoint_dir: Path, asg_dir: Path, inside: frozenset[str], transactions: Mapping[str, str]
) -> OutsideJumps:
    members = fixpoint_dir / "members"
    analysed = frozenset(p.name for p in members.iterdir() if p.is_dir()) if members.is_dir() else frozenset()
    jumps = tuple(jump for name in sorted(analysed - inside) for jump in _jumps(members / name))
    pairs = sorted({(target, jump.program) for jump in jumps for target in _targets(jump, transactions) if target in inside})
    return OutsideJumps(
        known_into=MappingProxyType(
            {target: tuple(p for t, p in pairs if t == target) for target in sorted({t for t, _ in pairs})}
        ),
        unresolved=sum(1 for jump in jumps if _unresolved(jump)),
        without_results=tuple(
            sorted(p.stem for p in asg_dir.glob("*.json") if p.stem not in analysed and p.stem not in inside)
        ),
    )
```

- [ ] **Step 4: Run** — PASS. Mutation-check: count unresolved jumps as known callers; drop the `not in inside` filter on `without_results`.
- [ ] **Step 5: Gate and commit** — `feat(cobble): name outside callers of a linked subset, report the rest once`.

---

### Task 9: `cobble-dataflow-combine`

**Files:**
- Create: `combine/asg_callee_areas.py`, `combine/outputs.py`, `combine/cli.py`
- Modify: `cobble/pyproject.toml` (`[project.scripts]` add `cobble-dataflow-combine = "cobble.dataflow.combine.cli:main"`), `cobble/README.md` (command table row + a "Linking programs" subsection: what it reads, what it writes, `--all` / `--member`, the run report)
- Test: `cobble/tests/dataflow/combine/test_cli.py` (hand-written dirs), `cobble/tests/dataflow/fixpoint/test_combine_synthetic.py` (real bridge, end to end)

**Interfaces:**
- `AsgCalleeAreas(asg_dir: Path)` implementing `CalleeAreas` over `callee_received_area(asg_dir, callee, kind is JumpKind.CALL, param)`, returning `NO_RANGE` for `NO_EXTENT`, else `byte_range(extent_text(extent), callee)`.
- `write_outputs(out_dir: Path, linked: Linked) -> None` — `targets.jsonl` rows: the fixpoint's `target_row` JSON plus `"outside": [...]`; `links.jsonl` rows: `{"caller","node","transfer","callee","caller_extent","callee_extent","returns","reason":"","discovered"}` with extents as `str(window)`.
- `cli(argv: Sequence[str] = ()) -> int`; `main() -> int`.

`combine/asg_callee_areas.py`:
```python
"""AsgCalleeAreas — callee received areas read from the parse cache, as aliases does."""

from pathlib import Path

from cobble.dataflow.combine.callee_areas import CalleeAreas
from cobble.dataflow.fields.aliases import NO_EXTENT, callee_received_area
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range, extent_text
from cobble.dataflow.jumps.jump_kind import JumpKind


class AsgCalleeAreas(CalleeAreas):
    def __init__(self, asg_dir: Path) -> None:
        self._asg_dir = asg_dir

    def area(self, callee: str, kind: JumpKind, param: int) -> ByteRange:
        extent = callee_received_area(self._asg_dir, callee, kind is JumpKind.CALL, param)
        return NO_RANGE if extent == NO_EXTENT else byte_range(extent_text(extent), callee)
```

`combine/outputs.py`:
```python
"""Write the linked targets and links tables."""

import json
from pathlib import Path

from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.linked_target import LinkedTarget
from cobble.dataflow.fields.side_tables import jsonl_writer, target_row
from cobble.dataflow.jumps.jump_kind import JumpKind

_RETURNS = frozenset({JumpKind.LINK, JumpKind.CALL})


def _target(found: LinkedTarget) -> tuple[str, str]:
    key, row = target_row(found.target)
    return key, json.dumps({**json.loads(row), "outside": list(found.outside)})


def _link(edge: Edge) -> tuple[str, str]:
    row = json.dumps(
        {
            "caller": edge.caller,
            "node": edge.node,
            "transfer": edge.kind.value,
            "callee": edge.callee,
            "caller_extent": str(edge.caller_window),
            "callee_extent": str(edge.callee_window),
            "returns": edge.kind in _RETURNS,
            "reason": "",
            "discovered": edge.discovered,
        }
    )
    return f"{edge.caller}\0{edge.node}\0{edge.callee}\0{edge.param}", row


def write_outputs(out_dir: Path, linked: Linked) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with jsonl_writer(out_dir / "targets.jsonl") as targets:
        targets.add_rows(map(_target, linked.targets))
    with jsonl_writer(out_dir / "links.jsonl") as links:
        links.add_rows(map(_link, linked.edges))
```

`combine/cli.py`:
```python
"""cobble-dataflow-combine — link the per-program fixpoint results across programs."""

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from cics.csd_parse import parse_csd
from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import load_corpus_config
from cobble.dataflow.combine.asg_callee_areas import AsgCalleeAreas
from cobble.dataflow.combine.link import link
from cobble.dataflow.combine.load import load_tables
from cobble.dataflow.combine.outputs import write_outputs
from cobble.dataflow.combine.outside import outside_jumps
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.run_report import RunReport


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Link the fixpoint's per-program results across programs.")
    parser.add_argument("--config", required=True, type=Path, help="the corpus TOML (csd_files, asg_dir)")
    parser.add_argument("--fixpoint-dir", required=True, type=Path, help="a cobble-dataflow-fixpoint --out-dir")
    parser.add_argument("--out-dir", required=True, type=Path, help="where targets.jsonl and links.jsonl go")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true", help="link every program with results")
    scope.add_argument("--member", nargs="+", default=[], metavar="NAME", help="link these programs only")
    return parser


def _transactions(csd_files: Sequence[Path]) -> Mapping[str, str]:
    return {transid: program for path in csd_files for transid, program in parse_csd(path).items()}


def _inside(fixpoint_dir: Path, members: Sequence[str], every: bool) -> tuple[frozenset[str], tuple[str, ...]]:
    present = frozenset(p.name for p in (fixpoint_dir / "members").iterdir() if p.is_dir())
    if every:
        return present, ()
    wanted = frozenset(name.upper() for name in members)
    return wanted & present, tuple(sorted(wanted - present))


def _report(report: RunReport) -> None:
    sys.stderr.write(
        f"combine: {report.rounds} rounds, {report.discovered} discovered edges, "
        f"{report.unresolved_outside_jumps} outside jumps with unresolved targets, "
        f"{len(report.without_results)} outside programs without results\n"
    )


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(argv or sys.argv[1:])
    config = load_corpus_config(arguments.config)
    inside, missing = _inside(arguments.fixpoint_dir, arguments.member, arguments.all)
    if missing:
        sys.stderr.write(f"combine: !! no fixpoint results for: {', '.join(missing)}\n")
        return 1
    transactions = _transactions(config.csd_files)
    outside = (
        OutsideJumps()
        if arguments.all
        else outside_jumps(arguments.fixpoint_dir, config.asg_dir, inside, transactions)
    )
    linked = link(
        {program: load_tables(arguments.fixpoint_dir, program) for program in sorted(inside)},
        AsgCalleeAreas(config.asg_dir),
        transactions,
        outside,
    )
    write_outputs(arguments.out_dir, linked)
    _report(linked.report)
    return 0


def main() -> int:
    sys.exit(cli())
```

(Check `cobble/cli_logging.py` exports `configure_cli_logging` — `fixpoint/query.py` imports it; use the same import line.)

- [ ] **Step 1: Write the failing CLI tests** (`test_cli.py`, over hand-written dirs reusing Task 7's table shapes written as files via `jump_row` and JSON rows):
  - `test_a_member_with_no_results_is_refused_and_nothing_is_written` — `--member B MISSING` → exit 1, stderr names `MISSING`, `out_dir` does not exist (Review Focus 4).
  - `test_a_member_named_twice_is_linked_once` — `--member B B` → exit 0, `targets.jsonl` has exactly one row for `B`'s site.
  A minimal corpus TOML for these tests:
  ```python
  CONFIG = """\
  [corpus]
  cobol_dir = "."
  cobol_globs = ["*.cbl"]
  jcl_dir = "."
  jcl_globs = ["*.jcl"]
  asg_dir = "{asg}"
  """
  ```
  (Add any further required `[corpus]` keys `CorpusTable` rejects the file without — check `cobble/corpus_table.py`.)

- [ ] **Step 2: Write the failing end-to-end test** (`tests/dataflow/fixpoint/test_combine_synthetic.py`):

```python
"""The return-to-caller idiom, compiled by the real bridge, linked end to end."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from cobble.dataflow.combine.cli import cli

PROGA = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-FROM          PIC X(8).
           05  WS-REST          PIC X(12).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGA' TO WS-FROM.
           EXEC CICS XCTL PROGRAM('PROGB') COMMAREA(WS-AREA) END-EXEC.
"""

PROGB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NEXT              PIC X(8).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-FROM          PIC X(8).
           05  LK-REST          PIC X(12).
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF LK-FROM = SPACES
               MOVE 'PROGM' TO WS-NEXT
           ELSE
               MOVE LK-FROM TO WS-NEXT
           END-IF.
           EXEC CICS XCTL PROGRAM(WS-NEXT) COMMAREA(DFHCOMMAREA) END-EXEC.
"""


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_return_to_caller_links_end_to_end(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path], tmp_path: Path
) -> None:
    out = fixpoint_corpus({"PROGA": PROGA, "PROGB": PROGB})
    config = tmp_path / "corpus.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"))
    combined = tmp_path / "combined"

    assert cli(["--config", str(config), "--fixpoint-dir", str(out), "--out-dir", str(combined), "--all"]) == 0

    single = [(r["caller"], r["candidates"], r["reasons"]) for r in _rows(out / "targets.jsonl")]
    linked = [(r["caller"], r["candidates"], r["reasons"], r["outside"]) for r in _rows(combined / "targets.jsonl")]
    links = sorted(
        (r["caller"], r["callee"], r["caller_extent"], r["callee_extent"], r["discovered"])
        for r in _rows(combined / "links.jsonl")
    )
    assert single == [("PROGB", ["PROGM"], ["inbound-linkage"])]
    assert linked == [("PROGB", ["PROGA", "PROGM"], [], [])]
    assert links == [
        ("PROGA", "PROGB", "WS-AREA@working_storage[0:20]", "DFHCOMMAREA@linkage[0:20]", False),
        ("PROGB", "PROGA", "DFHCOMMAREA@linkage[0:20]", "DFHCOMMAREA@linkage[0:20]", True),
    ]
```

(`CONFIG` is the same TOML as in `test_cli.py`; import it from a shared `tests/dataflow/combine/corpus_toml.py` module rather than duplicating it. Verify the `single` assertion against the fixpoint's real output before writing `linked` — it is what this design exists to change.)

- [ ] **Step 3: Run** — Expected: FAIL (missing modules / script).
- [ ] **Step 4: Implement** the three modules above, the script entry, and the README section; run `uv sync --all-packages` once at the forge root so the new console script exists.
- [ ] **Step 5: Run** both test files — Expected: PASS. Mutation-check: drop the `missing` refusal; make `write_outputs` skip `"outside"`.
- [ ] **Step 6: Gate and commit** — `feat(cobble): cobble-dataflow-combine links the fixpoint's per-program results`.

---

### Task 10: `--links` for the provenance query

**Files:**
- Modify: `cobble/cobble/dataflow/fixpoint/query.py` — `_parser` adds `--links` (`type=Path`, `default=Path()`); `load`, `load_for`, `_ready` take `links: Path = Path()`; `_ready` reads `_table(links if links != Path() else out_dir / ALIASES_FILE)`; `cli` passes `arguments.links`.
- Modify: `cobble/README.md` (the query row mentions `--links`)
- Test: extend `tests/dataflow/fixpoint/test_combine_synthetic.py`

- [ ] **Step 1: Write the failing test** — after the combine run in Task 9's test module, add:

```python
def test_links_let_the_provenance_query_cross_a_discovered_jump(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path], tmp_path: Path
) -> None:
    from cobble.dataflow.fields.extent_text import byte_range
    from cobble.dataflow.fixpoint.query import load_for

    out = fixpoint_corpus({"PROGA": PROGA, "PROGB": PROGB})
    config = tmp_path / "corpus.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"))
    combined = tmp_path / "combined"
    cli(["--config", str(config), "--fixpoint-dir", str(out), "--out-dir", str(combined), "--all"])
    extents = out.parent / "extents.jsonl"
    from_b = byte_range("DFHCOMMAREA@linkage[0:20]", "PROGB")

    plain = load_for(out, extents, "PROGB.DFHCOMMAREA")
    linked = load_for(out, extents, "PROGB.DFHCOMMAREA", combined / "links.jsonl")

    assert [a.callee for a, _ in plain.across((from_b,))] == []
    assert [(a.callee, str(landed)) for a, landed in linked.across((from_b,))] == [
        ("PROGA", "DFHCOMMAREA@linkage[0:20]")
    ]
```

(Confirm `FieldStore.across`'s return shape at `query.py:370` — it yields `(Alias, ByteRange)` pairs per the `_crossings_from` caller at line 702; adjust the unpacking, not the expectation.)

- [ ] **Step 2: Run** — FAIL (`load_for` takes no links argument).
- [ ] **Step 3: Implement** the four signature changes and the parser option.
- [ ] **Step 4: Run** — PASS; run every existing query test too (`uv run --no-sync python -m pytest tests/dataflow -q -k query`) — unchanged.
- [ ] **Step 5: Gate and commit** — `feat(cobble): --links lets the provenance query follow discovered jumps`.

---

### Task 11: CardDemo acceptance and the reference graph

**Files:**
- Modify: `cobble/reference/graph.jsonl` (regenerated), `cobble/README.md` (`cobble-compare` counts), `cobble/demo/carddemo/run.sh` (add the combine step; the demo directory itself stays uncommitted unless the user asks)
- Test: none new — this task is the acceptance run.

- [ ] **Step 1: Run the pipeline** (forge root): `. ./bridge-env.sh && cobble/demo/carddemo/run.sh`, then from `cobble/`:
  `uv run --no-sync cobble-dataflow-combine --config demo/carddemo/carddemo.toml --fixpoint-dir demo/carddemo/out-fixpoint --out-dir demo/carddemo/out-combined --all`
- [ ] **Step 2: Check the four sites and nothing else**, by script in the scratchpad:

```python
import json
from pathlib import Path

d = Path("demo/carddemo")
before = {(r["caller"], r["node"]): r["candidates"] for r in map(json.loads, (d / "out-fixpoint/targets.jsonl").read_text().splitlines())}
after = {(r["caller"], r["node"]): r["candidates"] for r in map(json.loads, (d / "out-combined/targets.jsonl").read_text().splitlines())}
changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
print(len(before), len(after), changed)
```

Expected: 24 and 24 sites; `changed` has exactly four keys — the `COCRDSLC` and `COCRDUPC` sites gaining `COCRDLIC`, the `COUSR02C` and `COUSR03C` sites gaining `COUSR00C` — and each `after` list is the `before` list plus that one name. Any other change is a defect: stop and investigate (`superpowers:systematic-debugging`).
- [ ] **Step 3: Regenerate the reference graph:** `uv run --no-sync cobble-build --config demo/carddemo/carddemo.toml --output /tmp/combined-graph.jsonl --dynamic-call-targets demo/carddemo/out-combined/targets.jsonl`; `diff <(sort reference/graph.jsonl) <(sort /tmp/combined-graph.jsonl)` must show exactly four added `XCTL_CANDIDATE` edge rows (COCRDSLC→COCRDLIC, COCRDUPC→COCRDLIC, COUSR02C→COUSR00C, COUSR03C→COUSR00C) and nothing removed; then `cp /tmp/combined-graph.jsonl reference/graph.jsonl` and `uv run --no-sync cobble-compare --graph reference/graph.jsonl` reports identical (448 nodes / 836 edges). Update the README's `448/832` to `448/836`.
- [ ] **Step 4: Close the issue:** `bd close red-dragon-forge-hab --reason "<the Step 2 output and the four edges>"`; `bd export -o issues/issues.jsonl`.
- [ ] **Step 5: Commit** — `test(cobble): CardDemo links its four return-to-caller targets; regenerate the reference graph` (`reference/graph.jsonl`, `cobble/README.md`, `issues/issues.jsonl`; include the Step 2 output in the message).

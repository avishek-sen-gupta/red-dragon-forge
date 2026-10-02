# Reachability from a PERFORM site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cobble-srccfg-reach --cfg <jsonl> --from <PERFORM node>` streams, as src-cfg JSONL rows, every node and edge that can run from that PERFORM until control returns, plus every way it can end instead.

**Architecture:** A breadth-first walk over (node, stack-of-resume-points) states, each state expanded once, over the typed `Cfg` that `load_bundle` reads from a `cobble-srccfg-build` file. Each expansion is a pure function from a state to the edges it takes and the facts it records; the walk turns each BFS level into rows as it goes — node rows, then edge rows, then outcome/unresolved/refused rows — and ends with a `summary` row. Four new row types join the `CfgRow` union, so `load_bundle` (and with it `cobble-srccfg-dot`/`-webgl`) reads the output as the reached subgraph.

**Tech Stack:** Python 3.13, Pydantic v2 rows (existing `cobble/dataflow/srccfg/rows/`), pytest, argparse, uv workspace (`cobble` member).

**Spec:** `docs/superpowers/specs/2026-10-02-execution-order-walk-design.md` (the src-cfg row format it builds on: `docs/superpowers/specs/2026-10-02-srccfg-jsonl-design.md`, implemented).

## Global Constraints

- Every Python command runs from `~/code/red-dragon-forge/cobble` as `uv run --no-sync python -m pytest ...`. cobble's unit tests need no `bridge-env.sh`; the integration test in Task 3 needs the ProLeap bridge JAR built (`make jar`) and skips without it.
- The commit hooks are the gate: python-fp-lint, Black, Pyright, import-linter, the test suites, the terminology guard on the diff and the message, Talisman. `--no-verify` is never used. A hook failure is fixed in the code, the test or the message.
- Before each commit also run: `make fmt` (repo root); `uv run --no-sync pyright <every file you touched, space-separated>` (repo root; in zsh expand a variable list with `${=VAR}`); `uv run --no-sync lint-imports` (repo root); `pre-commit run python-fp-lint-check --hook-stage manual --files <the .py files>` (repo root); and the whole cobble suite `uv run --no-sync python -m pytest -q -n auto` (in `cobble/`).
- python-fp-lint: no `for` loops with mutation, no `.append`/`.add`/`.update`/subscript assignment, no `is None`, no `Any`, no `object`, frozen dataclasses only, complexity at most 3 per function, at most 10 statements per function. A `while` loop that only rebinds names is allowed (`fixpoint._swept` does it).
- Pydantic models: `model_config = ConfigDict(frozen=True, extra="forbid")`. One class per file.
- Talisman: the words "key", "pass", "passed", "bypass" in code or prose can trip it. If it flags a file anyway, the user's standing ruling for this work is: replace that file's existing `.talismanrc` entry's checksum in place, or append an entry for a new file, using the checksum Talisman prints, and say so in the final report.
- Never reference an external codebase's identifiers in any tracked file. Tests use invented names (`PROGA`, `MAIN`, `WORK-PARA`, ...).
- Do not modify anything under `vendor/`.
- Docstrings match the surrounding code's density; no `#` comments.
- Commit messages end with:
  ```
  ```

## Review Focus

1. **A HANDLE CONDITION handler whose own command raises back into it** (the handler stays armed inside itself, so its dispatch's GOTO edge loops to its own label): the walk must terminate, record the handler's outcomes once, and emit the looping edge once. Test in Task 2 (`test_a_handled_condition_reaches_its_handler_and_the_loop_back_ends`).
2. **A seed whose range never returns** (its range ends in STOP RUN, so the build kept the `FLOW` edge past the seed as a safety net): no `returns` outcome, and that `FLOW` edge is not taken. Test in Task 2 (the `STOP_RUN` case of `test_each_way_out_of_the_range_is_an_outcome_at_its_node`, which asserts the outcome set and the absent edge).
3. **Arriving at a range end that only another site's PERFORM closes, with nowhere to fall through** (the program's last paragraph, entered by a GO TO while a different PERFORM is innermost): recorded as `dead-end` at that end, not a silent stop. Test in Task 2 (`test_an_end_only_another_site_closes_with_nowhere_to_fall_is_a_dead_end`).
4. **A seed in a closure file that is not in its first program**: refused with a message naming the program searched, never an empty walk. Test in Task 3 (`test_a_seed_the_file_does_not_hold_is_an_error_naming_the_program`).
5. **A reader stopping early**: every edge row comes after both its nodes' rows and the `summary` row comes last, so any prefix is a valid partial graph and a missing summary means an unfinished walk. Test in Task 2 (`test_rows_stream_nodes_before_their_edges_and_the_summary_last`).

---

## File Structure

| File | Task | Responsibility |
|---|---|---|
| `cobble/cobble/dataflow/srccfg/rows/cfg_row_type.py` | 1 | modify: four new `CfgRowType` members |
| `cobble/cobble/dataflow/srccfg/rows/reach_outcome.py` | 1 | create: `ReachOutcome` enum |
| `cobble/cobble/dataflow/srccfg/rows/outcome_row.py` | 1 | create: `CfgOutcomeRow` |
| `cobble/cobble/dataflow/srccfg/rows/unresolved_row.py` | 1 | create: `CfgUnresolvedRow` |
| `cobble/cobble/dataflow/srccfg/rows/refused_row.py` | 1 | create: `CfgRefusedRow` |
| `cobble/cobble/dataflow/srccfg/rows/summary_row.py` | 1 | create: `CfgSummaryRow` |
| `cobble/cobble/dataflow/srccfg/rows/cfg_row.py` | 1 | modify: union and four builders |
| `cobble/cobble/dataflow/srccfg/reach/__init__.py` | 2 | create: package header |
| `cobble/cobble/dataflow/srccfg/reach/reach_error.py` | 2 | create: `ReachError` |
| `cobble/cobble/dataflow/srccfg/reach/reach_state.py` | 2 | create: `ReachState` |
| `cobble/cobble/dataflow/srccfg/reach/reach_step.py` | 2 | create: `ReachStep` |
| `cobble/cobble/dataflow/srccfg/reach/reach_visit.py` | 2 | create: `ReachVisit` |
| `cobble/cobble/dataflow/srccfg/reach/reach_progress.py` | 2 | create: `ReachProgress` |
| `cobble/cobble/dataflow/srccfg/reach/expand.py` | 2 | create: the seed check and one state's expansion |
| `cobble/cobble/dataflow/srccfg/reach/walk.py` | 2 | create: `reach_rows`, the BFS that streams rows |
| `cobble/cobble/dataflow/srccfg/reach/cli.py` | 3 | create: `cobble-srccfg-reach` |
| `cobble/pyproject.toml` | 3 | modify: the script entry |
| `cobble/README.md` | 3 | modify: command table row, a section on the command |
| `cobble/tests/dataflow/srccfg/test_cfg_rows.py` | 1 | modify: the reach rows |
| `cobble/tests/dataflow/srccfg/test_reach.py` | 2 | create |
| `cobble/tests/dataflow/srccfg/test_reach_cli.py` | 3 | create |

The spec names one module, `srccfg/reach.py`; the walk needs five small value classes, and the repo's rule is one class per file, so it is a package `srccfg/reach/` instead (see Deviations).

---

### Task 1: The reach row types

**Files:**
- Modify: `cobble/cobble/dataflow/srccfg/rows/cfg_row_type.py`, `cobble/cobble/dataflow/srccfg/rows/cfg_row.py`
- Create: `cobble/cobble/dataflow/srccfg/rows/reach_outcome.py`, `outcome_row.py`, `unresolved_row.py`, `refused_row.py`, `summary_row.py`
- Test: `cobble/tests/dataflow/srccfg/test_cfg_rows.py`

**Interfaces:**
- Consumes: `CfgRow`, `CFG_ROWS`, `program_row`, `node_row`, `edge_row` (existing, `rows/cfg_row.py`); `bundle_of_rows(rows: Sequence[CfgRow], source: str = "<rows>") -> Bundle` and `load_bundle(path: Path) -> Bundle` (existing, `srccfg/bundle.py`), whose `isinstance` filters already ignore row types they do not build.
- Produces (Tasks 2 and 3 rely on these names):
  - `ReachOutcome(StrEnum)`: `RETURNS = "returns"`, `STOP_RUN = "stop-run"`, `GOBACK = "goback"`, `EXIT_PROGRAM = "exit-program"`, `ABEND = "abend"`, `XCTL = "xctl"`, `CICS_RETURN = "cics-return"`, `UNHANDLED_CONDITION = "unhandled-condition"`, `DEAD_END = "dead-end"`.
  - `CfgRowType` gains `OUTCOME = "outcome"`, `UNRESOLVED = "unresolved"`, `REFUSED = "refused"`, `SUMMARY = "summary"`.
  - `CfgOutcomeRow(type, kind: ReachOutcome, node: str)`, `CfgUnresolvedRow(type, node: str)`, `CfgRefusedRow(type, node: str)`, `CfgSummaryRow(type, seed: str, states: int)`.
  - In `rows/cfg_row.py`: `outcome_row(kind: ReachOutcome, node: str) -> CfgOutcomeRow`, `unresolved_row(node: str) -> CfgUnresolvedRow`, `refused_row(node: str) -> CfgRefusedRow`, `summary_row(seed: str, states: int) -> CfgSummaryRow`; `CfgRow` includes all four.

- [ ] **Step 1: Write the failing test.** Append to `cobble/tests/dataflow/srccfg/test_cfg_rows.py`:

```python
from pathlib import Path

from cobble.dataflow.srccfg.bundle import load_bundle
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.rows.cfg_row import (
    outcome_row,
    refused_row,
    summary_row,
    unresolved_row,
)
from cobble.dataflow.srccfg.rows.reach_outcome import ReachOutcome


def test_reach_rows_read_back_and_a_cfg_reader_sees_only_the_graph(
    tmp_path: Path,
) -> None:
    """The reach rows travel in the same file as the reached subgraph: each reads
    back as itself, and load_bundle -- so every renderer -- builds the graph and
    skips them."""
    edge = Edge(source="MAIN/0", target="MAIN#end", kind=EdgeKind.FLOW)
    end = Node(id="MAIN#end", kind=NodeKind.NOP, paragraph="MAIN")
    reach = (
        outcome_row(ReachOutcome.XCTL, "MAIN/0"),
        unresolved_row("MAIN/1"),
        refused_row("MAIN/2"),
        summary_row("MAIN/0", 3),
    )
    rows = (
        program_row("PROGA"),
        node_row("PROGA", NODE),
        node_row("PROGA", end),
        edge_row("PROGA", edge),
        *reach,
    )
    path = tmp_path / "reach.jsonl"
    path.write_text("".join(f"{row.model_dump_json()}\n" for row in rows))

    assert tuple(CFG_ROWS.validate_json(row.model_dump_json()) for row in reach) == reach
    assert load_bundle(path).cfgs == (
        Cfg(program="PROGA", nodes=(NODE, end), edges=(edge,)),
    )
```

(`NODE`, `Node`, `NodeKind`, `Edge`, `EdgeKind`, `CFG_ROWS`, `program_row`, `node_row`, `edge_row` are already imported or defined at the top of this file; merge the new imports into the existing import block. `NODE.id` is `MAIN/3`; the edge joins `MAIN/0`, which no node row declares, and that is fine -- `bundle_of_rows` does not check edge endpoints.)

- [ ] **Step 2: Run it to see it fail.**

Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg/test_cfg_rows.py -q`
Expected: FAIL at collection: `ImportError: cannot import name 'outcome_row'`.

- [ ] **Step 3: Write the row types.**

`cobble/cobble/dataflow/srccfg/rows/cfg_row_type.py` -- add four members:

```python
class CfgRowType(StrEnum):
    PROGRAM = "program"
    NODE = "node"
    EDGE = "edge"
    CALL = "call"
    OUTCOME = "outcome"
    UNRESOLVED = "unresolved"
    REFUSED = "refused"
    SUMMARY = "summary"
```

`cobble/cobble/dataflow/srccfg/rows/reach_outcome.py`:

```python
"""How a branch of a reachability walk ends."""

from enum import StrEnum


class ReachOutcome(StrEnum):
    RETURNS = "returns"
    STOP_RUN = "stop-run"
    GOBACK = "goback"
    EXIT_PROGRAM = "exit-program"
    ABEND = "abend"
    XCTL = "xctl"
    CICS_RETURN = "cics-return"
    UNHANDLED_CONDITION = "unhandled-condition"
    DEAD_END = "dead-end"
```

`cobble/cobble/dataflow/srccfg/rows/outcome_row.py`:

```python
"""A reach row: one way a branch of the walk ended, and the node it ended at."""

from typing import Literal

from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from cobble.dataflow.srccfg.rows.reach_outcome import ReachOutcome
from pydantic import BaseModel, ConfigDict


class CfgOutcomeRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.OUTCOME]
    kind: ReachOutcome
    node: str
```

`cobble/cobble/dataflow/srccfg/rows/unresolved_row.py`:

```python
"""A reach row: a PERFORM whose range the program does not declare."""

from typing import Literal

from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgUnresolvedRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.UNRESOLVED]
    node: str
```

`cobble/cobble/dataflow/srccfg/rows/refused_row.py`:

```python
"""A reach row: a PERFORM of a range already open, stepped over rather than entered."""

from typing import Literal

from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgRefusedRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.REFUSED]
    node: str
```

`cobble/cobble/dataflow/srccfg/rows/summary_row.py`:

```python
"""A reach row, always last: the seed, and how many states the walk visited."""

from typing import Literal

from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from pydantic import BaseModel, ConfigDict


class CfgSummaryRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.SUMMARY]
    seed: str
    states: int
```

`cobble/cobble/dataflow/srccfg/rows/cfg_row.py` -- import the four row classes and `ReachOutcome`, extend the union, and add four builders after `call_row`:

```python
CfgRow = (
    CfgProgramRow
    | CfgNodeRow
    | CfgEdgeRow
    | CfgCallRow
    | CfgOutcomeRow
    | CfgUnresolvedRow
    | CfgRefusedRow
    | CfgSummaryRow
)


def outcome_row(kind: ReachOutcome, node: str) -> CfgOutcomeRow:
    return CfgOutcomeRow(type=CfgRowType.OUTCOME, kind=kind, node=node)


def unresolved_row(node: str) -> CfgUnresolvedRow:
    return CfgUnresolvedRow(type=CfgRowType.UNRESOLVED, node=node)


def refused_row(node: str) -> CfgRefusedRow:
    return CfgRefusedRow(type=CfgRowType.REFUSED, node=node)


def summary_row(seed: str, states: int) -> CfgSummaryRow:
    return CfgSummaryRow(type=CfgRowType.SUMMARY, seed=seed, states=states)
```

Update `rows/cfg_row.py`'s module docstring if it says the union is graph rows only.

- [ ] **Step 4: Run the tests.**

Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg/test_cfg_rows.py tests/dataflow/srccfg/test_bundle.py -q`
Expected: PASS (the bundle tests are unaffected: their files hold no reach rows).

- [ ] **Step 5: Mutation-check.** In `bundle.py`'s `bundle_of_rows`, change the node filter `isinstance(row, CfgNodeRow)` to `not isinstance(row, (CfgProgramRow, CfgEdgeRow, CfgCallRow))` -- the new test must FAIL (a reach row is then treated as a node). Restore. Remove `| CfgSummaryRow` from the union -- the new test must FAIL at `validate_json`. Restore.

- [ ] **Step 6: Gate and commit.**

```bash
git add cobble/cobble/dataflow/srccfg/rows cobble/tests/dataflow/srccfg/test_cfg_rows.py
git commit -m "feat(cobble): src-cfg rows for a reachability walk's findings

Outcome, unresolved, refused and summary rows join the src-cfg row union, so a
reachability walk can write what it found into the same JSONL file as the
subgraph it reached; load_bundle reads that file as the subgraph alone.

```

---

### Task 2: The walk

**Files:**
- Create: `cobble/cobble/dataflow/srccfg/reach/__init__.py`, `reach_error.py`, `reach_state.py`, `reach_step.py`, `reach_visit.py`, `reach_progress.py`, `expand.py`, `walk.py`
- Test: `cobble/tests/dataflow/srccfg/test_reach.py`

**Interfaces:**
- Consumes: from Task 1, `CfgRow`, `ReachOutcome`, `program_row`, `node_row`, `edge_row`, `outcome_row`, `unresolved_row`, `refused_row`, `summary_row`, and the row classes `CfgNodeRow`, `CfgEdgeRow`, `CfgOutcomeRow`, `CfgUnresolvedRow`, `CfgRefusedRow`, `CfgSummaryRow`. From the codebase: `Cfg` (`.program`, `.nodes`, `.node(id) -> Node`, `.node_ids: frozenset[str]`, `.successors(id) -> tuple[Edge, ...]`), `Edge`, `EdgeKind`, `Node`; `PERFORM_TRANSFER = "PERFORM"` and `DISPATCH_TRANSFER_CICS = "HANDLE DISPATCH"` from `cobble.dataflow.srccfg.desugar`; `program_cfg(asg) -> Cfg` from `cobble.dataflow.srccfg.program`; the `asg_of` test fixture (`tests/dataflow/srccfg/conftest.py`, builds a `CobolASG` from a procedure-division dict).
- Produces (Task 3 relies on): `ReachError(ValueError)` in `reach/reach_error.py`; `reach_rows(cfg: Cfg, seed: str) -> Iterator[CfgRow]` in `reach/walk.py`, which raises `ReachError` before yielding anything when the seed is not a resolved PERFORM node of `cfg`.

Facts the code relies on, verified against `program_cfg` while writing this plan:
- Node `transfer` spellings: `PERFORM`, `STOPRUN`, `GOBACK`, `EXITPROGRAM`, `CICS_ABEND`, `CICS_XCTL`, `CICS_RETURN`, and `HANDLE DISPATCH` on a CICS `#dispatch` node.
- A PERFORM whose range can return has `Node.resume` set and no `FLOW` edge past it; one whose range never returns has an empty `resume` and keeps its `FLOW` edge; one whose range is undeclared has no `PERFORM` edge and keeps its `FLOW` edge.
- A range end (`<para>#end`) carries one `RETURN` edge per PERFORM site closing there, plus a `FALLTHRU` to the next paragraph unless it is the last.
- A HANDLE CONDITION stays armed inside its handler: a CICS command in the handler that raises routes through its `#dispatch` with a `GOTO` back to the handler's own label.

- [ ] **Step 1: Write the failing tests.** Create `cobble/tests/dataflow/srccfg/test_reach.py`:

```python
"""Reachability from one PERFORM: what can run until control returns, and how else
the PERFORM can end -- over CFGs built the way cobble-srccfg-build builds them."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import pytest
from cobble.dataflow.srccfg.cfg import EdgeKind
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.reach.reach_error import ReachError
from cobble.dataflow.srccfg.reach.walk import reach_rows
from cobble.dataflow.srccfg.rows.cfg_row import CfgRow
from cobble.dataflow.srccfg.rows.edge_row import CfgEdgeRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.outcome_row import CfgOutcomeRow
from cobble.dataflow.srccfg.rows.refused_row import CfgRefusedRow
from cobble.dataflow.srccfg.rows.summary_row import CfgSummaryRow
from cobble.dataflow.srccfg.rows.unresolved_row import CfgUnresolvedRow
from cobol_asg.asg_types import CobolASG

Asg = Callable[[Mapping], CobolASG]


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _perform(target: str, thru: str = "") -> dict:
    return {"type": "PERFORM", "operands": [target], **({"thru": thru} if thru else {})}


def _goto(target: str) -> dict:
    return {"type": "GOTO", "form": "simple", "target": {"paragraph": target}}


def _cics(verb: str, options: Mapping) -> dict:
    return {"type": "EXEC_CICS", "verb": verb, "options": dict(options)}


def _para(name: str, *statements: dict) -> dict:
    return {"name": name, "statements": list(statements)}


def _rows(asg_of: Asg, seed: str, *paragraphs: dict) -> tuple[CfgRow, ...]:
    cfg = program_cfg(asg_of({"program_id": "PROGA", "paragraphs": list(paragraphs)}))
    return tuple(reach_rows(cfg, seed))


def _nodes(rows: Sequence[CfgRow]) -> list[str]:
    return [row.id for row in rows if isinstance(row, CfgNodeRow)]


def _paragraphs(rows: Sequence[CfgRow]) -> list[str]:
    return list(dict.fromkeys(row.paragraph for row in rows if isinstance(row, CfgNodeRow)))


def _edges(rows: Sequence[CfgRow]) -> set[tuple[str, str, EdgeKind]]:
    return {(row.source, row.target, row.kind) for row in rows if isinstance(row, CfgEdgeRow)}


def _outcomes(rows: Sequence[CfgRow]) -> set[tuple[str, str]]:
    return {(row.kind.value, row.node) for row in rows if isinstance(row, CfgOutcomeRow)}


def _flagged(rows: Sequence[CfgRow], kind: type[CfgUnresolvedRow] | type[CfgRefusedRow]) -> list[str]:
    return [row.node for row in rows if isinstance(row, kind)]


def test_a_thru_range_falls_through_its_paragraphs_and_returns(asg_of: Asg) -> None:
    """The range is A THRU B: A's end falls through into B, whose end is the one a
    RETURN leaves from, back to the statement after the PERFORM."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A", "B"), _move("'X'", "WS-X"), {"type": "STOP_RUN"}),
        _para("A", _move("'A'", "WS-A")),
        _para("B", _move("'B'", "WS-B")),
    )

    assert _nodes(rows) == [
        "MAIN/0", "A#label", "A/0", "A#end", "B#label", "B/0", "B#end", "MAIN/1",
    ]
    assert _edges(rows) == {
        ("MAIN/0", "A#label", EdgeKind.PERFORM),
        ("A#label", "A/0", EdgeKind.FLOW),
        ("A/0", "A#end", EdgeKind.FLOW),
        ("A#end", "B#label", EdgeKind.FALLTHRU),
        ("B#label", "B/0", EdgeKind.FLOW),
        ("B/0", "B#end", EdgeKind.FLOW),
        ("B#end", "MAIN/1", EdgeKind.RETURN),
    }
    assert _outcomes(rows) == {("returns", "MAIN/1")}
    assert rows[-1] == CfgSummaryRow(type="summary", seed="MAIN/0", states=7)


def test_a_range_end_two_sites_share_returns_only_to_the_seeds(asg_of: Asg) -> None:
    """A's end has a RETURN to each PERFORM of it. From the second site, the RETURN
    to the first is never taken, though both its ends are in the subgraph."""
    rows = _rows(
        asg_of,
        "MAIN/1",
        _para("MAIN", _perform("A"), _perform("A"), {"type": "STOP_RUN"}),
        _para("A", _move("'A'", "WS-A")),
    )

    assert _nodes(rows) == ["MAIN/1", "A#label", "A/0", "A#end", "MAIN/2"]
    assert ("A#end", "MAIN/2", EdgeKind.RETURN) in _edges(rows)
    assert ("A#end", "MAIN/1", EdgeKind.RETURN) not in _edges(rows)
    assert _outcomes(rows) == {("returns", "MAIN/2")}


def test_a_nested_perform_returns_to_its_own_site_first(asg_of: Asg) -> None:
    """Inside the range, A performs B. B's end returns to A, and A's end -- which
    would otherwise fall through into B -- returns to the seed."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), {"type": "STOP_RUN"}),
        _para("A", _perform("B"), _move("'A'", "WS-A")),
        _para("B", _move("'B'", "WS-B")),
    )

    assert _nodes(rows) == [
        "MAIN/0", "A#label", "A/0", "B#label", "B/0", "B#end", "A/1", "A#end", "MAIN/1",
    ]
    assert {
        ("B#end", "A/1", EdgeKind.RETURN),
        ("A#end", "MAIN/1", EdgeKind.RETURN),
    } <= _edges(rows)
    assert ("A#end", "B#label", EdgeKind.FALLTHRU) not in _edges(rows)
    assert _outcomes(rows) == {("returns", "MAIN/1")}


def test_a_go_to_out_of_the_range_keeps_the_pending_return(asg_of: Asg) -> None:
    """A jumps out of A THRU B to C, and C jumps back to B: B's end still returns,
    because leaving a range by GO TO does not cancel the PERFORM."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A", "B"), {"type": "STOP_RUN"}),
        _para("A", _goto("C")),
        _para("B", _move("'B'", "WS-B")),
        _para("C", _goto("B")),
    )

    assert _paragraphs(rows) == ["MAIN", "A", "C", "B"]
    assert _outcomes(rows) == {("returns", "MAIN/1")}


@pytest.mark.parametrize(
    ("body", "extra", "outcomes"),
    (
        ((({"type": "STOP_RUN"},)), (), {("stop-run", "A/0")}),
        (({"type": "GOBACK"},), (), {("goback", "A/0")}),
        (({"type": "EXIT_PROGRAM"},), (), {("exit-program", "A/0")}),
        (
            (_cics("ABEND", {"ABCODE": {"text": "'AB01'", "is_literal": True}}),),
            (),
            {("abend", "A/0")},
        ),
        (
            (_cics("XCTL", {"PROGRAM": {"text": "'PROGB'", "is_literal": True}}),),
            (),
            {("xctl", "A/0"), ("unhandled-condition", "A/0#dispatch")},
        ),
        (
            (_cics("RETURN", {"RESP": {"text": "WS-RESP", "is_literal": False}}),),
            (),
            {("cics-return", "A/0"), ("returns", "MAIN/1")},
        ),
        ((_goto("Z"),), (_para("Z", _move("'Z'", "WS-Z")),), {("dead-end", "Z#end")}),
    ),
    ids=("stop-run", "goback", "exit-program", "abend", "xctl", "cics-return-resp", "dead-end"),
)
def test_each_way_out_of_the_range_is_an_outcome_at_its_node(
    asg_of: Asg, body: tuple[dict, ...], extra: tuple[dict, ...], outcomes: set[tuple[str, str]]
) -> None:
    """A terminator ends its branch. A successful XCTL or RETURN leaves the program
    from the command itself, and its failure path is walked on: with no handler
    armed the raised condition abends, under RESP the next statement runs. Falling
    off the program's last paragraph is a dead end, not a silent stop. A range
    that cannot return gives no `returns`, and the FLOW edge the build keeps past
    such a PERFORM is not taken."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), {"type": "STOP_RUN"}),
        _para("A", *body),
        *extra,
    )

    assert _outcomes(rows) == outcomes
    assert ("MAIN/0", "MAIN/1", EdgeKind.FLOW) not in _edges(rows)


def test_an_end_only_another_site_closes_with_nowhere_to_fall_is_a_dead_end(
    asg_of: Asg,
) -> None:
    """A jumps to Z, the last paragraph. Z's end returns only to the second PERFORM's
    site, which is not the innermost open frame here, and there is no next
    paragraph to fall into: the branch is a dead end at Z's end, recorded."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), _perform("Z"), {"type": "STOP_RUN"}),
        _para("A", _goto("Z")),
        _para("Z", _move("'Z'", "WS-Z")),
    )

    assert _outcomes(rows) == {("dead-end", "Z#end")}
    assert ("Z#end", "MAIN/2", EdgeKind.RETURN) not in _edges(rows)


def test_a_handled_condition_reaches_its_handler_and_the_loop_back_ends(
    asg_of: Asg,
) -> None:
    """The dispatch's edge to the armed handler is followed. The handler's own XCTL
    raises back into it -- the arming is still live there -- and the walk records
    that edge once and stops, since the state it reaches is already visited."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), {"type": "GOBACK"}),
        _para(
            "A",
            _cics("HANDLE CONDITION", {"MAPFAIL": {"text": "H", "is_literal": False}}),
            _cics("RECEIVE MAP", {"MAP": {"text": "'M'", "is_literal": True}}),
        ),
        _para("H", _cics("XCTL", {"PROGRAM": {"text": "'PROGB'", "is_literal": True}})),
    )

    assert _paragraphs(rows) == ["MAIN", "A", "H"]
    assert _outcomes(rows) == {("returns", "MAIN/1"), ("xctl", "H/0")}
    assert [
        (row.source, row.target)
        for row in rows
        if isinstance(row, CfgEdgeRow) and row.source == "H/0#dispatch"
    ] == [("H/0#dispatch", "H#label")]


def test_a_recursive_perform_is_refused_and_stepped_over(asg_of: Asg) -> None:
    """A performs A. The first time it is a real nested PERFORM; inside that, A's
    resume point is already open, so the PERFORM is refused and the walk resumes
    after it, as if the range had run."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), {"type": "STOP_RUN"}),
        _para("A", _perform("A"), _move("'A'", "WS-A")),
    )

    assert _flagged(rows, CfgRefusedRow) == ["A/0"]
    assert ("A/0", "A/1", EdgeKind.FLOW) in _edges(rows)
    assert _outcomes(rows) == {("returns", "MAIN/1")}


def test_an_unresolved_perform_is_recorded_and_stepped_past(asg_of: Asg) -> None:
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A"), {"type": "STOP_RUN"}),
        _para("A", _perform("NOWHERE"), _move("'A'", "WS-A")),
    )

    assert _flagged(rows, CfgUnresolvedRow) == ["A/0"]
    assert ("A/0", "A/1", EdgeKind.FLOW) in _edges(rows)
    assert _outcomes(rows) == {("returns", "MAIN/1")}


@pytest.mark.parametrize(
    ("seed", "message"),
    (
        ("MAIN/9", "PROGA has no node MAIN/9"),
        ("MAIN/1", r"MAIN/1 is not a PERFORM \(kind ASSIGN, transfer MOVE\)"),
        ("MAIN/2", "MAIN/2 performs NOWHERE, which PROGA does not declare"),
    ),
    ids=("absent", "not-a-perform", "unresolved"),
)
def test_a_seed_that_is_not_a_resolved_perform_is_refused_before_any_row(
    asg_of: Asg, seed: str, message: str
) -> None:
    cfg = program_cfg(
        asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [
                    _para(
                        "MAIN",
                        _perform("A"),
                        _move("'X'", "WS-X"),
                        _perform("NOWHERE"),
                        {"type": "STOP_RUN"},
                    ),
                    _para("A", _move("'A'", "WS-A")),
                ],
            }
        )
    )

    with pytest.raises(ReachError, match=message):
        reach_rows(cfg, seed)


def test_rows_stream_nodes_before_their_edges_and_the_summary_last(asg_of: Asg) -> None:
    """Any prefix of the output is a valid partial graph, and only a finished walk
    ends in a summary."""
    rows = _rows(
        asg_of,
        "MAIN/0",
        _para("MAIN", _perform("A", "B"), {"type": "STOP_RUN"}),
        _para("A", _goto("C")),
        _para("B", _move("'B'", "WS-B")),
        _para("C", _goto("B")),
    )
    position = {row.id: at for at, row in enumerate(rows) if isinstance(row, CfgNodeRow)}

    assert rows[0].type == "program"
    assert all(
        position[row.source] < at and position[row.target] < at
        for at, row in enumerate(rows)
        if isinstance(row, CfgEdgeRow)
    )
    assert [row.type for row in rows].count("summary") == 1
    assert isinstance(rows[-1], CfgSummaryRow)
```

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg/test_reach.py -q`
Expected: FAIL at collection: `ModuleNotFoundError: No module named 'cobble.dataflow.srccfg.reach'`.

- [ ] **Step 3: Write the value classes.**

`cobble/cobble/dataflow/srccfg/reach/__init__.py`:

```python
"""Reachability from one PERFORM: what can run until control returns, and how else it ends."""
```

`reach/reach_error.py`:

```python
"""A seed a reachability walk cannot start from."""


class ReachError(ValueError):
    """Named so a caller can report why, before any row is written."""
```

`reach/reach_state.py`:

```python
"""One reachability state: a node, and the resume points of the PERFORMs open there."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReachState:
    node: str
    stack: tuple[str, ...]
```

`reach/reach_step.py`:

```python
"""One edge a reachability walk takes, and the state it arrives in."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import Edge
from cobble.dataflow.srccfg.reach.reach_state import ReachState


@dataclass(frozen=True)
class ReachStep:
    edge: Edge
    state: ReachState
```

`reach/reach_visit.py`:

```python
"""What expanding one state gives: the steps out of it, and the facts it records."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.reach.reach_step import ReachStep
from cobble.dataflow.srccfg.rows.cfg_row import CfgRow


@dataclass(frozen=True)
class ReachVisit:
    steps: tuple[ReachStep, ...]
    events: tuple[CfgRow, ...]
```

`reach/reach_progress.py`:

```python
"""A reachability walk between two levels: what to expand next, and what it has written."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import Edge
from cobble.dataflow.srccfg.reach.reach_state import ReachState
from cobble.dataflow.srccfg.rows.cfg_row import CfgRow


@dataclass(frozen=True)
class ReachProgress:
    frontier: tuple[ReachState, ...]
    seen: frozenset[ReachState]
    nodes: frozenset[str]
    edges: frozenset[Edge]
    events: frozenset[CfgRow]
```

- [ ] **Step 4: Write the expansion.** `reach/expand.py`:

```python
"""What one reachability state leads to: the edges taken out of it, and what it records.

The rules are the spec's semantics table, one function each, chosen by the first
test in ``_RULES`` the state meets.
"""

from collections.abc import Callable, Mapping
from types import MappingProxyType

from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node
from cobble.dataflow.srccfg.desugar import DISPATCH_TRANSFER_CICS, PERFORM_TRANSFER
from cobble.dataflow.srccfg.reach.reach_error import ReachError
from cobble.dataflow.srccfg.reach.reach_state import ReachState
from cobble.dataflow.srccfg.reach.reach_step import ReachStep
from cobble.dataflow.srccfg.reach.reach_visit import ReachVisit
from cobble.dataflow.srccfg.rows.cfg_row import outcome_row, refused_row, unresolved_row
from cobble.dataflow.srccfg.rows.reach_outcome import ReachOutcome

_ENDING: Mapping[str, ReachOutcome] = MappingProxyType(
    {
        "STOPRUN": ReachOutcome.STOP_RUN,
        "GOBACK": ReachOutcome.GOBACK,
        "EXITPROGRAM": ReachOutcome.EXIT_PROGRAM,
        "CICS_ABEND": ReachOutcome.ABEND,
    }
)
_LEAVING: Mapping[str, ReachOutcome] = MappingProxyType(
    {"CICS_XCTL": ReachOutcome.XCTL, "CICS_RETURN": ReachOutcome.CICS_RETURN}
)

Test = Callable[[Cfg, Node, ReachState], bool]
Rule = Callable[[Cfg, Node, ReachState], ReachVisit]


def start(cfg: Cfg, seed: str) -> ReachVisit:
    """The seed's own expansion: enter its range with one frame, its resume point."""
    node = _performing(cfg, _present(cfg, seed))
    return _performed(cfg, node, ReachState(node=seed, stack=()))


def _present(cfg: Cfg, seed: str) -> Node:
    if seed not in cfg.node_ids:
        raise ReachError(f"{cfg.program} has no node {seed}")
    return cfg.node(seed)


def _performing(cfg: Cfg, node: Node) -> Node:
    if node.transfer != PERFORM_TRANSFER:
        raise ReachError(
            f"{node.id} is not a PERFORM "
            f"(kind {node.kind.value}, transfer {node.transfer or 'none'})"
        )
    if not _performs(cfg, node.id):
        raise ReachError(
            f"{node.id} performs {node.target}, which {cfg.program} does not declare"
        )
    return node


def expand(cfg: Cfg, state: ReachState) -> ReachVisit:
    node = cfg.node(state.node)
    rule = next(rule for test, rule in _RULES if test(cfg, node, state))
    return rule(cfg, node, state)


def _returns(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    return ReachVisit(steps=(), events=(outcome_row(ReachOutcome.RETURNS, node.id),))


def _ends(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    return ReachVisit(steps=(), events=(outcome_row(_ENDING[node.transfer], node.id),))


def _leaves(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    return ReachVisit(
        steps=_onward(cfg, node, state).steps,
        events=(outcome_row(_LEAVING[node.transfer], node.id),),
    )


def _onward(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    return ReachVisit(
        steps=tuple(
            ReachStep(edge=edge, state=ReachState(node=edge.target, stack=state.stack))
            for edge in cfg.successors(node.id)
        ),
        events=(),
    )


def _performed(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    performs = _performs(cfg, node.id)
    if not performs:
        return ReachVisit(
            steps=_onward(cfg, node, state).steps, events=(unresolved_row(node.id),)
        )
    resume = _resume(cfg, node)
    if resume in state.stack:
        return _stepped_over(node, resume, state)
    return ReachVisit(
        steps=tuple(
            ReachStep(
                edge=edge,
                state=ReachState(node=edge.target, stack=(*state.stack, resume)),
            )
            for edge in performs
        ),
        events=(),
    )


def _stepped_over(node: Node, resume: str, state: ReachState) -> ReachVisit:
    """A recursive PERFORM is undefined in COBOL: the walk does not push it, and goes
    on at its resume point along an edge the CFG does not hold, named by the
    ``refused`` row."""
    return ReachVisit(
        steps=(
            ReachStep(
                edge=Edge(source=node.id, target=resume, kind=EdgeKind.FLOW),
                state=ReachState(node=resume, stack=state.stack),
            ),
        ),
        events=(refused_row(node.id),),
    )


def _performs(cfg: Cfg, node_id: str) -> tuple[Edge, ...]:
    return tuple(
        edge for edge in cfg.successors(node_id) if edge.kind is EdgeKind.PERFORM
    )


def _resume(cfg: Cfg, node: Node) -> str:
    """Where the PERFORM continues once its range returns: ``Node.resume``, or for a
    range that never returns, the FLOW edge the build kept past it."""
    if node.resume:
        return node.resume
    return next(
        (edge.target for edge in cfg.successors(node.id) if edge.kind is EdgeKind.FLOW),
        "",
    )


def _range_end(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    """Return to the innermost open PERFORM if this end closes it; otherwise fall
    through, as COBOL does at an end no open PERFORM closes."""
    back = tuple(
        edge
        for edge in cfg.successors(node.id)
        if edge.kind is EdgeKind.RETURN and edge.target == state.stack[-1]
    )[:1]
    if back:
        return ReachVisit(
            steps=(
                ReachStep(
                    edge=back[0],
                    state=ReachState(node=back[0].target, stack=state.stack[:-1]),
                ),
            ),
            events=(),
        )
    return _fallen_through(cfg, node, state)


def _fallen_through(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    onward = tuple(
        ReachStep(edge=edge, state=ReachState(node=edge.target, stack=state.stack))
        for edge in cfg.successors(node.id)
        if edge.kind is not EdgeKind.RETURN
    )
    if not onward:
        return _stuck(cfg, node, state)
    return ReachVisit(steps=onward, events=())


def _stuck(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    kind = (
        ReachOutcome.UNHANDLED_CONDITION
        if node.transfer == DISPATCH_TRANSFER_CICS
        else ReachOutcome.DEAD_END
    )
    return ReachVisit(steps=(), events=(outcome_row(kind, node.id),))


_RULES: tuple[tuple[Test, Rule], ...] = (
    (lambda cfg, node, state: not state.stack, _returns),
    (lambda cfg, node, state: node.transfer in _ENDING, _ends),
    (lambda cfg, node, state: node.transfer in _LEAVING, _leaves),
    (lambda cfg, node, state: node.transfer == PERFORM_TRANSFER, _performed),
    (
        lambda cfg, node, state: any(
            edge.kind is EdgeKind.RETURN for edge in cfg.successors(node.id)
        ),
        _range_end,
    ),
    (lambda cfg, node, state: not cfg.successors(node.id), _stuck),
    (lambda cfg, node, state: True, _onward),
)
```

The first rule is the only way a state with an empty stack arises: the walk's one root frame is the seed's resume point, and only the RETURN that pops it empties the stack.

- [ ] **Step 5: Write the walk.** `reach/walk.py`:

```python
"""The breadth-first reachability walk, written out as src-cfg rows level by level.

Each level writes the nodes first reached in it, then the edges first taken in it
-- so every edge follows both its nodes -- then what it found. The summary row
comes last, so its presence says the walk finished.
"""

from collections.abc import Hashable, Iterator
from typing import TypeVar

from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.reach.expand import expand, start
from cobble.dataflow.srccfg.reach.reach_progress import ReachProgress
from cobble.dataflow.srccfg.reach.reach_visit import ReachVisit
from cobble.dataflow.srccfg.rows.cfg_row import (
    CfgRow,
    edge_row,
    node_row,
    program_row,
    summary_row,
)

ItemT = TypeVar("ItemT", bound=Hashable)


def reach_rows(cfg: Cfg, seed: str) -> Iterator[CfgRow]:
    """Everything that can run from ``seed`` until it returns, as rows.

    Raises ``ReachError`` here, before any row, for a seed the walk cannot start
    from -- the generator below only starts once the seed has been checked.
    """
    return _rows(cfg, seed, start(cfg, seed))


def _rows(cfg: Cfg, seed: str, first: ReachVisit) -> Iterator[CfgRow]:
    yield program_row(cfg.program)
    yield node_row(cfg.program, cfg.node(seed))
    rows, progress = _advanced(cfg, _begun(seed), (first,))
    yield from rows
    while progress.frontier:
        visits = tuple(expand(cfg, state) for state in progress.frontier)
        rows, progress = _advanced(cfg, progress, visits)
        yield from rows
    yield summary_row(seed, len(progress.seen))


def _begun(seed: str) -> ReachProgress:
    return ReachProgress(
        frontier=(),
        seen=frozenset(),
        nodes=frozenset({seed}),
        edges=frozenset(),
        events=frozenset(),
    )


def _advanced(
    cfg: Cfg, progress: ReachProgress, visits: tuple[ReachVisit, ...]
) -> tuple[tuple[CfgRow, ...], ReachProgress]:
    steps = tuple(step for visit in visits for step in visit.steps)
    states = _fresh(tuple(step.state for step in steps), progress.seen)
    nodes = _fresh(tuple(step.state.node for step in steps), progress.nodes)
    edges = _fresh(tuple(step.edge for step in steps), progress.edges)
    events = _fresh(
        tuple(event for visit in visits for event in visit.events), progress.events
    )
    rows = (
        *(node_row(cfg.program, cfg.node(node)) for node in nodes),
        *(edge_row(cfg.program, edge) for edge in edges),
        *events,
    )
    return rows, ReachProgress(
        frontier=states,
        seen=progress.seen | frozenset(states),
        nodes=progress.nodes | frozenset(nodes),
        edges=progress.edges | frozenset(edges),
        events=progress.events | frozenset(events),
    )


def _fresh(items: tuple[ItemT, ...], known: frozenset[ItemT]) -> tuple[ItemT, ...]:
    """The items not yet known, once each, in the order they arrived."""
    return tuple(dict.fromkeys(item for item in items if item not in known))
```

`seen` grows by a set union per level, which copies it: the cost is the number of states times the number of levels. That is the spec's stated risk; the summary's `states` count is how a run shows it.

- [ ] **Step 6: Run the tests.**

Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg/test_reach.py -q`
Expected: PASS -- 20 tests (the outcome test runs 7 times, the seed test 3).

The node lists and the summary's `states=7` were derived from the semantics table against the CFG shapes `program_cfg` produces (checked while writing this plan for the THRU and HANDLE programs). If one differs, work out from the CFG which is right before changing either side: print the CFG with `program_cfg(...)` and walk the rule table by hand. Change an assertion only when the CFG shows the expected value was wrong, and ledger it as a ruling.

- [ ] **Step 7: Mutation-check.**
  1. In `_range_end`, drop `and edge.target == state.stack[-1]`: `test_a_range_end_two_sites_share_returns_only_to_the_seeds` must FAIL. Restore.
  2. In `_RULES`, move the `_range_end` rule below `_onward`'s position (i.e. delete it): `test_a_thru_range_falls_through_its_paragraphs_and_returns` must FAIL (the walk takes the RETURN and the FALLTHRU alike, or never returns). Restore.
  3. In `_performed`, replace `if resume in state.stack:` with `if False:`: `test_a_recursive_perform_is_refused_and_stepped_over` must FAIL. Restore.
  4. In `_advanced`, put `*events` and the edge rows before the node rows: `test_rows_stream_nodes_before_their_edges_and_the_summary_last` must FAIL. Restore.

- [ ] **Step 8: Gate and commit.**

```bash
git add cobble/cobble/dataflow/srccfg/reach cobble/tests/dataflow/srccfg/test_reach.py
git commit -m "feat(cobble): reachability from a PERFORM, with return and abort semantics

A breadth-first walk over (node, stack of resume points) states from one PERFORM
site, each state visited once. A range end returns only to the innermost open
PERFORM and falls through otherwise; a GO TO out of a range keeps the pending
return; a recursive PERFORM is refused and stepped over. STOP RUN, GOBACK, EXIT
PROGRAM, ABEND, XCTL, CICS RETURN, an unhandled CICS condition and a dead end
each end a branch as a recorded outcome. The walk streams src-cfg rows level by
level: nodes, then edges, then findings, and a summary last.

```

---

### Task 3: The command

**Files:**
- Create: `cobble/cobble/dataflow/srccfg/reach/cli.py`
- Modify: `cobble/pyproject.toml` (the `[project.scripts]` table, after `cobble-srccfg-query`)
- Modify: `cobble/README.md` (the command table at lines ~46-48, and a new section before `### Point this at your own codebase`)
- Test: `cobble/tests/dataflow/srccfg/test_reach_cli.py`

**Interfaces:**
- Consumes: `reach_rows(cfg: Cfg, seed: str) -> Iterator[CfgRow]` and `ReachError` (Task 2); `load_bundle(path: Path) -> Bundle`, `Bundle`, `CfgDocumentError` (`srccfg/bundle.py`); `configure_cli_logging()` (`cobble.cli_logging`); `closure.main(argv: Sequence[str]) -> int` (`cobble-srccfg-build`), `dot.main(argv)` and `dot.dot_of(cfgs, calls)` (`srccfg/dot.py`); `parse_one(Job(source, out), jar, copybook_dirs, extensions)` (`cobble.parsing.parse_corpus`).
- Produces: `main(argv: Sequence[str] = ()) -> int` in `reach/cli.py`; the `cobble-srccfg-reach` script.

- [ ] **Step 1: Write the failing tests.** Create `cobble/tests/dataflow/srccfg/test_reach_cli.py`:

```python
"""cobble-srccfg-reach: a CFG file in, the reached subgraph and its outcomes out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.bundle import Bundle, bundle_jsonl, load_bundle
from cobble.dataflow.srccfg.closure import main as build_main
from cobble.dataflow.srccfg.dot import dot_of
from cobble.dataflow.srccfg.dot import main as dot_main
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.reach.cli import main
from cobble.dataflow.srccfg.rows.cfg_row import CFG_ROWS
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.outcome_row import CfgOutcomeRow
from cobble.dataflow.srccfg.rows.summary_row import CfgSummaryRow
from cobol_asg.asg_types import CobolASG

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REACHP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG              PIC X.
       01  WS-A                 PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WORK-PARA THRU WORK-EXIT.
           MOVE 'DONE' TO WS-A.
           STOP RUN.
       WORK-PARA.
           IF WS-FLAG = 'Y'
               GO TO FAIL-PARA
           END-IF.
           MOVE 'WORK' TO WS-A.
       WORK-EXIT.
           EXIT.
       FAIL-PARA.
           MOVE 'FAIL' TO WS-A.
           GOBACK.
"""


def _cfg_file(tmp_path: Path, *programs: str) -> Path:
    """A closure-shaped file of one-paragraph programs, each MAIN performing A."""
    def asg(program: str) -> CobolASG:
        body = {
            "program_id": program,
            "paragraphs": [
                {"name": "MAIN", "statements": [{"type": "PERFORM", "operands": ["A"]}]},
                {"name": "A", "statements": [{"type": "GOBACK"}]},
            ],
        }
        with cached_asg_dialect_parsers_registered():
            return CobolASG.from_dict(json.loads(json.dumps(body)))

    cfgs = tuple(program_cfg(asg(program)) for program in programs)
    path = tmp_path / "cfg.jsonl"
    path.write_text(bundle_jsonl(Bundle(seed=programs[0], cfgs=cfgs)), encoding="utf-8")
    return path


def test_the_command_streams_the_rows_and_says_nothing_else_on_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--cfg", str(_cfg_file(tmp_path, "PROGA")), "--from", "MAIN/0"]) == 0

    rows = [CFG_ROWS.validate_json(line) for line in capsys.readouterr().out.splitlines()]

    assert [row.type for row in rows][:2] == ["program", "node"]
    assert {(row.kind.value, row.node) for row in rows if isinstance(row, CfgOutcomeRow)} == {
        ("goback", "A/0")
    }
    assert rows[-1] == CfgSummaryRow(type="summary", seed="MAIN/0", states=2)


@pytest.mark.parametrize(
    ("argv_tail", "message"),
    (
        (["--from", "MAIN/0"], ""),
        (["--from", "MAIN/7"], "PROGA has no node MAIN/7"),
    ),
    ids=("missing-file", "absent-seed"),
)
def test_a_seed_the_file_does_not_hold_is_an_error_naming_the_program(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    argv_tail: list[str],
    message: str,
) -> None:
    """The walk runs in the file's first program; a seed elsewhere -- in a callee of a
    closure, say -- is reported against the program searched, and nothing reaches
    stdout. A file that is not there is the same: an error, an exit code, no rows."""
    cfg = _cfg_file(tmp_path, "PROGA", "PROGB") if message else tmp_path / "absent.jsonl"

    assert main(["--cfg", str(cfg), *argv_tail]) == 1
    assert capsys.readouterr().out == ""
    assert (message or "absent.jsonl") in caplog.text


def test_an_empty_cfg_file_is_an_error_not_an_empty_walk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    assert main(["--cfg", str(path), "--from", "MAIN/0"]) == 1
    assert capsys.readouterr().out == ""
    assert "holds no program" in caplog.text


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def test_a_compiled_program_reaches_its_range_and_renders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end: the bridge's ASG, cobble-srccfg-build's file, this command's rows,
    and cobble-srccfg-dot drawing them. The range is WORK-PARA THRU WORK-EXIT; a
    GO TO out of it ends in GOBACK, the other branch returns."""
    from cobble.parsing.parse_corpus import Job, parse_one

    cache = tmp_path / "parsed"
    cache.mkdir()
    source = tmp_path / "REACHP.cbl"
    source.write_text(SOURCE, encoding="utf-8")
    parsed = parse_one(Job(source, cache / "REACHP.json"), str(_bridge_jar()), (), ("cpy",))
    assert parsed.ok, parsed.error
    config = tmp_path / "srccfg.toml"
    config.write_text(f'[srccfg]\nasg_dir = "{cache}"\n', encoding="utf-8")
    built = tmp_path / "REACHP.jsonl"
    assert build_main(["--config", str(config), "REACHP", "--output", str(built)]) == 0

    assert main(["--cfg", str(built), "--from", "MAIN-PARA/0"]) == 0
    out = tmp_path / "reach.jsonl"
    out.write_text(capsys.readouterr().out, encoding="utf-8")
    rows = [CFG_ROWS.validate_json(line) for line in out.read_text().splitlines()]

    assert list(
        dict.fromkeys(row.paragraph for row in rows if isinstance(row, CfgNodeRow))
    ) == ["MAIN-PARA", "WORK-PARA", "FAIL-PARA", "WORK-EXIT"]
    assert {(row.kind.value, row.node) for row in rows if isinstance(row, CfgOutcomeRow)} == {
        ("goback", "FAIL-PARA/1"),
        ("returns", "MAIN-PARA/1"),
    }
    assert [row.type for row in rows if row.type in ("unresolved", "refused")] == []
    assert isinstance(rows[-1], CfgSummaryRow)
    assert dot_main(["--cfg", str(out), "--output", str(tmp_path / "reach.dot")]) == 0
    assert (tmp_path / "reach.dot").read_text(encoding="utf-8") == dot_of(
        load_bundle(out).cfgs, ()
    )
```

Before relying on the last assertion, read `cobble/cobble/dataflow/srccfg/dot.py`'s `main` to see exactly what it writes for a bundle (`dot_of(bundle.cfgs, bundle.calls)` plus a trailing newline, or not), and make the right-hand side match that call exactly -- the assertion is that the command renders the reached subgraph the way the library renders the loaded bundle, not a particular newline convention.

`states=2` in the first test: `A` ends in GOBACK, so its range never returns, `MAIN/0` has no `resume`, and the frame the walk opens is `MAIN/0`'s FLOW successor, `MAIN#end` (the PERFORM is MAIN's last statement). The walk then expands exactly two states, `A#label` and `A/0`, each with stack `("MAIN#end",)`, and `A/0` ends the branch with `goback`. Confirm the count from the CFG as in Task 2 Step 6 if it differs.

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg/test_reach_cli.py -q`
Expected: FAIL at collection: `ModuleNotFoundError: No module named 'cobble.dataflow.srccfg.reach.cli'`.

- [ ] **Step 3: Write the command.** `cobble/cobble/dataflow/srccfg/reach/cli.py`:

```python
"""cobble-srccfg-reach: what can run from one PERFORM until it returns, as src-cfg rows.

Reads a CFG file cobble-srccfg-build wrote, walks the first program in it from the
PERFORM node named by --from, and writes the reached subgraph and what it found to
stdout as JSONL, as the walk goes. cobble-srccfg-dot and -webgl render the output.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.srccfg.bundle import Bundle, CfgDocumentError, load_bundle
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.reach.reach_error import ReachError
from cobble.dataflow.srccfg.reach.walk import reach_rows

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-srccfg-reach",
        description="Everything that can run from one PERFORM until it returns.",
    )
    parser.add_argument(
        "--cfg",
        required=True,
        type=Path,
        help="a CFG file cobble-srccfg-build wrote; the walk runs in its first program",
    )
    parser.add_argument(
        "--from",
        dest="seed",
        required=True,
        help="the id of a PERFORM node in that program, e.g. MAIN-PARA/0",
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(list(argv) if argv else sys.argv[1:])
    try:
        rows = reach_rows(_walked_program(arguments.cfg), arguments.seed)
    except (CfgDocumentError, ReachError, FileNotFoundError) as error:
        logger.error("%s", error)
        return 1
    sys.stdout.writelines(f"{row.model_dump_json()}\n" for row in rows)
    return 0


def _walked_program(path: Path) -> Cfg:
    return _first(load_bundle(path))


def _first(bundle: Bundle) -> Cfg:
    if not bundle.cfgs:
        raise ReachError("the CFG file holds no program")
    return bundle.cfgs[0]
```

`cobble/pyproject.toml`, after the `cobble-srccfg-query` line:

```toml
cobble-srccfg-reach = "cobble.dataflow.srccfg.reach.cli:main"
```

Then register the script: run `make python` at the repo root (it runs `uv sync --all-packages`; every `uv run` elsewhere uses `--no-sync` and would not pick the entry up). Confirm with `uv run --no-sync cobble-srccfg-reach --help`.

- [ ] **Step 4: Run the tests.**

Run: `uv run --no-sync python -m pytest tests/dataflow/srccfg/test_reach_cli.py -q`
Expected: PASS (the bridge test is skipped only if `make jar` has never been run; it must run here -- if it skips, build the JAR and rerun).

- [ ] **Step 5: Mutation-check.** In `cli.py`, remove `FileNotFoundError` from the `except` tuple: the `missing-file` case must FAIL with a traceback. Restore. In `_first`, return `Cfg(program="", nodes=(), edges=())` instead of raising: `test_an_empty_cfg_file_is_an_error_not_an_empty_walk` must FAIL. Restore.

- [ ] **Step 6: Document it.** In `cobble/README.md`:

- In the command table, after the `cobble-srccfg-query` row, add:

  ```
  | `cobble-srccfg-reach --cfg <jsonl> --from <node-id>` | What can run from one PERFORM until control returns, and every other way it ends, as rows `cobble-srccfg-dot`/`-webgl` render |
  ```

- Before `### Point this at your own codebase`, add a section:

  ```markdown
  ### Reachability from a PERFORM

  `cobble-srccfg-reach --cfg <file> --from <PERFORM node id>` answers "what can run
  from this PERFORM until control comes back, and how else can it end". It walks
  the first program in a `cobble-srccfg-build` file over states of a node and the
  PERFORMs open there, so a range end returns only to the innermost open PERFORM
  and falls through otherwise — the call-stack knowledge a plain BFS over the CFG
  lacks. It is reachability, not path enumeration: each state is visited once.

  | At | The walk |
  | --- | --- |
  | a PERFORM | opens a frame for its resume point and enters the range; never takes the edge past it |
  | a range end | returns to the innermost open PERFORM if this end closes it, else falls through |
  | a GO TO | follows it; a GO TO out of a range keeps the pending return |
  | a decision | follows every arm |
  | a recursive PERFORM | is not entered (`refused`); the walk resumes after it |
  | a PERFORM of an undeclared range | is stepped past (`unresolved`) |
  | a CALL or LINK | is stepped past; other programs are not entered |

  Output is JSONL on stdout, written as the walk goes: the reached nodes and the
  edges actually taken, in the src-cfg row format, so `cobble-srccfg-dot` and
  `-webgl` draw it; then `outcome` rows — `returns`, `stop-run`, `goback`,
  `exit-program`, `abend`, `xctl`, `cics-return`, `unhandled-condition`, `dead-end`,
  each at its node — plus `unresolved` and `refused` rows, and a last `summary` row
  with the number of states visited. A missing summary means the walk did not
  finish. The graph does not keep the stack: a paragraph reached from two
  PERFORMs shows both returns, so one route through the picture is not
  guaranteed to be a real execution.
  ```

- [ ] **Step 7: Gate and commit.**

Run the gate. Then:

```bash
git add cobble/cobble/dataflow/srccfg/reach/cli.py cobble/pyproject.toml cobble/README.md \
  cobble/tests/dataflow/srccfg/test_reach_cli.py
git commit -m "feat(cobble): cobble-srccfg-reach

Reads a cobble-srccfg-build file and walks its first program from a named
PERFORM, streaming the reached subgraph and its outcomes to stdout as src-cfg
rows that cobble-srccfg-dot and -webgl render. A seed the program does not hold,
a missing file and an empty one are errors with an exit code and nothing on
stdout.

```

If `uv.lock` changed when `make python` ran, it is not part of this commit unless the change is the new script entry alone; report it either way.

---

## Deviations from the spec

- **A package, not one module.** The spec names `srccfg/reach.py`. The walk needs five small frozen value classes and an error type, and the repo's rule is one class per file, so it is `srccfg/reach/` with one file per class, the expansion rules in `expand.py`, the walk in `walk.py` and the command in `cli.py`.
- **A refused PERFORM's continuation is an edge the CFG does not hold.** The spec says the walk "continues at the resume point as if the range had run"; there is no edge from the PERFORM to its resume point once the range can return. The walk takes a synthetic `FLOW` edge there and writes it like any other, with the `refused` row naming the node -- the same step `fields.trace._stepped_over` takes.
- **The integration test asserts the paragraph order, the outcomes, the absence of unresolved and refused rows, the summary's place, and the rendering -- not every node id.** The bridge's ids for an IF's test and arms are lowering detail the unit tests pin on dict-built CFGs; repeating them here would make the end-to-end test fail on a lowering change it is not about.
- **The seed's program is the file's first.** The spec says "the seed's program"; a closure file can hold many, and node ids repeat across programs, so the command walks the first (the seed `cobble-srccfg-build` was asked for) and a seed it does not hold is an error naming that program.

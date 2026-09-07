# Cross-program byte dataflow across a commarea — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a byte-interval dataflow question continue from a caller into the program it `LINK`s or `XCTL`s to, by emitting the commarea's shared window as a fifth artefact table and adding an opt-in traversal that rebases a range across it.

**Architecture:** A commarea is shared storage, so caller byte `start(WS-AREA)+k` **is** callee byte `k` of `DFHCOMMAREA`. That is a byte-identity alias with an offset rebase, not a `FLOWS_TO` edge, so it gets its own table (`aliases.jsonl`) rather than an attribute on an edge — a row relates two programs and belongs to neither one's flow graph. A new `fields/aliases.py` computes rows from inputs that already exist (`srccfg/link.py` for sites, `dataflow/layout.py` for both sides' byte extents, `fields/extent_text.py` for the wire form); no fixpoint and no walk, one LINKAGE layout per distinct callee. The query side gains a separate `crossing()` walk beside the untouched `reaches()`, so default output stays byte-identical.

**Tech Stack:** Python 3.12, `uv`, pytest, Black (88), pyright, `lint-imports`, `python-fp-lint` (ast-grep). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-07-cross-program-commarea-dataflow-design.md`

## Global Constraints

- **The alias covers `min(len(caller extent), len(callee DFHCOMMAREA))` bytes.** Past that the two areas are not both addressable and the table must not claim they are. Of 203 measurable sites, 61 disagree (24 caller-bigger, 37 callee-bigger) — the `min` is load-bearing.
- **`LENGTH` never narrows the window.** Zero of 4078 sites give a literal; 3535 give `LENGTH OF <the caller's own commarea field>`, which restates the caller's declared length. Do not read the `LENGTH` option.
- **`LINK` returns, `XCTL` does not.** A `LINK` alias is symmetric and traversable both ways; an `XCTL` alias is inbound-only. One `returns` flag on the row carries it.
- **A site that cannot be aliased emits a row with a `reason`, never silence.** `callee` and both extent fields are empty. An answer that cannot distinguish "nothing flows here" from "the analysis stopped here" is a plausible wrong answer (`red-dragon-forge-y02`).
- **The existing `%CALL:<program>` synthetic origin stays unchanged.** It is the correct intra-program answer and every current edge depends on it.
- **`--across-calls` is off by default, `--max-hops` defaults to 3.** Without the flag, all four existing tables and all existing queries produce byte-identical output.
- **Extent wire form is `fields/extent_text.py`'s**, `~` clamp mark included, so `byte_range` parses both sides unchanged.
- **Static `CALL ... USING` is out of scope.** The ASG carries no `PROCEDURE DIVISION USING` list; bead `red-dragon-forge-4ut` tracks the bridge work. A `CALL` site emits a dead-end row, not a guess.
- **No corpus identifier in any tracked file** — code, tests, docs, commit messages. Synthetic COBOL only; the fixtures in this plan use `XPROGA`/`XPROGB` and `WS-`/`SUB-` names.
- **Comments are a smell.** Reach for a name or a docstring first; a surviving comment must carry an external constraint or a non-obvious "why".
- **fp-lint:** `max_complexity: 3`, `max_statements: 10` per function; no `Optional`, no `None` default, no `x or default` fallback, no mutation outside `__init__`, no `list.append`, no unfrozen dataclass, no `Any`. Sentinel objects (see `fields/state.py:NOWHERE`) replace `None`.
- **No test counts in living documentation.**
- Commands: `uv run --no-sync python -m pytest` from `cobble/`; `make fmt`, `make lint` per package; `uv run lint-imports` at the root.

### Three spec/reality reconciliations the executor must know

1. **There is no `origin` query and no `--member`/`--field` flags.** The spec's example CLI line is illustrative, not real. The actual surface is `cobble-fields-query <query> <subject> --out DIR [--depth N]`. `--across-calls`/`--max-hops` therefore attach to the two transitive queries, `reaches` and `reached-by` — not to `origin`/`writers`/`readers`.
2. **There are eight existing queries, not seven:** `extents`, `writers`, `readers`, `reaches`, `reached-by`, `contains`, `within`, `overlapping`. All eight must stay byte-identical.
3. **Three dead-end reasons are added beyond the spec's five:** `caller-field-unknown` (the `COMMAREA` operand resolves to no cell in the caller's layout), `call-using-unsupported` (a static `CALL` site — silence would read as "nothing shared"), and `unreadable: <error>` (the callee's ASG JSON exists but will not load, separated from `unsizeable`, which is specifically `UnsizeableFieldError` from `layout`). A caller-side `UnsizeableFieldError` cannot reach this pass — `analysed()` skips the whole member first, and a skipped member is already reported by name — so `unsizeable` here is always the callee's.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `cobble/cobble/dataflow/fields/aliases.py` | **new.** Computes `CommareaAlias` rows for one member: call sites, both sides' extents, the shared window, dead-end reasons. |
| `cobble/cobble/dataflow/fields/side_tables.py` | gains `CommareaAlias` (the row dataclass, beside `FieldExtents`/`ReachingDefs`) and `alias_row()`. |
| `cobble/cobble/dataflow/fields/build_corpus.py` | gains the fifth sink, `ALIASES_FILE`, per-member alias records, and the alias/dead-end counts in the run summary. |
| `cobble/cobble/dataflow/fields/rows.py` | gains `flag()`, the boolean reader `returns` needs. |
| `cobble/cobble/dataflow/fields/query.py` | gains `Alias`, the alias load, `FieldStore.across`/`dead_ends`, the `crossing()` walk, `Limits`, the crossing report, and the two CLI flags. |
| `cobble/tests/dataflow/fields/test_fields_aliases.py` | **new.** Row-level unit tests for `aliases.py` against hand-built ASG dicts. |
| `cobble/tests/dataflow/fields/test_fields_crossing.py` | **new.** Store- and walk-level tests from hand-built rows: rebase, direction, narrowing, cycles, dead-end stops, default-unchanged. |
| `cobble/tests/dataflow/fields/test_fields_synthetic.py` | gains a two-program end-to-end module: real COBOL, real parse, real artefact, real crossing query. |

---

## Task 1: `aliases.py` — the fifth artefact's rows

**Files:**
- Create: `cobble/cobble/dataflow/fields/aliases.py`
- Modify: `cobble/cobble/dataflow/fields/side_tables.py` (append `CommareaAlias` and `alias_row`)
- Test: `cobble/tests/dataflow/fields/test_fields_aliases.py` (create)

**Interfaces:**
- Consumes: `srccfg.link.call_sites(cfg) -> tuple[CallSite, ...]` and `CallSite(caller, node, transfer, program, resolved, commarea)`; `srccfg.link.COMMAREA_RECORD`; `srccfg.build.build_program(asg) -> Cfg`; `srccfg.desugar.LINK_TRANSFER`/`XCTL_TRANSFER`/`CALL_TRANSFER`; `dataflow.layout.section_records(origin, roots) -> tuple[Record, ...]` and `UnsizeableFieldError`; `fields.extent.cell_index(records) -> CellIndex` with `.cells_named(name, qualifiers, arity)` and `.extent_of(cell) -> FieldExtent`; `fields.extent_text.extent_text(extent) -> str`; `cobol_memory.field_extent.FieldExtent(region, start, length, precision, field_name)`; `cobol_memory.region_id.RegionId`; `dataflow.depgraph.cics_cache.cached_asg_dialect_parsers_registered()`.
- Produces:
  - `side_tables.CommareaAlias(caller: str, node: str, transfer: str, callee: str = "", caller_extent: str = "", callee_extent: str = "", returns: bool = False, reason: str = "")`
  - `side_tables.alias_row(alias: CommareaAlias) -> _Row`
  - `aliases.commarea_aliases(asg, index: CellIndex, asg_dir: Path) -> tuple[CommareaAlias, ...]`
  - reason constants `NOT_IN_CACHE`, `DYNAMIC_TARGET`, `NO_COMMAREA_OPERAND`, `CALLEE_HAS_NO_COMMAREA`, `UNSIZEABLE`, `UNREADABLE`, `CALLER_FIELD_UNKNOWN`, `CALL_USING`

- [ ] **Step 1: Write the failing test for the happy path and the shared window**

Create `cobble/tests/dataflow/fields/test_fields_aliases.py`:

```python
"""Commarea alias rows: the shared window, its direction, and its dead ends."""

import json
from pathlib import Path

from cobble.dataflow.fields.aliases import (
    CALLEE_HAS_NO_COMMAREA,
    CALL_USING,
    DYNAMIC_TARGET,
    NOT_IN_CACHE,
    NO_COMMAREA_OPERAND,
    commarea_aliases,
)
from cobble.dataflow.fields.side_tables import alias_row
from conftest import field, index_of, program_of


def _link(program: str, area: str) -> dict:
    return {
        "type": "EXEC_CICS",
        "verb": "LINK",
        "options": {
            "PROGRAM": {"text": f"'{program}'", "is_literal": True},
            "COMMAREA": {"text": area, "is_literal": False},
        },
    }


def _caller(area_children: tuple[dict, ...], statement: dict) -> dict:
    return program_of(
        [statement],
        data_fields=[{**field(1, "WS-AREA"), "children": list(area_children)}],
    )


def _callee_json(directory: Path, program: str, size: int) -> None:
    asg = program_of([], linkage_fields=[field(1, "DFHCOMMAREA", pic=f"X({size})")])
    asg["program_id"] = program
    (directory / f"{program}.json").write_text(json.dumps(asg), encoding="utf-8")


def _rows(asg, asg_dir: Path):
    return commarea_aliases(asg, index_of(asg), asg_dir)


def test_link_shares_the_whole_area_when_both_sides_agree(tmp_path):
    _callee_json(tmp_path, "XPROGB", 12)
    asg = _caller(
        (field(5, "WS-KEY", pic="X(4)"), field(5, "WS-REST", pic="X(8)")),
        _link("XPROGB", "WS-AREA"),
    )

    (row,) = _rows(asg, tmp_path)

    assert row.callee == "XPROGB"
    assert row.caller_extent == "WS-AREA@working_storage[0:12]"
    assert row.callee_extent == "DFHCOMMAREA@linkage[0:12]"
    assert row.returns is True
    assert row.reason == ""


def test_the_window_narrows_to_the_shorter_side(tmp_path):
    _callee_json(tmp_path, "XPROGB", 8)
    asg = _caller(
        (field(5, "WS-KEY", pic="X(4)"), field(5, "WS-REST", pic="X(8)")),
        _link("XPROGB", "WS-AREA"),
    )

    (row,) = _rows(asg, tmp_path)

    assert row.caller_extent == "WS-AREA@working_storage[0:8]"
    assert row.callee_extent == "DFHCOMMAREA@linkage[0:8]"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_aliases.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobble.dataflow.fields.aliases'`

- [ ] **Step 3: Add the row dataclass and its serialiser to `side_tables.py`**

Append to `cobble/cobble/dataflow/fields/side_tables.py`, after `ReachingDefs`:

```python
@dataclass(frozen=True)
class CommareaAlias:
    """One call site's shared commarea window, or a named reason there is none.

    ``caller``/``node``/``transfer`` are always present, so a site that could not
    be aliased is a row a consumer can read rather than an absence it has to
    interpret. ``returns`` is false for XCTL, which never comes back.
    """

    caller: str
    node: str
    transfer: str
    callee: str = ""
    caller_extent: str = ""
    callee_extent: str = ""
    returns: bool = False
    reason: str = ""
```

and, beside `extent_row`/`defs_row`:

```python
def alias_row(alias: CommareaAlias) -> _Row:
    """One alias, keyed by the site and the caller window it shares.

    A group commarea can resolve to more than one caller cell, so the window is
    part of the key: two rows for one site are two windows, not a duplicate.
    """
    return (
        f"{alias.caller}\x00{alias.node}\x00{alias.caller_extent}",
        json.dumps(
            {
                "caller": alias.caller,
                "node": alias.node,
                "transfer": alias.transfer,
                "callee": alias.callee,
                "caller_extent": alias.caller_extent,
                "callee_extent": alias.callee_extent,
                "returns": alias.returns,
                "reason": alias.reason,
            }
        ),
    )
```

- [ ] **Step 4: Write `aliases.py`**

Create `cobble/cobble/dataflow/fields/aliases.py`:

```python
"""Commarea aliases: the bytes a caller and its callee share.

A ``LINK ... COMMAREA(WS-AREA)`` passes storage, not a copy, so caller byte
``start(WS-AREA) + k`` *is* callee byte ``k`` of ``DFHCOMMAREA``. That makes the
relation a byte-identity alias with an offset rebase rather than a flow: nothing
converts, nothing pads, and there is no distribution rule to derive.

The window is the shorter of the two declared areas. Past it the two areas are
not both addressable, and a table that claimed they were would over-claim on
roughly a third of real sites. The ``LENGTH`` option does not narrow it further:
in the measured corpus it either restates the caller's own declared length or is
a variable, and a shorter runtime length does not make the alias wrong -- the
bytes are still the same storage, bounded by the callee's own declaration, which
is already one side of the ``min``.

No fixpoint and no walk. The callee is read for its LINKAGE layout only, so the
cost is one layout per distinct callee, and a single-member run still emits that
member's outbound aliases.
"""

import json
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.extent import CellIndex, cell_index
from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.layout import UnsizeableFieldError, section_records
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.desugar import CALL_TRANSFER, LINK_TRANSFER
from cobble.dataflow.srccfg.link import COMMAREA_RECORD, CallSite, call_sites
from cobble.dataflow.fields.side_tables import CommareaAlias
from cobol_asg.asg_types import CobolASG
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

LINKAGE_ORIGIN = "LINKAGE"

NOT_IN_CACHE = "callee-not-in-cache"
DYNAMIC_TARGET = "dynamic-target"
NO_COMMAREA_OPERAND = "no-commarea-operand"
CALLEE_HAS_NO_COMMAREA = "callee-declares-no-commarea"
UNSIZEABLE = "unsizeable"
UNREADABLE = "unreadable"
CALLER_FIELD_UNKNOWN = "caller-field-unknown"
CALL_USING = "call-using-unsupported"

NO_EXTENT = FieldExtent(
    region=RegionId.LINKAGE,
    start=0,
    length=0,
    precision=Precision.EXACT,
    field_name="",
)


@dataclass(frozen=True)
class _Callee:
    """A callee's commarea window, or why there is not one to have."""

    extent: FieldExtent = NO_EXTENT
    reason: str = ""


_REFUSALS = (
    (lambda site: site.transfer == CALL_TRANSFER, CALL_USING),
    (lambda site: not site.resolved, DYNAMIC_TARGET),
    (lambda site: not site.commarea, NO_COMMAREA_OPERAND),
)


def commarea_aliases(
    asg: CobolASG, index: CellIndex, asg_dir: Path
) -> tuple[CommareaAlias, ...]:
    """Every ``LINK``/``XCTL``/``CALL`` site in ``asg``, aliased or refused.

    ``index`` is the caller's own layout, already built by the walk that calls
    this; the CFG is rebuilt here because the fixpoint returns only its flow and
    that index, and widening its result for a pass that shares none of its work
    would couple the two for no reason.
    """
    return tuple(
        row
        for site in call_sites(build_program(asg))
        for row in _site_rows(site, index, asg_dir)
    )


def _site_rows(
    site: CallSite, index: CellIndex, asg_dir: Path
) -> tuple[CommareaAlias, ...]:
    refused = _refused(site)
    if refused:
        return (_dead(site, refused),)
    callee = _callee_commarea(asg_dir, site.program)
    if callee.reason:
        return (_dead(site, callee.reason),)
    return _windows(site, index, callee.extent)


def _refused(site: CallSite) -> str:
    """The first reason this site cannot be aliased from the caller alone."""
    return next((reason for holds, reason in _REFUSALS if holds(site)), "")


def _dead(site: CallSite, reason: str) -> CommareaAlias:
    return CommareaAlias(
        caller=site.caller, node=site.node, transfer=site.transfer, reason=reason
    )


def _windows(
    site: CallSite, index: CellIndex, callee: FieldExtent
) -> tuple[CommareaAlias, ...]:
    cells = index.cells_named(site.commarea, (), 0)
    if not cells:
        return (_dead(site, CALLER_FIELD_UNKNOWN),)
    return tuple(_aliased(site, index.extent_of(cell), callee) for cell in cells)


def _aliased(
    site: CallSite, caller: FieldExtent, callee: FieldExtent
) -> CommareaAlias:
    shared = min(caller.length, callee.length)
    return CommareaAlias(
        caller=site.caller,
        node=site.node,
        transfer=site.transfer,
        callee=site.program,
        caller_extent=extent_text(replace(caller, length=shared)),
        callee_extent=extent_text(replace(callee, length=shared)),
        returns=site.transfer == LINK_TRANSFER,
    )


@cache
def _callee_commarea(asg_dir: Path, callee: str) -> _Callee:
    """The callee's ``DFHCOMMAREA`` window, memoised per cache directory.

    ``asg_dir`` is part of the key, so a run against a different parse never
    reads another one's answer.
    """
    path = asg_dir / f"{callee}.json"
    if not path.is_file():
        return _Callee(reason=NOT_IN_CACHE)
    try:
        return _linkage_commarea(_asg_at(path))
    except UnsizeableFieldError:
        return _Callee(reason=UNSIZEABLE)
    except (OSError, ValueError, KeyError) as error:
        return _Callee(reason=f"{UNREADABLE}: {error!r}")


def _asg_at(path: Path) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _linkage_commarea(asg: CobolASG) -> _Callee:
    """Only LINKAGE is laid out: no row here uses the callee's other sections."""
    index = cell_index(section_records(LINKAGE_ORIGIN, tuple(asg.linkage_fields)))
    cells = index.cells_named(COMMAREA_RECORD, (), 0)
    if not cells:
        return _Callee(reason=CALLEE_HAS_NO_COMMAREA)
    return _Callee(extent=index.extent_of(cells[0]))
```

- [ ] **Step 5: Run the two tests and make them pass**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_aliases.py -v`
Expected: PASS (2 passed)

If `cells_named` needs different arguments than `(name, (), 0)`, read `cobble/cobble/dataflow/fields/extent.py` and use the real signature — do not guess.

- [ ] **Step 6: Write the failing tests for `XCTL`, each dead-end reason, and the row wire form**

Append to `cobble/tests/dataflow/fields/test_fields_aliases.py`:

```python
def _xctl(program: str, area: str) -> dict:
    return {
        "type": "EXEC_CICS",
        "verb": "XCTL",
        "options": {
            "PROGRAM": {"text": f"'{program}'", "is_literal": True},
            "COMMAREA": {"text": area, "is_literal": False},
        },
    }


def test_xctl_never_returns_so_the_alias_is_inbound_only(tmp_path):
    _callee_json(tmp_path, "XPROGB", 12)
    asg = _caller((field(5, "WS-KEY", pic="X(12)"),), _xctl("XPROGB", "WS-AREA"))

    (row,) = _rows(asg, tmp_path)

    assert row.returns is False
    assert row.transfer == "XCTL"


def test_an_absent_callee_is_a_named_dead_end(tmp_path):
    asg = _caller((field(5, "WS-KEY", pic="X(12)"),), _link("XPROGZ", "WS-AREA"))

    (row,) = _rows(asg, tmp_path)

    assert row.reason == NOT_IN_CACHE
    assert (row.callee, row.caller_extent, row.callee_extent) == ("", "", "")


def test_a_dynamic_target_is_a_named_dead_end(tmp_path):
    statement = {
        "type": "EXEC_CICS",
        "verb": "LINK",
        "options": {
            "PROGRAM": {"text": "WS-TARGET", "is_literal": False},
            "COMMAREA": {"text": "WS-AREA", "is_literal": False},
        },
    }
    asg = _caller((field(5, "WS-KEY", pic="X(12)"),), statement)

    (row,) = _rows(asg, tmp_path)

    assert row.reason == DYNAMIC_TARGET


def test_a_callee_without_a_commarea_is_a_named_dead_end(tmp_path):
    empty = program_of([], linkage_fields=[])
    empty["program_id"] = "XPROGB"
    (tmp_path / "XPROGB.json").write_text(json.dumps(empty), encoding="utf-8")
    asg = _caller((field(5, "WS-KEY", pic="X(12)"),), _link("XPROGB", "WS-AREA"))

    (row,) = _rows(asg, tmp_path)

    assert row.reason == CALLEE_HAS_NO_COMMAREA


def test_a_link_without_a_commarea_shares_nothing(tmp_path):
    _callee_json(tmp_path, "XPROGB", 12)
    statement = {
        "type": "EXEC_CICS",
        "verb": "LINK",
        "options": {"PROGRAM": {"text": "'XPROGB'", "is_literal": True}},
    }
    asg = _caller((field(5, "WS-KEY", pic="X(12)"),), statement)

    (row,) = _rows(asg, tmp_path)

    assert row.reason == NO_COMMAREA_OPERAND


def test_a_static_call_is_refused_rather_than_guessed(tmp_path):
    statement = {"type": "CallStatement", "name": "'XPROGB'", "using": ["WS-AREA"]}
    asg = _caller((field(5, "WS-KEY", pic="X(12)"),), statement)

    rows = _rows(asg, tmp_path)

    assert [row.reason for row in rows] == [CALL_USING]


def test_the_row_keys_on_the_site_and_the_window(tmp_path):
    _callee_json(tmp_path, "XPROGB", 12)
    asg = _caller((field(5, "WS-KEY", pic="X(12)"),), _link("XPROGB", "WS-AREA"))

    (row,) = _rows(asg, tmp_path)
    key, payload = alias_row(row)

    assert key == f"PROGA\x00{row.node}\x00WS-AREA@working_storage[0:12]"
    assert json.loads(payload)["returns"] is True
```

- [ ] **Step 7: Run them**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_aliases.py -v`
Expected: PASS (9 passed).

`test_a_static_call_is_refused_rather_than_guessed` is the risky one: if `desugar` does not produce a `CALL` transfer from that statement dict, `call_sites` yields nothing and the assertion sees `[]`. Read `cobble/cobble/dataflow/srccfg/desugar.py`'s `CallStatement` handler and use the dict shape it actually parses. If the ASG genuinely cannot express a static `CALL` (the measured corpus has zero `CallStatement`), replace this test with a direct `_refused()` unit test:

```python
def test_a_call_site_is_refused_rather_than_guessed():
    from cobble.dataflow.fields.aliases import _refused
    from cobble.dataflow.srccfg.link import CallSite

    site = CallSite(
        caller="PROGA", node="MAIN/1", transfer="CALL", program="XPROGB",
        resolved=True, commarea="WS-AREA",
    )

    assert _refused(site) == CALL_USING
```

- [ ] **Step 8: Gates**

Run: `cd cobble && make fmt && make lint && uv run --no-sync python -m pytest`
Expected: Black clean, pyright 0 errors, fp-lint clean, whole cobble suite passes.

- [ ] **Step 9: Commit**

```bash
git add cobble/cobble/dataflow/fields/aliases.py \
        cobble/cobble/dataflow/fields/side_tables.py \
        cobble/tests/dataflow/fields/test_fields_aliases.py
git commit -m "feat(cobble): compute the commarea window a caller shares with its callee"
```

---

## Task 2: emit `aliases.jsonl` from the corpus pass

**Files:**
- Modify: `cobble/cobble/dataflow/fields/build_corpus.py`
- Test: `cobble/tests/dataflow/fields/test_fields_build_corpus.py`

**Interfaces:**
- Consumes: `aliases.commarea_aliases(asg, index, asg_dir)`; `side_tables.alias_row(alias)`; `side_tables.CommareaAlias`; the existing `_Sinks`, `MemberResult`, `RunTotals`, `_analysed_member`, `_analysed_run`, `_summary`, `JsonlWriter`.
- Produces: `build_corpus.ALIASES_FILE = "aliases.jsonl"`; `MemberResult.aliases: tuple[CommareaAlias, ...]`; `RunTotals.aliased: int` and `RunTotals.dead_ends: tuple[str, ...]`; the summary keys `"aliased"` and `"alias_dead_ends"` (a `Mapping[str, int]`).

- [ ] **Step 1: Write the failing test**

Append to `cobble/tests/dataflow/fields/test_fields_build_corpus.py`:

```python
def test_the_run_emits_the_alias_table_and_counts_its_dead_ends(tmp_path, capsys):
    """A fifth table beside the four, with the coverage of it as a stated number."""
    out = tmp_path / "out"
    asg_dir = tmp_path / "asg"
    asg_dir.mkdir()
    _write_member(asg_dir, "XPROGA", _linking_member("XPROGB", "XPROGZ"))
    _write_member(asg_dir, "XPROGB", _commarea_member(12))
    config = _config(tmp_path, asg_dir, out)

    assert cli(["--config", str(config), "--all"]) == 0

    rows = [json.loads(line) for line in (out / "aliases.jsonl").read_text().splitlines()]
    assert {row["callee"] for row in rows} == {"XPROGB", ""}
    assert [row["reason"] for row in rows if row["reason"]] == ["callee-not-in-cache"]
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["aliased"] == 1
    assert summary["alias_dead_ends"] == {"callee-not-in-cache": 1}
```

Write the two helpers the test needs beside it, following the module's existing fixture helpers — read the file first and reuse `_write_member`/`_config` if they already exist under those or other names:

```python
def _linking_member(present: str, absent: str) -> dict:
    return program_of(
        [
            {
                "type": "EXEC_CICS",
                "verb": "LINK",
                "options": {
                    "PROGRAM": {"text": f"'{target}'", "is_literal": True},
                    "COMMAREA": {"text": "WS-AREA", "is_literal": False},
                },
            }
            for target in (present, absent)
        ],
        data_fields=[
            {**field(1, "WS-AREA"), "children": [field(5, "WS-KEY", pic="X(12)")]}
        ],
    )


def _commarea_member(size: int) -> dict:
    return program_of([], linkage_fields=[field(1, "DFHCOMMAREA", pic=f"X({size})")])
```

`program_of` hardcodes `program_id` as `PROGA`; set it per member inside `_write_member` (`asg["program_id"] = name`) so the two members are distinguishable and the callee resolves by filename.

- [ ] **Step 2: Run it to see it fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_build_corpus.py -k alias -v`
Expected: FAIL — `FileNotFoundError` on `aliases.jsonl`.

- [ ] **Step 3: Add the constant, the sink, and the per-member records**

In `cobble/cobble/dataflow/fields/build_corpus.py`, beside the other filenames:

```python
ALIASES_FILE = "aliases.jsonl"
```

Add the field to `MemberResult` (after `defs`):

```python
    aliases: tuple[CommareaAlias, ...] = ()
```

Add the writer to `_Sinks` and route the rows in `add_result`:

```python
@dataclass(frozen=True)
class _Sinks:
    graph: JsonlWriter
    extents: JsonlWriter
    defs: JsonlWriter
    aliases: JsonlWriter

    def add_result(self, result: MemberResult) -> None:
        ...
        self.aliases.add_rows(map(alias_row, result.aliases))
```

In `_analysed_member`, compute the rows once the index exists, and pass the ASG's own directory as the callee cache:

```python
    return MemberResult(
        ...
        aliases=commarea_aliases(asg, index, path.parent),
    )
```

Open the fourth writer in `_analysed_run` alongside the existing three.

Imports to add:

```python
from cobble.dataflow.fields.aliases import commarea_aliases
from cobble.dataflow.fields.side_tables import CommareaAlias, alias_row
```

- [ ] **Step 4: Count them in the run totals**

Add to `RunTotals`:

```python
    aliased: int = 0
    dead_ends: tuple[str, ...] = ()
```

Accumulate them wherever `RunTotals` is folded over `MemberResult`s, using two small helpers so neither the fold nor the summary grows a branch:

```python
def _aliased(result: MemberResult) -> int:
    return sum(1 for alias in result.aliases if not alias.reason)


def _dead_ends(result: MemberResult) -> tuple[str, ...]:
    return tuple(alias.reason for alias in result.aliases if alias.reason)
```

Report them in `_summary`, widening its return annotation to admit the breakdown:

```python
def _summary(totals: RunTotals) -> dict[str, float | int | Mapping[str, int]]:
    return {
        ...
        "aliased": totals.aliased,
        "alias_dead_ends": _tallied(totals.dead_ends),
    }


def _tallied(reasons: Sequence[str]) -> Mapping[str, int]:
    """How many sites stopped for each reason, so the table's coverage is stated
    rather than assumed."""
    return {reason: reasons.count(reason) for reason in dict.fromkeys(reasons)}
```

An `unreadable: <error>` reason carries the error text, so it tallies as its own
key per distinct error. That is deliberate: an unreadable callee is a parse
problem whose message is the useful part.

- [ ] **Step 5: Run the test and the module's other tests**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_build_corpus.py -v`
Expected: PASS — the new test plus every existing one in the module.

- [ ] **Step 6: Document the table**

In `cobble/cobble/dataflow/fields/build_corpus.py`'s module docstring, extend the list of emitted tables with `aliases.jsonl` in one line: what a row is (a call site and the commarea window it shares, or the reason it shares none) and that a skipped member contributes none, because the layout the rows need is the layout the skip could not compute.

- [ ] **Step 7: Gates**

Run: `cd cobble && make fmt && make lint && uv run --no-sync python -m pytest`
Expected: all clean, whole suite passes.

- [ ] **Step 8: Commit**

```bash
git add cobble/cobble/dataflow/fields/build_corpus.py \
        cobble/tests/dataflow/fields/test_fields_build_corpus.py
git commit -m "feat(cobble): emit aliases.jsonl and report its coverage per run"
```

---

## Task 3: load the alias table and rebase a range across it

**Files:**
- Modify: `cobble/cobble/dataflow/fields/rows.py`
- Modify: `cobble/cobble/dataflow/fields/query.py`
- Test: `cobble/tests/dataflow/fields/test_fields_crossing.py` (create)

**Interfaces:**
- Consumes: `build_corpus.ALIASES_FILE`; `extent_text.ByteRange(program, region, start, end, name, exact, known)`, `byte_range(text, program)`, `NO_RANGE`; the existing `FieldStore`, `store_of(declared, edges, defs)`, `load(out_dir)`, `rows.read/text/number/nested/strings`.
- Produces:
  - `rows.flag(row: Row, key: str) -> bool`
  - `query.Alias(caller: str, node: str, transfer: str, callee: str, caller_range: ByteRange, callee_range: ByteRange, returns: bool, reason: str)` with `.site -> str`
  - `FieldStore.aliases: tuple[Alias, ...]`
  - `FieldStore.across(ranges: Sequence[ByteRange]) -> tuple[tuple[Alias, ByteRange], ...]`
  - `FieldStore.dead_ends(program: str) -> tuple[Alias, ...]`
  - `store_of(declared, edges, defs, aliases=())` — fourth parameter, defaulted
  - `load(out_dir)` reads `ALIASES_FILE`, missing table loading empty

- [ ] **Step 1: Write the failing tests**

Create `cobble/tests/dataflow/fields/test_fields_crossing.py`:

```python
"""Crossing a commarea: the rebase, its direction, and where it stops."""

from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fields.query import store_of


def _alias_row(
    caller="XPROGA",
    node="MAIN/2",
    transfer="LINK",
    callee="XPROGB",
    caller_extent="WS-AREA@working_storage[0:12]",
    callee_extent="DFHCOMMAREA@linkage[0:12]",
    returns=True,
    reason="",
) -> dict:
    return {
        "caller": caller,
        "node": node,
        "transfer": transfer,
        "callee": callee,
        "caller_extent": caller_extent,
        "callee_extent": callee_extent,
        "returns": returns,
        "reason": reason,
    }


def _crossed(store, text: str, program: str):
    return tuple(
        (alias.site, str(landing))
        for alias, landing in store.across((byte_range(text, program),))
    )


def test_a_caller_range_rebases_onto_the_callee_bytes():
    store = store_of((), (), (), (_alias_row(),))

    assert _crossed(store, "WS-KEY@working_storage[4:8]", "XPROGA") == (
        ("XPROGA:MAIN/2", "DFHCOMMAREA@linkage[4:8]"),
    )


def test_the_rebase_shifts_by_the_difference_of_the_two_window_starts():
    """The caller's area does not start at zero; the callee's always does."""
    store = store_of(
        (), (), (), (_alias_row(caller_extent="WS-AREA@working_storage[40:52]"),)
    )

    assert _crossed(store, "WS-KEY@working_storage[44:48]", "XPROGA") == (
        ("XPROGA:MAIN/2", "DFHCOMMAREA@linkage[4:8]"),
    )


def test_a_link_travels_back_from_the_callee():
    store = store_of((), (), (), (_alias_row(),))

    assert _crossed(store, "DFHCOMMAREA@linkage[8:12]", "XPROGB") == (
        ("XPROGA:MAIN/2", "WS-AREA@working_storage[8:12]"),
    )


def test_an_xctl_does_not_travel_back():
    store = store_of((), (), (), (_alias_row(transfer="XCTL", returns=False),))

    assert _crossed(store, "DFHCOMMAREA@linkage[8:12]", "XPROGB") == ()
    assert _crossed(store, "WS-KEY@working_storage[0:4]", "XPROGA") == (
        ("XPROGA:MAIN/2", "DFHCOMMAREA@linkage[0:4]"),
    )


def test_a_range_past_the_shared_window_does_not_cross():
    store = store_of(
        (),
        (),
        (),
        (
            _alias_row(
                caller_extent="WS-AREA@working_storage[0:8]",
                callee_extent="DFHCOMMAREA@linkage[0:8]",
            ),
        ),
    )

    assert _crossed(store, "WS-TAIL@working_storage[8:12]", "XPROGA") == ()


def test_a_range_straddling_the_window_edge_is_clipped_to_it():
    store = store_of(
        (),
        (),
        (),
        (
            _alias_row(
                caller_extent="WS-AREA@working_storage[0:8]",
                callee_extent="DFHCOMMAREA@linkage[0:8]",
            ),
        ),
    )

    assert _crossed(store, "WS-WIDE@working_storage[4:12]", "XPROGA") == (
        ("XPROGA:MAIN/2", "DFHCOMMAREA@linkage[4:8]"),
    )


def test_a_dead_end_row_never_crosses_but_is_reportable():
    store = store_of(
        (),
        (),
        (),
        (
            _alias_row(
                callee="", caller_extent="", callee_extent="",
                returns=False, reason="dynamic-target",
            ),
        ),
    )

    assert _crossed(store, "WS-KEY@working_storage[0:4]", "XPROGA") == ()
    assert [alias.reason for alias in store.dead_ends("XPROGA")] == ["dynamic-target"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_crossing.py -v`
Expected: FAIL — `store_of()` takes 3 positional arguments.

- [ ] **Step 3: Add the boolean row reader**

In `cobble/cobble/dataflow/fields/rows.py`, beside `text`/`number`:

```python
def flag(row: Row, key: str) -> bool:
    """A row's boolean. Only JSON ``true`` reads as true, so a missing or
    misspelled value is the conservative answer instead of a crash."""
    return row.get(key) is True
```

- [ ] **Step 4: Add `Alias`, the rebase, and the store's two methods**

In `cobble/cobble/dataflow/fields/query.py`:

```python
@dataclass(frozen=True)
class Alias:
    """One commarea's shared window, both sides parsed, or a named dead end.

    A dead end has an empty ``callee`` and two absent ranges: it is the reason a
    traversal stopped, which a consumer can name, rather than an edge that is
    merely missing.
    """

    caller: str
    node: str
    transfer: str
    callee: str
    caller_range: ByteRange
    callee_range: ByteRange
    returns: bool
    reason: str

    @property
    def site(self) -> str:
        return f"{self.caller}:{self.node}"
```

```python
def _rebased(one: ByteRange, window: ByteRange, onto: ByteRange) -> ByteRange:
    """``one``'s bytes as the other side of the alias addresses them.

    The two windows are the same storage, so an offset from the start of one is
    the same offset from the start of the other. Clipped to the window: past its
    end the two areas are not both addressable and nothing may be claimed.
    """
    shift = onto.start - window.start
    return ByteRange(
        program=onto.program,
        region=onto.region,
        start=max(one.start, window.start) + shift,
        end=min(one.end, window.end) + shift,
        name=onto.name,
        exact=one.exact and onto.exact,
        known=True,
    )


def _one_way(
    ranges: Sequence[ByteRange], window: ByteRange, onto: ByteRange
) -> tuple[ByteRange, ...]:
    return tuple(_rebased(one, window, onto) for one in ranges if window.overlaps(one))


def _crossings(alias: Alias, ranges: Sequence[ByteRange]) -> tuple[ByteRange, ...]:
    """Inbound always; outbound only where the transfer comes back.

    ``LINK`` returns, so its caller can observe what the callee wrote and the
    alias is symmetric. ``XCTL`` never returns, so no caller observes a
    write-back and travelling that way would invent one.
    """
    inbound = _one_way(ranges, alias.caller_range, alias.callee_range)
    if not alias.returns:
        return inbound
    return (*inbound, *_one_way(ranges, alias.callee_range, alias.caller_range))
```

`ByteRange.overlaps` already requires both `program` and `region` to match, so an
alias fires only for a range genuinely in the window's own storage and a rebased
range compares only against the far side's flows — a hop cannot leak into a third
member.

Add the field and the two methods to `FieldStore`:

```python
    aliases: tuple[Alias, ...] = ()

    def across(
        self, ranges: Sequence[ByteRange]
    ) -> tuple[tuple[Alias, ByteRange], ...]:
        """Every live alias whose window overlaps ``ranges``, with the rebase."""
        return tuple(
            (alias, landing)
            for alias in self.aliases
            if not alias.reason
            for landing in _crossings(alias, ranges)
        )

    def dead_ends(self, program: str) -> tuple[Alias, ...]:
        """``program``'s call sites that could not be aliased at all."""
        return tuple(
            alias
            for alias in self.aliases
            if alias.caller == program and alias.reason
        )
```

- [ ] **Step 5: Parse the rows and load the table**

```python
def _alias(row: Row) -> Alias:
    caller, callee = rows.text(row, "caller"), rows.text(row, "callee")
    return Alias(
        caller=caller,
        node=rows.text(row, "node"),
        transfer=rows.text(row, "transfer"),
        callee=callee,
        caller_range=byte_range(rows.text(row, "caller_extent"), caller),
        callee_range=byte_range(rows.text(row, "callee_extent"), callee),
        returns=rows.flag(row, "returns"),
        reason=rows.text(row, "reason"),
    )
```

Widen `store_of` with a defaulted fourth parameter — defaulted so every existing
caller and test keeps working and a missing table loads empty:

```python
def store_of(
    declared: Iterable[Row],
    edges: Iterable[Row],
    defs: Iterable[Row],
    aliases: Iterable[Row] = (),
) -> FieldStore:
    ...
        aliases=tuple(_alias(row) for row in aliases),
```

and read it in `load`:

```python
        rows.read(out_dir / ALIASES_FILE),
```

importing `ALIASES_FILE` beside the other filenames.

- [ ] **Step 6: Run the tests**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_crossing.py tests/dataflow/fields/test_fields_query.py -v`
Expected: PASS — all seven new tests plus every existing query test unchanged.

- [ ] **Step 7: Gates**

Run: `cd cobble && make fmt && make lint && uv run --no-sync python -m pytest`
Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add cobble/cobble/dataflow/fields/rows.py \
        cobble/cobble/dataflow/fields/query.py \
        cobble/tests/dataflow/fields/test_fields_crossing.py
git commit -m "feat(cobble): rebase a byte range across a commarea in the query store"
```

---

## Task 4: the crossing walk and its CLI

**Files:**
- Modify: `cobble/cobble/dataflow/fields/query.py`
- Test: `cobble/tests/dataflow/fields/test_fields_crossing.py`

**Interfaces:**
- Consumes: from Task 3, `Alias`, `FieldStore.across`, `FieldStore.dead_ends`, `store_of(..., aliases)`; the existing `Side`, `Field`, `Flow`, `FieldStore.touching`, `MAX_DEPTH`, `_end`, `_far_end`, `_far_id`, `_program_of`, `_ANSWERS`, `_answer`, `_report`, `_parsed`, `cli`.
- Produces:
  - `query.DEFAULT_HOPS = 3`
  - `query.Limits(depth: int = MAX_DEPTH, hops: int = 0)`
  - `query.Landing(field_id: str, depth: int, hops: int, via: str)`
  - `query.Crossing(landings: tuple[Landing, ...], stops: tuple[str, ...])`
  - `query.crossing(store: FieldStore, start: Sequence[ByteRange], side: Side, depth: int, hops: int) -> Crossing`
  - every `_ANSWERS` arm takes `(store, field, limits: Limits)` instead of `(store, field, depth: int)`
  - CLI flags `--across-calls` (store_true) and `--max-hops N` (default `DEFAULT_HOPS`)

- [ ] **Step 1: Write the failing walk tests**

Append to `cobble/tests/dataflow/fields/test_fields_crossing.py`:

```python
from cobble.dataflow.fields.query import Side, crossing

from test_fields_query import _declared, _edge, _range  # row-building helpers


def _two_program_store(*aliases: dict):
    declared = (
        _declared("WS-AREA", 1, (_range("WS-AREA", 0, 12),), program="XPROGA"),
        _declared("WS-SINK", 1, (_range("WS-SINK", 16, 20),), program="XPROGA"),
        _declared("DFHCOMMAREA", 1, (_range("DFHCOMMAREA", 0, 12),), program="XPROGB"),
        _declared("SUB-REC", 1, (_range("SUB-REC", 0, 12),), program="XPROGB"),
    )
    edges = (
        _edge(
            "XPROGB.DFHCOMMAREA", "XPROGB.SUB-REC", "SUB/1",
            "DFHCOMMAREA@linkage[0:12]", "SUB-REC@working_storage[0:12]",
            program="XPROGB",
        ),
    )
    return store_of(declared, edges, (), aliases or (_alias_row(),))


def _landings(found):
    return tuple((one.hops, one.field_id, one.via) for one in found.landings)


def test_a_crossing_walk_continues_into_the_callee():
    store = _two_program_store()
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    assert (1, "XPROGB.DFHCOMMAREA", "XPROGA:MAIN/2") in _landings(found)
    assert (1, "XPROGB.SUB-REC", "XPROGA:MAIN/2") in _landings(found)


def test_without_a_hop_budget_the_walk_never_leaves_the_caller():
    store = _two_program_store()
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=0)

    assert _landings(found) == ()
    assert "hop limit 0" in found.stops


def test_the_hop_limit_is_a_named_stop():
    store = _two_program_store()
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=1)

    assert max(one.hops for one in found.landings) == 1
    assert "hop limit 1" in found.stops


def test_a_cycle_stops_as_a_cycle_not_as_a_hop_limit():
    """XPROGA links XPROGB links XPROGA: the walk must terminate and say why."""
    back = _alias_row(
        caller="XPROGB",
        node="SUB/9",
        callee="XPROGA",
        caller_extent="SUB-REC@working_storage[0:12]",
        callee_extent="DFHCOMMAREA@linkage[0:12]",
    )
    store = _two_program_store(_alias_row(), back)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=6)

    assert any(stop.startswith("cycle at ") for stop in found.stops)
    assert "hop limit 6" not in found.stops


def test_a_dead_end_in_a_program_the_walk_entered_is_a_named_stop():
    blocked = _alias_row(
        caller="XPROGB", node="SUB/7", callee="", caller_extent="",
        callee_extent="", returns=False, reason="callee-not-in-cache",
    )
    store = _two_program_store(_alias_row(), blocked)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    assert "callee-not-in-cache at XPROGB" in found.stops
```

`_declared`, `_edge` and `_range` live in `cobble/tests/dataflow/fields/test_fields_query.py`; read their real signatures there before using them and adjust the calls to match rather than adding overloads.

- [ ] **Step 2: Run them to see them fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_crossing.py -k crossing -v`
Expected: FAIL — `ImportError: cannot import name 'crossing'`.

- [ ] **Step 3: Write the walk**

In `cobble/cobble/dataflow/fields/query.py`:

```python
DEFAULT_HOPS = 3


@dataclass(frozen=True)
class Limits:
    """How far a transitive question travels: flows, and commarea crossings.

    ``hops`` of zero is not a bound of nothing -- it selects the plain walk, so
    an answer nobody asked to cross is byte-identical to what it always was.
    """

    depth: int = MAX_DEPTH
    hops: int = 0


@dataclass(frozen=True)
class Landing:
    """One field a crossing walk reached, and what it cost to get there."""

    field_id: str
    depth: int
    hops: int
    via: str


@dataclass(frozen=True)
class Crossing:
    """What a crossing walk found, and every reason it stopped."""

    landings: tuple[Landing, ...]
    stops: tuple[str, ...]


@dataclass(frozen=True)
class _At:
    """One place the frontier stands, carrying the cost of reaching it."""

    field_id: str
    at: ByteRange
    hops: int
    via: str


@dataclass(frozen=True)
class _Cross:
    seen: tuple[tuple[str, ByteRange], ...]
    frontier: tuple[_At, ...]
    landings: tuple[Landing, ...]
    stops: tuple[str, ...]
    depth: int


def crossing(
    store: FieldStore,
    start: Sequence[ByteRange],
    side: Side,
    depth: int,
    hops: int,
) -> Crossing:
    """``reaches``, but a commarea window is a step the walk may take.

    Separate from ``reaches`` rather than a flag on it, for two reasons: the
    default answer stays byte-identical because it is still the same function,
    and what a crossing answer has to carry -- which site it went through, how
    many, and why it stopped -- is a different shape from a depth per field.
    """
    at = tuple(_At(field_id="", at=one, hops=0, via="") for one in start)
    return _crossed(
        store,
        side,
        depth,
        hops,
        _Cross(
            seen=tuple((one.field_id, one.at) for one in at),
            frontier=at,
            landings=(),
            stops=(),
            depth=0,
        ),
    )


def _crossed(
    store: FieldStore, side: Side, depth: int, hops: int, walk: _Cross
) -> Crossing:
    if not walk.frontier:
        return Crossing(landings=walk.landings, stops=_stops(walk.stops))
    if walk.depth >= depth:
        return Crossing(
            landings=walk.landings,
            stops=_stops((*walk.stops, f"depth limit {depth}")),
        )
    return _crossed(store, side, depth, hops, _stepped(store, side, hops, walk))


def _stepped(store: FieldStore, side: Side, hops: int, walk: _Cross) -> _Cross:
    """One level: every flow the frontier touches, then every alias it can cross."""
    flowed = _flow_step(store, side, walk)
    crossed = _alias_step(store, hops, walk)
    fresh = tuple(one for one in (*flowed, *crossed) if _fresh(one, walk.seen))
    return _Cross(
        seen=(*walk.seen, *((one.field_id, one.at) for one in fresh)),
        frontier=fresh,
        landings=(*walk.landings, *_named(fresh, walk.depth + 1)),
        stops=(*walk.stops, *_limits(walk, crossed, fresh, hops), *_gaps(store, walk)),
        depth=walk.depth + 1,
    )


def _flow_step(store: FieldStore, side: Side, walk: _Cross) -> tuple[_At, ...]:
    ranges = tuple(one.at for one in walk.frontier)
    return tuple(
        _stepped_from(_from(walk.frontier, _end(flow, side)), flow, side)
        for flow in store.touching(ranges, side)
        if _far_end(flow, side).known
    )


def _stepped_from(came: _At, flow: Flow, side: Side) -> _At:
    """A flow costs no hop, so the cost of standing here carries forward."""
    return _At(
        field_id=_far_id(flow, side),
        at=_far_end(flow, side),
        hops=came.hops,
        via=came.via,
    )


def _from(frontier: Sequence[_At], near: ByteRange) -> _At:
    """The frontier entry a flow's near end matched, so its cost is known."""
    return next(
        (one for one in frontier if one.at.overlaps(near)),
        _At(field_id="", at=NO_RANGE, hops=0, via=""),
    )


def _crossings_from(store: FieldStore, one: _At) -> tuple[_At, ...]:
    return tuple(
        _At(
            field_id=_qualified(landing),
            at=landing,
            hops=one.hops + 1,
            via=alias.site,
        )
        for alias, landing in store.across((one.at,))
    )


def _alias_step(store: FieldStore, hops: int, walk: _Cross) -> tuple[_At, ...]:
    affordable = tuple(one for one in walk.frontier if one.hops < hops)
    return tuple(
        landed for one in affordable for landed in _crossings_from(store, one)
    )


def _qualified(one: ByteRange) -> str:
    return f"{one.program}.{one.name}".upper()


def _fresh(one: _At, seen: Sequence[tuple[str, ByteRange]]) -> bool:
    """Not already stood on over overlapping bytes, the same rule as ``_unseen``."""
    return one.at.known and not any(
        one.field_id == other and one.at.overlaps(part) for other, part in seen
    )


def _named(fresh: Sequence[_At], depth: int) -> tuple[Landing, ...]:
    return tuple(
        Landing(field_id=one.field_id, depth=depth, hops=one.hops, via=one.via)
        for one in fresh
    )


def _limits(
    walk: _Cross, crossed: Sequence[_At], fresh: Sequence[_At], hops: int
) -> tuple[str, ...]:
    """Why some of this level's steps were not taken.

    A frontier entry already at the hop limit stopped there. A crossing dropped
    as already seen is a cycle -- a different fact from running out of budget,
    and a reader who cannot tell them apart cannot tell a bounded answer from a
    complete one.
    """
    capped = any(one.hops >= hops for one in walk.frontier)
    looped = tuple(one for one in crossed if one not in fresh)
    return (
        *((f"hop limit {hops}",) if capped else ()),
        *(f"cycle at {_program_of(one.field_id)}" for one in looped),
    )


def _programs(frontier: Sequence[_At]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(one.at.program for one in frontier if one.at.known))


def _gaps(store: FieldStore, walk: _Cross) -> tuple[str, ...]:
    """Sites in the programs this level stands in that could not be aliased.

    Provenance may continue through them and this walk cannot say whether it
    does, which is exactly what a reader needs told.
    """
    return tuple(
        f"{alias.reason} at {alias.caller}"
        for program in _programs(walk.frontier)
        for alias in store.dead_ends(program)
    )


def _stops(reasons: Sequence[str]) -> tuple[str, ...]:
    """Deduped, in the order met: one gap met at three levels is one fact."""
    return tuple(dict.fromkeys(reasons))
```

Import `NO_RANGE` from `extent_text` beside `ByteRange`/`byte_range`.

- [ ] **Step 4: Run the walk tests**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_crossing.py -v`
Expected: PASS (12 passed).

- [ ] **Step 5: Write the failing report/CLI tests**

Append to `cobble/tests/dataflow/fields/test_fields_crossing.py`:

```python
import json

from cobble.dataflow.fields.query import cli


def _artefact(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _write(out / "extents.jsonl", _two_program_store()  and ())
    return out


def _written(out, name: str, payloads) -> None:
    (out / name).write_text(
        "".join(f"{json.dumps(payload)}\n" for payload in payloads), encoding="utf-8"
    )


def test_the_default_answer_does_not_mention_crossing(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    _written(out, "extents.jsonl", _two_program_extent_rows())
    _written(out, "edges.jsonl", _two_program_edge_rows())
    _written(out, "aliases.jsonl", (_alias_row(),))

    assert cli(["reaches", "XPROGA.WS-AREA", "--out", str(out)]) == 0

    printed = capsys.readouterr().out
    assert "across calls" not in printed
    assert "XPROGB" not in printed


def test_the_flag_reports_the_hop_the_site_and_the_stop(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    _written(out, "extents.jsonl", _two_program_extent_rows())
    _written(out, "edges.jsonl", _two_program_edge_rows())
    _written(out, "aliases.jsonl", (_alias_row(),))

    assert (
        cli(
            [
                "reaches", "XPROGA.WS-AREA", "--out", str(out),
                "--across-calls", "--max-hops", "2",
            ]
        )
        == 0
    )

    printed = capsys.readouterr().out
    assert "across calls (depth 6, max 2 hops" in printed
    assert "hop 1" in printed
    assert "via XPROGA:MAIN/2" in printed
    assert "stopped:" in printed


def test_asking_to_cross_zero_hops_is_rejected(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _written(out, "extents.jsonl", _two_program_extent_rows())

    with pytest.raises(SystemExit):
        cli(
            [
                "reaches", "XPROGA.WS-AREA", "--out", str(out),
                "--across-calls", "--max-hops", "0",
            ]
        )
```

Replace `_two_program_extent_rows()` / `_two_program_edge_rows()` with the row
tuples `_two_program_store` already builds — extract them into two module-level
helpers so both the store test and the CLI test use one definition, and delete
the `_artefact`/`_write` sketch above (it is scaffolding, not a helper to keep).
Add `import pytest` at the top of the module.

- [ ] **Step 6: Run them to see them fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_crossing.py -k "default_answer or the_flag or zero_hops" -v`
Expected: FAIL — `unrecognized arguments: --across-calls`.

- [ ] **Step 7: Thread `Limits` through the answers and add the flags**

Change every `_ANSWERS` arm's third parameter from `depth: int` to `limits: Limits`,
taking `limits.depth` where it used `depth`. The arms that ignore depth ignore
`limits`. Then split the transitive report on the hop budget:

```python
def _reach_report(
    store: FieldStore, field: Field, limits: Limits, label: str, side: Side
) -> tuple[str, ...]:
    if limits.hops:
        return _crossing_report(store, field, side, limits, label)
    return _plain_reach_report(store, field, side, limits.depth, label)
```

Rename the existing body to `_plain_reach_report` unchanged — an untouched
function is what makes "byte-identical" a fact rather than a claim — and add:

```python
def _crossing_report(
    store: FieldStore, field: Field, side: Side, limits: Limits, label: str
) -> tuple[str, ...]:
    found = crossing(store, field.ranges, side, limits.depth, limits.hops)
    return (
        f"{label} across calls (depth {limits.depth}, max {limits.hops} hops, "
        f"{len(found.landings)} landings):",
        *(_landing_line(one) for one in _ordered(found.landings)),
        f"  stopped: {', '.join(found.stops) or 'frontier exhausted'}",
    )


def _landing_line(one: Landing) -> str:
    via = f"  via {one.via}" if one.via else ""
    return f"  hop {one.hops}  depth {one.depth}  {one.field_id}{via}"


def _ordered(landings: Sequence[Landing]) -> tuple[Landing, ...]:
    return tuple(sorted(landings, key=lambda one: (one.hops, one.depth, one.field_id)))
```

The `or 'frontier exhausted'` there is a string join's empty case, not a
`None` fallback — it stands.

In `_parsed`:

```python
    parser.add_argument(
        "--across-calls",
        action="store_true",
        help="let reaches/reached-by cross a commarea window into the callee",
    )
    parser.add_argument(
        "--max-hops",
        type=_hop_budget,
        default=DEFAULT_HOPS,
        metavar="N",
        help="commarea crossings allowed per path, with --across-calls",
    )
```

```python
def _hop_budget(given: str) -> int:
    """Zero hops is what the default already is, so asking for it while also
    asking to cross calls is a contradiction rather than a setting."""
    count = int(given)
    if count < 1:
        raise argparse.ArgumentTypeError(f"needs at least one hop, got {count}")
    return count


def _limits_of(arguments: argparse.Namespace) -> Limits:
    return Limits(
        depth=arguments.depth,
        hops=arguments.max_hops if arguments.across_calls else 0,
    )
```

In `cli`, pass `_limits_of(arguments)` where it passed `arguments.depth`.

- [ ] **Step 8: Run the whole crossing module and the whole query module**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_crossing.py tests/dataflow/fields/test_fields_query.py -v`
Expected: PASS — every existing query test unchanged, all new ones green.

- [ ] **Step 9: Document the flags**

In `query.py`'s module docstring, add one line: `reaches`/`reached-by` accept
`--across-calls` with `--max-hops N` (default 3), off by default because the
corpus's call graph reaches most of itself within a few hops, so an unbounded
provenance answer names half the system and tells a reader nothing.

- [ ] **Step 10: Gates**

Run: `cd cobble && make fmt && make lint && uv run --no-sync python -m pytest`
Expected: all clean. Then from the repo root: `uv run lint-imports` — expected all contracts kept.

- [ ] **Step 11: Commit**

```bash
git add cobble/cobble/dataflow/fields/query.py \
        cobble/tests/dataflow/fields/test_fields_crossing.py
git commit -m "feat(cobble): traverse a commarea with --across-calls and a hop budget"
```

---

## Task 5: two-program synthetic end to end

**Files:**
- Modify: `cobble/tests/dataflow/fields/test_fields_synthetic.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4; the module's existing `_bridge_jar()`, `FORGE`, `BRIDGE_GLOB`, and its parse-then-`cli()` pattern; `cobble.parsing.parse_corpus.Job`/`parse_one`; `build_corpus.cli`; `query.load`, `query.crossing`, `query.Side`.
- Produces: nothing other tasks consume — this is the acceptance gate.

- [ ] **Step 1: Add the two-program fixture and the failing end-to-end test**

Append to `cobble/tests/dataflow/fields/test_fields_synthetic.py`. Read the
module first: reuse its `_bridge_jar()` skip, its `Job`/`parse_one` call shape,
and its config-writing helper exactly rather than re-deriving them.

```python
CALLER = "XPROGA"
CALLEE = "XPROGB"

CALLER_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XPROGA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-OUT-KEY           PIC X(4).
           05  WS-OUT-VAL           PIC X(4).
           05  WS-IN-RESULT         PIC X(4).
       01  WS-SEED                  PIC X(4).
       01  WS-SINK                  PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'KKKK' TO WS-SEED.
           MOVE WS-SEED TO WS-OUT-KEY.
           EXEC CICS LINK PROGRAM('XPROGB')
                          COMMAREA(WS-AREA)
                          LENGTH(12)
           END-EXEC.
           MOVE WS-IN-RESULT TO WS-SINK.
           STOP RUN.
"""

CALLEE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XPROGB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  SUB-REC.
           05  SUB-KEY              PIC X(4).
           05  SUB-VAL              PIC X(4).
           05  SUB-RESULT           PIC X(4).
       LINKAGE SECTION.
       01  DFHCOMMAREA              PIC X(12).
       PROCEDURE DIVISION.
       SUB-PARA.
           MOVE DFHCOMMAREA TO SUB-REC.
           MOVE SUB-KEY TO SUB-RESULT.
           MOVE SUB-RESULT TO DFHCOMMAREA(9:4).
           EXEC CICS RETURN END-EXEC.
"""
```

The callee writes back through `DFHCOMMAREA(9:4)` rather than repacking the whole
record: a full repack lands on bytes the inbound hop already stood on, and the
walk's overlap pruning — the same rule `reaches` has always used — would drop it,
hiding the return direction behind a limitation that has nothing to do with
aliases.

```python
@pytest.fixture(scope="module")
def two_program_artefact(tmp_path_factory):
    """Parse both members for real, then build all five tables from them."""
    root = tmp_path_factory.mktemp("crossing")
    cache, out = root / "asg", root / "out"
    cache.mkdir()
    for program, source in ((CALLER, CALLER_SOURCE), (CALLEE, CALLEE_SOURCE)):
        path = root / f"{program}.cbl"
        path.write_text(source, encoding="utf-8")
        parse_one(Job(path, cache / f"{program}.json"), str(_bridge_jar()), (), ("cpy",))
    config = root / "fields.toml"
    config.write_text(
        f'[fields]\nasg_dir = "{cache}"\nout_dir = "{out}"\n', encoding="utf-8"
    )
    assert build_cli(["--config", str(config), "--all"]) == 0
    return out


def test_the_alias_row_carries_both_real_layouts(two_program_artefact):
    rows = [
        json.loads(line)
        for line in (two_program_artefact / "aliases.jsonl").read_text().splitlines()
    ]

    (row,) = [one for one in rows if one["callee"] == CALLEE]
    assert row["caller"] == CALLER
    assert row["transfer"] == "LINK"
    assert row["caller_extent"] == "WS-AREA@working_storage[0:12]"
    assert row["callee_extent"] == "DFHCOMMAREA@linkage[0:12]"
    assert row["returns"] is True


def test_a_crossing_query_reaches_the_callee_write_and_comes_back(
    two_program_artefact,
):
    """The whole point: the caller's key crosses in, the callee's write crosses
    back, and the caller's own sink sees it."""
    store = load(two_program_artefact)
    start = store.field(f"{CALLER}.WS-OUT-KEY")

    found = crossing(store, start.ranges, Side.SOURCE, depth=6, hops=2)
    landed = {one.field_id: one for one in found.landings}

    assert landed[f"{CALLEE}.SUB-REC"].hops == 1
    assert landed[f"{CALLEE}.SUB-RESULT"].hops == 1
    assert landed[f"{CALLER}.WS-SINK"].hops == 2
    assert landed[f"{CALLER}.WS-SINK"].via == landed[f"{CALLEE}.SUB-REC"].via


def test_the_callee_bytes_are_the_rebased_caller_bytes(two_program_artefact):
    """A name match would get this wrong; a byte rebase does not."""
    store = load(two_program_artefact)
    key = store.field(f"{CALLER}.WS-OUT-KEY")

    ((_alias, landing),) = store.across(key.ranges)

    assert str(landing) == "DFHCOMMAREA@linkage[0:4]"
```

Import at the top of the module what it does not already import: `json`,
`build_corpus.cli as build_cli`, and `load`, `crossing`, `Side` from
`cobble.dataflow.fields.query`.

- [ ] **Step 2: Run it**

Run: `cd cobble && uv run --no-sync python -m pytest tests/dataflow/fields/test_fields_synthetic.py -v`
Expected: PASS (all four new tests plus the module's existing ones), or SKIP with
`no bridge JAR at …; run \`make jar\`` if the JAR is absent — build it with
`make jar` at the repo root and re-run; the acceptance criterion needs a real
parse, so a skipped run is not a pass.

- [ ] **Step 3: If a landing's hop or depth is off, read before adjusting**

The expected chain is: `WS-OUT-KEY@working_storage[0:4]` crosses at hop 1 to
`DFHCOMMAREA@linkage[0:4]`; the callee's `MOVE DFHCOMMAREA TO SUB-REC` reaches
`SUB-REC@working_storage[0:12]`; `MOVE SUB-KEY TO SUB-RESULT` reaches
`SUB-RESULT@working_storage[8:12]`; `MOVE SUB-RESULT TO DFHCOMMAREA(9:4)`
reaches `DFHCOMMAREA@linkage[8:12]`; that crosses back at hop 2 to
`WS-AREA@working_storage[8:12]`; and `MOVE WS-IN-RESULT TO WS-SINK` reaches
`WS-SINK`. That is depth 5 against a default of 6.

If a landing is missing, dump the store's flows for the callee and check which
link in that chain is absent — do not raise `depth` or `hops` to make the
assertion pass. A missing link is a real gap in either the alias or the walk, and
the assertion is the thing telling you so.

- [ ] **Step 4: Full gates**

Run: `cd cobble && make fmt && make lint && uv run --no-sync python -m pytest`
Then from the repo root: `uv run lint-imports`
Expected: Black clean, pyright 0 errors, fp-lint clean, cobble suite green, 11/11 import contracts.

- [ ] **Step 5: File follow-ups and refresh the issue snapshot**

Two facts this work surfaces are worth beads, and neither is in scope here:

```bash
bd create --title="Overlap pruning drops a commarea write-back over already-walked bytes" \
  --type=bug --priority=2 \
  --description="The crossing walk inherits reaches()'s pruning rule: a landing is dropped when its field id matches a seen one and its bytes overlap. A callee that repacks its whole commarea (MOVE CALLEE-REC TO DFHCOMMAREA) lands on bytes the inbound hop already stood on, so the return direction is pruned even though it carries different content. The synthetic fixture writes back through a narrower reference-modified target to sidestep it. Fix needs the seen set to track the bytes actually claimed rather than any overlap, which changes reaches() too."
bd create --title="aliases.jsonl coverage is bounded by the parse, not by the model" \
  --type=task --priority=3 \
  --description="A third of measured LINK sites resolve to callee-not-in-cache: a literal target the parse never covered. The reason makes the gap visible, which is the point, but the table's usefulness scales with corpus coverage. Worth measuring the reason tally per corpus config after a full parse so the number is tracked rather than rediscovered."
bd export -o issues/issues.jsonl && git add issues/issues.jsonl
```

- [ ] **Step 6: Commit**

```bash
git add cobble/tests/dataflow/fields/test_fields_synthetic.py issues/issues.jsonl
git commit -m "test(cobble): cross a real commarea end to end on a two-program synthetic"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: what a commarea is and the
shared window → Task 1 (`_aliased`'s `min`, two tests); `LENGTH` never narrows →
Global Constraints plus `aliases.py`'s docstring, and no code reads the option;
LINK/XCTL direction → Task 1's `returns` and Task 3's `_crossings`; the
`aliases.jsonl` row shape and wire form → Task 1's `alias_row`; dead ends as rows
→ Task 1's eight reasons and six tests; where it is computed → Task 1's inputs,
which are exactly the three the spec names; the `%CALL:` origin unchanged → no
task touches `transfer.py`; `FieldStore` gains alias rows and one rebase method →
Task 3; `--across-calls`/`--max-hops 3` off by default → Task 4; cycles as a stop
distinct from the hop limit → Task 4's `_limits` and its test; out-of-scope
`CALL ... USING` → Task 1's `CALL_USING` refusal, not a guess; out-of-scope group
commarea handled with no special case → Task 3's rebase is name-blind, tested by
Task 5's `test_the_callee_bytes_are_the_rebased_caller_bytes`; out-of-scope
interprocedural reaching definitions → `defs.jsonl` is untouched. Every test the
spec lists has a home: two-program fixture → Task 5; differing declarations →
Task 3's shift test and Task 5's rebase test; window narrowing → Task 1 and Task
3; XCTL inbound-only → Task 1 and Task 3; each dead-end reason → Task 1; a cycle
terminates → Task 4; default unchanged → Task 4. All four acceptance criteria are
gated: the table is emitted per member (Task 2), a crossing query names the
callee statement and the site it crossed (Task 5), the default output is
byte-identical (Task 4's `_plain_reach_report` stays untouched and its test
asserts the absence), and the run reports aliased plus per-reason counts (Task
2).

**Two gaps found and closed.** The spec says "seven existing queries" — there are
eight, now named in the reconciliations. The spec's five dead-end reasons cannot
express a caller whose `COMMAREA` operand resolves to nothing, a static `CALL`, or
an unreadable callee JSON; three reasons were added rather than letting any of
those three read as "nothing shared".

**Placeholders.** None. Every code step carries the code. Three steps ask the
executor to read a real signature before using it (`cells_named`, the
`test_fields_query.py` row helpers, `test_fields_synthetic.py`'s parse pattern)
and say what to do if it differs — that is a named risk with a named resolution,
not a deferred decision. Task 1's Step 7 carries the fallback test in full for
the one case that may not be expressible in the ASG.

**Type consistency.** `CommareaAlias` is defined once (Task 1, `side_tables.py`)
and imported by `aliases.py`, `build_corpus.py`. `Alias` (Task 3, `query.py`) is
the parsed counterpart and is never confused with it: the row dataclass carries
extent *strings*, the query dataclass carries `ByteRange`s. `commarea_aliases`
keeps its `(asg, index, asg_dir)` signature in Tasks 1 and 2. `store_of` gains
one defaulted parameter in Task 3 and Task 4's tests call it with four. `Limits`
is introduced in Task 4 and is the only thing that changes the `_ANSWERS` arm
signature. `crossing(store, start, side, depth, hops)` is called with keywords in
both Task 4's and Task 5's tests, matching its definition. `Landing.field_id` is
built by `_qualified` as `f"{program}.{name}".upper()`, the same shape
`emit.field_id` produces, so Task 5's `store.field(f"{CALLER}.WS-OUT-KEY")` and
`landed[f"{CALLEE}.SUB-REC"]` agree.

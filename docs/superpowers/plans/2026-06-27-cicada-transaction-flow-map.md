# Cicada Transaction Flow Map — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a static-analysis API to Cicada that extracts a JSON transaction flow map from a CICS project — which EXEC CICS verbs fire in which programs, which BMS maps they touch, and which fields are inputs vs. outputs.

**Architecture:** A `CicsFlowObserver` protocol (+ null object) is added to `cics/flow_observer.py`. `CicsLoweringStrategy.__init__` grows an `observer` parameter that defaults to `NullCicsFlowObserver`; `lower()` calls `observer.on_verb()` after each verb's operands are resolved. A standalone `extract_transaction_flow_map()` function in `cics/flow_map.py` wires observer + `compile_cics_program()` + CSD + BMS models into the final JSON list.

**Tech Stack:** Python 3.12, existing `cics.strategy.CicsLoweringStrategy`, `cics.bootstrap.compile_cics_program`, `bms_copybook_gen.models.BmsMapSet/BmsMap/BmsField`, `cics.dispatcher.parse_csd`.

## Global Constraints

- No changes to `compile_cics_program()`, `compile_cobol()`, the linker, the resolver, or any other compile-pipeline internals beyond adding `observer=` to `CicsLoweringStrategy.__init__`.
- New files live in the `cicada` repo (not `red-dragon`): `cics/flow_observer.py`, `cics/flow_map.py`.
- Tests go in `tests/unit/cics/test_flow_observer.py` and `tests/integration/cics/test_flow_map.py`.
- `NullCicsFlowObserver` is the default at every existing `CicsLoweringStrategy` construction site — zero call-site changes required.
- No CardDemo dependency in tests — synthetic fixtures only.
- Integration tests need `PROLEAP_BRIDGE_JAR` env var. Use the `bridge_jar` fixture from `tests/integration/cobol_helpers.py` — it fails loudly if JAR is missing. Import pattern: `from tests.integration.cobol_helpers import bridge_jar  # noqa: F401 — pytest fixture`.
- `compile_cics_program(source, parser, strategy, *, ...)` — first three args are positional. Call it as `compile_cics_program(prepassed_bytes, parser, strategy)`.
- `cobol_sources` values passed to `extract_transaction_flow_map` are raw (un-prepassed) COBOL bytes. Apply `apply_cics_prepass` inside the function: `apply_cics_prepass(raw.decode("utf-8", errors="replace")).encode()`.
- `parse_csd` in `cics.dispatcher` expects a `Path` — write CSD text to a temp file internally.
- Run tests with `poetry run python -m pytest` (not `poetry run pytest`).
- Format with `poetry run python -m black .` before committing.

---

### Task 1: CicsVerb dataclass and CicsFlowObserver protocol

**Files:**
- Create: `cics/flow_observer.py`
- Test: `tests/unit/cics/test_flow_observer.py`

**Interfaces:**
- Produces:
  - `CicsVerb(verb: str, program: str, map_name: str | None, mapset_name: str | None, xctl_target: str | None, transid: str | None)` — frozen dataclass
  - `class CicsFlowObserver(Protocol)` with `on_verb(self, verb: CicsVerb) -> None`
  - `class NullCicsFlowObserver` with `on_verb(self, verb: CicsVerb) -> None` (no-op)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/cics/test_flow_observer.py
from dataclasses import FrozenInstanceError
import pytest
from cics.flow_observer import CicsVerb, NullCicsFlowObserver


def test_cics_verb_is_frozen():
    v = CicsVerb(verb="SEND_MAP", program="PROG1", map_name="MAP1",
                 mapset_name="SET1", xctl_target=None, transid=None)
    with pytest.raises((FrozenInstanceError, AttributeError)):
        v.verb = "OTHER"  # type: ignore[misc]


def test_cics_verb_optional_fields_default_none():
    v = CicsVerb(verb="XCTL", program="PROG1", map_name=None,
                 mapset_name=None, xctl_target="PROG2", transid=None)
    assert v.map_name is None
    assert v.transid is None
    assert v.xctl_target == "PROG2"


def test_null_observer_on_verb_is_noop():
    observer = NullCicsFlowObserver()
    v = CicsVerb(verb="SEND_MAP", program="PROG1", map_name="MAP1",
                 mapset_name="SET1", xctl_target=None, transid=None)
    observer.on_verb(v)  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/code/cicada
poetry run python -m pytest tests/unit/cics/test_flow_observer.py -v
```

Expected: `ModuleNotFoundError: No module named 'cics.flow_observer'`

- [ ] **Step 3: Implement `cics/flow_observer.py`**

```python
# cics/flow_observer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from bms_copybook_gen.models import BmsField


@dataclass(frozen=True)
class CicsVerb:
    verb: str
    program: str
    map_name: str | None
    mapset_name: str | None
    xctl_target: str | None
    transid: str | None


class CicsFlowObserver(Protocol):
    def on_verb(self, verb: CicsVerb) -> None: ...


class NullCicsFlowObserver:
    def on_verb(self, verb: CicsVerb) -> None:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
poetry run python -m pytest tests/unit/cics/test_flow_observer.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Format and commit**

```bash
poetry run python -m black .
git add cics/flow_observer.py tests/unit/cics/test_flow_observer.py
git commit -m "feat(flow-map): CicsVerb dataclass and CicsFlowObserver protocol"
```

---

### Task 2: Hook observer into CicsLoweringStrategy.lower()

**Files:**
- Modify: `cics/strategy.py` — `CicsLoweringStrategy.__init__` and `lower()`
- Test: `tests/unit/cics/test_flow_observer.py` (extend)

**Interfaces:**
- Consumes: `CicsVerb`, `NullCicsFlowObserver` from Task 1
- Produces: `CicsLoweringStrategy.__init__` gains `observer: CicsFlowObserver | None = None` as the last keyword-only argument. `None` → `NullCicsFlowObserver()` stored as `self._observer`. All existing call sites pass no `observer=`, so they continue to work unchanged.

The hook fires in `lower()` for exactly these five verb groups, **after** operands are resolved and **before** IR is emitted:

| verb check in `lower()` | `CicsVerb.verb` string | populated fields |
|---|---|---|
| `verb == "RETURN"` with `"TRANSID" in opts` | `"RETURN_TRANSID"` | `transid` |
| `verb == "XCTL"` | `"XCTL"` | `xctl_target` |
| `verb == "LINK"` | `"LINK"` | `xctl_target` |
| BMS branch, `verb == "SEND MAP"` | `"SEND_MAP"` | `map_name`, `mapset_name` |
| BMS branch, `verb == "RECEIVE MAP"` | `"RECEIVE_MAP"` | `map_name`, `mapset_name` |

Leave `program=""` for all observer calls — Task 4's `_CollectingObserver` wraps each event and tags the program name from the outside (it knows which program it compiled).

Add this module-level helper above `CicsLoweringStrategy` to extract operand text without emitting IR:

```python
def _operand_text(opt: "CicsOperand | None") -> str | None:
    return opt.text if opt is not None else None
```

- [ ] **Step 1: Write the failing tests**

```python
# Extend tests/unit/cics/test_flow_observer.py

from cics.strategy import CicsLoweringStrategy
from cics.flow_observer import CicsVerb


class _CapturingObserver:
    def __init__(self):
        self.captured: list[CicsVerb] = []

    def on_verb(self, verb: CicsVerb) -> None:
        self.captured.append(verb)


def _minimal_ctx():
    from interpreter.register import Register

    class _Ctx:
        def __init__(self):
            self.emitted = []
            self._n = 0
        def fresh_reg(self):
            self._n += 1
            return Register(f"%r{self._n}")
        def emit_inst(self, inst):
            self.emitted.append(inst)
        def group_leaf_names(self, group_name, materialised):
            return []
        def has_field(self, name, materialised):
            return False

    return _Ctx()


def test_send_map_notifies_observer():
    import queue
    from interpreter.cobol.cobol_statements import ExecCicsStatement, CicsOperand

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        screen_queue=queue.Queue(),
        input_queue=queue.Queue(),
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="SEND MAP",
        options={
            "MAP": CicsOperand("CACTVWA", True),
            "MAPSET": CicsOperand("COACTVW", True),
        },
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    assert len(observer.captured) == 1
    v = observer.captured[0]
    assert v.verb == "SEND_MAP"
    assert v.map_name == "CACTVWA"
    assert v.mapset_name == "COACTVW"


def test_xctl_notifies_observer():
    from interpreter.cobol.cobol_statements import ExecCicsStatement, CicsOperand

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="XCTL",
        options={"PROGRAM": CicsOperand("COSGN00C", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    assert len(observer.captured) == 1
    v = observer.captured[0]
    assert v.verb == "XCTL"
    assert v.xctl_target == "COSGN00C"


def test_return_transid_notifies_observer():
    from interpreter.cobol.cobol_statements import ExecCicsStatement, CicsOperand

    observer = _CapturingObserver()
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        observer=observer,
    )
    stmt = ExecCicsStatement(
        verb="RETURN",
        options={"TRANSID": CicsOperand("CA00", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)

    assert len(observer.captured) == 1
    v = observer.captured[0]
    assert v.verb == "RETURN_TRANSID"
    assert v.transid == "CA00"


def test_null_observer_is_default():
    from interpreter.cobol.cobol_statements import ExecCicsStatement, CicsOperand

    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
    )
    stmt = ExecCicsStatement(
        verb="XCTL",
        options={"PROGRAM": CicsOperand("COSGN00C", True)},
    )
    strategy.lower(_minimal_ctx(), stmt, materialised=None)  # must not raise
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
poetry run python -m pytest tests/unit/cics/test_flow_observer.py -v -k "observer or notifies or default"
```

Expected: `TypeError: CicsLoweringStrategy.__init__() got an unexpected keyword argument 'observer'`

- [ ] **Step 3: Modify `cics/strategy.py`**

At the top of the file, add the import:

```python
from cics.flow_observer import CicsFlowObserver, CicsVerb, NullCicsFlowObserver
```

Add the helper just above `class CicsLoweringStrategy`:

```python
def _operand_text(opt: "CicsOperand | None") -> str | None:
    return opt.text if opt is not None else None
```

Change `CicsLoweringStrategy.__init__` signature — add `observer` as the last parameter:

```python
def __init__(
    self,
    context_holder: "list[CicsContext]",
    result_holder: list | None = None,
    program_cache: dict | None = None,
    td_queue: list[str] | None = None,
    applid: str = "CARDDEMO",
    sysid: str = "SYS1",
    screen_queue: "ScreenChannel | None" = None,
    input_queue: "InputChannel | None" = None,
    vsam_engine: object = None,
    receive_timeout: float = 30.0,
    conversational: bool = False,
    observer: "CicsFlowObserver | None" = None,
) -> None:
    ...
    # Add at the end of __init__, after all existing body:
    self._observer: CicsFlowObserver = observer if observer is not None else NullCicsFlowObserver()
```

In `lower()`, add observer calls at the five hook sites. Place each call immediately **before** the `return` statement in its branch:

```python
# ── RETURN with TRANSID branch (inside `if verb == "RETURN": if "TRANSID" in opts:`) ──
# Add before `ctx.emit_inst(Return_())`:
self._observer.on_verb(CicsVerb(
    verb="RETURN_TRANSID",
    program="",
    map_name=None,
    mapset_name=None,
    xctl_target=None,
    transid=_operand_text(opts.get("TRANSID")),
))

# ── XCTL branch (inside `if verb == "XCTL":`) ──
# Add before `ctx.emit_inst(Return_())`:
self._observer.on_verb(CicsVerb(
    verb="XCTL",
    program="",
    map_name=None,
    mapset_name=None,
    xctl_target=_operand_text(opts.get("PROGRAM")),
    transid=None,
))

# ── BMS branch (inside `if bms_builtin:`, after `map_op = opts.get(...)`) ──
# Add after resolving map_op/mapset_op, before the SEND TEXT / RECEIVE MAP / SEND MAP blocks:
map_op_text = _operand_text(opts.get("MAP", opts.get("MAPNAME")))
mapset_op_text = _operand_text(opts.get("MAPSET"))
if verb == "SEND MAP":
    self._observer.on_verb(CicsVerb(
        verb="SEND_MAP",
        program="",
        map_name=map_op_text,
        mapset_name=mapset_op_text,
        xctl_target=None,
        transid=None,
    ))
elif verb == "RECEIVE MAP":
    self._observer.on_verb(CicsVerb(
        verb="RECEIVE_MAP",
        program="",
        map_name=map_op_text,
        mapset_name=mapset_op_text,
        xctl_target=None,
        transid=None,
    ))

# ── LINK branch (inside `if verb == "LINK":`) ──
# Add before `emit_resp_writeback(...)`:
self._observer.on_verb(CicsVerb(
    verb="LINK",
    program="",
    map_name=None,
    mapset_name=None,
    xctl_target=_operand_text(opts.get("PROGRAM")),
    transid=None,
))
```

- [ ] **Step 4: Run all observer tests**

```bash
poetry run python -m pytest tests/unit/cics/test_flow_observer.py -v
```

Expected: all 7 tests pass (3 from Task 1 + 4 new).

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
poetry run python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: same pass count as before.

- [ ] **Step 6: Format and commit**

```bash
poetry run python -m black .
git add cics/strategy.py cics/flow_observer.py tests/unit/cics/test_flow_observer.py
git commit -m "feat(flow-map): hook CicsFlowObserver into CicsLoweringStrategy.lower()"
```

---

### Task 3: Field direction classification from BmsField

**Files:**
- Modify: `cics/flow_observer.py` — add `field_direction(field: BmsField) -> str`
- Test: `tests/unit/cics/test_flow_observer.py` (extend)

**Interfaces:**
- Consumes: `BmsField` from `bms_copybook_gen.models` (has `attrb: list[str]`)
- Produces: `field_direction(field: BmsField) -> str` — returns `"input"` or `"output"`

Rule: if `"PROT"` or `"ASKIP"` is in `field.attrb` (case-insensitive) → `"output"`. Otherwise → `"input"`. Default for no `ATTRB` is UNPROT (input).

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/unit/cics/test_flow_observer.py

from bms_copybook_gen.models import BmsField
from cics.flow_observer import field_direction


def test_unprot_field_is_input():
    f = BmsField(label="ACCTSID", length=11, attrb=["UNPROT"])
    assert field_direction(f) == "input"


def test_prot_field_is_output():
    f = BmsField(label="ACCTNAME", length=50, attrb=["PROT", "BRT"])
    assert field_direction(f) == "output"


def test_askip_field_is_output():
    f = BmsField(label="HDNG", length=40, attrb=["ASKIP"])
    assert field_direction(f) == "output"


def test_no_attrb_defaults_to_input():
    f = BmsField(label="INPUTFLD", length=10, attrb=[])
    assert field_direction(f) == "input"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run python -m pytest tests/unit/cics/test_flow_observer.py -v -k "direction"
```

Expected: `ImportError: cannot import name 'field_direction' from 'cics.flow_observer'`

- [ ] **Step 3: Add `field_direction` to `cics/flow_observer.py`**

Add these lines to `cics/flow_observer.py` (add the real import, not the TYPE_CHECKING one):

```python
from bms_copybook_gen.models import BmsField


def field_direction(field: BmsField) -> str:
    """Return "input" for unprotected fields, "output" for protected/auto-skip."""
    protected = {"PROT", "ASKIP"}
    if any(a.upper() in protected for a in field.attrb):
        return "output"
    return "input"
```

Also remove `BmsField` from the `TYPE_CHECKING` block since it's now a real import.

- [ ] **Step 4: Run tests to verify they pass**

```bash
poetry run python -m pytest tests/unit/cics/test_flow_observer.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 5: Format and commit**

```bash
poetry run python -m black .
git add cics/flow_observer.py tests/unit/cics/test_flow_observer.py
git commit -m "feat(flow-map): field_direction classifier for BMS ATTRB"
```

---

### Task 4: extract_transaction_flow_map() — builder API

**Files:**
- Create: `cics/flow_map.py`
- Test: `tests/integration/cics/test_flow_map.py`

**Interfaces:**
- Consumes:
  - `CicsVerb`, `field_direction` from `cics.flow_observer` (Tasks 1, 3)
  - `CicsLoweringStrategy` with `observer=` from `cics.strategy` (Task 2)
  - `compile_cics_program(source, parser, strategy, *, ...)` from `cics.bootstrap`
  - `parse_csd(path: Path) -> dict[str, str]` from `cics.dispatcher`
  - `apply_cics_prepass(text: str) -> str` from `cics.preprocessor`
  - `BmsMapSet` from `bms_copybook_gen.models`
- Produces:
  ```python
  def extract_transaction_flow_map(
      csd_source: str,
      bms_mapsets: dict[str, BmsMapSet],
      cobol_sources: dict[str, bytes],
      *,
      parser: Any = None,
  ) -> list[dict]
  ```

Output shape per transaction:
```python
{
    "transid": "VACV",
    "entry_program": "COACTVWC",
    "flow": [
        {
            "verb": "RECEIVE_MAP",
            "program": "COACTVWC",
            "map": "CACTVWA",
            "mapset": "COACTVW",
            "xctl_target": None,
            "transid": None,
            "fields": [{"name": "ACCTSIDI", "direction": "input"}],
        },
        {
            "verb": "XCTL",
            "program": "COACTVWC",
            "map": None,
            "mapset": None,
            "xctl_target": "COSGN00C",
            "transid": None,
            "fields": [],
        },
    ],
}
```

**Program tagging:** `CicsLoweringStrategy.lower()` leaves `verb.program = ""`. Use a `_CollectingObserver(program_name)` per compilation — it tags each captured `CicsVerb` with the program name it knows.

- [ ] **Step 1: Write integration tests**

```python
# tests/integration/cics/test_flow_map.py
"""Integration tests for extract_transaction_flow_map().

Synthetic COBOL + synthetic BmsMapSet fixtures. No CardDemo dependency.
Require PROLEAP_BRIDGE_JAR (via bridge_jar fixture from cobol_helpers).
"""
from __future__ import annotations

from bms_copybook_gen.models import BmsField, BmsMap, BmsMapSet
from cics.flow_map import extract_transaction_flow_map
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401 — pytest fixture


def _make_mapset(name: str, map_name: str, fields: list[BmsField]) -> BmsMapSet:
    bms_map = BmsMap(label=map_name, fields=fields)
    return BmsMapSet(label=name, lang="COBOL", mode="INOUT", tioapfx=False, maps=[bms_map])


_CSD = "TRANSACTION ACCT GROUP(DEMO) PROGRAM(ACCTPROG)\n"

_ACCTPROG = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 DFHCOMMAREA PIC X(100).
       PROCEDURE DIVISION.
           EXEC CICS RECEIVE MAP('ACCMAP') MAPSET('ACCSET') END-EXEC.
           EXEC CICS SEND MAP('ACCMAP') MAPSET('ACCSET') END-EXEC.
           EXEC CICS RETURN TRANSID('ACCT') END-EXEC.
           STOP RUN.
"""


def test_send_receive_and_return_in_flow(bridge_jar):
    from interpreter.cobol.cobol_parser import CobolParser
    parser = CobolParser(bridge_jar)
    mapset = _make_mapset("ACCSET", "ACCMAP", [
        BmsField(label="ACCTID", length=11, attrb=["UNPROT"]),
        BmsField(label="ACCTNAME", length=50, attrb=["PROT"]),
    ])
    result = extract_transaction_flow_map(
        csd_source=_CSD,
        bms_mapsets={"ACCSET": mapset},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=parser,
    )
    assert len(result) == 1
    txn = result[0]
    assert txn["transid"] == "ACCT"
    assert txn["entry_program"] == "ACCTPROG"
    verbs = [e["verb"] for e in txn["flow"]]
    assert "RECEIVE_MAP" in verbs
    assert "SEND_MAP" in verbs
    assert "RETURN_TRANSID" in verbs


def test_field_direction_enriched_in_send_map(bridge_jar):
    from interpreter.cobol.cobol_parser import CobolParser
    parser = CobolParser(bridge_jar)
    mapset = _make_mapset("ACCSET", "ACCMAP", [
        BmsField(label="ACCTID", length=11, attrb=["UNPROT"]),
        BmsField(label="ACCTNAME", length=50, attrb=["PROT"]),
    ])
    result = extract_transaction_flow_map(
        csd_source=_CSD,
        bms_mapsets={"ACCSET": mapset},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=parser,
    )
    send_entries = [e for e in result[0]["flow"] if e["verb"] == "SEND_MAP"]
    assert len(send_entries) == 1
    fields = {f["name"]: f["direction"] for f in send_entries[0]["fields"]}
    assert fields["ACCTID"] == "input"
    assert fields["ACCTNAME"] == "output"


def test_xctl_target_populated(bridge_jar):
    from interpreter.cobol.cobol_parser import CobolParser
    parser = CobolParser(bridge_jar)
    csd = "TRANSACTION MENU GROUP(DEMO) PROGRAM(MENUPROG)\n"
    src = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MENUPROG.
       PROCEDURE DIVISION.
           EXEC CICS XCTL PROGRAM('NEXTPROG') END-EXEC.
           STOP RUN.
"""
    result = extract_transaction_flow_map(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"MENUPROG": src},
        parser=parser,
    )
    xctl_entries = [e for e in result[0]["flow"] if e["verb"] == "XCTL"]
    assert len(xctl_entries) == 1
    assert xctl_entries[0]["xctl_target"] == "NEXTPROG"


def test_return_transid_populated(bridge_jar):
    from interpreter.cobol.cobol_parser import CobolParser
    parser = CobolParser(bridge_jar)
    result = extract_transaction_flow_map(
        csd_source=_CSD,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=parser,
    )
    ret_entries = [e for e in result[0]["flow"] if e["verb"] == "RETURN_TRANSID"]
    assert len(ret_entries) == 1
    assert ret_entries[0].get("transid") == "ACCT"


_CSD_MULTI = (
    "TRANSACTION ACCT GROUP(DEMO) PROGRAM(MAINPROG)\n"
    "TRANSACTION MENU GROUP(DEMO) PROGRAM(MENUPROG)\n"
)

_MAINPROG = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPROG.
       PROCEDURE DIVISION.
           EXEC CICS SEND MAP('MAP1') MAPSET('SET1') END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""

_MENUPROG = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MENUPROG.
       PROCEDURE DIVISION.
           EXEC CICS SEND MAP('MAP2') MAPSET('SET2') END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""


def test_multiple_transactions_produce_separate_entries(bridge_jar):
    from interpreter.cobol.cobol_parser import CobolParser
    parser = CobolParser(bridge_jar)
    result = extract_transaction_flow_map(
        csd_source=_CSD_MULTI,
        bms_mapsets={},
        cobol_sources={"MAINPROG": _MAINPROG, "MENUPROG": _MENUPROG},
        parser=parser,
    )
    transids = {r["transid"] for r in result}
    assert "ACCT" in transids
    assert "MENU" in transids


def test_no_mapset_yields_empty_fields(bridge_jar):
    """SEND MAP referencing a mapset not in bms_mapsets → fields: []."""
    from interpreter.cobol.cobol_parser import CobolParser
    parser = CobolParser(bridge_jar)
    result = extract_transaction_flow_map(
        csd_source=_CSD,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=parser,
    )
    send_entries = [e for e in result[0]["flow"] if e["verb"] == "SEND_MAP"]
    for entry in send_entries:
        assert entry["fields"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run python -m pytest tests/integration/cics/test_flow_map.py -v
```

Expected: `ModuleNotFoundError: No module named 'cics.flow_map'`

- [ ] **Step 3: Implement `cics/flow_map.py`**

```python
# cics/flow_map.py
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from bms_copybook_gen.models import BmsMapSet
from cics.flow_observer import CicsVerb, field_direction


class _CollectingObserver:
    """Accumulates CicsVerb events for one program compilation, tagging program name."""

    def __init__(self, program_name: str) -> None:
        self._program_name = program_name
        self.verbs: list[CicsVerb] = []

    def on_verb(self, verb: CicsVerb) -> None:
        # Strategy leaves verb.program = ""; tag it here with the known program name.
        self.verbs.append(
            CicsVerb(
                verb=verb.verb,
                program=self._program_name,
                map_name=verb.map_name,
                mapset_name=verb.mapset_name,
                xctl_target=verb.xctl_target,
                transid=verb.transid,
            )
        )


def _enrich_verb(verb: CicsVerb, bms_mapsets: dict[str, BmsMapSet]) -> dict:
    """Convert CicsVerb → JSON-serialisable dict with BMS field metadata."""
    entry: dict[str, Any] = {
        "verb": verb.verb,
        "program": verb.program,
        "map": verb.map_name,
        "mapset": verb.mapset_name,
        "xctl_target": verb.xctl_target,
        "transid": verb.transid,
        "fields": [],
    }
    if verb.mapset_name and verb.map_name and verb.verb in ("SEND_MAP", "RECEIVE_MAP"):
        mapset = bms_mapsets.get(verb.mapset_name)
        if mapset:
            bms_map = next((m for m in mapset.maps if m.label == verb.map_name), None)
            if bms_map:
                entry["fields"] = [
                    {"name": f.label, "direction": field_direction(f)}
                    for f in bms_map.fields
                ]
    return entry


def extract_transaction_flow_map(
    csd_source: str,
    bms_mapsets: dict[str, BmsMapSet],
    cobol_sources: dict[str, bytes],
    *,
    parser: Any = None,
) -> list[dict]:
    """Static analysis: extract a JSON transaction flow map from a CICS project.

    Args:
        csd_source: CSD text with TRANSACTION ... PROGRAM ... entries.
        bms_mapsets: parsed BmsMapSet models keyed by mapset name.
        cobol_sources: program name → raw (un-prepassed) COBOL bytes.
        parser: ProLeap parser instance (built on first use if None).

    Returns:
        List of dicts, one per transaction, in CSD order.
    """
    from cics.dispatcher import parse_csd  # noqa: PLC0415
    from cics.bootstrap import compile_cics_program  # noqa: PLC0415
    from cics.strategy import CicsLoweringStrategy  # noqa: PLC0415
    from cics.preprocessor import apply_cics_prepass  # noqa: PLC0415

    # parse_csd expects a Path; write CSD text to a temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csd", delete=False) as f:
        f.write(csd_source)
        csd_path = Path(f.name)
    transid_to_program = parse_csd(csd_path)
    csd_path.unlink(missing_ok=True)

    # Compile each distinct program with its own observer
    compiled_verbs: dict[str, list[CicsVerb]] = {}
    for prog_name in transid_to_program.values():
        if prog_name in compiled_verbs:
            continue
        raw = cobol_sources.get(prog_name)
        if raw is None:
            compiled_verbs[prog_name] = []
            continue
        # compile_cics_program expects pre-passed bytes; apply the prepass here
        prepassed = apply_cics_prepass(raw.decode("utf-8", errors="replace")).encode()
        observer = _CollectingObserver(prog_name)
        strategy = CicsLoweringStrategy(
            context_holder=[None],
            result_holder=[None],
            observer=observer,
        )
        # Positional args: source, parser, strategy
        compile_cics_program(prepassed, parser, strategy)
        compiled_verbs[prog_name] = observer.verbs

    results: list[dict] = []
    for transid, prog_name in transid_to_program.items():
        verbs = compiled_verbs.get(prog_name, [])
        results.append({
            "transid": transid,
            "entry_program": prog_name,
            "flow": [_enrich_verb(v, bms_mapsets) for v in verbs],
        })
    return results
```

- [ ] **Step 4: Run integration tests**

```bash
poetry run python -m pytest tests/integration/cics/test_flow_map.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Run full test suite**

```bash
poetry run python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: no regressions.

- [ ] **Step 6: Format and commit**

```bash
poetry run python -m black .
git add cics/flow_map.py tests/integration/cics/test_flow_map.py
git commit -m "feat(flow-map): extract_transaction_flow_map() builder API"
```

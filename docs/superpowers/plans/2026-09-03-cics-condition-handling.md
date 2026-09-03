# CICS Condition Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `EXEC CICS` conditions real — a failing command raises, a registered `HANDLE CONDITION` transfers control to its paragraph, and an unhandled condition abends instead of letting the program run on with stale data.

**Architecture:** The handler table is a COBOL table in injected WORKING-STORAGE, so `HANDLE`/`IGNORE` lower to ordinary writes and the mapping is visible in the IR. Each fallible command gets a two-instruction tail branching to one per-program dispatcher block, which reads the slot for the raised condition and runs a cascade of two-way branches to the handler paragraph — the shape `GO TO … DEPENDING ON` is already lowered to, so no VM change is needed.

**Tech Stack:** Python 3.13, pytest, the red-dragon interpreter IR (`BranchIf`, `Branch`, `Label_`, `Binop`, `CallFunction`), ProLeap COBOL bridge (JAR-gated integration tests), EBCDIC cp037.

**Spec:** `docs/superpowers/specs/2026-09-03-cics-condition-handling-design.md`

**Beads:** forge-5by (raising), red-dragon-pz9g.12 (dispatch)

## Global Constraints

- **No `None` in signatures.** `.python-fp-lint/rules/` forbids `is None`, `is not None`, and `None` default parameters in owned code. Model absence as `()`, `b""`, `""`, or `0`. Adjudicated exception: `emit_copy_in` and `resolve_field_ref` are pre-existing and return `X | None`; matching `strategy.py`'s existing `is None` idiom for THEIR results is accepted.
- **Black, line length 88** (`cd cicada && make fmt`).
- **Comments are a smell.** A comment must carry an external constraint, a non-obvious "why", or a reference to a standard — never narrate the code.
- **Tests assert concrete decoded values.** The project's `no-weak-assert` rule forbids existence, containment and truthiness assertions; booleans use `is True` / `is False`. Assert what a handler paragraph *wrote*, never that a branch was taken.
- **`cicada` must not import `squall` or `jackal`.** Verify with `uv run lint-imports`.
- **No edits to red-dragon's core engine** (`interpreter/vm/**`, `ir.py`, `run.py`, `executor.py`, `cfg.py`). Every CICS behaviour reaches the VM through `CallFunction` IR to registered builtins. This design needs no VM change; if you conclude it does, stop and report rather than editing `vendor/`.
- **EBCDIC is cp037.**
- **The blocking fp-lint hook excludes `cicada/cics/` and all test trees**, so a "Skipped" there proves nothing. For real signal run `uv run --no-sync python -m python_fp_lint check <file>` directly.
- **Tests run from `cicada/`** via `make test`, which sets `PROLEAP_BRIDGE_JAR`. Running `pytest` directly without it produces ~73 errors that are not your bug.
- **Baseline: 413 cicada tests pass** before this plan starts.
- **No commit may leave the suite red, so no task may end red.** The pre-commit hook
  runs the full cicada suite including the CardDemo e2e set, and `--no-verify` is
  forbidden. Where a task below says to commit with failures and let a later task
  clean up, that instruction is void: either mark the not-yet-satisfiable test
  `xfail(strict=True)` naming the task that retires it (`strict` makes an unexpected
  pass fail, so the marker cannot be left behind), or merge the task with the one
  that makes it green. Tasks 4 and 6 took the xfail route; Tasks 7 and 8 were merged
  for this reason.
- **Synthetic COBOL fixtures must end at or before column 72.** Fixed format reserves
  columns 73-80 and the parser's line reader discards them, so a longer line silently
  loses its `END-EXEC` and surfaces as a misleading "missing END_EXEC" ANTLR error —
  the operand count is a red herring. This cost this project a wrongly-filed P1.
- **Implementers leave work staged; the controller commits.** Report status only from
  a test run you personally observed in the foreground.

## The seams you will use

Verified against the code; use these rather than inventing new ones.

| Need | Call |
|---|---|
| resolve a field, optionally subscripted | `ctx.resolve_field_ref(name, materialised, subscripts=(node,)) -> (ref, region_reg)` |
| read a field | `ctx.emit_decode_field(region_reg, ref.fl, ref.offset_reg) -> Register` |
| write a field | `ctx.emit_encode_and_write(region_reg, ref.fl, value_str_reg, ref.offset_reg)` |
| number → string register | `ctx.emit_to_string(reg) -> Register` |
| constant registers | `ctx.const_to_reg(value)`, `Const.int_(reg, n)`, `Const.string(reg, s)` |
| fresh label | `ctx.fresh_label("prefix") -> CodeLabel` |
| subscript expression nodes | `from cobol_asg.cobol_expression import BinOpNode, FieldRefNode, LiteralNode` |
| a paragraph's label | `CodeLabel(f"para_{name}")` — the convention `lower_goto` uses |

`emit_copy_back_str` explicitly does **not** thread subscripts ("write-back targets are plain data-names, never subscripted"), so Task 3 adds a subscripted-write helper rather than bending it.

---

## File Structure

| File | Responsibility |
|---|---|
| `cicada/cics/conditions.py` *(new)* | The one condition-name → DFHRESP-code table, the raisable set, and the abend code for an unhandled condition. |
| `cicada/cics/copybooks/DFHHANDLE.cpy` *(new)* | The injected handler and raisable tables. |
| `cicada/cics/preprocessor.py` | Injects `DFHHANDLE` alongside `DFHEIBLK`. |
| `cicada/cics/handler_labels.py` *(new)* | The pre-pass: collect a program's `HANDLE`/`IGNORE` target paragraphs, assign indices. |
| `cicada/cics/strategy.py` | `HANDLE`/`IGNORE` lowering, the raise tail, the dispatcher block. |
| `cicada/cics/builtins/system.py` | `__cics_abend_unhandled`. |
| `cicada/tests/unit/cics/test_conditions.py` *(new)* | The code table in isolation. |
| `cicada/tests/unit/cics/test_handler_labels.py` *(new)* | The pre-pass in isolation. |
| `cicada/tests/integration/cics/test_condition_handling.py` *(new)* | The scenarios, through real COBOL. |

---

### Task 1: One condition table

**Files:**
- Create: `cicada/cics/conditions.py`
- Test: `cicada/tests/unit/cics/test_conditions.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CONDITION_CODES: dict[str, int]`; `RAISABLE: frozenset[str]`; `code_for(name: str) -> int`; `is_raisable_code(code: int) -> bool`; `MAX_CODE: int`; `UNHANDLED_ABCODE: str`.

The spec records that DFHRESP codes are scattered across four modules with no source of truth (`vsam/eibresp.py`, `builtins/system.py`, `builtins/interval.py`, `builtins/screen.py`). This task creates the single table. It does **not** yet rewrite those modules to import from it — that is a mechanical follow-up and would bury this task's diff.

- [ ] **Step 1: Write the failing test**

```python
"""The one condition-name -> DFHRESP-code table."""

from __future__ import annotations

import pytest

from cics.conditions import (
    CONDITION_CODES,
    MAX_CODE,
    RAISABLE,
    code_for,
    is_raisable_code,
)


def test_codes_match_the_values_already_used_across_the_runtime():
    """These are the codes the scattered modules already encode; the table must
    agree with them or a verb's EIBRESP would stop matching its condition."""
    assert code_for("TERMIDERR") == 11
    assert code_for("NOTFND") == 13
    assert code_for("DUPREC") == 14
    assert code_for("INVREQ") == 16
    assert code_for("IOERR") == 17
    assert code_for("ENDFILE") == 20
    assert code_for("PGMIDERR") == 27
    assert code_for("TRANSIDERR") == 28
    assert code_for("ENDDATA") == 29
    assert code_for("MAPFAIL") == 36


def test_the_raisable_set_is_the_nine_the_corpus_handles():
    assert RAISABLE == frozenset(
        {
            "NOTOPEN",
            "NOTFND",
            "INVREQ",
            "ERROR",
            "LENGERR",
            "MAPFAIL",
            "NOSPACE",
            "DUPKEY",
            "DUPREC",
        }
    )


def test_normal_is_never_raisable():
    """Slot 0 is NORMAL; a success must never reach the dispatcher."""
    assert is_raisable_code(0) is False


def test_every_raisable_condition_has_a_code_and_is_raisable_by_code():
    for name in RAISABLE:
        assert is_raisable_code(code_for(name)) is True


def test_max_code_covers_every_raisable_condition():
    """The injected table is sized MAX_CODE + 1; a raisable code beyond it would
    index past the table."""
    assert MAX_CODE >= max(code_for(name) for name in RAISABLE)


def test_an_unknown_condition_name_raises():
    with pytest.raises(KeyError):
        code_for("NOSUCHCONDITION")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd cicada && uv run --no-sync python -m pytest tests/unit/cics/test_conditions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cics.conditions'`

- [ ] **Step 3: Write the implementation**

```python
"""CICS condition names and their DFHRESP codes.

The single source of truth. These codes were previously spelled as module
constants in cics/vsam/eibresp.py, cics/builtins/system.py,
cics/builtins/interval.py and cics/builtins/screen.py, partially duplicated
between them; the injected handler table, the raise tail and the unhandled
abend all index by code, so they need one table to agree on.
"""

from __future__ import annotations

CONDITION_CODES: dict[str, int] = {
    "NORMAL": 0,
    "ERROR": 1,
    "EOF": 4,
    "TERMIDERR": 11,
    "FILENOTFOUND": 12,
    "NOTFND": 13,
    "DUPREC": 14,
    "DUPKEY": 15,
    "INVREQ": 16,
    "IOERR": 17,
    "NOSPACE": 18,
    "NOTOPEN": 19,
    "ENDFILE": 20,
    "ILLOGIC": 21,
    "LENGERR": 22,
    "ITEMERR": 26,
    "PGMIDERR": 27,
    "TRANSIDERR": 28,
    "ENDDATA": 29,
    "MAPFAIL": 36,
}

# The conditions this runtime raises: the ones the production corpus codes
# HANDLE CONDITION for. Everything else keeps writing EIBRESP and nothing more,
# which is exactly as truthful as it is today.
RAISABLE: frozenset[str] = frozenset(
    {
        "NOTOPEN",
        "NOTFND",
        "INVREQ",
        "ERROR",
        "LENGERR",
        "MAPFAIL",
        "NOSPACE",
        "DUPKEY",
        "DUPREC",
    }
)

MAX_CODE: int = max(CONDITION_CODES.values())

# IBM assigns a distinct AEIx code per unhandled condition. That mapping is not
# reproduced here because it has not been sourced from documentation; one code
# naming the condition in its message beats inventing letters that read as
# authoritative. See the design doc's "__cics_abend_unhandled" section.
UNHANDLED_ABCODE = "AEIZ"

_RAISABLE_CODES: frozenset[int] = frozenset(
    CONDITION_CODES[name] for name in RAISABLE
)


def code_for(name: str) -> int:
    """The DFHRESP code for a condition name. Raises KeyError on an unknown name
    — the table is exhaustive for what this runtime produces, and a new condition
    must be added deliberately."""
    return CONDITION_CODES[name]


def is_raisable_code(code: int) -> bool:
    return code in _RAISABLE_CODES
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd cicada && uv run --no-sync python -m pytest tests/unit/cics/test_conditions.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Check the codes against the modules that already spell them**

Run: `cd cicada && grep -rn "RESP_[A-Z]* = \|_RESP_[A-Z]* = " cics/ | grep -v __pycache__`
Every code printed must match `CONDITION_CODES`. If one disagrees, the existing module is the authority for what the runtime actually produces today — fix the table, and say so in your report.

- [ ] **Step 6: Format, lint and commit**

```bash
cd cicada && make fmt
uv run --no-sync python -m python_fp_lint check cics/conditions.py
git add cicada/cics/conditions.py cicada/tests/unit/cics/test_conditions.py
git commit -m "feat(cics): one condition-name to DFHRESP-code table"
```

---

### Task 2: Inject the handler table

**Files:**
- Create: `cicada/cics/copybooks/DFHHANDLE.cpy`
- Modify: `cicada/cics/preprocessor.py`
- Test: `cicada/tests/integration/cics/test_condition_handling.py`

**Interfaces:**
- Consumes: `MAX_CODE`, `RAISABLE`, `code_for` (Task 1).
- Produces: two COBOL tables in every compiled program's WORKING-STORAGE — `DFH-RAISABLE OCCURS n TIMES PIC X` and `DFH-HANDLER OCCURS n TIMES PIC S9(4) COMP` — plus `inject_dfhhandle(source: str) -> str` in `preprocessor.py`, called by `apply_cics_prepass`.

**The `DFH-RAISABLE` literal must be generated from Task 1's table, not typed by hand.** Write a module-level constant in the copybook file by generating it once and pasting the result, and add a test that regenerates it and compares — so the copybook cannot drift from the table.

- [ ] **Step 1: Write the failing test**

```python
"""Integration: EXEC CICS condition raising and HANDLE CONDITION dispatch."""

from __future__ import annotations

# ruff: noqa: I001

import queue
import struct
from pathlib import Path

import pytest
from cics.bootstrap import compile_cics_program
from cics.conditions import MAX_CODE, RAISABLE, code_for
from cics.coprocessor import build_cics_spec
from cics.dispatcher import run_cics
from cics.types import CicsContext, DispatchKind
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature

from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

_CICS_COPYBOOKS = Path(__file__).resolve().parents[3] / "cics" / "copybooks"


@pytest.fixture(autouse=True)
def _require_bridge_jar(bridge_jar):  # noqa: F811
    """Fails loudly when PROLEAP_BRIDGE_JAR is unset."""


@pytest.fixture
def cobol_parser(bridge_jar):  # noqa: F811
    runner = RealSubprocessRunner()
    return ProLeapCobolParser(runner, bridge_jar, copybook_dirs=[_CICS_COPYBOOKS])


def test_the_raisable_literal_matches_the_condition_table():
    """The copybook's Y positions are generated from conditions.py; regenerate
    and compare so the two cannot drift."""
    from cics.preprocessor import raisable_literal

    expected = "".join(
        "Y" if code in {code_for(n) for n in RAISABLE} else "N"
        for code in range(MAX_CODE + 1)
    )
    assert raisable_literal() == expected


COBOL_READS_ITS_OWN_TABLE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDPROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-NOTFND  PIC X.
           05  WS-CA-NORMAL  PIC X.
       PROCEDURE DIVISION.
           MOVE DFH-RAISABLE(14) TO WS-CA-NOTFND.
           MOVE DFH-RAISABLE(1)  TO WS-CA-NORMAL.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_the_injected_table_is_visible_to_the_program(cobol_parser):
    """DFH-RAISABLE(14) is NOTFND (code 13, 1-based) and must be Y; slot 1 is
    NORMAL and must not be."""
    context_holder = [CicsContext(transid="HND0", commarea=b"", eibaid="\\x7d")]
    result_holder: list = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(
        COBOL_READS_ITS_OWN_TABLE.encode(), cobol_parser, spec
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )

    assert result.commarea[0:1] == "Y".encode("cp037")
    assert result.commarea[1:2] == "N".encode("cp037")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_condition_handling.py -v`
Expected: FAIL — `ImportError: cannot import name 'raisable_literal'`, and the COBOL test fails to resolve `DFH-RAISABLE`.

- [ ] **Step 3: Write the copybook**

Generate the literal first:

```bash
cd cicada && uv run --no-sync python -c "
from cics.conditions import MAX_CODE, RAISABLE, code_for
codes = {code_for(n) for n in RAISABLE}
print(''.join('Y' if c in codes else 'N' for c in range(MAX_CODE + 1)))
print('slots:', MAX_CODE + 1, 'handler bytes:', (MAX_CODE + 1) * 2)
"
```

Create `cicada/cics/copybooks/DFHHANDLE.cpy` using the printed values. `PIC X(n)` is the slot count; the handler area is twice that because `S9(4) COMP` is two bytes:

```cobol
      * Condition handler tables, indexed by DFHRESP code + 1 (COBOL OCCURS is
      * 1-based). DFH-RAISABLE marks the conditions this runtime raises; its
      * literal is generated from cics/conditions.py. DFH-HANDLER holds a label
      * index, LOW-VALUES meaning none, so WORKING-STORAGE initialisation gives
      * each program an empty table and a called program cannot inherit one.
       01  DFH-RAISABLE-BYTES PIC X(37) VALUE
           'NNNNNNNNNNNNYYYYYYNYNNYNNNNNNNNNNNNNY'.
       01  DFH-RAISABLE-TAB REDEFINES DFH-RAISABLE-BYTES.
           05  DFH-RAISABLE OCCURS 37 TIMES PIC X.
       01  DFH-HANDLER-BYTES PIC X(74) VALUE LOW-VALUES.
       01  DFH-HANDLER-TAB REDEFINES DFH-HANDLER-BYTES.
           05  DFH-HANDLER OCCURS 37 TIMES PIC S9(4) COMP.
```

**Use the generated literal, not the one above** — it is written here to show the shape and the test in Step 1 will fail if you transcribe it.

- [ ] **Step 4: Inject it**

In `cicada/cics/preprocessor.py`, next to `inject_dfheiblk`:

```python
_DFHHANDLE_COPY = "       COPY DFHHANDLE."


def raisable_literal() -> str:
    """The DFH-RAISABLE VALUE literal, generated from the condition table so the
    copybook cannot drift from it."""
    codes = {code_for(name) for name in RAISABLE}
    return "".join("Y" if c in codes else "N" for c in range(MAX_CODE + 1))


def inject_dfhhandle(source: str) -> str:
    """Insert COPY DFHHANDLE. after WORKING-STORAGE SECTION, as for DFHEIBLK."""
    lines = source.splitlines(keepends=True)
    result: list[str] = []
    injected = False
    for line in lines:
        result.append(line)
        if not injected and _is_ws_section(line):
            ending = "\\r\\n" if line.endswith("\\r\\n") else "\\n"
            result.append(_DFHHANDLE_COPY + ending)
            injected = True
    return "".join(result)
```

Import `MAX_CODE`, `RAISABLE`, `code_for` from `cics.conditions`, and call `inject_dfhhandle` from `apply_cics_prepass` after `inject_dfheiblk`.

- [ ] **Step 5: Run the tests**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_condition_handling.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite — this injects into EVERY compiled program**

Run: `cd cicada && make test`
Expected: 413 + 2 passing. A failure here means the injected area disturbed a program's storage layout; that is a real problem, not a test to update — report it.

- [ ] **Step 7: Format, lint and commit**

```bash
cd cicada && make fmt
uv run --no-sync python -m python_fp_lint check cics/preprocessor.py
git add cicada/cics/copybooks/DFHHANDLE.cpy cicada/cics/preprocessor.py cicada/tests/integration/cics/test_condition_handling.py
git commit -m "feat(cics): inject the condition handler table into WORKING-STORAGE"
```

---

### Task 3: The label pre-pass

**Files:**
- Create: `cicada/cics/handler_labels.py`
- Test: `cicada/tests/unit/cics/test_handler_labels.py`

**Interfaces:**
- Consumes: `ExecCicsStatement` (`verb: str`, `options: dict[str, CicsOperand | None]`).
- Produces: `collect_handler_labels(statements: Sequence[ExecCicsStatement]) -> dict[str, int]` — paragraph name → index, 1-based, in first-appearance order.

`HANDLE CONDITION NOTFND(PARA-X) ERROR(PARA-Y)` arrives with the condition names as option KEYS and the paragraph as the operand, so a statement's pairs are `stmt.options.items()`. `IGNORE CONDITION NOTFND` has the condition as a key with a `None` operand.

- [ ] **Step 1: Write the failing test**

```python
"""The HANDLE/IGNORE label pre-pass: paragraph name -> dispatch index."""

from __future__ import annotations

from cics.handler_labels import collect_handler_labels
from cics.cics_parser import CicsOperand
from cics.statements import ExecCicsStatement


def _operand(text: str) -> CicsOperand:
    return CicsOperand(text=text, is_literal=False)


def test_labels_are_numbered_from_one_in_first_appearance_order():
    stmts = [
        ExecCicsStatement(
            verb="HANDLE CONDITION",
            options={"NOTFND": _operand("PARA-A"), "ERROR": _operand("PARA-B")},
        ),
        ExecCicsStatement(
            verb="HANDLE CONDITION", options={"LENGERR": _operand("PARA-C")}
        ),
    ]

    assert collect_handler_labels(stmts) == {"PARA-A": 1, "PARA-B": 2, "PARA-C": 3}


def test_a_paragraph_named_twice_keeps_one_index():
    """Two conditions handled by the same paragraph share its index."""
    stmts = [
        ExecCicsStatement(
            verb="HANDLE CONDITION",
            options={"NOTFND": _operand("PARA-A"), "ERROR": _operand("PARA-A")},
        )
    ]

    assert collect_handler_labels(stmts) == {"PARA-A": 1}


def test_ignore_contributes_no_label():
    """IGNORE CONDITION cancels a handler; it names no paragraph."""
    stmts = [
        ExecCicsStatement(verb="IGNORE CONDITION", options={"NOTFND": None}),
    ]

    assert collect_handler_labels(stmts) == {}


def test_other_verbs_are_not_scanned():
    """A READ's FILE operand is not a handler label."""
    stmts = [ExecCicsStatement(verb="READ", options={"FILE": _operand("ACCTFILE")})]

    assert collect_handler_labels(stmts) == {}


def test_a_program_with_no_handlers_yields_an_empty_map():
    assert collect_handler_labels([]) == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd cicada && uv run --no-sync python -m pytest tests/unit/cics/test_handler_labels.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cics.handler_labels'`

- [ ] **Step 3: Write the implementation**

```python
"""Collect a program's HANDLE CONDITION target paragraphs and number them.

The dispatcher's cascade compares a runtime index against compile-time constants,
so every paragraph a program can transfer to needs an index before the first
fallible command is lowered — and a HANDLE CONDITION may appear textually after
that command. Hence a pre-pass rather than collection during lowering.
"""

from __future__ import annotations

from collections.abc import Sequence

from cics.statements import ExecCicsStatement

_HANDLE = "HANDLE CONDITION"


def collect_handler_labels(
    statements: Sequence[ExecCicsStatement],
) -> dict[str, int]:
    """Paragraph name -> 1-based dispatch index, in first-appearance order.

    Index 0 is reserved for "no handler", which is what LOW-VALUES gives every
    slot of the injected table.
    """
    labels: dict[str, int] = {}
    for stmt in statements:
        if stmt.verb != _HANDLE:
            continue
        for operand in stmt.options.values():
            if operand is None or operand.is_literal:
                continue
            if operand.text not in labels:
                labels = {**labels, operand.text: len(labels) + 1}
    return labels
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd cicada && uv run --no-sync python -m pytest tests/unit/cics/test_handler_labels.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Format, lint and commit**

```bash
cd cicada && make fmt
uv run --no-sync python -m python_fp_lint check cics/handler_labels.py
git add cicada/cics/handler_labels.py cicada/tests/unit/cics/test_handler_labels.py
git commit -m "feat(cics): collect and number HANDLE CONDITION target paragraphs"
```

---

### Task 4: `HANDLE` and `IGNORE` write the table

**Files:**
- Modify: `cicada/cics/strategy.py`
- Test: `cicada/tests/integration/cics/test_condition_handling.py`

**Interfaces:**
- Consumes: `code_for` (Task 1), the injected table (Task 2), `collect_handler_labels` (Task 3).
- Produces: `emit_indexed_write(ctx, name, index, value_str_reg, materialised) -> None` in `strategy.py`; `HANDLE CONDITION` and `IGNORE CONDITION` lowering that writes `DFH-HANDLER(code + 1)`.

Nothing dispatches yet — this task only makes the writes happen, and proves them by having COBOL read its own table back. That keeps the diff reviewable and means a failure here is unambiguous.

- [ ] **Step 1: Write the failing test**

Append to `test_condition_handling.py`:

```python
COBOL_HANDLE_WRITES_THE_SLOT = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDWRITE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-NOTFND  PIC S9(4) COMP.
           05  WS-CA-ERROR   PIC S9(4) COMP.
           05  WS-CA-LENGERR PIC S9(4) COMP.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) ERROR(PARA-B) END-EXEC.
           EXEC CICS HANDLE CONDITION LENGERR(PARA-A) END-EXEC.
           MOVE DFH-HANDLER(14) TO WS-CA-NOTFND.
           MOVE DFH-HANDLER(2)  TO WS-CA-ERROR.
           MOVE DFH-HANDLER(23) TO WS-CA-LENGERR.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-A.
           EXEC CICS RETURN END-EXEC.
       PARA-B.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_handle_condition_writes_the_label_index_into_its_slot(cobol_parser):
    """PARA-A is index 1 and PARA-B index 2, so NOTFND holds 1, ERROR 2, and
    LENGERR 1 again — the same paragraph keeps one index."""
    context_holder = [CicsContext(transid="HND1", commarea=b"", eibaid="\\x7d")]
    result_holder: list = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(
        COBOL_HANDLE_WRITES_THE_SLOT.encode(), cobol_parser, spec
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )

    assert result.commarea[0:2] == struct.pack(">h", 1)
    assert result.commarea[2:4] == struct.pack(">h", 2)
    assert result.commarea[4:6] == struct.pack(">h", 1)


COBOL_OVERRIDE_AND_IGNORE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDOVER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-AFTER-OVERRIDE PIC S9(4) COMP.
           05  WS-CA-AFTER-IGNORE   PIC S9(4) COMP.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) END-EXEC.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-B) END-EXEC.
           MOVE DFH-HANDLER(14) TO WS-CA-AFTER-OVERRIDE.
           EXEC CICS IGNORE CONDITION NOTFND END-EXEC.
           MOVE DFH-HANDLER(14) TO WS-CA-AFTER-IGNORE.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-A.
           EXEC CICS RETURN END-EXEC.
       PARA-B.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_later_handle_overrides_and_ignore_cancels(cobol_parser):
    """Override and cancellation are just later writes to the same slot."""
    context_holder = [CicsContext(transid="HND2", commarea=b"", eibaid="\\x7d")]
    result_holder: list = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(
        COBOL_OVERRIDE_AND_IGNORE.encode(), cobol_parser, spec
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )

    assert result.commarea[0:2] == struct.pack(">h", 2)
    assert result.commarea[2:4] == struct.pack(">h", 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_condition_handling.py -v -k "writes_the_label or overrides"`
Expected: FAIL — both slots read 0, because `HANDLE CONDITION` is still the no-op builtin.

- [ ] **Step 3: Add the subscripted-write helper**

In `strategy.py`, beside `emit_copy_back_str`:

```python
def emit_indexed_write(
    ctx: "EmitContext",
    name: str,
    index: int,
    value_str_reg: "Register",
    materialised: "MaterialisedSectionedLayout",
) -> None:
    """Write into a fixed element of a table. emit_copy_back_str deliberately
    does not thread subscripts, so the handler table needs its own path."""
    if not ctx.has_field(name, materialised):
        return
    ref, region_reg = ctx.resolve_field_ref(
        name, materialised, subscripts=(LiteralNode(str(index)),)
    )
    ctx.emit_encode_and_write(region_reg, ref.fl, value_str_reg, ref.offset_reg)
```

Import `LiteralNode` from `cobol_asg.cobol_expression`.

- [ ] **Step 4: Lower the two verbs**

The strategy needs the label map. Add `handler_labels: dict[str, int] = {}` to `CicsLoweringStrategy.__init__` (a read-only default; add the one-line comment saying it is never mutated, as `transid_to_program` carries) and store it. Populating it is Task 5's job; until then it is empty and the writes emit index 0, which the Step-1 tests will catch.

In `lower`, before the `_SYS_VERBS` lookup so the no-op registration stops being reached:

```python
        if verb in ("HANDLE CONDITION", "IGNORE CONDITION"):
            for condition, operand in opts.items():
                slot = code_for(condition) + 1
                index = (
                    self._handler_labels.get(operand.text, 0)
                    if verb == "HANDLE CONDITION" and operand is not None
                    else 0
                )
                r_idx = ctx.fresh_reg()
                ctx.emit_inst(Const.int_(r_idx, index))
                emit_indexed_write(
                    ctx, "DFH-HANDLER", slot, ctx.emit_to_string(r_idx), materialised
                )
            return
```

Remove `"HANDLE CONDITION"` and `"IGNORE CONDITION"` from `_SYS_VERBS` and delete their `make_handle_noop_builtin` registrations. Leave `HANDLE AID` exactly as it is — it is out of scope and still a no-op.

An unknown condition name will raise `KeyError` from `code_for`. That is deliberate: a condition this runtime cannot name is a gap to see, not to swallow.

- [ ] **Step 5: Run the tests**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_condition_handling.py -v`
Expected: the two new tests FAIL on index 0 (labels are not collected yet) and the Task 2 tests PASS. That is the correct intermediate state — Task 5 wires the pre-pass. Record the failure output in your report and proceed; do NOT fake the indices.

- [ ] **Step 6: Run the whole suite**

Run: `cd cicada && make test`
Expected: no NEW failures beyond the two above. Any CardDemo program using `HANDLE CONDITION` now emits writes instead of a logged no-op; nothing dispatches yet, so behaviour must be unchanged.

- [ ] **Step 7: Format, lint and commit**

```bash
cd cicada && make fmt
uv run --no-sync python -m python_fp_lint check cics/strategy.py
git add cicada/cics/strategy.py cicada/tests/integration/cics/test_condition_handling.py
git commit -m "feat(cics): HANDLE and IGNORE CONDITION write the handler table"
```

---

### Task 5: Wire the pre-pass into compilation

**Files:**
- Modify: `cicada/cics/strategy.py`, `cicada/cics/coprocessor.py`
- Test: `cicada/tests/integration/cics/test_condition_handling.py`

**Interfaces:**
- Consumes: `collect_handler_labels` (Task 3), the lowering (Task 4).
- Produces: a `CicsLoweringStrategy` whose `handler_labels` is populated from the program being compiled, so Task 4's writes carry real indices.

**Find where the strategy can see every statement before lowering begins.** `apply_cics_prepass` works on source text, which is too early — the statements are not parsed yet. Read `CicsDialectParser` in `cics/statements.py` and the `RedDragonExtensionLoweringStrategy` protocol in `vendor/red-dragon/interpreter/frontend_extension_lowering.py` to find the hook that sees the parsed statements. If the protocol has no such hook, say so and report BLOCKED rather than inventing one — that is a design gap, and the fix belongs in the spec, not in a workaround.

- [ ] **Step 1: Run the two failing tests from Task 4 and confirm they still fail on index 0**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_condition_handling.py -v -k "writes_the_label or overrides"`
Expected: FAIL, slots reading 0.

- [ ] **Step 2: Populate the labels from the parsed program**

Wire `collect_handler_labels` at the hook you found, so the strategy's `handler_labels` is set before any statement is lowered. State in your report exactly which hook you used and why.

- [ ] **Step 3: Run the tests**

Run the same command.
Expected: PASS — `NOTFND` 1, `ERROR` 2, `LENGERR` 1; override 2 then `IGNORE` 0.

- [ ] **Step 4: Run the whole suite**

Run: `cd cicada && make test`
Expected: no new failures; still nothing dispatches.

- [ ] **Step 5: Commit**

```bash
cd cicada && make fmt
git add cicada/cics/strategy.py cicada/cics/coprocessor.py cicada/tests/integration/cics/test_condition_handling.py
git commit -m "feat(cics): number a program's handler paragraphs before lowering"
```

---

### Task 6: The dispatcher and the unhandled abend

**Files:**
- Modify: `cicada/cics/strategy.py`, `cicada/cics/builtins/system.py`
- Test: `cicada/tests/integration/cics/test_condition_handling.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `make_abend_unhandled_builtin(result_holder: list) -> object` registered as `__cics_abend_unhandled`; a per-program `__cics_cond_dispatch` block.

Still nothing branches TO the dispatcher — Task 7 adds the raise tail. This task builds the target and proves it by abending on a directly-branched entry.

- [ ] **Step 1: Write the abend builtin**

In `builtins/system.py`, modelled on `make_abend_builtin`:

```python
def make_abend_unhandled_builtin(result_holder: list) -> object:
    """Abend for a raised condition with no handler registered.

    Real CICS assigns a distinct AEIx code per condition; that mapping is not
    reproduced here (see cics/conditions.py), so the message carries the resp
    code and the abcode is one value meaning "unhandled condition".
    """

    def __cics_abend_unhandled(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        resp = int(args[0].value) if args else 0
        logger.error("unhandled CICS condition, EIBRESP=%d — abending %s", resp, UNHANDLED_ABCODE)
        result_holder[0] = DispatchResult(
            kind=DispatchKind.ABEND, abcode=UNHANDLED_ABCODE
        )
        return BuiltinResult(value=resp)

    return __cics_abend_unhandled
```

Import `UNHANDLED_ABCODE` from `cics.conditions`. Register it in `strategy.py` beside the other `_register` calls.

- [ ] **Step 2: Emit the dispatcher block**

The block goes after the program's own code, so every handler paragraph label exists. Emit it from the same hook that ends lowering; if there is none, append it when the last statement is lowered and say so in your report.

```python
    def _emit_dispatcher(self, ctx, materialised) -> None:
        """One per program. Entered by a Branch, so it takes no arguments: it
        reads EIBRESP, which emit_resp_writeback has already written."""
        ctx.emit_inst(Label_(label=CodeLabel("__cics_cond_dispatch")))
        ref, region_reg = ctx.resolve_field_ref(
            "DFH-HANDLER",
            materialised,
            subscripts=(
                BinOpNode("+", FieldRefNode("EIBRESP"), LiteralNode("1")),
            ),
        )
        idx_reg = ctx.emit_decode_field(region_reg, ref.fl, ref.offset_reg)
        for name, index in self._handler_labels.items():
            k_reg = ctx.const_to_reg(index)
            cmp_reg = ctx.fresh_reg()
            ctx.emit_inst(
                Binop(
                    result_reg=cmp_reg,
                    operator=resolve_binop("=="),
                    left=Register(str(idx_reg)),
                    right=Register(str(k_reg)),
                )
            )
            match_lbl = ctx.fresh_label("cond_match")
            next_lbl = ctx.fresh_label("cond_next")
            ctx.emit_inst(
                BranchIf(cond_reg=cmp_reg, branch_targets=(match_lbl, next_lbl))
            )
            ctx.emit_inst(Label_(label=match_lbl))
            ctx.emit_inst(Branch(label=CodeLabel(f"para_{name}")))
            ctx.emit_inst(Label_(label=next_lbl))
        r_resp = ctx.emit_decode_field(*self._eibresp_ref(ctx, materialised))
        ctx.emit_inst(
            CallFunction(
                result_reg=ctx.fresh_reg(),
                func_name=FuncName("__cics_abend_unhandled"),
                args=(r_resp,),
            )
        )
        ctx.emit_inst(Return_())
```

`_eibresp_ref` is a two-line helper returning `(region_reg, ref.fl, ref.offset_reg)` for `EIBRESP` — write it beside the dispatcher. This mirrors `_lower_computed_goto` (`vendor/red-dragon/interpreter/cobol/lower_arithmetic.py:1942`); read that function before writing this one.

- [ ] **Step 3: Write the failing test**

```python
COBOL_UNHANDLED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDUNH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       PROCEDURE DIVISION.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_an_unhandled_condition_abends(cobol_parser, vsam_engine_with_acctfile):
    """A READ that misses, with no HANDLE registered and no RESP coded, abends
    rather than falling through to RETURN on an untouched record area."""
    ...
```

Build the VSAM fixture the way `tests/integration/cics/test_vsam_roundtrip.py` does — read it and copy its engine setup rather than inventing one. Assert `result.kind == DispatchKind.ABEND` and `result.abcode == "AEIZ"`.

- [ ] **Step 4: Run it — it will still fall through**

Expected: FAIL with `DispatchKind.RETURN`, because nothing branches to the dispatcher yet. This is the correct intermediate state.

- [ ] **Step 5: Commit**

```bash
cd cicada && make fmt
git add cicada/cics/strategy.py cicada/cics/builtins/system.py cicada/tests/integration/cics/test_condition_handling.py
git commit -m "feat(cics): the per-program condition dispatcher and unhandled abend"
```

---

### Task 7: The raise tail — turning it on

**Files:**
- Modify: `cicada/cics/strategy.py`
- Test: `cicada/tests/integration/cics/test_condition_handling.py`

**Interfaces:**
- Consumes: the dispatcher (Task 6).
- Produces: the two-instruction tail after `emit_resp_writeback` on qualifying commands.

**This is the task that changes behaviour.** Expect existing tests to fail; that triage is Task 8.

- [ ] **Step 1: Add the tail**

Called from `emit_resp_writeback`'s callers — NOT from inside it, because `emit_resp_writeback` is also used where no raise is wanted. Emit only when `"RESP" not in opts and "NOHANDLE" not in opts`:

```python
def emit_raise_tail(
    ctx: "EmitContext",
    opts: dict[str, "CicsOperand | None"],
    materialised: "MaterialisedSectionedLayout",
) -> None:
    """Branch to the dispatcher when the command raised a condition this runtime
    handles. RESP and NOHANDLE are the program's undertaking to check inline, so
    a command coding either does not raise (CICS)."""
    if "RESP" in opts or "NOHANDLE" in opts:
        return
    ref, region_reg = ctx.resolve_field_ref(
        "DFH-RAISABLE",
        materialised,
        subscripts=(BinOpNode("+", FieldRefNode("EIBRESP"), LiteralNode("1")),),
    )
    flag_reg = ctx.emit_decode_field(region_reg, ref.fl, ref.offset_reg)
    y_reg = ctx.const_to_reg("Y")
    cmp_reg = ctx.fresh_reg()
    ctx.emit_inst(
        Binop(
            result_reg=cmp_reg,
            operator=resolve_binop("=="),
            left=Register(str(flag_reg)),
            right=Register(str(y_reg)),
        )
    )
    cont_lbl = ctx.fresh_label("cond_continue")
    ctx.emit_inst(
        BranchIf(
            cond_reg=cmp_reg,
            branch_targets=(CodeLabel("__cics_cond_dispatch"), cont_lbl),
        )
    )
    ctx.emit_inst(Label_(label=cont_lbl))
```

Call it after each `emit_resp_writeback(...)` in `lower`. Slot 1 is `NORMAL` and is never `Y`, so the success path needs no separate zero test.

- [ ] **Step 2: Run the Task 6 test — it must now pass**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_condition_handling.py::test_an_unhandled_condition_abends -v`
Expected: PASS — `ABEND`, abcode `AEIZ`.

- [ ] **Step 3: Write the scenario this whole plan exists for**

```python
COBOL_HANDLED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDCORP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       01  WS-CA         PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-MISSING) END-EXEC.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           MOVE 'NOTTAKEN' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-MISSING.
           MOVE 'HANDLED0' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""
```

Assert `result.commarea == "HANDLED0".encode("cp037")`. The `NOTTAKEN` write is the discriminator: it proves control transferred rather than fell through, by what the handler wrote — not by a flag.

Also add: `RESP` coded suppresses the raise (assert execution continues AND `EIBRESP` holds 13); `NOHANDLE` the same; and a `HANDLE` inside an `IF` that does not execute leaves the condition unhandled.

- [ ] **Step 4: Run them**

Expected: PASS.

- [ ] **Step 5: Run the whole suite and RECORD the damage**

Run: `cd cicada && make test 2>&1 | tail -40`
Expected: **failures.** Do not fix them here. Capture the full list of failing tests and their assertions into your report — that list is Task 8's input and the most valuable artifact of this task.

- [ ] **Step 6: Commit**

```bash
cd cicada && make fmt
git add cicada/cics/strategy.py cicada/tests/integration/cics/test_condition_handling.py
git commit -m "feat(cics): raise conditions the corpus handles"
```

---

### Task 8: Triage the fallout

**Files:** whichever the failures name.

This task has no predetermined diff. Its input is Task 7's failure list; its output is a decision per failure, and the decisions are the deliverable.

- [ ] **Step 1: Classify every failure**

For each, decide which it is and say so explicitly in your report:

1. **The program was genuinely broken and the runtime was hiding it.** The test asserted on a result produced after a failing command. The abend is correct; the test's expectation was built on the old lie. Fix the test to assert the abend, and note what the program was actually doing wrong.
2. **The raising is wrong.** The condition should not have been raised — the verb produced a resp that is not really a failure, or the command should have been treated as coding `RESP`. Fix the runtime, not the test.
3. **A missing handler that the program does register elsewhere.** The pre-pass or the slot arithmetic is wrong. Fix the runtime.

- [ ] **Step 2: Fix each, smallest change first**

Category 2 and 3 are runtime bugs and take priority — they mean the feature is wrong, not just noisy.

- [ ] **Step 3: Run the whole suite**

Run: `cd cicada && make test`
Expected: PASS.

- [ ] **Step 4: Run every package**

```bash
cd ~/code/red-dragon-forge
uv run lint-imports
make test-all
```

`make test-all` needs Db2: `cd squall && make db2-up`, and if it reports `SQL30081N` see the README's Db2 section — the container needs `INSTANCE_MEMORY` capped, not just VM memory.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix(cics): triage the error paths raising made visible"
```

---

### Task 9: Close out

- [ ] **Step 1: Record it in the analysis document**

`docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md` lists step 8 as defect F. Add it to the Status section in the same form as steps 1–6: what landed, in which commits, and the findings the diagnosis did not predict. No test counts — the repo forbids them in living documentation.

- [ ] **Step 2: Close the beads**

```bash
bd close forge-5by red-dragon-pz9g.12 --reason="..."
bd export -o issues/issues.jsonl && git add issues/issues.jsonl
```

- [ ] **Step 3: File what this deliberately left**

Beads for: `HANDLE AID`; `PUSH`/`POP HANDLE`; conditions outside the nine; the `AEIx` per-condition abend mapping; and — the one that matters — **`NOTOPEN` is never raised** because `cics/vsam/eibresp.py` maps `NOT_OPEN` to `IOERR`, so the most-handled condition in the corpus registers a handler that cannot fire.

- [ ] **Step 4: Commit**

---

## Self-Review

**Spec coverage.** Every section maps to a task: the condition table → 1; injected copybook → 2; label indices → 3; `HANDLE`/`IGNORE` lowering, override, `IGNORE` → 4, 5; dispatcher and unhandled abend → 6; raise tail, `RESP`/`NOHANDLE` suppression → 7; "what this will break" → 8; out-of-scope items → 9 Step 3. `LINK` isolation is asserted in Task 8's full-suite run rather than a dedicated test — **gap noted**: add a `LINK` isolation test in Task 7 Step 3 if the suite does not already cover a `LINK`ed program registering a handler.

**Known soft spots, flagged not hidden:**
- **Task 5 may be BLOCKED by design.** The strategy may have no hook that sees every parsed statement before lowering. The task says to report rather than invent one, because that would be a spec gap. If it is blocked, the fallback is emitting the dispatcher at the end of lowering with labels collected as statements are lowered — which works only because the dispatcher is emitted last.
- **Task 6 Step 2's `_eibresp_ref`** is described rather than written out; it is two lines and its shape depends on whether `resolve_field_ref` returns the region register in the position the dispatcher needs.
- **The `AEIZ` abcode is a placeholder with a reason.** Task 9 Step 3 files a bead to source the real per-condition mapping.
- Task 2's copybook literal in this plan is illustrative and **will fail its own test if transcribed** — that is deliberate.

# WHENEVER (SQLERROR / NOT FOUND) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement DB2 `EXEC SQL WHENEVER <condition> <action>` for the `SQLERROR` and `NOT FOUND` conditions with the `CONTINUE` and `GO TO` actions — the program-controlled automatic error branching of embedded SQL (squall-3d0).

**Architecture:** WHENEVER is a *precompiler directive*, lexically scoped in source order: it changes how *subsequent* EXEC SQL statements lower. `SqlLoweringStrategy` keeps a mutable per-condition action map (textual-order updates = precompiler scoping). On a `WHENEVER` statement it updates the map and emits **no** runtime IR. After lowering any other EXEC SQL statement, for each active non-`CONTINUE` condition it builds a synthetic COBOL `IF SQLCODE <cmp> <val> GO TO <target>` (via `parse_statement(dict)`) and lowers it through `EmitContext.lower_statement` — reusing RedDragon's native IF + GO TO lowering (label resolution, scoping). No raw-IR branch emission, no coupling to RedDragon label naming, no source surgery.

**Tech Stack:** Python; squall (`squall/parser/parse.py`, `squall/strategy.py`); Lark grammar (already parses `whenever`); RedDragon vendored interpreter (`parse_statement`, `EmitContext.lower_statement`, `IfStatement`/`GotoStatement`). Tests: pytest; DB2 via `SQUALL_DB2_DSN`; ProLeap via `PROLEAP_BRIDGE_JAR`.

**Scope (this plan = slice 1):** conditions `SQLERROR` (`SQLCODE < 0`) and `NOT FOUND` (`SQLCODE = 100`); actions `CONTINUE` and `GO TO`/`GOTO`. **Out of scope:** `SQLWARNING` (needs SQLCA `SQLWARN` population — depends on squall-ud0); Pro\*COBOL-only actions (`PERFORM`/`STOP`/`DO`) which DB2's WHENEVER does not define.

**Established facts (verified before writing this plan):**
- Grammar already yields `kind == "whenever"`; the parse tree is `whenever → [WHENEVER, whenever_cond, whenever_action]`, where `whenever_cond` holds tokens `SQLERROR` / `SQLWARNING` / `NOT FOUND` and `whenever_action` holds `CONTINUE` or `GOTO`/`GO TO` + a `NAME` target. `ParsedSql` does **not** yet surface these.
- `parse_statement({"type":"IF","condition":{"not":False,"relation":{"left":{"kind":"ref","name":"SQLCODE"},"op":"<","right":{"kind":"lit","value":"0"}}},"children":[{"type":"GOTO","operands":["ERR-EXIT"]}]})` returns an `IfStatement` whose child is `GotoStatement(target="ERR-EXIT")`. (`parse_statement` lives in `interpreter.cobol.cobol_statements`.)
- `SqlLoweringStrategy.lower(self, ctx, stmt, materialised)` has `ctx` (an `EmitContext` exposing `lower_statement(stmt, materialised)`) and `materialised`.
- Today a `WHENEVER` statement is (incorrectly) lowered to a `__exec_sql` call and would hit the `_h_query` default → `backend.execute("WHENEVER …")`. This plan makes it a real directive, which also removes that latent bug.
- The only testbed program with `WHENEVER … GOTO` is `outsrv.sqb`, a stored-procedure *server* (not standalone-runnable), so the e2e uses a focused program (documented in Task 4).

---

## File Structure

- **Modify** `squall/parser/parse.py` — add `whenever_condition` / `whenever_action` / `whenever_target` to `ParsedSql`; extract them in `parse_exec_sql`.
- **Modify** `squall/strategy.py` — per-condition WHENEVER state; `lower()` treats `whenever` as a directive and emits synthetic IF/GO TO after other statements.
- **Create** `tests/unit/test_whenever.py` — parse-layer + strategy-state unit tests.
- **Create** `tests/integration/test_db2_whenever_e2e.py` — DB2 e2e: a failing statement under `WHENEVER SQLERROR GO TO` branches to the handler.

Each EXEC SQL kind is parsed once at lowering time (constant-pool design); WHENEVER is parsed the same way but consumed by the strategy rather than producing a `__exec_sql` call.

---

## Task 1: `ParsedSql` carries the WHENEVER directive

**Files:**
- Modify: `squall/parser/parse.py`
- Test: `tests/unit/test_whenever.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_whenever.py`:

```python
"""
tests/unit/test_whenever.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
EXEC SQL WHENEVER <condition> <action> — a precompiler directive that squall
surfaces on ParsedSql and the strategy applies as lexically-scoped automatic
SQLCODE branching. Slice 1: SQLERROR / NOT FOUND with CONTINUE / GO TO.
"""

from __future__ import annotations

from squall.parser.parse import parse_exec_sql


def test_parse_whenever_sqlerror_goto():
    p = parse_exec_sql("EXEC SQL WHENEVER SQLERROR GOTO ERR-EXIT END-EXEC")
    assert p.kind == "whenever"
    assert p.whenever_condition == "SQLERROR"
    assert p.whenever_action == "GOTO"
    assert p.whenever_target == "ERR-EXIT"


def test_parse_whenever_go_to_two_words():
    p = parse_exec_sql("EXEC SQL WHENEVER SQLERROR GO TO ERR-EXIT END-EXEC")
    assert p.whenever_action == "GOTO"
    assert p.whenever_target == "ERR-EXIT"


def test_parse_whenever_not_found_continue():
    p = parse_exec_sql("EXEC SQL WHENEVER NOT FOUND CONTINUE END-EXEC")
    assert p.kind == "whenever"
    assert p.whenever_condition == "NOT FOUND"
    assert p.whenever_action == "CONTINUE"
    assert p.whenever_target is None


def test_parse_non_whenever_has_no_whenever_fields():
    p = parse_exec_sql("EXEC SQL SELECT a INTO :x FROM t END-EXEC")
    assert p.whenever_condition is None
    assert p.whenever_action is None
    assert p.whenever_target is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m pytest tests/unit/test_whenever.py -q`
Expected: FAIL — `AttributeError: 'ParsedSql' object has no attribute 'whenever_condition'`.

- [ ] **Step 3: Add the fields to `ParsedSql`**

In `squall/parser/parse.py`, extend the frozen dataclass (after `include_name`):

```python
@dataclass(frozen=True)
class ParsedSql:
    kind: str                       # the grammar kind, e.g. "select_into"
    in_vars: tuple[HostVar, ...]    # input (bind) host vars, in source order
    out_vars: tuple[HostVar, ...]   # output (INTO) host vars, in order
    cursor: str | None              # cursor name for cursor statements, else None
    query: str                      # cleaned SQL for the DB
    include_name: str | None = None # INCLUDE target name, e.g. "SQLCA", else None
    # WHENEVER directive (kind == "whenever"); None for every other kind.
    whenever_condition: str | None = None  # "SQLERROR" / "NOT FOUND" / "SQLWARNING"
    whenever_action: str | None = None      # "CONTINUE" / "GOTO"
    whenever_target: str | None = None      # GO TO label, else None
```

- [ ] **Step 4: Extract the WHENEVER fields in `parse_exec_sql`**

In `squall/parser/parse.py`, add these helpers near `_cursor_name`:

```python
def _whenever_fields(
    stmt: Tree, kind: str
) -> tuple[str | None, str | None, str | None]:
    """Return (condition, action, target) for a WHENEVER directive, else Nones."""
    if kind != "whenever":
        return None, None, None
    cond_node = next(
        (c for c in stmt.children if isinstance(c, Tree) and c.data == "whenever_cond"),
        None,
    )
    action_node = next(
        (c for c in stmt.children if isinstance(c, Tree) and c.data == "whenever_action"),
        None,
    )
    condition = _whenever_condition(cond_node) if cond_node is not None else None
    action, target = (
        _whenever_action(action_node) if action_node is not None else (None, None)
    )
    return condition, action, target


def _whenever_condition(node: Tree) -> str:
    """Normalise the condition tokens to 'SQLERROR' / 'NOT FOUND' / 'SQLWARNING'."""
    tokens = [str(c) for c in node.children if isinstance(c, Token)]
    return " ".join(tokens).upper()


def _whenever_action(node: Tree) -> tuple[str, str | None]:
    """Return ('CONTINUE', None) or ('GOTO', <target>) for the action subtree."""
    tokens = [c for c in node.children if isinstance(c, Token)]
    if tokens and str(tokens[0]).upper() == "CONTINUE":
        return "CONTINUE", None
    # GOTO <name> or GO TO <name>: the target is the trailing NAME token.
    target = str(tokens[-1]) if tokens else None
    return "GOTO", target
```

Then in `parse_exec_sql`, compute and pass them through:

```python
    cursor = _cursor_name(stmt, kind)
    query = _build_query(inner, stmt, kind)
    inc_name = _include_name(stmt, kind)
    wh_cond, wh_action, wh_target = _whenever_fields(stmt, kind)

    return ParsedSql(
        kind=kind,
        in_vars=in_vars,
        out_vars=out_vars,
        cursor=cursor,
        query=query,
        include_name=inc_name,
        whenever_condition=wh_cond,
        whenever_action=wh_action,
        whenever_target=wh_target,
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_whenever.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add squall/parser/parse.py tests/unit/test_whenever.py
git commit -m "feat(sql): surface WHENEVER condition/action/target on ParsedSql"
```

---

## Task 2: Strategy applies WHENEVER as lexically-scoped automatic branching

**Files:**
- Modify: `squall/strategy.py`
- Test: `tests/unit/test_whenever.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_whenever.py`:

```python
import importlib.util
import os
from pathlib import Path

import pytest

from interpreter.instructions import BranchIf

_HELPERS = Path(__file__).parent.parent / "integration" / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
compile_cobol = _helpers.compile_cobol


class _NullBackend:
    """A backend whose execute always fails (SQLCODE -1) — enough to compile."""

    def execute(self, sql, params):
        from squall.backend import SqlResult

        return SqlResult(rows=(), rowcount=0, sqlcode=-1)

    def open_cursor(self, name, sql, params):  # pragma: no cover - unused here
        pass

    def fetch(self, name):  # pragma: no cover - unused here
        from squall.backend import SqlResult

        return SqlResult(rows=(), rowcount=0, sqlcode=100)

    def close(self, name):  # pragma: no cover - unused here
        pass

    def commit(self):  # pragma: no cover - unused here
        pass

    def rollback(self):  # pragma: no cover - unused here
        pass


_PROGRAM_GOTO = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. WHENT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01 WS-ID PIC 9(4) VALUE 1.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GO TO ERR-PARA END-EXEC
           EXEC SQL SELECT 1 INTO :WS-ID FROM SYSIBM.SYSDUMMY1 END-EXEC
           STOP RUN.
       ERR-PARA.
           STOP RUN.
"""


def test_whenever_goto_emits_conditional_branch(bridge_jar=None):
    """A SELECT under an active WHENEVER SQLERROR GO TO lowers a BranchIf
    (the synthetic IF SQLCODE < 0 GO TO ERR-PARA) into the IR."""
    jar = os.environ["PROLEAP_BRIDGE_JAR"]
    _frontend, linked = compile_cobol(_PROGRAM_GOTO, jar, _NullBackend(), copybook_dirs=[])
    assert any(isinstance(i, BranchIf) for i in linked.merged_ir), (
        "expected a conditional branch from the synthetic WHENEVER IF/GO TO"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PROLEAP_BRIDGE_JAR=$PROLEAP_BRIDGE_JAR uv run python -m pytest tests/unit/test_whenever.py::test_whenever_goto_emits_conditional_branch -q`
Expected: FAIL — no `BranchIf` in the IR (WHENEVER is currently lowered to a `__exec_sql` call with no branch).

- [ ] **Step 3: Add WHENEVER state to the strategy**

In `squall/strategy.py`, in `SqlLoweringStrategy.__init__`, after `self._field_meta = field_meta`:

```python
        # WHENEVER directive state: condition -> (action, target). Updated in
        # textual order as `lower` sees each WHENEVER statement (precompiler
        # scoping); absent condition == CONTINUE (no automatic branch).
        self._whenever: dict[str, tuple[str, str | None]] = {}
```

- [ ] **Step 4: Make `lower` consume WHENEVER and emit the synthetic check**

In `squall/strategy.py`, replace the body of `lower` (which currently always parses + emits a `__exec_sql` call) with:

```python
    def lower(self, ctx, stmt, materialised) -> None:
        """Lower one ``ExecSqlStatement``.

        WHENEVER is a compile-time directive: it updates per-condition state and
        emits no runtime IR. Every other kind lowers to a ``__exec_sql`` call,
        followed by the synthetic ``IF SQLCODE <cmp> <val> GO TO <target>`` for
        each active (non-CONTINUE) condition.
        """
        from interpreter.func_name import FuncName  # noqa: PLC0415
        from interpreter.instructions import CallFunction, Const  # noqa: PLC0415

        from squall.parser.parse import parse_exec_sql  # noqa: PLC0415

        plan = parse_exec_sql(stmt.text)

        if plan.kind == "whenever":
            if plan.whenever_action == "CONTINUE":
                self._whenever.pop(plan.whenever_condition, None)
            else:  # GOTO
                self._whenever[plan.whenever_condition] = (
                    plan.whenever_action,
                    plan.whenever_target,
                )
            return  # directive — no plan-pool entry, no IR

        # Carry only the plan's pool index through the IR (a primitive).
        plan_index = len(self._plans)
        self._plans.append(plan)
        index_reg = ctx.fresh_reg()
        ctx.emit_inst(Const(result_reg=index_reg, value=plan_index))
        result_reg = ctx.fresh_reg()
        ctx.emit_inst(
            CallFunction(
                result_reg=result_reg,
                func_name=FuncName(_BUILTIN_NAME),
                args=(index_reg,),
            )
        )

        self._emit_whenever_checks(ctx, materialised)

    def _emit_whenever_checks(self, ctx, materialised) -> None:
        """Emit `IF SQLCODE <cmp> <val> GO TO target` for each active condition."""
        from interpreter.cobol.cobol_statements import parse_statement  # noqa: PLC0415

        for condition, (_action, target) in self._whenever.items():
            relation = _WHENEVER_RELATION.get(condition)
            if relation is None:
                continue  # SQLWARNING (and custom conditions) deferred — slice 3
            op, value = relation
            if_stmt = parse_statement(
                {
                    "type": "IF",
                    "condition": {
                        "not": False,
                        "relation": {
                            "left": {"kind": "ref", "name": "SQLCODE"},
                            "op": op,
                            "right": {"kind": "lit", "value": value},
                        },
                    },
                    "children": [{"type": "GOTO", "operands": [target]}],
                }
            )
            ctx.lower_statement(if_stmt, materialised)
```

Add the relation table near the top of `squall/strategy.py` (after `_BUILTIN_NAME = "__exec_sql"`):

```python
# WHENEVER condition -> (COBOL comparison op, literal) for the synthetic check.
# SQLWARNING is omitted: it needs SQLCA SQLWARN populated (squall-ud0).
_WHENEVER_RELATION = {
    "SQLERROR": ("<", "0"),
    "NOT FOUND": ("=", "100"),
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `PROLEAP_BRIDGE_JAR=$PROLEAP_BRIDGE_JAR uv run python -m pytest tests/unit/test_whenever.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Run the full unit suite (regression: strategy/cursor/select still lower)**

Run: `uv run python -m pytest tests/unit/ -q`
Expected: PASS (no regressions; WHENEVER statements no longer produce a `__exec_sql` call).

- [ ] **Step 7: Commit**

```bash
git add squall/strategy.py tests/unit/test_whenever.py
git commit -m "feat(sql): WHENEVER SQLERROR/NOT FOUND auto-branch via synthetic IF/GO TO"
```

---

## Task 3: DB2 end-to-end — WHENEVER SQLERROR GO TO takes the error path

**Files:**
- Create: `tests/integration/test_db2_whenever_e2e.py`

(The only testbed `WHENEVER … GOTO` program, `outsrv.sqb`, is a non-standalone stored-procedure server, so this e2e uses a focused program that deterministically triggers `SQLERROR`.)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_db2_whenever_e2e.py`:

```python
"""
tests/integration/test_db2_whenever_e2e.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
EXEC SQL WHENEVER SQLERROR GO TO against REAL Db2. A SELECT from a non-existent
table fails (SQLCODE < 0); the active WHENEVER must branch to the handler, which
sets a flag we read back. (No standalone testbed program exercises WHENEVER GOTO
— outsrv.sqb is a stored-procedure server — so this uses a focused program.)
Requires PROLEAP_BRIDGE_JAR and a live Db2 via SQUALL_DB2_DSN (no skip, fail loud).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_HERE = Path(__file__).parent
_HELPERS = _HERE / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
run_cobol = _helpers.run_cobol
read_ws_field = _helpers.read_ws_field
bridge_jar = _helpers.bridge_jar  # noqa: F401  (re-exported pytest fixture)

from squall.backends.db2 import Db2Backend

_DB2_INCLUDES = _HERE / "db2_includes"

_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. WHENE2E.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01 WS-FLAG PIC X VALUE "N".
       01 WS-VAL  PIC S9(4) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GO TO ERR-PARA END-EXEC
           EXEC SQL SELECT 1 INTO :WS-VAL FROM NO_SUCH_TABLE_XYZ END-EXEC
           MOVE "T" TO WS-FLAG.
           STOP RUN.
       ERR-PARA.
           MOVE "E" TO WS-FLAG.
           STOP RUN.
"""


def test_whenever_sqlerror_branches_to_handler(bridge_jar):
    import ibm_db

    conn = ibm_db.connect(os.environ["SQUALL_DB2_DSN"], "", "")
    try:
        vm = run_cobol(
            _PROGRAM,
            bridge_jar,
            Db2Backend(conn),
            copybook_dirs=[_DB2_INCLUDES],
            max_steps=4000,
        )
        # The SELECT failed (-204); WHENEVER branched to ERR-PARA (flag 'E').
        # Without the branch, control would fall through to 'T'.
        assert read_ws_field(vm, "WS-FLAG") == "E"
    finally:
        ibm_db.close(conn)
```

- [ ] **Step 2: Run it to verify it fails (before Tasks 1–2 are merged) / passes (after)**

Run: `SQUALL_DB2_DSN=… PROLEAP_BRIDGE_JAR=… uv run python -m pytest tests/integration/test_db2_whenever_e2e.py -q`
Expected after Tasks 1–2: PASS (`WS-FLAG == "E"`). If run against `main` before the strategy change, it FAILS (`"T"` or a crash from WHENEVER-as-query), confirming the test drives the feature.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_db2_whenever_e2e.py
git commit -m "test(sql): DB2 e2e — WHENEVER SQLERROR GO TO takes the error path"
```

---

## Task 4: Full-suite regression + format

**Files:** none (verification only)

- [ ] **Step 1: Format**

Run: `uv run python -m black squall/ tests/`

- [ ] **Step 2: Full suite**

Run: `SQUALL_DB2_DSN=… PROLEAP_BRIDGE_JAR=… uv run python -m pytest tests/ -q`
Expected: PASS (all green, including the new WHENEVER unit + e2e tests).

- [ ] **Step 3: python_fp_lint + pyright on changed modules**

Run: `uv run python -m python_fp_lint check squall/parser/parse.py squall/strategy.py`
Run: `uv run pyright squall/parser/parse.py squall/strategy.py`
Expected: no NEW violations (the `_whenever_action` `GOTO`/`CONTINUE` branches use distinct names; `lower` keeps single-assignment).

- [ ] **Step 4: Close the bead**

```bash
bd update squall-3d0 --claim
# ... after merge:
bd close squall-3d0 --reason "Slice 1 shipped: WHENEVER SQLERROR/NOT FOUND with CONTINUE/GO TO via synthetic IF/GO TO lowered through ctx.lower_statement. SQLWARNING split out (needs SQLWARN population / squall-ud0)."
```

---

## Notes for the implementer

- **Lexical scoping is automatic:** `lower()` is called for EXEC SQL statements in textual order, so updating `self._whenever` on each WHENEVER and reading it for each subsequent statement *is* the precompiler's source-order scoping. No execution-order reasoning needed.
- **Why synthetic ASG, not raw IR:** building `IF SQLCODE … GO TO target` as a dict and lowering it via `ctx.lower_statement` reuses RedDragon's GO TO label resolution and condition lowering. Emitting a raw `BranchIf` to a hand-named label would couple squall to RedDragon's `para_`/`section_` naming (the exact footgun behind the PERFORM-THRU bug).
- **`SQLCODE` resolves natively:** the synthetic IF references `SQLCODE`, a field provided by the `INCLUDE SQLCA` copybook in `data_layout`; the `__exec_sql` call wrote it immediately before, so the check reads the just-written value.
- **Multiple active conditions:** if both `SQLERROR GO TO err` and `NOT FOUND GO TO eof` are active, both checks are emitted after each statement (they test mutually-exclusive `SQLCODE` values, so order is irrelevant).
- **Do not** add `SQLWARNING`, `PERFORM`, or `STOP` here — `SQLWARNING` needs SQLCA `SQLWARN` population (squall-ud0); `PERFORM`/`STOP` are not DB2 WHENEVER actions.

# RedDragon EXEC SQL Extension Seam — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace RedDragon's single hardwired `exec_cics_strategy` hook with an **array of injectable, dialect-agnostic extension-lowering strategies**, and add `EXEC SQL` as a routed statement kind — the prerequisite seam the standalone `squall` runtime (Plan 2) plugs into.

**Architecture:** One generic `RedDragonExtensionLoweringStrategy` protocol with a `handles(stmt)` discriminator. `CobolFrontend` takes `extension_strategies: Sequence[...]` (empty = no extension processing). `preprocess_program_dict` and `on_procedure_entry` run for every strategy in order; `lower(stmt)` routes to the first strategy whose `handles(stmt)` is true. Dispatch no longer hardcodes any EXEC type — **CICS and SQL both flow through the array**. CICS migrates onto it in lockstep (cicada's `CicsLoweringStrategy` gains `handles()`; its bootstrap passes `extension_strategies=[…]`). The bridge gains `serializeExecSql` (ProLeap already tags EXEC SQL and populates `execSqlText`).

**Tech Stack:** Python 3 (RedDragon `interpreter/cobol/`, cicada `cics/`), Java (ProLeap bridge), Maven (JAR), pytest.

**Repos (two, in lockstep):**
- **`~/code/red-dragon`** — the seam (Tasks 1–5, 7). Commit/push here.
- **`~/code/cicada`** — migrate CICS onto the array (Task 6), gated on RedDragon landing + submodule bump.

squall later pins the resulting RedDragon commit (Plan 2). Cross-repo ordering: land + push RedDragon (1–5, 7) → bump cicada's `vendor/red-dragon` → migrate cicada (6) → regression both (8).

**Scope:** Plan 1 of 2 for EXEC SQL slice 1 — the seam only (an un-handled SQL statement is a logged "unhandled statement" no-op). Plan 2 (the squall runtime: parser, binding engine, `SqlBackend`, `SqliteBackend`, builtins, `SqlLoweringStrategy`) follows once this lands. See `../design/2026-06-13-exec-sql-support-design.md`.

---

## File Structure

| File | Repo-relative path | Change |
|---|---|---|
| Statement node + dispatch table | `red-dragon: interpreter/cobol/cobol_statements.py` | add `ExecSqlStatement`, union member, `_DISPATCH_TABLE` entry |
| Generic strategy protocol | `red-dragon: interpreter/cobol/red_dragon_extension_strategy.py` | **create** (`RedDragonExtensionLoweringStrategy`, `@runtime_checkable`, 4 methods) |
| Emit context | `red-dragon: interpreter/cobol/emit_context.py` | replace `exec_cics_strategy` with `extension_strategies` seq + property |
| Statement dispatch | `red-dragon: interpreter/cobol/statement_dispatch.py` | remove CICS branch; route EXEC statements via the array + `handles()` |
| Procedure entry | `red-dragon: interpreter/cobol/lower_procedure.py` | iterate `extension_strategies` for `on_procedure_entry` |
| Frontend wiring | `red-dragon: interpreter/cobol/cobol_frontend.py` | replace `exec_cics_strategy` param with `extension_strategies`; chain preprocess |
| Bridge serializer | `red-dragon: proleap-bridge/.../StatementSerializer.java` | add `serializeExecSql` + dispatch |
| RedDragon tests | `red-dragon: tests/unit/test_exec_sql_seam.py`, `tests/integration/test_exec_sql_seam.py` | **create** |
| CICS strategy (cicada) | `cicada: cics/strategy.py` | add `handles()` to `CicsLoweringStrategy` |
| CICS bootstrap (cicada) | `cicada: cics/bootstrap.py` | `extension_strategies=[strategy]` |

`interpreter/cobol/exec_cics_strategy.py` is **retained** (cicada re-exports `ExecCicsStrategy`/`CatchAllLoweringStrategy` from it); the frontend simply stops importing it.

**Test commands:**
- RedDragon unit (no JAR): `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py -v`
- RedDragon integration (JAR): `cd ~/code/red-dragon && python -m pytest tests/integration/test_exec_sql_seam.py -v`
- RedDragon full: `cd ~/code/red-dragon && python -m pytest -q`
- cicada full: `cd ~/code/cicada && uv run python -m pytest tests/ -x -q`

---

## Task 1: `ExecSqlStatement` node + dispatch table  *(red-dragon)*

The bridge will emit `{"type": "EXEC_SQL", "exec_sql_text": "<raw SQL>"}`. The node carries raw SQL text + a cheap `verb` (first keyword) for logging/routing; it does **no** structural parsing (squall parses later).

**Files:**
- Modify: `interpreter/cobol/cobol_statements.py` (union ~line 91; node after `ExecCicsStatement` ~line 1042; `_DISPATCH_TABLE` after line 1167)
- Test: `tests/unit/test_exec_sql_seam.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_exec_sql_seam.py`:

```python
"""RedDragon EXEC SQL extension seam — node, protocol, dispatch, frontend wiring."""

from interpreter.cobol.cobol_statements import ExecSqlStatement, parse_statement


class TestExecSqlStatementNode:
    def test_from_dict_extracts_text_and_verb(self):
        data = {
            "type": "EXEC_SQL",
            "exec_sql_text": "SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID",
        }
        stmt = ExecSqlStatement.from_dict(data)
        assert stmt.verb == "SELECT"
        assert stmt.text == data["exec_sql_text"]

    def test_from_dict_empty_text_yields_empty_verb(self):
        stmt = ExecSqlStatement.from_dict({"type": "EXEC_SQL"})
        assert stmt.verb == ""
        assert stmt.text == ""

    def test_verb_is_uppercased_first_token(self):
        stmt = ExecSqlStatement.from_dict({"type": "EXEC_SQL", "exec_sql_text": "  insert into T values (1)"})
        assert stmt.verb == "INSERT"

    def test_parse_statement_dispatches_exec_sql(self):
        stmt = parse_statement({"type": "EXEC_SQL", "exec_sql_text": "DELETE FROM T"})
        assert isinstance(stmt, ExecSqlStatement)
        assert stmt.verb == "DELETE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestExecSqlStatementNode -v`
Expected: FAIL with `ImportError: cannot import name 'ExecSqlStatement'`.

- [ ] **Step 3: Add node, union member, dispatch entry**

In `interpreter/cobol/cobol_statements.py`, add to the `CobolStatementType` union (after `"ExecCicsStatement",` at line 91):

```python
    "ExecSqlStatement",
```

Add the dataclass after the `ExecCicsStatement` class (after line 1042):

```python
@dataclass(frozen=True)
class ExecSqlStatement:
    """EXEC SQL block. Carries the raw (untagged) SQL text verbatim; host-variable /
    INTO parsing is done by the injected SQL strategy, not here (the COBOL frontend
    treats the SQL body as opaque text)."""

    verb: str  # first SQL keyword (SELECT/INSERT/UPDATE/DELETE/...), uppercased
    text: str  # raw untagged SQL body (between EXEC SQL and END-EXEC)

    @classmethod
    def from_dict(cls, data: dict) -> "ExecSqlStatement":
        text = data.get("exec_sql_text", "") or ""
        stripped = text.strip()
        verb = stripped.split(None, 1)[0].upper() if stripped else ""
        return cls(verb=verb, text=text)

    def to_dict(self) -> dict:
        return {"type": "EXEC_SQL", "verb": self.verb, "text": self.text}
```

Add to `_DISPATCH_TABLE` (after `"EXEC_CICS": ExecCicsStatement,` at line 1167):

```python
    "EXEC_SQL": ExecSqlStatement,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestExecSqlStatementNode -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/cobol/cobol_statements.py tests/unit/test_exec_sql_seam.py
git commit -m "feat(cobol): add ExecSqlStatement node + EXEC_SQL dispatch"
```

---

## Task 2: `RedDragonExtensionLoweringStrategy` protocol (with `handles`)  *(red-dragon)*

A `@runtime_checkable` Protocol with four methods. No catch-all class — an empty `extension_strategies` array is the no-op.

**Files:**
- Create: `interpreter/cobol/red_dragon_extension_strategy.py`
- Test: `tests/unit/test_exec_sql_seam.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_exec_sql_seam.py`:

```python
from interpreter.cobol.red_dragon_extension_strategy import (
    RedDragonExtensionLoweringStrategy,
)


class _ConformingStrategy:
    def handles(self, stmt): return True
    def preprocess_program_dict(self, data): return data
    def on_procedure_entry(self, ctx, materialised): ...
    def lower(self, ctx, stmt, materialised): ...


class _MissingHandles:
    def preprocess_program_dict(self, data): return data
    def on_procedure_entry(self, ctx, materialised): ...
    def lower(self, ctx, stmt, materialised): ...


class TestExtensionStrategyProtocol:
    def test_conforming_class_is_instance(self):
        assert isinstance(_ConformingStrategy(), RedDragonExtensionLoweringStrategy)

    def test_missing_handles_is_not_instance(self):
        assert not isinstance(_MissingHandles(), RedDragonExtensionLoweringStrategy)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestExtensionStrategyProtocol -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'interpreter.cobol.red_dragon_extension_strategy'`.

- [ ] **Step 3: Create the module**

Create `interpreter/cobol/red_dragon_extension_strategy.py`:

```python
"""RedDragonExtensionLoweringStrategy — the injectable seam for lowering embedded
coprocessor-extension statements (EXEC CICS, EXEC SQL, EXEC DLI) to IR.

The frontend holds an *array* of these. Each extension's full implementation lives
in its own runtime package (cicada for CICS, squall for SQL) and is injected at
CobolFrontend construction. The protocol is dialect-agnostic — it carries no
CICS/SQL semantics. An empty array means no extension processing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from interpreter.cobol.emit_context import EmitContext
    from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout


@runtime_checkable
class RedDragonExtensionLoweringStrategy(Protocol):
    """One injectable extension-lowering strategy (CICS, SQL, …)."""

    def handles(self, stmt: Any) -> bool:
        """True if this strategy owns ``stmt`` (e.g. isinstance(stmt, ExecSqlStatement))."""
        ...

    def preprocess_program_dict(self, data: dict) -> dict:
        """Transform the raw bridge JSON dict before generic COBOL parsing.
        Return ``data`` unchanged for a no-op."""
        ...

    def on_procedure_entry(
        self, ctx: "EmitContext", materialised: "MaterialisedSectionedLayout"
    ) -> None:
        """Called once at the start of the procedure division."""
        ...

    def lower(
        self, ctx: "EmitContext", stmt: Any, materialised: "MaterialisedSectionedLayout"
    ) -> None:
        """Lower one extension statement to IR."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestExtensionStrategyProtocol -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/cobol/red_dragon_extension_strategy.py tests/unit/test_exec_sql_seam.py
git commit -m "feat(cobol): add RedDragonExtensionLoweringStrategy protocol (array seam)"
```

---

## Task 3: `EmitContext` holds the `extension_strategies` array  *(red-dragon)*

Replace the single `exec_cics_strategy` param/property with `extension_strategies`.

**Files:**
- Modify: `interpreter/cobol/emit_context.py` (imports 21-24; `__init__` 81-95; property 111-113)
- Test: `tests/unit/test_exec_sql_seam.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_exec_sql_seam.py`:

```python
from interpreter.cobol.emit_context import EmitContext
from interpreter.cobol.statement_dispatch import dispatch_statement
from interpreter.cobol.cobol_statements import ExecSqlStatement


class _SpyStrategy:
    def __init__(self, kind):
        self._kind = kind  # the statement class this spy claims
        self.lowered = []
        self.entered = 0
        self.preprocessed = 0
    def handles(self, stmt): return isinstance(stmt, self._kind)
    def preprocess_program_dict(self, data):
        self.preprocessed += 1
        return data
    def on_procedure_entry(self, ctx, materialised): self.entered += 1
    def lower(self, ctx, stmt, materialised): self.lowered.append(stmt)


class TestEmitContextExtensionArray:
    def test_default_is_empty(self):
        ctx = EmitContext(dispatch_fn=dispatch_statement)
        assert tuple(ctx.extension_strategies) == ()

    def test_injected_array_is_exposed(self):
        spy = _SpyStrategy(ExecSqlStatement)
        ctx = EmitContext(dispatch_fn=dispatch_statement, extension_strategies=[spy])
        assert list(ctx.extension_strategies) == [spy]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestEmitContextExtensionArray -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'extension_strategies'`.

- [ ] **Step 3: Edit `emit_context.py`**

Replace the import block (lines 21-24):

```python
from interpreter.cobol.exec_cics_strategy import (
    CatchAllLoweringStrategy,
    ExecCicsStrategy,
)
```

with:

```python
from interpreter.cobol.red_dragon_extension_strategy import (
    RedDragonExtensionLoweringStrategy,
)
```

In `__init__` (lines 81-87), remove the `exec_cics_strategy` parameter and add `extension_strategies`:

```python
    def __init__(
        self,
        dispatch_fn: DispatchFn,
        observer: FrontendObserver | None = None,
        condition_index: ConditionNameIndex = ConditionNameIndex({}),
        extension_strategies: Sequence[RedDragonExtensionLoweringStrategy] = (),
    ) -> None:
```

In the body, replace `self._exec_cics_strategy = exec_cics_strategy` (line 91) with:

```python
        self._extension_strategies = tuple(extension_strategies)
```

Replace the `exec_cics_strategy` property (lines 111-113) with:

```python
    @property
    def extension_strategies(self) -> tuple[RedDragonExtensionLoweringStrategy, ...]:
        return self._extension_strategies
```

(`Sequence` is already imported from `collections.abc` at line 15.)

- [ ] **Step 4: Run test to verify it passes** (dispatch import still works because Task 4 hasn't changed it yet — but `statement_dispatch.py` imports `EmitContext`; this step only needs the EmitContext edit)

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestEmitContextExtensionArray -v`
Expected: PASS (2 tests).

> If an `ImportError` about `exec_cics_strategy` appears from another module at import time, it is `cobol_frontend.py` (still on the old param) — that is fixed in Task 5. Running just this test class imports `emit_context` + `statement_dispatch`, neither of which imports `cobol_frontend`, so it passes in isolation.

- [ ] **Step 5: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/cobol/emit_context.py tests/unit/test_exec_sql_seam.py
git commit -m "feat(cobol): EmitContext holds extension_strategies array"
```

---

## Task 4: Array-routed dispatch + per-strategy procedure entry  *(red-dragon)*

Remove the hardcoded CICS branch; route every extension statement through the array via `handles()`.

**Files:**
- Modify: `interpreter/cobol/statement_dispatch.py` (import line 20; CICS branch + else, lines 161-165)
- Modify: `interpreter/cobol/lower_procedure.py` (line 24)
- Test: `tests/unit/test_exec_sql_seam.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_exec_sql_seam.py`:

```python
class TestArrayDispatch:
    def test_routes_to_strategy_that_handles(self):
        sql_spy = _SpyStrategy(ExecSqlStatement)
        ctx = EmitContext(dispatch_fn=dispatch_statement, extension_strategies=[sql_spy])
        stmt = ExecSqlStatement(verb="SELECT", text="SELECT 1 INTO :X FROM T")
        dispatch_statement(ctx, stmt, materialised=None)
        assert sql_spy.lowered == [stmt]

    def test_first_handler_wins_and_others_skipped(self):
        from interpreter.cobol.cobol_statements import ExecCicsStatement
        cics_spy = _SpyStrategy(ExecCicsStatement)
        sql_spy = _SpyStrategy(ExecSqlStatement)
        ctx = EmitContext(dispatch_fn=dispatch_statement, extension_strategies=[cics_spy, sql_spy])
        stmt = ExecSqlStatement(verb="DELETE", text="DELETE FROM T")
        dispatch_statement(ctx, stmt, materialised=None)
        assert sql_spy.lowered == [stmt]
        assert cics_spy.lowered == []

    def test_empty_array_no_handler_warns(self, caplog):
        import logging
        ctx = EmitContext(dispatch_fn=dispatch_statement, extension_strategies=[])
        stmt = ExecSqlStatement(verb="SELECT", text="SELECT 1")
        with caplog.at_level(logging.WARNING):
            dispatch_statement(ctx, stmt, materialised=None)
        assert "Unhandled" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestArrayDispatch -v`
Expected: FAIL — `ExecSqlStatement` currently falls to the `else` warning (the spy is never called), so `sql_spy.lowered == []`.

- [ ] **Step 3: Edit `statement_dispatch.py`**

Remove `ExecCicsStatement` from the `cobol_statements` import block (line 20 — it is no longer referenced here).

Replace the CICS branch + else (lines 161-165):

```python
    # ── CICS ──────────────────────────────────────────────
    elif isinstance(stmt, ExecCicsStatement):
        ctx.exec_cics_strategy.lower(ctx, stmt, materialised)
    else:
        logger.warning("Unhandled COBOL statement type: %s", type(stmt).__name__)
```

with:

```python
    # ── Extension statements (EXEC CICS / EXEC SQL / …) routed via the array ──
    else:
        for strat in ctx.extension_strategies:
            if strat.handles(stmt):
                strat.lower(ctx, stmt, materialised)
                return
        logger.warning("Unhandled COBOL statement type: %s", type(stmt).__name__)
```

In `interpreter/cobol/lower_procedure.py`, replace line 24:

```python
    ctx.exec_cics_strategy.on_procedure_entry(ctx, materialised)
```

with:

```python
    for strat in ctx.extension_strategies:
        strat.on_procedure_entry(ctx, materialised)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestArrayDispatch -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/cobol/statement_dispatch.py interpreter/cobol/lower_procedure.py tests/unit/test_exec_sql_seam.py
git commit -m "feat(cobol): route extension statements through extension_strategies array"
```

---

## Task 5: `CobolFrontend` takes the array + chains preprocessors  *(red-dragon)*

**Files:**
- Modify: `interpreter/cobol/cobol_frontend.py` (imports 41-44; `__init__` 64-78; `lower` 176-197)
- Test: `tests/unit/test_exec_sql_seam.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_exec_sql_seam.py`:

```python
from interpreter.cobol.cobol_frontend import CobolFrontend
from interpreter.cobol.cobol_asg import CobolASG
from interpreter.cobol.cobol_parser import CobolParser


class _PreprocessRecordingParser(CobolParser):
    """Fake parser: calls the injected preprocessor on a minimal program dict,
    then returns an empty ASG so frontend.lower() completes."""
    def parse(self, source: bytes, preprocessor=None) -> CobolASG:
        if preprocessor is not None:
            preprocessor({"type": "PROGRAM", "program_id": "T"})
        return CobolASG()


class TestFrontendExtensionArray:
    def test_all_strategies_preprocess_in_order(self):
        a = _SpyStrategy(ExecSqlStatement)
        b = _SpyStrategy(ExecSqlStatement)
        frontend = CobolFrontend(_PreprocessRecordingParser(), extension_strategies=[a, b])
        frontend.lower(b"")
        assert a.preprocessed == 1
        assert b.preprocessed == 1

    def test_default_array_is_empty(self):
        frontend = CobolFrontend(_PreprocessRecordingParser())
        assert tuple(frontend._extension_strategies) == ()
```

> Note: `CobolASG()` is constructed with no args in existing tests (`tests/unit/test_cobol_frontend.py`). If its required fields differ in this tree, mirror that test's construction; the point here is the array wiring, not ASG shape.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestFrontendExtensionArray -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'extension_strategies'` (and/or an `ImportError` for `exec_cics_strategy` once `cobol_frontend` is imported — both fixed in Step 3).

- [ ] **Step 3: Edit `cobol_frontend.py`**

Replace the strategy import (lines 41-44):

```python
from interpreter.cobol.exec_cics_strategy import (
    CatchAllLoweringStrategy,
    ExecCicsStrategy,
)
```

with:

```python
from interpreter.cobol.red_dragon_extension_strategy import (
    RedDragonExtensionLoweringStrategy,
)
```

Ensure `Sequence` is importable — add near the top imports if absent:

```python
from collections.abc import Sequence
```

Replace `__init__` (lines 64-78):

```python
    def __init__(
        self,
        cobol_parser: CobolParser,
        observer: FrontendObserver = NullFrontendObserver(),
        extension_strategies: Sequence[RedDragonExtensionLoweringStrategy] = (),
    ):
        self._parser = cobol_parser
        self._observer = observer
        self._extension_strategies = tuple(extension_strategies)
        self._layout = DataLayout()
        self._ctx = EmitContext(
            dispatch_fn=dispatch_statement,
            observer=observer,
            extension_strategies=self._extension_strategies,
        )
```

In `lower` (lines 176-179), replace the single-strategy preprocessor with a chained one:

```python
        def _chained_preprocess(data: dict) -> dict:
            for strat in self._extension_strategies:
                data = strat.preprocess_program_dict(data)
            return data

        asg = self._parser.parse(source, preprocessor=_chained_preprocess)
```

And in the second `EmitContext` construction (lines 192-197), replace `exec_cics_strategy=self._exec_cics_strategy` with:

```python
            extension_strategies=self._extension_strategies,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py -v`
Expected: PASS (whole file — all classes green).

- [ ] **Step 5: RedDragon regression**

Run: `cd ~/code/red-dragon && python -m pytest -q`
Expected: All green. (No RedDragon test injected `exec_cics_strategy=` or asserts CICS lowering via the frontend — CICS is exercised in cicada. If any RedDragon test has EXEC CICS source expecting the old catch-all warning, update it to the new "Unhandled COBOL statement type: ExecCicsStatement" wording.)

- [ ] **Step 6: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/cobol/cobol_frontend.py tests/unit/test_exec_sql_seam.py
git commit -m "feat(cobol): CobolFrontend takes extension_strategies array; chain preprocessors"
```

---

## Task 6: Bridge `serializeExecSql` + JAR rebuild + integration test  *(red-dragon)*

**Files:**
- Modify: `proleap-bridge/src/main/java/org/reddragon/bridge/StatementSerializer.java` (import near the `execcics` import; method near line 1424; dispatch after line 195)
- Create: `tests/integration/test_exec_sql_seam.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_exec_sql_seam.py`:

```python
"""Integration: a real EXEC SQL program flows through the JAR bridge into the
injected SQL strategy (proves serializeExecSql + the full array seam)."""

import os
import pytest

from interpreter.cobol.cobol_frontend import CobolFrontend
from interpreter.cobol.cobol_statements import ExecSqlStatement
from tests.integration.cobol_helpers import JAR_AVAILABLE, JAR_PATH, to_fixed

pytestmark = pytest.mark.skipif(not JAR_AVAILABLE, reason="ProLeap bridge JAR not available")

_PROGRAM = to_fixed(
    [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. SQLT.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "77 WS-ID PIC 9(4) VALUE 0.",
        "PROCEDURE DIVISION.",
        "    EXEC SQL",
        "        SELECT 1 INTO :WS-ID FROM SYSIBM.SYSDUMMY1",
        "    END-EXEC.",
        "    STOP RUN.",
    ]
).encode("utf-8")


class _SqlSpy:
    def __init__(self): self.lowered = []
    def handles(self, stmt): return isinstance(stmt, ExecSqlStatement)
    def preprocess_program_dict(self, data): return data
    def on_procedure_entry(self, ctx, materialised): ...
    def lower(self, ctx, stmt, materialised): self.lowered.append(stmt)


def _real_frontend(extension_strategies):
    os.environ["PROLEAP_BRIDGE_JAR"] = JAR_PATH
    from interpreter.cobol.cobol_parser import ProLeapCobolParser
    from interpreter.process_runner import SubprocessRunner  # real command runner

    parser = ProLeapCobolParser(SubprocessRunner(), JAR_PATH)
    return CobolFrontend(parser, extension_strategies=extension_strategies)


def test_real_exec_sql_reaches_strategy():
    spy = _SqlSpy()
    _real_frontend([spy]).lower(_PROGRAM)
    assert len(spy.lowered) == 1
    assert isinstance(spy.lowered[0], ExecSqlStatement)
    assert spy.lowered[0].verb == "SELECT"
    assert "SYSDUMMY1" in spy.lowered[0].text
```

> Runner note: existing tests build the parser as `ProLeapCobolParser(runner, JAR_PATH)`. Confirm the concrete runner the production `run()` path uses (grep `interpreter/` for `ProLeapCobolParser(`); it may be `SubprocessRunner` or a `build_cobol_parser()` factory). Substitute if the name differs — the intent is "real JAR-backed parser + injected SQL strategy."

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/integration/test_exec_sql_seam.py -v`
Expected: FAIL — current JAR emits no `EXEC_SQL`; the block is dropped, so `spy.lowered` is empty.

- [ ] **Step 3: Add `serializeExecSql` + dispatch (Java)**

In `StatementSerializer.java`, add the import alongside the existing `ExecCicsStatement` import:

```java
import io.proleap.cobol.asg.metamodel.procedure.execsql.ExecSqlStatement;
```

Add the serializer next to `serializeExecCics` (near line 1424):

```java
    private static JsonObject serializeExecSql(ExecSqlStatement stmt) {
        JsonObject obj = newStatement("EXEC_SQL");
        String text = stmt.getExecSqlText();
        if (text != null) {
            obj.addProperty("exec_sql_text", text);
        }
        return obj;
    }
```

Add the dispatch line right after the EXEC_CICS line (line 195), before `return serializeUnknown(stmtType);`:

```java
        if (stmtType == StatementTypeEnum.EXEC_SQL) return serializeExecSql((ExecSqlStatement) stmt);
```

- [ ] **Step 4: Rebuild the JAR**

Run: `cd ~/code/red-dragon/proleap-bridge && ./build.sh`
Expected: Maven build succeeds; `target/proleap-bridge-0.1.0-shaded.jar` refreshed (the `cobol_helpers.JAR_PATH`).

- [ ] **Step 5: Run integration test to verify it passes**

Run: `cd ~/code/red-dragon && python -m pytest tests/integration/test_exec_sql_seam.py -v`
Expected: PASS — the bridge now emits `{"type":"EXEC_SQL","exec_sql_text":"SELECT 1 INTO :WS-ID FROM SYSIBM.SYSDUMMY1"}`, routed to the spy via `handles()`.

- [ ] **Step 6: Commit + push RedDragon**

```bash
cd ~/code/red-dragon
git add proleap-bridge/src/main/java/org/reddragon/bridge/StatementSerializer.java tests/integration/test_exec_sql_seam.py
git commit -m "feat(bridge): serialize EXEC SQL statements (exec_sql_text)"
python -m pytest -q   # full RedDragon suite green
git push              # only with explicit go-ahead per RedDragon git policy
```

Record the SHA: `git -C ~/code/red-dragon rev-parse HEAD` — cicada (Task 6) and squall (Plan 2) pin it.

---

## Task 7: Migrate CICS onto the array  *(cicada — gated on RedDragon pushed)*

cicada's `CicsLoweringStrategy` must gain `handles()`, and its single construction site must pass `extension_strategies=[strategy]`. First bump the submodule to the RedDragon SHA from Task 6.

**Files:**
- Modify: `cics/strategy.py` (`CicsLoweringStrategy` — add `handles`; ensure `ExecCicsStatement` imported at runtime)
- Modify: `cics/bootstrap.py:52`

- [ ] **Step 1: Bump cicada's RedDragon submodule to the seam SHA**

```bash
cd ~/code/cicada/vendor/red-dragon && git fetch -q origin && git checkout -q <REDDRAGON_SHA_FROM_TASK_6>
cd ~/code/cicada && git add vendor/red-dragon
```

- [ ] **Step 2: Run cicada tests to verify they fail**

Run: `cd ~/code/cicada && uv run python -m pytest tests/integration/cics/ -x -q`
Expected: FAIL — `cics/bootstrap.py:52` still passes `exec_cics_strategy=` (now an unexpected kwarg → `TypeError`), so CICS compilation errors out.

- [ ] **Step 3: Add `handles()` to `CicsLoweringStrategy` + switch bootstrap to the array**

In `cics/strategy.py`, ensure `ExecCicsStatement` is imported at runtime (the existing import at line ~43 is under `TYPE_CHECKING`). Add a runtime import near the other `interpreter.cobol` imports:

```python
from interpreter.cobol.cobol_statements import ExecCicsStatement
```

Add a `handles` method to `CicsLoweringStrategy` (alongside `preprocess_program_dict` / `on_procedure_entry` / `lower`, ~line 497-520):

```python
    def handles(self, stmt) -> bool:
        return isinstance(stmt, ExecCicsStatement)
```

In `cics/bootstrap.py:52`, change:

```python
    frontend = CobolFrontend(cobol_parser=parser, exec_cics_strategy=strategy)
```

to:

```python
    frontend = CobolFrontend(cobol_parser=parser, extension_strategies=[strategy])
```

- [ ] **Step 4: Run cicada tests to verify they pass**

Run: `cd ~/code/cicada && uv run python -m pytest tests/ -x -q`
Expected: All green — CardDemo + zBANK conversational flows lower EXEC CICS through the array exactly as before.

- [ ] **Step 5: Commit (cicada)**

```bash
cd ~/code/cicada
git add vendor/red-dragon cics/strategy.py cics/bootstrap.py
git commit -m "refactor(cics): migrate CicsLoweringStrategy onto extension_strategies array"
```

---

## Task 8: Final regression + handoff

- [ ] **Step 1: RedDragon full suite** — `cd ~/code/red-dragon && python -m pytest -q` → green.
- [ ] **Step 2: cicada full suite** — `cd ~/code/cicada && uv run python -m pytest tests/ -x -q` → green.
- [ ] **Step 3: Push** (each repo, only with explicit go-ahead per its git policy).
- [ ] **Step 4: Hand off** the RedDragon SHA — Plan 2 (squall runtime) pins `vendor/red-dragon` at it before building `SqlLoweringStrategy` (which implements `RedDragonExtensionLoweringStrategy` incl. `handles()` and is injected via `extension_strategies=[sql_strategy]`, or alongside CICS as `[cics, sql]`).

---

## Self-Review

**Spec coverage** (design §5.2):
- bridge `serializeExecSql` → Task 6 ✓
- `ExecSqlStatement` node → Task 1 ✓
- generic `RedDragonExtensionLoweringStrategy` protocol with `handles()` → Task 2 ✓
- `extension_strategies` **array** replacing `exec_cics_strategy` (empty = no-op) → Tasks 3-5 ✓
- array-routed dispatch (`handles()`, first-match), preprocess/entry iterate all → Task 4 ✓
- CICS migrated onto the array in lockstep → Task 7 ✓
- invariant "no edits to `vm/**`, `ir.py`, `run.py`, `executor.py`, `cfg.py`" → every touched RedDragon file is under `interpreter/cobol/` or the bridge ✓
- `EXEC SQL INCLUDE → COPY` + SQL semantics (binding/backend) → out of scope (Plan 2 / later slices) ✓

**Placeholder scan:** every code step shows complete code. Two flagged uncertainties — the Task 6 runner/factory class and the exact `CicsLoweringStrategy` method-insertion line — are called out with how to resolve, not left as "TBD".

**Type consistency:** `extension_strategies` (param/attr/property) is identical across `EmitContext` (Task 3), `cobol_frontend` (Task 5), dispatch/lower_procedure (Task 4). `handles(stmt) -> bool` signature matches across the protocol (Task 2), the spies (Tasks 3-6), and `CicsLoweringStrategy` (Task 7). `ExecSqlStatement(verb, text)` identical in Tasks 1, 4, 6. Bridge key `exec_sql_text` (Task 6) matches `from_dict` (Task 1).

**Cross-repo ordering:** RedDragon (1-6) lands + pushes first; cicada (7) bumps the submodule to that SHA, then migrates — so the breaking `exec_cics_strategy` removal and the cicada fix never coexist in a tested state.

**Known risk (flagged, not blocking slice 1):** the SQL grammar production is `execSqlStatement : EXECSQLLINE+` (no `EXECSQLENDLINE` split), so *adjacent* EXEC SQL blocks could merge their text — the same class of bug fixed for CICS. Slice 1 uses a single statement; a fork grammar split is a future item if CBSA has adjacent SQL blocks.

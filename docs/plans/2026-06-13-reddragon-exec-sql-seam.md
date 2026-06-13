# RedDragon EXEC SQL Extension Seam — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RedDragon route embedded `EXEC SQL … END-EXEC` statements to an injectable, dialect-agnostic lowering strategy — the prerequisite seam that the standalone `squall` runtime (Plan 2) plugs into.

**Architecture:** Mirror the existing EXEC CICS path exactly. ProLeap already preprocesses and tags `EXEC SQL` (re-emitting `*>EXECSQL` marker lines) and its ASG already populates `execSqlText`; the bridge just needs to serialize that text. Downstream we add an `ExecSqlStatement` node, a generic `RedDragonExtensionLoweringStrategy` protocol (the SQL strategy implements it), and wire a second injectable strategy (`exec_sql_strategy`) through `CobolFrontend` → `EmitContext` → `statement_dispatch`, leaving the CICS path and cicada untouched.

**Tech Stack:** Python 3 (RedDragon `interpreter/cobol/`), Java (ProLeap bridge `org.reddragon.bridge`), Maven (JAR build), pytest.

**Repo:** All work is in **`~/code/red-dragon`** (NOT the cicada/squall submodule checkout). Per RedDragon convention, commit/push there; squall later pins this commit.

**Scope:** This is **Plan 1 of 2** for EXEC SQL slice 1. It delivers only the RedDragon seam (no SQL semantics — an un-injected SQL strategy is a logging no-op). Plan 2 (the `squall` runtime: parser, binding engine, `SqlBackend`, `SqliteBackend`, builtins, `SqlLoweringStrategy`) is written after this lands and squall pins the RedDragon commit. See `../design/2026-06-13-exec-sql-support-design.md`.

---

## File Structure

| File | Repo-relative path | Responsibility | Change |
|---|---|---|---|
| Statement node + dispatch | `interpreter/cobol/cobol_statements.py` | typed COBOL statements + `type`→node table | add `ExecSqlStatement`, union member, `_DISPATCH_TABLE` entry |
| Generic strategy protocol | `interpreter/cobol/red_dragon_extension_strategy.py` | injectable extension-lowering seam (CICS/SQL/…) | **create** |
| Emit context | `interpreter/cobol/emit_context.py` | shared lowering state | add `exec_sql_strategy` param + property |
| Statement dispatch | `interpreter/cobol/statement_dispatch.py` | route statement → lowering | add `ExecSqlStatement` branch |
| Procedure entry | `interpreter/cobol/lower_procedure.py` | once-per-procedure hooks | add SQL `on_procedure_entry` call |
| Frontend wiring | `interpreter/cobol/cobol_frontend.py` | construct `EmitContext`, run preprocessor | add param, chain preprocessors, pass to both `EmitContext` sites |
| Bridge serializer | `proleap-bridge/src/main/java/org/reddragon/bridge/StatementSerializer.java` | ASG statement → JSON | add `serializeExecSql` + dispatch |
| Unit tests | `tests/unit/test_exec_sql_seam.py` | node, strategy, dispatch, frontend wiring | **create** |
| Integration test | `tests/integration/test_exec_sql_seam.py` | real JAR: program flows to SQL strategy | **create** |

**Test commands:**
- Unit (no JAR): `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py -v`
- Integration (needs JAR): `cd ~/code/red-dragon && python -m pytest tests/integration/test_exec_sql_seam.py -v`
- Full suite before final commit: `python -m pytest -q`

---

## Task 1: `ExecSqlStatement` node + dispatch

The bridge will emit `{"type": "EXEC_SQL", "exec_sql_text": "<raw SQL>"}`. We need a typed node carrying the raw SQL text plus a cheap `verb` (first keyword) for logging/dispatch. Unlike `ExecCicsStatement`, this node does **no** structural parsing — the squall binding engine parses the text later.

**Files:**
- Modify: `interpreter/cobol/cobol_statements.py` (union ~line 91; node after `ExecCicsStatement` ~line 1042; `_DISPATCH_TABLE` after line 1167)
- Test: `tests/unit/test_exec_sql_seam.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_exec_sql_seam.py`:

```python
"""RedDragon EXEC SQL extension seam — node, strategy, dispatch, frontend wiring."""

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

    def test_verb_is_uppercased_and_first_token(self):
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

- [ ] **Step 3: Add the node, union member, dispatch entry**

In `interpreter/cobol/cobol_statements.py`, add to the `CobolStatementType` union (after `"ExecCicsStatement",` at line 91):

```python
    "ExecSqlStatement",
```

Add the dataclass immediately after the `ExecCicsStatement` class (after line 1042):

```python
@dataclass(frozen=True)
class ExecSqlStatement:
    """EXEC SQL block. Carries the raw (untagged) SQL text verbatim; structural
    parsing of host variables / INTO is done by the injected SQL strategy, not
    here (the COBOL frontend treats the SQL body as opaque text)."""

    verb: str  # first SQL keyword (SELECT/INSERT/UPDATE/DELETE/...), uppercased — for logging/dispatch
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

## Task 2: Generic `RedDragonExtensionLoweringStrategy` protocol

A dialect-agnostic seam: the same three-method shape as `ExecCicsStrategy`, but named generically because both CICS and SQL (and later DLI) implement it. The default `CatchAllExtensionLoweringStrategy` is a logging no-op so an un-injected SQL program runs without crashing. (We leave the existing `ExecCicsStrategy`/`CatchAllLoweringStrategy` untouched to avoid churning the proven CICS path; collapsing it into this protocol is a trivial deferred follow-up.)

**Files:**
- Create: `interpreter/cobol/red_dragon_extension_strategy.py`
- Test: `tests/unit/test_exec_sql_seam.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_exec_sql_seam.py`:

```python
import logging

from interpreter.cobol.cobol_statements import ExecSqlStatement
from interpreter.cobol.red_dragon_extension_strategy import (
    CatchAllExtensionLoweringStrategy,
)


class TestCatchAllExtensionStrategy:
    def test_preprocess_is_identity(self):
        strat = CatchAllExtensionLoweringStrategy()
        data = {"type": "PROGRAM", "x": 1}
        assert strat.preprocess_program_dict(data) is data

    def test_on_procedure_entry_is_noop(self):
        strat = CatchAllExtensionLoweringStrategy()
        strat.on_procedure_entry(None, None)  # must not raise

    def test_lower_logs_warning_with_verb(self, caplog):
        strat = CatchAllExtensionLoweringStrategy()
        stmt = ExecSqlStatement(verb="SELECT", text="SELECT 1")
        with caplog.at_level(logging.WARNING):
            strat.lower(None, stmt, None)  # must not raise
        assert "SELECT" in caplog.text
        assert "ignored" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestCatchAllExtensionStrategy -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'interpreter.cobol.red_dragon_extension_strategy'`.

- [ ] **Step 3: Create the module**

Create `interpreter/cobol/red_dragon_extension_strategy.py`:

```python
"""RedDragonExtensionLoweringStrategy protocol and null-object default.

The injectable seam for lowering embedded coprocessor-extension statements
(EXEC CICS, EXEC SQL, EXEC DLI) to IR. Each extension's full implementation
lives in its own runtime package (cicada for CICS, squall for SQL) and is
injected at CobolFrontend construction time. This protocol is dialect-agnostic;
it carries no CICS/SQL semantics.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from interpreter.cobol.emit_context import EmitContext
    from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout

logger = logging.getLogger(__name__)


class RedDragonExtensionLoweringStrategy(Protocol):
    """Injectable strategy for lowering one kind of EXEC extension statement."""

    def preprocess_program_dict(self, data: dict) -> dict:  # type: ignore[return]
        """Transform the raw bridge JSON dict before generic COBOL parsing.
        Default no-op. Override to rewrite extension-specific nodes."""
        return data

    def on_procedure_entry(
        self,
        ctx: "EmitContext",
        materialised: "MaterialisedSectionedLayout",
    ) -> None:
        """Called once at the start of the procedure division."""
        ...

    def lower(
        self,
        ctx: "EmitContext",
        stmt: Any,
        materialised: "MaterialisedSectionedLayout",
    ) -> None:
        """Lower one extension statement to IR."""
        ...


class CatchAllExtensionLoweringStrategy:
    """Default no-op strategy. Logs a warning for every extension statement."""

    def preprocess_program_dict(self, data: dict) -> dict:
        return data

    def on_procedure_entry(
        self,
        ctx: "EmitContext",
        materialised: "MaterialisedSectionedLayout",
    ) -> None:
        logger.debug("on_procedure_entry: no-op (CatchAllExtensionLoweringStrategy)")

    def lower(
        self,
        ctx: "EmitContext",
        stmt: Any,
        materialised: "MaterialisedSectionedLayout",
    ) -> None:
        verb = getattr(stmt, "verb", "")
        logger.warning("EXEC SQL %s ignored (no SQL strategy injected)", verb)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestCatchAllExtensionStrategy -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/cobol/red_dragon_extension_strategy.py tests/unit/test_exec_sql_seam.py
git commit -m "feat(cobol): add generic RedDragonExtensionLoweringStrategy protocol"
```

---

## Task 3: Wire `exec_sql_strategy` through `EmitContext`

**Files:**
- Modify: `interpreter/cobol/emit_context.py` (imports ~line 21-24; `__init__` ~line 81-95; property ~line 111-113)
- Test: `tests/unit/test_exec_sql_seam.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_exec_sql_seam.py`:

```python
from interpreter.cobol.emit_context import EmitContext
from interpreter.cobol.statement_dispatch import dispatch_statement
from interpreter.cobol.red_dragon_extension_strategy import (
    CatchAllExtensionLoweringStrategy,
)


class _SpyStrategy:
    def __init__(self):
        self.lowered = []
        self.entered = 0
        self.preprocessed = 0

    def preprocess_program_dict(self, data):
        self.preprocessed += 1
        return data

    def on_procedure_entry(self, ctx, materialised):
        self.entered += 1

    def lower(self, ctx, stmt, materialised):
        self.lowered.append(stmt)


class TestEmitContextSqlStrategy:
    def test_default_sql_strategy_is_catch_all(self):
        ctx = EmitContext(dispatch_fn=dispatch_statement)
        assert isinstance(ctx.exec_sql_strategy, CatchAllExtensionLoweringStrategy)

    def test_injected_sql_strategy_is_exposed(self):
        spy = _SpyStrategy()
        ctx = EmitContext(dispatch_fn=dispatch_statement, exec_sql_strategy=spy)
        assert ctx.exec_sql_strategy is spy
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestEmitContextSqlStrategy -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'exec_sql_strategy'`.

- [ ] **Step 3: Add the param + property**

In `interpreter/cobol/emit_context.py`, extend the import block (lines 21-24) to also import the generic strategy:

```python
from interpreter.cobol.exec_cics_strategy import (
    CatchAllLoweringStrategy,
    ExecCicsStrategy,
)
from interpreter.cobol.red_dragon_extension_strategy import (
    CatchAllExtensionLoweringStrategy,
    RedDragonExtensionLoweringStrategy,
)
```

In `__init__` (lines 81-87), add the parameter after `exec_cics_strategy`:

```python
    def __init__(
        self,
        dispatch_fn: DispatchFn,
        observer: FrontendObserver | None = None,
        condition_index: ConditionNameIndex = ConditionNameIndex({}),
        exec_cics_strategy: ExecCicsStrategy = CatchAllLoweringStrategy(),  # type: ignore[assignment]  # Pyright can't infer structural Protocol match for default args
        exec_sql_strategy: RedDragonExtensionLoweringStrategy = CatchAllExtensionLoweringStrategy(),  # type: ignore[assignment]
    ) -> None:
```

In the `__init__` body (after `self._exec_cics_strategy = exec_cics_strategy` at line 91), add:

```python
        self._exec_sql_strategy = exec_sql_strategy
```

After the existing `exec_cics_strategy` property (line 113), add:

```python
    @property
    def exec_sql_strategy(self) -> RedDragonExtensionLoweringStrategy:
        return self._exec_sql_strategy
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestEmitContextSqlStrategy -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/cobol/emit_context.py tests/unit/test_exec_sql_seam.py
git commit -m "feat(cobol): thread exec_sql_strategy through EmitContext"
```

---

## Task 4: Route `ExecSqlStatement` in dispatch + procedure entry

**Files:**
- Modify: `interpreter/cobol/statement_dispatch.py` (import ~line 20; branch after line 163)
- Modify: `interpreter/cobol/lower_procedure.py` (after line 24)
- Test: `tests/unit/test_exec_sql_seam.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_exec_sql_seam.py`:

```python
class TestDispatchRoutesExecSql:
    def test_dispatch_calls_sql_strategy_lower(self):
        spy = _SpyStrategy()
        ctx = EmitContext(dispatch_fn=dispatch_statement, exec_sql_strategy=spy)
        stmt = ExecSqlStatement(verb="SELECT", text="SELECT 1 INTO :X FROM T")
        dispatch_statement(ctx, stmt, materialised=None)
        assert spy.lowered == [stmt]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestDispatchRoutesExecSql -v`
Expected: FAIL — the spy is not called (a warning "Unhandled COBOL statement type: ExecSqlStatement" is logged), so `spy.lowered == []`.

- [ ] **Step 3: Add the dispatch branch + procedure-entry hook**

In `interpreter/cobol/statement_dispatch.py`, add `ExecSqlStatement` to the import from `cobol_statements` (the block at lines 7-42, e.g. after `ExecCicsStatement,` at line 20):

```python
    ExecSqlStatement,
```

Add a branch in `dispatch_statement` immediately after the CICS branch (after line 163, before the `else`):

```python
    elif isinstance(stmt, ExecSqlStatement):
        ctx.exec_sql_strategy.lower(ctx, stmt, materialised)
```

In `interpreter/cobol/lower_procedure.py`, after the CICS entry call at line 24:

```python
    ctx.exec_cics_strategy.on_procedure_entry(ctx, materialised)
```

add:

```python
    ctx.exec_sql_strategy.on_procedure_entry(ctx, materialised)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestDispatchRoutesExecSql -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/cobol/statement_dispatch.py interpreter/cobol/lower_procedure.py tests/unit/test_exec_sql_seam.py
git commit -m "feat(cobol): dispatch ExecSqlStatement to exec_sql_strategy"
```

---

## Task 5: Wire `exec_sql_strategy` through `CobolFrontend` (param + preprocessor chain)

The frontend must accept the SQL strategy, pass it to both `EmitContext` constructions, and **chain** both strategies' `preprocess_program_dict` (CICS then SQL) into the single `preprocessor` the parser accepts.

**Files:**
- Modify: `interpreter/cobol/cobol_frontend.py` (imports ~line 41-44; `__init__` 64-78; `lower` 176-197)
- Test: `tests/unit/test_exec_sql_seam.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_exec_sql_seam.py`. This uses a fake parser that *invokes* the preprocessor (so we can assert chaining) and returns a minimal ASG:

```python
from interpreter.cobol.cobol_frontend import CobolFrontend
from interpreter.cobol.cobol_asg import CobolASG
from interpreter.cobol.cobol_parser import CobolParser


class _PreprocessRecordingParser(CobolParser):
    """Fake parser: calls the injected preprocessor on an empty program dict,
    then returns a minimal (empty) ASG so frontend.lower() completes."""

    def __init__(self):
        self.preprocessed_dict = None

    def parse(self, source: bytes, preprocessor=None) -> CobolASG:
        data = {"type": "PROGRAM", "program_id": "T"}
        if preprocessor is not None:
            self.preprocessed_dict = preprocessor(data)
        return CobolASG()


class TestFrontendSqlStrategyWiring:
    def test_both_strategies_preprocess_chained(self):
        cics_spy = _SpyStrategy()
        sql_spy = _SpyStrategy()
        parser = _PreprocessRecordingParser()
        frontend = CobolFrontend(
            parser, exec_cics_strategy=cics_spy, exec_sql_strategy=sql_spy
        )
        frontend.lower(b"")
        assert cics_spy.preprocessed == 1
        assert sql_spy.preprocessed == 1

    def test_frontend_default_sql_strategy_is_catch_all(self):
        from interpreter.cobol.red_dragon_extension_strategy import (
            CatchAllExtensionLoweringStrategy,
        )
        frontend = CobolFrontend(_PreprocessRecordingParser())
        assert isinstance(frontend._exec_sql_strategy, CatchAllExtensionLoweringStrategy)
```

> Note: `CobolASG()` is constructed with no args in existing tests (`tests/unit/test_cobol_frontend.py`); if its required fields differ, mirror that test's construction. The point of this task is the strategy wiring, not ASG shape.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestFrontendSqlStrategyWiring -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'exec_sql_strategy'`.

- [ ] **Step 3: Wire the frontend**

In `interpreter/cobol/cobol_frontend.py`, extend the strategy import (lines 41-44):

```python
from interpreter.cobol.exec_cics_strategy import (
    CatchAllLoweringStrategy,
    ExecCicsStrategy,
)
from interpreter.cobol.red_dragon_extension_strategy import (
    CatchAllExtensionLoweringStrategy,
    RedDragonExtensionLoweringStrategy,
)
```

Update `__init__` (lines 64-78):

```python
    def __init__(
        self,
        cobol_parser: CobolParser,
        observer: FrontendObserver = NullFrontendObserver(),
        exec_cics_strategy: ExecCicsStrategy = CatchAllLoweringStrategy(),  # type: ignore[assignment]  # Pyright can't infer structural Protocol match for default args
        exec_sql_strategy: RedDragonExtensionLoweringStrategy = CatchAllExtensionLoweringStrategy(),  # type: ignore[assignment]
    ):
        self._parser = cobol_parser
        self._observer = observer
        self._exec_cics_strategy = exec_cics_strategy
        self._exec_sql_strategy = exec_sql_strategy
        self._layout = DataLayout()
        self._ctx = EmitContext(
            dispatch_fn=dispatch_statement,
            observer=observer,
            exec_cics_strategy=exec_cics_strategy,
            exec_sql_strategy=exec_sql_strategy,
        )
```

In `lower` (lines 176-197), replace the single-strategy preprocessor with a chained one and pass the SQL strategy to the second `EmitContext`:

```python
        def _chained_preprocess(data: dict) -> dict:
            data = self._exec_cics_strategy.preprocess_program_dict(data)
            data = self._exec_sql_strategy.preprocess_program_dict(data)
            return data

        asg = self._parser.parse(source, preprocessor=_chained_preprocess)
```

and (lines 192-197):

```python
        self._ctx = EmitContext(
            dispatch_fn=dispatch_statement,
            observer=self._observer,
            condition_index=condition_index,
            exec_cics_strategy=self._exec_cics_strategy,
            exec_sql_strategy=self._exec_sql_strategy,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py::TestFrontendSqlStrategyWiring -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the whole new unit file + a CICS regression sanity check**

Run: `cd ~/code/red-dragon && python -m pytest tests/unit/test_exec_sql_seam.py tests/unit/test_cobol_frontend.py -q`
Expected: PASS (no CICS regressions — the CICS path is unchanged).

- [ ] **Step 6: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/cobol/cobol_frontend.py tests/unit/test_exec_sql_seam.py
git commit -m "feat(cobol): inject exec_sql_strategy into CobolFrontend + chain preprocessors"
```

---

## Task 6: Bridge `serializeExecSql` (Java) + JAR rebuild + end-to-end integration test

The ASG already populates `execSqlText` (`ScopeImpl:798-800`); `StatementTypeEnum.EXEC_SQL` already exists. We only add a serializer mirroring `serializeExecCics` and a dispatch line, then rebuild the JAR and prove a real `EXEC SQL` program flows end-to-end (bridge → `ExecSqlStatement` → dispatch → strategy).

**Files:**
- Modify: `proleap-bridge/src/main/java/org/reddragon/bridge/StatementSerializer.java` (import near the existing `execcics` import; method near line 1424; dispatch after line 195)
- Create: `tests/integration/test_exec_sql_seam.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_exec_sql_seam.py`:

```python
"""Integration: a real EXEC SQL program flows through the JAR bridge to the
injected SQL strategy. Proves serializeExecSql + the full downstream seam."""

import logging

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


class _CollectingSqlStrategy:
    def __init__(self):
        self.lowered = []

    def preprocess_program_dict(self, data):
        return data

    def on_procedure_entry(self, ctx, materialised):
        pass

    def lower(self, ctx, stmt, materialised):
        self.lowered.append(stmt)


def _make_real_frontend(exec_sql_strategy):
    """Build a CobolFrontend backed by the real ProLeap JAR parser."""
    import os

    os.environ["PROLEAP_BRIDGE_JAR"] = JAR_PATH
    from interpreter.cobol.cobol_parser import ProLeapCobolParser
    from interpreter.process_runner import SubprocessRunner  # real command runner

    parser = ProLeapCobolParser(SubprocessRunner(), JAR_PATH)
    return CobolFrontend(parser, exec_sql_strategy=exec_sql_strategy)


def test_real_exec_sql_reaches_strategy():
    spy = _CollectingSqlStrategy()
    frontend = _make_real_frontend(spy)
    frontend.lower(_PROGRAM)
    assert len(spy.lowered) == 1
    stmt = spy.lowered[0]
    assert isinstance(stmt, ExecSqlStatement)
    assert stmt.verb == "SELECT"
    assert "SYSDUMMY1" in stmt.text


def test_uninjected_sql_logs_catch_all_warning(caplog):
    """Default frontend (no SQL strategy) routes EXEC SQL to the catch-all no-op."""
    frontend = _make_real_frontend(__import__(
        "interpreter.cobol.red_dragon_extension_strategy",
        fromlist=["CatchAllExtensionLoweringStrategy"],
    ).CatchAllExtensionLoweringStrategy())
    with caplog.at_level(logging.WARNING):
        frontend.lower(_PROGRAM)
    assert "EXEC SQL SELECT ignored" in caplog.text
```

> Note on the runner: existing tests build the parser as `ProLeapCobolParser(runner, JAR_PATH)`. Confirm the concrete runner class used by the production `run()` path (grep `interpreter/` for `ProLeapCobolParser(` construction — likely `SubprocessRunner` or similar in a parser factory). If the class name differs, substitute it; the test's intent is "real JAR-backed parser + injected SQL strategy." If a ready-made factory exists (e.g. a `build_cobol_parser()` helper), prefer it over hand-constructing the runner.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/red-dragon && python -m pytest tests/integration/test_exec_sql_seam.py -v`
Expected: FAIL — `spy.lowered` is empty (the current JAR emits no `EXEC_SQL`; the SQL block is dropped as an unknown statement), so `len(spy.lowered) == 1` fails.

- [ ] **Step 3: Add `serializeExecSql` + dispatch (Java)**

In `proleap-bridge/src/main/java/org/reddragon/bridge/StatementSerializer.java`:

Add the import alongside the existing `ExecCicsStatement` import:

```java
import io.proleap.cobol.asg.metamodel.procedure.execsql.ExecSqlStatement;
```

Add the serializer method next to `serializeExecCics` (near line 1424):

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

Add the dispatch line immediately after the EXEC_CICS line (line 195), before `return serializeUnknown(stmtType);`:

```java
        if (stmtType == StatementTypeEnum.EXEC_SQL) return serializeExecSql((ExecSqlStatement) stmt);
```

- [ ] **Step 4: Rebuild the JAR**

Run:
```bash
cd ~/code/red-dragon/proleap-bridge && ./build.sh
```
Expected: Maven build succeeds; `target/proleap-bridge-0.1.0-shaded.jar` is refreshed (the path `cobol_helpers.JAR_PATH` points at).

- [ ] **Step 5: Run integration test to verify it passes**

Run: `cd ~/code/red-dragon && python -m pytest tests/integration/test_exec_sql_seam.py -v`
Expected: PASS (2 tests) — the real bridge now emits `{"type":"EXEC_SQL","exec_sql_text":"SELECT 1 INTO :WS-ID FROM SYSIBM.SYSDUMMY1"}`, which flows to the injected strategy.

- [ ] **Step 6: Commit (Java + test)**

```bash
cd ~/code/red-dragon
git add proleap-bridge/src/main/java/org/reddragon/bridge/StatementSerializer.java tests/integration/test_exec_sql_seam.py
git commit -m "feat(bridge): serialize EXEC SQL statements (exec_sql_text)"
```

---

## Task 7: Full regression + push

- [ ] **Step 1: Run the full RedDragon suite**

Run: `cd ~/code/red-dragon && python -m pytest -q`
Expected: All green (the CICS path and all existing behaviour are untouched; new unit + integration tests pass).

- [ ] **Step 2: Push (only with explicit go-ahead per RedDragon git policy)**

```bash
cd ~/code/red-dragon
git push
```

- [ ] **Step 3: Hand off the commit SHA for the squall submodule pin**

Record `git -C ~/code/red-dragon rev-parse HEAD`. Plan 2 (squall runtime) pins `vendor/red-dragon` at this SHA before building the SQL strategy/binding engine against the new seam.

---

## Self-Review

**Spec coverage** (against `../design/2026-06-13-exec-sql-support-design.md` §5.2, "What RedDragon must add"):
- bridge `serializeExecSql` → Task 6 ✓
- `ExecSqlStatement` node → Task 1 ✓
- generic `RedDragonExtensionLoweringStrategy` protocol → Task 2 ✓
- registry/dispatch by EXEC kind → Tasks 3-5 (realized as a second injectable `exec_sql_strategy` param normalized alongside `exec_cics_strategy`; a full dict-keyed registry is deferred until a third coprocessor appears — noted in §5.2 as acceptable) ✓
- preprocessor chaining (dict layer) → Task 5 `_chained_preprocess` ✓ (the design's §7 dict-layer pipeline, two strategies)
- invariant "no edits to `vm/**`, `ir.py`, `run.py`, `executor.py`, `cfg.py`" → every touched file is under `interpreter/cobol/` or the bridge ✓
- `EXEC SQL INCLUDE → COPY` and the SQL semantics (binding/backend) → **out of scope** for this plan (Plan 2 + later slices), per the design's slice table ✓

**Placeholder scan:** every code step shows complete code. The one flagged uncertainty (Task 6 runner class / parser factory) is called out explicitly with how to resolve it, not left as "TBD".

**Type consistency:** `ExecSqlStatement(verb, text)` is used identically in Tasks 1, 2, 4, 6. `exec_sql_strategy` param/property/attribute name is identical across `EmitContext` (Task 3), `dispatch_statement`/`lower_procedure` (Task 4), `CobolFrontend` (Task 5). `CatchAllExtensionLoweringStrategy` / `RedDragonExtensionLoweringStrategy` names match across Tasks 2, 3, 5. The bridge JSON key `exec_sql_text` (Task 6) matches `ExecSqlStatement.from_dict`'s `data.get("exec_sql_text")` (Task 1).

**Known risk (flagged, not blocking slice 1):** the SQL grammar production is `execSqlStatement : EXECSQLLINE+` (no `EXECSQLENDLINE` split), so *adjacent* EXEC SQL blocks could merge their text — the same class of bug fixed for CICS. Slice 1 uses a single statement and is unaffected; a fork grammar split (mirroring the CICS fix) is a future item if CBSA has adjacent SQL blocks.

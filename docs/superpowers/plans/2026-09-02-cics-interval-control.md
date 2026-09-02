# CICS Interval Control (START + RETRIEVE) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `EXEC CICS START` and `EXEC CICS RETRIEVE` in cicada so a program can hand a transaction off to a later-started task carrying data, and keep running afterwards.

**Architecture:** `START` appends a `StartRequest` to a region-held `StartQueue` and emits no `Return_()`, so the issuing program falls through as in real CICS. When a task ends, each dispatcher driver drains the queue *before* waiting on terminal input — a started task is runnable immediately, a next-transid task is not. `RETRIEVE` consumes the start data into its `INTO` operand using the same Option-A buffer fill `__cics_read` already uses.

**Tech Stack:** Python 3.13, pytest, the red-dragon interpreter IR (`CallFunction`, `Const`, `Return_`), ProLeap COBOL bridge (JAR-gated integration tests), EBCDIC cp037.

**Spec:** `docs/superpowers/specs/2026-09-02-cics-interval-control-design.md`

**Bead:** forge-9zb

## Global Constraints

- **No `None` in signatures.** `.python-fp-lint/rules/` forbids `is None`, `is not None` and `None` default parameters. Model absence as an empty tuple (`()`), empty bytes (`b""`) or empty string (`""`). Existing code that uses `is None` stays as it is — do not refactor it; new code must not add more.
- **Black, line length 88.** `make fmt` at the repo root, or `cd cicada && make fmt`.
- **Package independence:** `cicada` must not import `squall` or `jackal`. Verify with `uv run lint-imports` at the repo root.
- **No test counts in living documentation** (READMEs, package docs, design overviews). This plan is an execution record and is exempt.
- **Comments are a smell.** A comment must carry what code cannot: an external constraint, a non-obvious "why", or a reference to a standard. Do not narrate the code.
- **EBCDIC:** COBOL field bytes are cp037. Assertions on program-written data compare against `"...".encode("cp037")`.
- **DFHRESP codes used here:** `NORMAL` 0, `TERMIDERR` 11, `INVREQ` 16, `TRANSIDERR` 28, `ENDDATA` 29. `system.py` already carries `_RESP_NORMAL = 0` and `_RESP_PGMIDERR = 27`, confirming this numbering.
- **Run tests from `cicada/`** with `PROLEAP_BRIDGE_JAR` set. `cd cicada && make test` does this; a single test is `PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/... -v`.

---

## File Structure

| File | Responsibility |
|---|---|
| `cicada/cics/interval.py` *(new)* | `StartRequest`, `RejectReason`, `StartQueue` — the queue and its record of what could not be honoured. No IR, no VM. |
| `cicada/cics/builtins/interval.py` *(new)* | `make_start_builtin`, `make_retrieve_builtin` — runtime behaviour, closures over the queue. |
| `cicada/cics/types.py` | `CicsContext` gains `termid`. |
| `cicada/cics/strategy.py` | `START`/`RETRIEVE` lowering; builtin registration; new constructor keywords. |
| `cicada/cics/builtins/system.py` | `__cics_init_eib` writes `EIBTERM`. |
| `cicada/cics/builtins/screen.py` | `SEND MAP`/`RECEIVE MAP` raise `INVREQ` in a non-terminal task. |
| `cicada/cics/dispatcher.py` | Queue drain in both drivers; `CicsRegion` pending-next slot; runaway guard. |
| `cicada/cics/bootstrap.py` | Creates the `StartQueue`, owns the region terminal id, threads both. |
| `cicada/tests/unit/cics/test_interval.py` *(new)* | `StartQueue` semantics in isolation. |
| `cicada/tests/integration/cics/test_interval_control.py` *(new)* | Scenarios S1–S11 through a real region. |

---

### Task 1: The start queue

**Files:**
- Create: `cicada/cics/interval.py`
- Test: `cicada/tests/unit/cics/test_interval.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `StartRequest(transid: str, data: bytes = b"", termid: str = "", reqid: str = "", timing_text: str = "")`; `RejectReason` enum with members `UNKNOWN_TRANSID`, `NO_SUCH_TERMINAL`; `StartQueue` with `queue(req) -> None`, `reject(req, reason) -> None`, `pop_runnable(region_termid: str) -> tuple[StartRequest, ...]`, `take_start_data() -> tuple[bytes, ...]`, `put_start_data(data: bytes) -> None`, `discard_for_abend() -> None`, and read-only properties `pending`, `rejected`, `ignored_delays`.

Note on `timing_text`: the spec's `delay_seconds: int` is replaced by the raw operand text. We never schedule on a delay, so parsing `hhmmss` buys nothing; the raw text is a more honest record of what was asked for and ignored. `ignored_delays` is every queued request whose `timing_text` is non-empty.

- [ ] **Step 1: Write the failing test**

```python
"""Unit: StartQueue — FIFO, terminal routing, and the record of what was refused."""

from __future__ import annotations

from cics.interval import RejectReason, StartQueue, StartRequest


def test_pop_runnable_returns_matching_terminal_request_fifo():
    q = StartQueue()
    q.queue(StartRequest(transid="SRTB", data=b"first", termid="T001"))
    q.queue(StartRequest(transid="SRTC", data=b"second", termid="T001"))

    assert q.pop_runnable("T001") == (
        StartRequest(transid="SRTB", data=b"first", termid="T001"),
    )
    assert q.pop_runnable("T001") == (
        StartRequest(transid="SRTC", data=b"second", termid="T001"),
    )
    assert q.pop_runnable("T001") == ()


def test_pop_runnable_returns_non_terminal_request():
    """No TERMID means a non-terminal task, which is still runnable."""
    q = StartQueue()
    q.queue(StartRequest(transid="SRTD", termid=""))

    assert q.pop_runnable("T001") == (StartRequest(transid="SRTD", termid=""),)


def test_pop_runnable_skips_another_terminals_request():
    q = StartQueue()
    q.queue(StartRequest(transid="PRNT", termid="P001"))
    q.queue(StartRequest(transid="SRTB", termid="T001"))

    assert q.pop_runnable("T001") == (StartRequest(transid="SRTB", termid="T001"),)
    assert q.pending == (StartRequest(transid="PRNT", termid="P001"),)


def test_start_data_is_consumed_once():
    q = StartQueue()
    q.put_start_data(b"payload")

    assert q.take_start_data() == (b"payload",)
    assert q.take_start_data() == ()


def test_take_start_data_is_empty_for_a_task_nobody_started():
    assert StartQueue().take_start_data() == ()


def test_rejected_records_the_reason_and_does_not_queue():
    q = StartQueue()
    req = StartRequest(transid="ZZZZ", termid="T001")
    q.reject(req, RejectReason.UNKNOWN_TRANSID)

    assert q.pending == ()
    assert q.rejected == ((req, RejectReason.UNKNOWN_TRANSID),)


def test_ignored_delays_records_every_queued_request_carrying_timing():
    q = StartQueue()
    timed = StartRequest(transid="SRTB", termid="T001", timing_text="000005")
    q.queue(timed)
    q.queue(StartRequest(transid="SRTC", termid="T001"))

    assert q.ignored_delays == (timed,)


def test_discard_for_abend_clears_pending_but_keeps_the_record():
    q = StartQueue()
    timed = StartRequest(transid="SRTB", termid="T001", timing_text="000005")
    q.queue(timed)
    q.reject(StartRequest(transid="ZZZZ"), RejectReason.UNKNOWN_TRANSID)

    q.discard_for_abend()

    assert q.pending == ()
    assert len(q.rejected) == 1
    assert q.ignored_delays == (timed,)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cicada && uv run --no-sync python -m pytest tests/unit/cics/test_interval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cics.interval'`

- [ ] **Step 3: Write the implementation**

```python
"""CICS interval control — the region's queue of START requests.

A START asks CICS to run a transaction as a separate task while the issuing task
carries on. This module holds the requests and the record of the ones the region
could not honour; scheduling lives in the dispatcher drivers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class StartRequest:
    """One EXEC CICS START. ``termid`` is "" for a non-terminal task (no TERMID
    coded), which is a distinct case from a START naming another terminal."""

    transid: str
    data: bytes = b""
    termid: str = ""
    reqid: str = ""
    timing_text: str = ""


class RejectReason(Enum):
    UNKNOWN_TRANSID = "unknown_transid"
    NO_SUCH_TERMINAL = "no_such_terminal"


class StartQueue:
    """FIFO of pending START requests, plus what this region refused or ignored.

    ``rejected`` and ``ignored_delays`` exist so a caller can ASSERT on what the
    runtime could not honour instead of reading logs for it (forge-p9t).
    """

    def __init__(self) -> None:
        self._pending: tuple[StartRequest, ...] = ()
        self._rejected: tuple[tuple[StartRequest, RejectReason], ...] = ()
        self._ignored_delays: tuple[StartRequest, ...] = ()
        self._start_data: tuple[bytes, ...] = ()

    def queue(self, req: StartRequest) -> None:
        self._pending = self._pending + (req,)
        if req.timing_text:
            self._ignored_delays = self._ignored_delays + (req,)

    def reject(self, req: StartRequest, reason: RejectReason) -> None:
        self._rejected = self._rejected + ((req, reason),)

    def pop_runnable(self, region_termid: str) -> tuple[StartRequest, ...]:
        """The first request this region can run, removed. Empty when there is none.

        Runnable means the request names this region's terminal, or names no
        terminal at all (a non-terminal task). One naming another terminal stays
        pending forever — this region has no channel for it.
        """
        runnable = [
            req
            for req in self._pending
            if req.termid in ("", region_termid)
        ]
        if not runnable:
            return ()
        taken = runnable[0]
        index = self._pending.index(taken)
        self._pending = self._pending[:index] + self._pending[index + 1 :]
        return (taken,)

    def put_start_data(self, data: bytes) -> None:
        self._start_data = (data,)

    def take_start_data(self) -> tuple[bytes, ...]:
        """The started task's data, consumed. Empty for a task nobody started."""
        taken = self._start_data
        self._start_data = ()
        return taken

    def discard_for_abend(self) -> None:
        """START requests are recoverable in CICS and back out with the unit of
        work. The rejected/ignored records are history, not pending work, and stay."""
        self._pending = ()
        self._start_data = ()

    @property
    def pending(self) -> tuple[StartRequest, ...]:
        return self._pending

    @property
    def rejected(self) -> tuple[tuple[StartRequest, RejectReason], ...]:
        return self._rejected

    @property
    def ignored_delays(self) -> tuple[StartRequest, ...]:
        return self._ignored_delays
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd cicada && uv run --no-sync python -m pytest tests/unit/cics/test_interval.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Format and commit**

```bash
cd cicada && make fmt
git add cics/interval.py tests/unit/cics/test_interval.py
git commit -m "feat(cics): add the interval-control start queue"
```

---

### Task 2: Terminal identity — `CicsContext.termid` and `EIBTERM`

**Files:**
- Modify: `cicada/cics/types.py:10-15`
- Modify: `cicada/cics/builtins/system.py:66-73`
- Test: `cicada/tests/integration/cics/test_interval_control.py` (new file)

**Interfaces:**
- Consumes: nothing.
- Produces: `CicsContext(transid, commarea, eibaid, termid: str = "")`; `EIBTERM` populated in WORKING-STORAGE at program entry.

`termid` is defaulted so the 36 existing `CicsContext(...)` construction sites keep working untouched. `EIBTERM` is already declared in `cics/copybooks/DFHEIBLK.cpy` and has never been written.

- [ ] **Step 1: Write the failing test (scenario S11)**

```python
"""Integration: EXEC CICS interval control — START and RETRIEVE scenarios.

Each scenario drives complete COBOL through the real compile + region path and
asserts DECODED DATA, never that a branch ran (see
docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md).
"""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.coprocessor import build_cics_spec
from cics.types import CicsContext, DispatchKind
from cics.dispatcher import run_cics
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature
from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar

_CICS_COPYBOOKS = Path(__file__).resolve().parents[3] / "cics" / "copybooks"


@pytest.fixture(autouse=True)
def _require_bridge_jar(bridge_jar):
    """Fails loudly when PROLEAP_BRIDGE_JAR is unset."""


@pytest.fixture
def cobol_parser(bridge_jar):
    runner = RealSubprocessRunner()
    return ProLeapCobolParser(runner, bridge_jar, copybook_dirs=[_CICS_COPYBOOKS])


COBOL_EIBTERM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMPRB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(4)  VALUE SPACES.
       PROCEDURE DIVISION.
           MOVE EIBTRMID TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_eibterm_is_readable_by_the_program(cobol_parser):
    """S11: EIBTRMID reaches the program, which START TERMID(EIBTRMID) needs."""
    context_holder = [
        CicsContext(transid="TRM0", commarea=b"", eibaid="\\x7d", termid="T001")
    ]
    result_holder: list = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(COBOL_EIBTERM.encode(), cobol_parser, spec)

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )

    assert result.kind == DispatchKind.RETURN
    assert result.commarea == "T001".encode("cp037")
```

Note: `EXEC CICS RETURN COMMAREA(...)` with no `TRANSID` yields `DispatchKind.RETURN`; the commarea still round-trips through `__cics_set_return_context`. If it does not, that is a real gap — fix `make_set_return_context_builtin` to carry the commarea on the no-transid branch as part of this task.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py::test_eibterm_is_readable_by_the_program -v`
Expected: FAIL — `TypeError: CicsContext.__init__() got an unexpected keyword argument 'termid'`

- [ ] **Step 3: Add `termid` to `CicsContext`**

In `cicada/cics/types.py`, replace the `CicsContext` body:

```python
@dataclass
class CicsContext:
    """Runtime state passed into each CICS program execution."""

    transid: str
    commarea: bytes
    eibaid: str  # 1-char attention identifier (e.g. "\\x7d" = DFHENTER)
    termid: str = ""  # "" == a non-terminal task (a START with no TERMID)
```

- [ ] **Step 4: Write `EIBTERM` in `__cics_init_eib`**

In `cicada/cics/builtins/system.py`, immediately after the `_write_field("EIBTRNID", ...)` line, add:

```python
        _write_field("EIBTERM", _ascii_to_ebcdic_bytes(ctx.termid, 4))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole cicada suite — nothing else may break**

Run: `cd cicada && make test`
Expected: PASS. A failure here means a `CicsContext` construction site or an EIB layout assertion needs updating.

- [ ] **Step 7: Commit**

```bash
git add cics/types.py cics/builtins/system.py tests/integration/cics/test_interval_control.py
git commit -m "feat(cics): give a task a terminal id and write EIBTERM"
```

---

### Task 3: `START` lowering and builtin — queue it, keep running

**Files:**
- Create: `cicada/cics/builtins/interval.py`
- Modify: `cicada/cics/strategy.py` (constructor ~`:400-470`, `lower` ~`:596`)
- Modify: `cicada/cics/coprocessor.py` — nothing to change; `build_cics_spec(**kwargs)` already forwards unknown keywords to the strategy.
- Test: `cicada/tests/integration/cics/test_interval_control.py`

**Interfaces:**
- Consumes: `StartQueue`, `StartRequest`, `RejectReason` from Task 1.
- Produces: builtin `__cics_start(transid, data, termid, reqid, timing)` returning a DFHRESP int; `make_start_builtin(start_queue: StartQueue, transid_to_program: dict[str, str], region_termid: str) -> object`; `CicsLoweringStrategy(..., start_queue=..., transid_to_program=..., region_termid=...)`.

The builtin returns a resp code and the lowering writes it back through `emit_resp_writeback` — the same contract every other CICS service verb uses. Crucially the lowering emits **no** `Return_()`.

- [ ] **Step 1: Write the failing tests**

Append to `cicada/tests/integration/cics/test_interval_control.py`:

```python
from cics.interval import RejectReason, StartQueue, StartRequest
from cics.strategy import CicsLoweringStrategy
from cics.preprocessor import apply_cics_prepass
from interpreter.cobol.cobol_frontend import CobolFrontend
from interpreter.instructions import Return_

COBOL_START_A = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-START-DATA.
           05  WS-SD-KEY   PIC X(6)  VALUE 'ACCT01'.
           05  WS-SD-AMT   PIC X(8)  VALUE '00012345'.
       01  WS-AFTER        PIC X(8)  VALUE SPACES.
       01  WS-CA           PIC X(8)  VALUE SPACES.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB')
                           TERMID(EIBTRMID)
                           FROM(WS-START-DATA)
                           LENGTH(14)
           END-EXEC.
           MOVE 'RANAFTER' TO WS-AFTER.
           MOVE WS-AFTER   TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


def _spec_with_queue(context_holder, result_holder, start_queue, transid_map):
    return build_cics_spec(
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        transid_to_program=transid_map,
        region_termid="T001",
    )


@covers(CobolFeature.EXEC_CICS)
def test_start_queues_the_request_and_the_program_keeps_running(cobol_parser):
    """S1 assertions 1 and 3, without a region: the request lands AND the
    statement after the START executes."""
    context_holder = [
        CicsContext(transid="SRTA", commarea=b"", eibaid="\\x7d", termid="T001")
    ]
    result_holder: list = [None]
    start_queue = StartQueue()
    spec = _spec_with_queue(
        context_holder, result_holder, start_queue, {"SRTB": "STARTB"}
    )
    program = compile_cics_program(COBOL_START_A.encode(), cobol_parser, spec)

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )

    assert start_queue.pending == (
        StartRequest(
            transid="SRTB",
            data="ACCT01" .encode("cp037") + "00012345".encode("cp037"),
            termid="T001",
        ),
    )
    # The MOVE after the START ran: START is not a task end.
    assert result.commarea == "RANAFTER".encode("cp037")


@covers(CobolFeature.EXEC_CICS)
def test_start_lowering_emits_no_return(cobol_parser):
    """The invariant no passing scenario can observe: if START ever emits a
    Return_ again, the program silently stops there."""
    context_holder = [
        CicsContext(transid="SRTA", commarea=b"", eibaid="\\x7d", termid="T001")
    ]
    strategy = CicsLoweringStrategy(
        context_holder=context_holder,
        result_holder=[None],
        start_queue=StartQueue(),
        transid_to_program={"SRTB": "STARTB"},
        region_termid="T001",
    )
    frontend = CobolFrontend(
        cobol_parser=cobol_parser,
        extension_strategies=[strategy],
    )
    program = frontend.compile_program(apply_cics_prepass(COBOL_START_A).encode())

    instructions = [i for f in program.functions for i in f.instructions]
    start_calls = [
        n
        for n, inst in enumerate(instructions)
        if getattr(inst, "func_name", None) == FuncName("__cics_start")
    ]
    assert start_calls, "no __cics_start call was emitted"
    after_start = instructions[start_calls[0] + 1 : start_calls[0] + 4]
    assert not any(isinstance(i, Return_) for i in after_start)
```

`FuncName` and `CobolFrontend` need importing at the top of the test module; `frontend.compile_program` mirrors `test_commarea_roundtrip.py`'s IR-level tests — copy its exact fixture usage if the signature differs.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py -v -k start`
Expected: FAIL — `TypeError: CicsLoweringStrategy.__init__() got an unexpected keyword argument 'start_queue'`

- [ ] **Step 3: Write the START builtin**

Create `cicada/cics/builtins/interval.py`:

```python
"""CICS interval-control builtins — START and RETRIEVE, closed over a StartQueue.

RETRIEVE fills the program's INTO buffer itself and returns only a response code,
the same "Option A" contract __cics_read uses (see cics/builtins/vsam.py).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cics.builtins.system import _get_ws_region_addr
from cics.interval import RejectReason, StartQueue, StartRequest
from interpreter.vm.vm_types import BuiltinResult, VMState

if TYPE_CHECKING:
    from interpreter.types.typed_value import TypedValue

logger = logging.getLogger(__name__)

_RESP_NORMAL = 0
_RESP_TERMIDERR = 11
_RESP_TRANSIDERR = 28
_RESP_ENDDATA = 29


def _text(args: list[TypedValue], i: int) -> str:
    return str(args[i].value).strip("'\\" ") if len(args) > i else ""


def _payload(args: list[TypedValue], i: int) -> bytes:
    v = args[i].value if len(args) > i else b""
    return (
        bytes(v)
        if isinstance(v, (bytes, bytearray, list))
        else str(v).encode("cp037", "replace")
    )


def make_start_builtin(
    start_queue: StartQueue,
    transid_to_program: dict[str, str],
    region_termid: str,
) -> object:
    """START: queues a start-request and returns a resp code.

    args: (transid_str, data_bytes, termid_str, reqid_str, timing_str)

    Deliberately does NOT end the task — the lowering emits no Return_, so the
    issuing program falls through to its next statement as in real CICS.
    """

    def __cics_start(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        req = StartRequest(
            transid=_text(args, 0),
            data=_payload(args, 1),
            termid=_text(args, 2),
            reqid=_text(args, 3),
            timing_text=_text(args, 4),
        )
        if req.transid not in transid_to_program:
            start_queue.reject(req, RejectReason.UNKNOWN_TRANSID)
            return BuiltinResult(value=_RESP_TRANSIDERR)
        if req.termid not in ("", region_termid):
            start_queue.reject(req, RejectReason.NO_SUCH_TERMINAL)
            return BuiltinResult(value=_RESP_TERMIDERR)
        start_queue.queue(req)
        return BuiltinResult(value=_RESP_NORMAL)

    return __cics_start
```

- [ ] **Step 4: Accept the new keywords in the strategy constructor**

In `cicada/cics/strategy.py`, add three keyword parameters to `CicsLoweringStrategy.__init__` alongside the existing `td_queue` / `program_cache` ones:

```python
        start_queue: StartQueue = StartQueue(),
        transid_to_program: dict[str, str] = {},
        region_termid: str = "",
```

Because `no-none-default-param` forbids `None` defaults, these take real empty defaults. A shared-mutable default is safe here only because the strategy never mutates them itself — it passes them to the builtin factory. Store them on `self` and register the builtin next to the other `_register` calls:

```python
        from cics.builtins.interval import make_start_builtin  # noqa: PLC0415

        _register(
            Builtins.TABLE,
            "__cics_start",
            make_start_builtin(start_queue, transid_to_program, region_termid),
        )
```

Import `StartQueue` at module top: `from cics.interval import StartQueue`.

- [ ] **Step 5: Lower the START verb**

In `CicsLoweringStrategy.lower`, immediately after the `if verb == "ABEND":` block returns and before the BMS section, add:

```python
        if verb == "START":
            r_transid = emit_operand_value(ctx, opts.get("TRANSID"), materialised)
            r_data = emit_copy_in(ctx, opts.get("FROM"), materialised)
            if r_data is None:
                r_data = ctx.fresh_reg()
                ctx.emit_inst(Const(result_reg=r_data, value=b"", type_expr=UNKNOWN))
            r_termid = emit_operand_value(ctx, opts.get("TERMID"), materialised)
            r_reqid = emit_operand_value(ctx, opts.get("REQID"), materialised)
            r_timing = ctx.fresh_reg()
            ctx.emit_inst(Const.string(r_timing, _timing_text(opts)))
            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName("__cics_start"),
                    args=(r_transid, r_data, r_termid, r_reqid, r_timing),
                )
            )
            emit_resp_writeback(ctx, r_res, opts, materialised)
            return
```

And a module-level helper next to `_resolve_into`:

```python
_TIMING_OPTIONS = ("INTERVAL", "AFTER", "AT", "HOURS", "MINUTES", "SECONDS")


def _timing_text(opts: dict[str, "CicsOperand | None"]) -> str:
    """The timing operands as written, or "" when none were coded.

    Recorded, never scheduled on: a region has no clock, so every START is
    dispatched as soon as the issuing task ends. Keeping the raw text lets a
    caller assert on what was asked for and ignored (StartQueue.ignored_delays).
    """
    present = [
        f"{name}({opts[name].text})" if opts.get(name) is not None else name
        for name in _TIMING_OPTIONS
        if name in opts
    ]
    return " ".join(present)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py -v`
Expected: PASS

- [ ] **Step 7: Confirm the "unimplemented verb" warning for START is gone**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py -v --log-cli-level=WARNING 2>&1 | grep -c "unimplemented verb 'START'"`
Expected: `0`

- [ ] **Step 8: Format and commit**

```bash
cd cicada && make fmt
git add cics/builtins/interval.py cics/strategy.py tests/integration/cics/test_interval_control.py
git commit -m "feat(cics): lower EXEC CICS START onto the start queue"
```

---

### Task 4: `RETRIEVE` lowering and builtin

**Files:**
- Modify: `cicada/cics/builtins/interval.py`
- Modify: `cicada/cics/strategy.py` (`lower`, next to the START branch)
- Test: `cicada/tests/integration/cics/test_interval_control.py`

**Interfaces:**
- Consumes: Task 1's `StartQueue.take_start_data`; Task 3's builtin module and registration site.
- Produces: builtin `__cics_retrieve(into_offset_int, into_length_int)` returning a DFHRESP int; `make_retrieve_builtin(start_queue: StartQueue) -> object`.

- [ ] **Step 1: Write the failing test (scenario S3)**

Append to the integration test module:

```python
COBOL_RETRIEVE_NO_DATA = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RTVNONE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN           PIC X(8)  VALUE 'UNTOUCHD'.
       01  WS-LEN          PIC S9(4) COMP VALUE 8.
       01  WS-CA.
           05  WS-CA-RESP  PIC S9(8) COMP.
           05  WS-CA-IN    PIC X(8).
       PROCEDURE DIVISION.
           EXEC CICS RETRIEVE INTO(WS-IN) LENGTH(WS-LEN) END-EXEC.
           MOVE EIBRESP TO WS-CA-RESP.
           MOVE WS-IN   TO WS-CA-IN.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_retrieve_with_no_start_data_yields_enddata(cobol_parser):
    """S3: a task nobody started gets ENDDATA and its INTO area is UNCHANGED."""
    import struct

    context_holder = [
        CicsContext(transid="RTV0", commarea=b"", eibaid="\\x7d", termid="T001")
    ]
    result_holder: list = [None]
    start_queue = StartQueue()
    spec = _spec_with_queue(context_holder, result_holder, start_queue, {})
    program = compile_cics_program(COBOL_RETRIEVE_NO_DATA.encode(), cobol_parser, spec)

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )

    assert result.commarea[:4] == struct.pack(">i", 29)  # DFHRESP(ENDDATA)
    assert result.commarea[4:12] == "UNTOUCHD".encode("cp037")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py::test_retrieve_with_no_start_data_yields_enddata -v`
Expected: FAIL — `EIBRESP` is 0, because `RETRIEVE` still falls through to the unimplemented-verb warning and emits no IR.

- [ ] **Step 3: Write the RETRIEVE builtin**

Append to `cicada/cics/builtins/interval.py`:

```python
def _write_into_ws(vm: VMState, data: bytes, offset: int, length: int) -> None:
    """Write ``data`` into the WORKING-STORAGE region at the INTO field's offset.

    Same Option-A buffer fill as the VSAM read builtins; see cics/builtins/vsam.py.
    """
    addr = _get_ws_region_addr(vm)
    if not addr:
        logger.warning("RETRIEVE: no __ws_region in VM — INTO not filled")
        return
    region = vm.region_get(addr)
    if not region:
        logger.warning("RETRIEVE: WS region not allocated — INTO not filled")
        return
    payload = data[:length].ljust(length, b"\\x00")
    region[offset : offset + length] = payload
    vm.region_set(addr, region)


def make_retrieve_builtin(start_queue: StartQueue) -> object:
    """RETRIEVE: consumes this task's start data into INTO; returns a resp code.

    args: (into_offset_int, into_length_int)

    ENDDATA when there is no start data — the normal case for a task entered from
    the terminal rather than by START. The INTO area is then left untouched.
    """

    def __cics_retrieve(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        into_off = int(args[0].value) if args else 0
        into_len = int(args[1].value) if len(args) > 1 else 0
        data = start_queue.take_start_data()
        if not data:
            return BuiltinResult(value=_RESP_ENDDATA)
        _write_into_ws(vm, data[0], into_off, into_len)
        return BuiltinResult(value=_RESP_NORMAL)

    return __cics_retrieve
```

- [ ] **Step 4: Register it and lower the verb**

In `strategy.py`, alongside the `__cics_start` registration:

```python
        _register(
            Builtins.TABLE, "__cics_retrieve", make_retrieve_builtin(start_queue)
        )
```

(extend the existing `from cics.builtins.interval import ...` line to include `make_retrieve_builtin`), and in `lower`, directly after the `START` branch:

```python
        if verb == "RETRIEVE":
            into_off, into_len = _resolve_into(ctx, opts.get("INTO"), materialised)
            r_off = ctx.fresh_reg()
            ctx.emit_inst(Const.int_(r_off, into_off))
            r_len = ctx.fresh_reg()
            ctx.emit_inst(Const.int_(r_len, into_len))
            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName("__cics_retrieve"),
                    args=(r_off, r_len),
                )
            )
            emit_resp_writeback(ctx, r_res, opts, materialised)
            return
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py -v`
Expected: PASS

- [ ] **Step 6: Format and commit**

```bash
cd cicada && make fmt
git add cics/builtins/interval.py cics/strategy.py tests/integration/cics/test_interval_control.py
git commit -m "feat(cics): lower EXEC CICS RETRIEVE, ENDDATA when nothing started the task"
```

---

### Task 5: The region drain — scenario S1 end to end

**Files:**
- Modify: `cicada/cics/dispatcher.py` — `CicsRegion.__init__`, `CicsRegion._dispatch`
- Modify: `cicada/cics/bootstrap.py` — create and thread the queue and terminal id
- Test: `cicada/tests/integration/cics/test_interval_control.py`

**Interfaces:**
- Consumes: `StartQueue.pop_runnable`, `StartQueue.put_start_data` (Task 1); the `START`/`RETRIEVE` verbs (Tasks 3–4).
- Produces: `CicsRegion(..., start_queue: StartQueue = StartQueue(), region_termid: str = "")`; a region that, after a task ends with a runnable start pending, is **not** done and whose next `step()` (called with **no** `input_event`, exactly as after an `XCTL`) runs the started task.

The turn-by-turn contract is unchanged: a started task needs no terminal input, so the caller omits `input_event` — the same convention `CicsRegion`'s docstring already states for `XCTL`.

- [ ] **Step 1: Write the failing test (scenario S1, full)**

```python
COBOL_START_B = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN.
           05  WS-IN-KEY   PIC X(6)  VALUE SPACES.
           05  WS-IN-AMT   PIC X(8)  VALUE SPACES.
       01  WS-LEN          PIC S9(4) COMP VALUE 14.
       01  WS-CA.
           05  WS-CA-CALEN PIC S9(4) COMP.
           05  WS-CA-KEY   PIC X(6).
           05  WS-CA-AMT   PIC X(8).
       PROCEDURE DIVISION.
           MOVE EIBCALEN TO WS-CA-CALEN.
           EXEC CICS RETRIEVE INTO(WS-IN) LENGTH(WS-LEN) END-EXEC.
           MOVE WS-IN-KEY TO WS-CA-KEY.
           MOVE WS-IN-AMT TO WS-CA-AMT.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_started_task_runs_and_retrieves_the_data(cobol_parser):
    """S1: the corpus idiom end to end through a region."""
    import struct
    from cics.dispatcher import CicsRegion, InputEvent

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTA", "SRTB": "STARTB"}
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
    program_cache = {
        "STARTA": compile_cics_program(COBOL_START_A.encode(), cobol_parser, spec),
        "STARTB": compile_cics_program(COBOL_START_B.encode(), cobol_parser, spec),
    }

    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
    )

    first = region.start("SRTA", input_event=InputEvent())
    assert first.kind == DispatchKind.RETURN
    assert first.commarea == "RANAFTER".encode("cp037")
    assert not region.done, "a runnable START was pending — the region is not done"
    assert region.transid == "SRTB"

    # No input_event: a started task needs no terminal input (as after an XCTL).
    second = region.step()

    assert second.kind == DispatchKind.RETURN
    assert second.commarea[0:2] == struct.pack(">h", 0)  # EIBCALEN == 0
    assert second.commarea[2:8] == "ACCT01".encode("cp037")
    assert second.commarea[8:16] == "00012345".encode("cp037")
    assert region.done
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py::test_started_task_runs_and_retrieves_the_data -v`
Expected: FAIL — `TypeError: CicsRegion.__init__() got an unexpected keyword argument 'start_queue'`

- [ ] **Step 3: Accept the queue in `CicsRegion.__init__`**

Add two keyword parameters after `min_commarea_len`:

```python
        start_queue: StartQueue = StartQueue(),
        region_termid: str = "",
```

and store them, plus the pending-next slot:

```python
        self._start_queue = start_queue
        self._region_termid = region_termid
        self._pending_next: tuple[str, Any, bytes] = ("", None, b"")
```

Import `StartQueue` at module top: `from cics.interval import StartQueue`.

- [ ] **Step 4: Pass the terminal id into every context the region builds**

In `CicsRegion._dispatch`, change the context construction to carry the terminal:

```python
        ctx = CicsContext(
            transid=self._transid,
            commarea=self._commarea,
            eibaid=eibaid,
            termid=self._task_termid,
        )
```

and add `self._task_termid: str = region_termid` in `__init__`. A started non-terminal task sets it to `""` in Step 5; every other task runs on the region's terminal.

- [ ] **Step 5: Drain the queue in `_dispatch`**

Replace the routing block at the end of `_dispatch` with:

```python
        routing = _advance_routing(
            result, self._transid, self._program_cache, self._transid_to_program
        )
        if isinstance(routing, DispatchResult):
            self._settle_terminal(routing)
        else:
            self._pending_next = ("", None, b"")
            self._adopt(routing)
        return result

    def _settle_terminal(self, routing: DispatchResult) -> None:
        """A task ended. Run what is runnable before waiting on terminal input:
        a started task needs none, a next-transid task does."""
        if routing.kind == DispatchKind.ABEND:
            self._start_queue.discard_for_abend()
            self._done = True
            return
        started = self._start_queue.pop_runnable(self._region_termid)
        if started:
            self._adopt_started(started[0])
            return
        if self._pending_next[0]:
            self._adopt(self._pending_next)
            self._pending_next = ("", None, b"")
            return
        self._done = True

    def _adopt(self, routing: "tuple[str, Any, bytes]") -> None:
        self._transid, self._program, next_commarea = routing
        self._task_termid = self._region_termid
        if len(next_commarea) < self._min_commarea_len:
            next_commarea = next_commarea.ljust(self._min_commarea_len, b"\\x00")
        self._commarea = next_commarea

    def _adopt_started(self, req: StartRequest) -> None:
        """A started task carries start data, no COMMAREA (so EIBCALEN is 0), and
        the terminal the START named — "" for a non-terminal task."""
        self._transid = req.transid
        self._program = self._program_cache[self._transid_to_program[req.transid]]
        self._commarea = b""
        self._task_termid = req.termid
        self._start_queue.put_start_data(req.data)
```

Import `StartRequest` alongside `StartQueue`.

- [ ] **Step 6: Stash the next-transid when a start is pending**

Still in `_dispatch`, the non-terminal (tuple) branch must not lose a `RETURN TRANSID` target when a started task is going to run first. Replace the `else:` branch body with:

```python
        else:
            if self._start_queue.pop_runnable_peek(self._region_termid):
                self._pending_next = routing
                started = self._start_queue.pop_runnable(self._region_termid)
                self._adopt_started(started[0])
            else:
                self._pending_next = ("", None, b"")
                self._adopt(routing)
```

and add the peek to `StartQueue` in `cics/interval.py`:

```python
    def pop_runnable_peek(self, region_termid: str) -> tuple[StartRequest, ...]:
        """Like pop_runnable, without removing — the drivers need to know whether
        a start will run before deciding what to do with a next-transid."""
        runnable = [
            req for req in self._pending if req.termid in ("", region_termid)
        ]
        return (runnable[0],) if runnable else ()
```

Add a unit test for the peek in `tests/unit/cics/test_interval.py`:

```python
def test_peek_does_not_remove():
    q = StartQueue()
    req = StartRequest(transid="SRTB", termid="T001")
    q.queue(req)

    assert q.pop_runnable_peek("T001") == (req,)
    assert q.pending == (req,)
```

- [ ] **Step 7: Thread the queue through bootstrap**

In `cicada/cics/bootstrap.py`, in `run_carddemo_region`, add a `region_termid: str = "T001"` keyword parameter, create the queue before `build_cics_spec`, and pass both:

```python
    start_queue = StartQueue()

    spec = build_cics_spec(
        context_holder=context_holder,
        result_holder=result_holder,
        vsam_engine=vsam_engine,
        screen_queue=screen_queue,
        input_queue=input_queue,
        applid=applid,
        sysid=sysid,
        start_queue=start_queue,
        transid_to_program=transid_to_program,
        region_termid=region_termid,
    )
```

and the entry context becomes
`CicsContext(transid=entry_transid, commarea=b"", eibaid="\\x7d", termid=region_termid)`.
Import `StartQueue` from `cics.interval`.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py tests/unit/cics/test_interval.py -v`
Expected: PASS

- [ ] **Step 9: Run the whole cicada suite**

Run: `cd cicada && make test`
Expected: PASS

- [ ] **Step 10: Format and commit**

```bash
cd cicada && make fmt
git add cics/dispatcher.py cics/bootstrap.py cics/interval.py tests/
git commit -m "feat(cics): dispatch a started task when the issuing task ends"
```

---

### Task 6: Runnable first — scenario S2

**Files:**
- Test: `cicada/tests/integration/cics/test_interval_control.py`
- Modify: `cicada/cics/dispatcher.py` only if the test fails

**Interfaces:**
- Consumes: Task 5's `_pending_next` slot and `_settle_terminal`.
- Produces: no new API. This task proves the ordering rule the slot exists for.

- [ ] **Step 1: Write the failing test**

```python
COBOL_START_THEN_TRANSID = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTA2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-START-DATA.
           05  WS-SD-KEY   PIC X(6)  VALUE 'ACCT01'.
           05  WS-SD-AMT   PIC X(8)  VALUE '00012345'.
       01  WS-CA           PIC X(8)  VALUE 'FROMSRTA'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB')
                           TERMID(EIBTRMID)
                           FROM(WS-START-DATA)
                           LENGTH(14)
           END-EXEC.
           EXEC CICS RETURN TRANSID('SRTC') COMMAREA(WS-CA) END-EXEC.
"""

COBOL_NEXT_TRANSID = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE SPACES.
       PROCEDURE DIVISION.
           MOVE 'RANSRTC0' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_started_task_runs_before_the_next_transid(cobol_parser):
    """S2: runnable first — SRTB needs no input, SRTC does, and the next-transid
    slot survives the started task."""
    from cics.dispatcher import CicsRegion, InputEvent

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTA2", "SRTB": "STARTB", "SRTC": "STARTC"}
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
    program_cache = {
        "STARTA2": compile_cics_program(
            COBOL_START_THEN_TRANSID.encode(), cobol_parser, spec
        ),
        "STARTB": compile_cics_program(COBOL_START_B.encode(), cobol_parser, spec),
        "STARTC": compile_cics_program(
            COBOL_NEXT_TRANSID.encode(), cobol_parser, spec
        ),
    }

    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
    )

    region.start("SRTA", input_event=InputEvent())
    assert region.transid == "SRTB", "the started task must run before SRTC"

    started = region.step()
    assert started.commarea[2:8] == "ACCT01".encode("cp037")
    assert region.transid == "SRTC", "the next-transid must survive the started task"
    assert not region.done

    last = region.step(input_event=InputEvent())
    assert last.commarea == "RANSRTC0".encode("cp037")
    assert region.done
```

- [ ] **Step 2: Run it**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py::test_started_task_runs_before_the_next_transid -v`
Expected: PASS if Task 5 Step 6 is correct. If it fails at `region.transid == "SRTB"`, the peek-then-stash branch is not running; if it fails at `region.transid == "SRTC"`, `_pending_next` is being cleared too early.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/cics/test_interval_control.py
git commit -m "test(cics): a started task runs before the next-transid"
```

---

### Task 7: Rejections — scenarios S5 and S6

**Files:**
- Test: `cicada/tests/integration/cics/test_interval_control.py`

**Interfaces:**
- Consumes: Task 3's `__cics_start` validation and `StartQueue.rejected`.
- Produces: no new API.

- [ ] **Step 1: Write the failing tests**

```python
COBOL_START_BAD_TRANSID = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTBT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('ZZZZ') TERMID(EIBTRMID) END-EXEC.
           MOVE EIBRESP TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""

COBOL_START_BAD_TERMID = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTBM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB') TERMID('P001') END-EXEC.
           MOVE EIBRESP TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


def _run_one(cobol_parser, source, transid_map, start_queue):
    context_holder = [
        CicsContext(transid="SRTA", commarea=b"", eibaid="\\x7d", termid="T001")
    ]
    result_holder: list = [None]
    spec = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
    )
    program = compile_cics_program(source.encode(), cobol_parser, spec)
    return run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )


@covers(CobolFeature.EXEC_CICS)
def test_start_to_an_unknown_transid_yields_transiderr(cobol_parser):
    """S6."""
    import struct

    start_queue = StartQueue()
    result = _run_one(
        cobol_parser, COBOL_START_BAD_TRANSID, {"SRTB": "STARTB"}, start_queue
    )

    assert result.commarea[:4] == struct.pack(">i", 28)  # TRANSIDERR
    assert start_queue.pending == ()
    assert start_queue.rejected[0][1] == RejectReason.UNKNOWN_TRANSID


@covers(CobolFeature.EXEC_CICS)
def test_start_for_another_terminal_yields_termiderr(cobol_parser):
    """S5: this region has no terminal P001, so the request never runs here."""
    import struct

    start_queue = StartQueue()
    result = _run_one(
        cobol_parser, COBOL_START_BAD_TERMID, {"SRTB": "STARTB"}, start_queue
    )

    assert result.commarea[:4] == struct.pack(">i", 11)  # TERMIDERR
    assert start_queue.pending == ()
    assert start_queue.rejected[0][1] == RejectReason.NO_SUCH_TERMINAL
```

- [ ] **Step 2: Run them**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py -v -k "transiderr or termiderr"`
Expected: PASS from Task 3's validation.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/cics/test_interval_control.py
git commit -m "test(cics): START rejects an unknown transid and an undefined terminal"
```

---

### Task 8: Non-terminal started tasks — scenario S4

**Files:**
- Modify: `cicada/cics/builtins/screen.py` — `make_send_map_builtin`, `make_receive_map_builtin`
- Modify: `cicada/cics/strategy.py` — pass `context_holder` into the two screen factories
- Test: `cicada/tests/integration/cics/test_interval_control.py`

**Interfaces:**
- Consumes: `CicsContext.termid` (Task 2); `_adopt_started` setting `_task_termid` to `""` (Task 5).
- Produces: `make_send_map_builtin(screen_queue, context_holder)` and `make_receive_map_builtin(input_queue, context_holder, ...)` — both gain a `context_holder` parameter and return `INVREQ` (16) when `context_holder[0].termid` is `""`.

- [ ] **Step 1: Write the failing test**

```python
COBOL_START_NOTERM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTNT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'FROMNTRM'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTD') END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""

COBOL_NONTERMINAL_TASK = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS SEND MAP('NOMAP') MAPSET('NOSET') END-EXEC.
           MOVE EIBRESP TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_non_terminal_started_task_runs_and_send_map_is_invreq(cobol_parser):
    """S4: a START with no TERMID runs, but terminal I/O is invalid for it."""
    import struct
    from cics.dispatcher import CicsRegion, InputEvent

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTNT", "SRTD": "STARTD"}
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
    program_cache = {
        "STARTNT": compile_cics_program(
            COBOL_START_NOTERM.encode(), cobol_parser, spec
        ),
        "STARTD": compile_cics_program(
            COBOL_NONTERMINAL_TASK.encode(), cobol_parser, spec
        ),
    }
    screen_queue: queue.Queue = queue.Queue()

    region = CicsRegion(
        program_cache,
        transid_map,
        screen_queue,
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
    )

    region.start("SRTA", input_event=InputEvent())
    assert region.transid == "SRTD"

    started = region.step()

    assert started.commarea[:4] == struct.pack(">i", 16)  # INVREQ
    assert screen_queue.empty(), "a non-terminal task must not write to the screen"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py::test_non_terminal_started_task_runs_and_send_map_is_invreq -v`
Expected: FAIL — `EIBRESP` is 0 and the screen queue is non-empty; `SEND MAP` currently writes regardless of terminal.

- [ ] **Step 3: Guard the screen builtins**

In `cicada/cics/builtins/screen.py`, add a module-level constant and helper:

```python
_RESP_INVREQ = 16


def _has_terminal(context_holder: list) -> bool:
    """A task started with no TERMID has no terminal; CICS makes terminal I/O
    invalid for it rather than writing somewhere arbitrary."""
    ctx = context_holder[0]
    return bool(ctx) and bool(ctx.termid)
```

Give `make_send_map_builtin` and `make_receive_map_builtin` a `context_holder: list` parameter and open each inner builtin with:

```python
        if not _has_terminal(context_holder):
            return BuiltinResult(value=_RESP_INVREQ)
```

- [ ] **Step 4: Pass `context_holder` at the registration sites**

In `strategy.py`, update the two `make_send_map_builtin(...)` / `make_receive_map_builtin(...)` calls to pass `context_holder` (the constructor already holds it as `self._context_holder`).

- [ ] **Step 5: Confirm SEND MAP writes back a resp**

`SEND MAP`'s lowering must call `emit_resp_writeback` for `EIBRESP` to receive the 16. Check the BMS branch in `lower`; if it does not, add `emit_resp_writeback(ctx, r_res, opts, materialised)` after the `CallFunction` for both map verbs.

- [ ] **Step 6: Run the tests**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/ -v`
Expected: PASS — including every existing BMS test, which runs with a terminal and must be unaffected.

- [ ] **Step 7: Format and commit**

```bash
cd cicada && make fmt
git add cics/builtins/screen.py cics/strategy.py tests/integration/cics/test_interval_control.py
git commit -m "feat(cics): terminal I/O is INVREQ in a non-terminal task"
```

---

### Task 9: Ignored delays, FIFO, and consume-once — scenarios S7, S9, S10

**Files:**
- Test: `cicada/tests/integration/cics/test_interval_control.py`

**Interfaces:**
- Consumes: `StartQueue.ignored_delays` (Task 1), `_timing_text` (Task 3), the region drain (Task 5).
- Produces: no new API.

- [ ] **Step 1: Write the failing tests**

```python
COBOL_START_INTERVAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTIV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'FROMIVAL'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB')
                           TERMID(EIBTRMID)
                           INTERVAL(000005)
           END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""

COBOL_START_TWICE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTTW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FIRST.
           05  FILLER      PIC X(6)  VALUE 'FIRST1'.
           05  FILLER      PIC X(8)  VALUE '00000001'.
       01  WS-SECOND.
           05  FILLER      PIC X(6)  VALUE 'SECND2'.
           05  FILLER      PIC X(8)  VALUE '00000002'.
       01  WS-CA           PIC X(8)  VALUE 'TWOSTART'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB') TERMID(EIBTRMID)
                           FROM(WS-FIRST) LENGTH(14) END-EXEC.
           EXEC CICS START TRANSID('SRTB') TERMID(EIBTRMID)
                           FROM(WS-SECOND) LENGTH(14) END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""

COBOL_RETRIEVE_TWICE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RTVTWICE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN           PIC X(14) VALUE SPACES.
       01  WS-LEN          PIC S9(4) COMP VALUE 14.
       01  WS-CA.
           05  WS-CA-FIRST PIC X(14).
           05  WS-CA-RESP2 PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS RETRIEVE INTO(WS-IN) LENGTH(WS-LEN) END-EXEC.
           MOVE WS-IN TO WS-CA-FIRST.
           EXEC CICS RETRIEVE INTO(WS-IN) LENGTH(WS-LEN) END-EXEC.
           MOVE EIBRESP TO WS-CA-RESP2.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_non_zero_interval_is_recorded_and_dispatched_immediately(cobol_parser):
    """S7."""
    start_queue = StartQueue()
    _run_one(cobol_parser, COBOL_START_INTERVAL, {"SRTB": "STARTB"}, start_queue)

    assert len(start_queue.pending) == 1
    assert len(start_queue.ignored_delays) == 1
    assert "INTERVAL" in start_queue.ignored_delays[0].timing_text


@covers(CobolFeature.EXEC_CICS)
def test_two_starts_run_in_order_each_with_its_own_data(cobol_parser):
    """S9."""
    from cics.dispatcher import CicsRegion, InputEvent

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTTW", "SRTB": "STARTB"}
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
    program_cache = {
        "STARTTW": compile_cics_program(
            COBOL_START_TWICE.encode(), cobol_parser, spec
        ),
        "STARTB": compile_cics_program(COBOL_START_B.encode(), cobol_parser, spec),
    }
    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
    )

    region.start("SRTA", input_event=InputEvent())
    first = region.step()
    assert first.commarea[2:8] == "FIRST1".encode("cp037")

    second = region.step()
    assert second.commarea[2:8] == "SECND2".encode("cp037")
    assert region.done


@covers(CobolFeature.EXEC_CICS)
def test_start_data_is_consumed_by_the_first_retrieve(cobol_parser):
    """S10: the second RETRIEVE in the same task gets ENDDATA."""
    import struct
    from cics.dispatcher import CicsRegion, InputEvent

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTA", "SRTB": "RTVTWICE"}
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
    program_cache = {
        "STARTA": compile_cics_program(COBOL_START_A.encode(), cobol_parser, spec),
        "RTVTWICE": compile_cics_program(
            COBOL_RETRIEVE_TWICE.encode(), cobol_parser, spec
        ),
    }
    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
    )

    region.start("SRTA", input_event=InputEvent())
    started = region.step()

    assert started.commarea[:6] == "ACCT01".encode("cp037")
    assert started.commarea[14:18] == struct.pack(">i", 29)  # ENDDATA
```

- [ ] **Step 2: Run them**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py -v -k "interval or two_starts or consumed"`
Expected: PASS. If `test_two_starts_run_in_order` fails on the second `step()`, `_settle_terminal` is not re-draining after a started task ends.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/cics/test_interval_control.py
git commit -m "test(cics): FIFO starts, consume-once data, recorded delays"
```

---

### Task 10: The runaway guard — scenario S8

**Files:**
- Modify: `cicada/cics/dispatcher.py` — `CicsRegion`
- Test: `cicada/tests/integration/cics/test_interval_control.py`

**Interfaces:**
- Consumes: Task 5's `_adopt_started`.
- Produces: `CicsRegion` abends with `abcode="ASTL"` after `_MAX_CONSECUTIVE_STARTS` (256) started-task dispatches without an intervening terminal input.

- [ ] **Step 1: Write the failing test**

```python
COBOL_START_SELF = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTLP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'LOOPING0'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTL') TERMID(EIBTRMID) END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_self_starting_transaction_hits_the_runaway_guard(cobol_parser):
    """S8: 'runnable first' has no terminal input to break the cycle, so the
    region must stop itself rather than spin."""
    from cics.dispatcher import CicsRegion, InputEvent

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTL": "STARTLP"}
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
    program_cache = {
        "STARTLP": compile_cics_program(COBOL_START_SELF.encode(), cobol_parser, spec)
    }
    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
    )

    region.start("SRTL", input_event=InputEvent())
    results = [region.step() for _ in range(300) if not region.done]

    assert region.done
    assert results[-1].kind == DispatchKind.ABEND
    assert results[-1].abcode == "ASTL"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py::test_a_self_starting_transaction_hits_the_runaway_guard -v`
Expected: FAIL — the region never sets `done`, so `results[-1]` is a plain `RETURN`.

- [ ] **Step 3: Add the guard**

In `cicada/cics/dispatcher.py`, add a module constant next to `_DFHENTER`:

```python
# "Runnable first" means a transaction that STARTs itself never waits for terminal
# input, so nothing breaks the cycle. Mirrors red-dragon's _RUNAWAY_GUARD: a cap
# far above any real flow, logged when it is what stopped the region.
_MAX_CONSECUTIVE_STARTS = 256
```

Initialise `self._consecutive_starts = 0` in `__init__`, reset it to `0` in `_adopt` (a task that came from routing or terminal input breaks the chain), and in `_adopt_started` count and check:

```python
    def _adopt_started(self, req: StartRequest) -> None:
        if self._consecutive_starts >= _MAX_CONSECUTIVE_STARTS:
            logger.error(
                "runaway guard: %d consecutive started tasks without terminal "
                "input (last transid %s) — abending ASTL",
                self._consecutive_starts,
                req.transid,
            )
            self._start_queue.discard_for_abend()
            self._done = True
            self._result_holder[0] = DispatchResult(
                kind=DispatchKind.ABEND, abcode="ASTL"
            )
            return
        self._consecutive_starts = self._consecutive_starts + 1
        self._transid = req.transid
        self._program = self._program_cache[self._transid_to_program[req.transid]]
        self._commarea = b""
        self._task_termid = req.termid
        self._start_queue.put_start_data(req.data)
```

The guard runs inside `_settle_terminal`, which is called with the just-finished task's `DispatchResult` already returned to the caller — so `_dispatch` must return the abend instead. Change `_settle_terminal` to return a `DispatchResult` and have `_dispatch` return that when it is set:

```python
        settled = self._settle_terminal(routing)
        return settled if settled else result
```

with `_settle_terminal` returning `DispatchResult(kind=DispatchKind.ABEND, abcode="ASTL")` on the guard path and an empty result otherwise. Model "no override" as a falsy `DispatchResult`-free path by returning `()`-style absence: declare it `-> tuple[DispatchResult, ...]` and return `()` or `(abend,)`, per the no-`None` constraint.

- [ ] **Step 4: Run the test**

Run: `cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py -v`
Expected: PASS, all scenarios.

- [ ] **Step 5: Format and commit**

```bash
cd cicada && make fmt
git add cics/dispatcher.py tests/integration/cics/test_interval_control.py
git commit -m "feat(cics): runaway guard for self-starting transactions"
```

---

### Task 11: The blocking dispatcher driver

**Files:**
- Modify: `cicada/cics/dispatcher.py` — `_run_dispatcher_with_runner`
- Test: `cicada/tests/unit/cics/test_dispatcher.py`

**Interfaces:**
- Consumes: `StartQueue.pop_runnable` / `pop_runnable_peek` (Tasks 1, 5).
- Produces: `_run_dispatcher_with_runner(..., start_queue: StartQueue = StartQueue(), region_termid: str = "")` draining the queue before it waits for input.

The ordering matters: the existing loop calls `_peek_input_event` (blocking, 30s) on `RETURN_TRANSID`. A pending start must be dispatched **before** that, or a started task would wait on terminal input that never comes.

- [ ] **Step 1: Write the failing test**

This driver takes an injected `run_fn`, so the test needs no COBOL. Append to `cicada/tests/unit/cics/test_dispatcher.py`:

```python
def test_loop_runs_a_started_task_before_waiting_for_input():
    """The blocking driver must drain the start queue BEFORE _peek_input_event,
    or a started task waits on terminal input that never arrives."""
    from cics.dispatcher import _run_dispatcher_with_runner
    from cics.interval import StartQueue, StartRequest

    start_queue = StartQueue()
    ran: list[str] = []

    def run_fn(program, context, sq, iq):
        ran.append(context.transid)
        if context.transid == "SRTA":
            start_queue.queue(StartRequest(transid="SRTB", termid="T001"))
            return DispatchResult(kind=DispatchKind.RETURN)
        return DispatchResult(kind=DispatchKind.RETURN)

    result = _run_dispatcher_with_runner(
        run_fn,
        {"STARTA": object(), "STARTB": object()},
        {"SRTA": "STARTA", "SRTB": "STARTB"},
        CicsContext(transid="SRTA", commarea=b"", eibaid="\\x7d", termid="T001"),
        queue.Queue(),
        queue.Queue(),
        start_queue=start_queue,
        region_termid="T001",
    )

    assert ran == ["SRTA", "SRTB"]
    assert result.kind == DispatchKind.RETURN
```

Match the imports (`queue`, `CicsContext`, `DispatchKind`, `DispatchResult`) to whatever the existing module already imports.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd cicada && uv run --no-sync python -m pytest tests/unit/cics/test_dispatcher.py::test_loop_runs_a_started_task_before_waiting_for_input -v`
Expected: FAIL — `TypeError: _run_dispatcher_with_runner() got an unexpected keyword argument 'start_queue'`

- [ ] **Step 3: Drain in the loop**

Add the two keyword parameters and, inside the `while True:` body, place the drain **before** the `RETURN_TRANSID` peek:

```python
        started = start_queue.pop_runnable(region_termid)
        if started:
            req = started[0]
            start_queue.put_start_data(req.data)
            program = program_cache[transid_to_program[req.transid]]
            context = CicsContext(
                transid=req.transid,
                commarea=b"",
                eibaid=context.eibaid,
                termid=req.termid,
            )
            continue
```

placed immediately after `result = run_fn(...)` and before the `if result.kind == DispatchKind.RETURN_TRANSID:` peek block. On `DispatchKind.ABEND`, call `start_queue.discard_for_abend()` before returning.

A `RETURN_TRANSID` result whose next-transid must survive a started task needs the same stash the region does; for this driver hold it in a local `pending_next: tuple[str, Any, bytes] = ("", None, b"")` and consult it when the queue drains empty.

- [ ] **Step 4: Run the tests**

Run: `cd cicada && uv run --no-sync python -m pytest tests/unit/cics/test_dispatcher.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `cd cicada && make test`
Expected: PASS

- [ ] **Step 6: Format and commit**

```bash
cd cicada && make fmt
git add cics/dispatcher.py tests/unit/cics/test_dispatcher.py
git commit -m "feat(cics): drain the start queue in the blocking dispatcher loop"
```

---

### Task 12: Full verification and issue close-out

**Files:**
- Modify: `issues/issues.jsonl` (regenerated)

- [ ] **Step 1: Run every gate**

```bash
cd ~/code/red-dragon-forge
cd cicada && make fmt && make test && cd ..
uv run lint-imports
make test-all
```

Expected: all suites pass; `lint-imports` reports contracts kept. `make test-all` needs Db2 up — `cd squall && make db2-up` (and `make db2-restart` if it reports `SQL30081N`).

- [ ] **Step 2: Confirm the verbs no longer hit the unimplemented path**

```bash
cd cicada && PROLEAP_BRIDGE_JAR=$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
  uv run --no-sync python -m pytest tests/integration/cics/test_interval_control.py \
  --log-cli-level=WARNING 2>&1 | grep "unimplemented verb"
```

Expected: no output.

- [ ] **Step 3: Close the bead and export**

```bash
cd ~/code/red-dragon-forge
bd close forge-9zb --reason="START and RETRIEVE implemented per docs/superpowers/specs/2026-09-02-cics-interval-control-design.md: queue-and-continue semantics, runnable-first dispatch, TERMID routing with EIBTERM, TRANSIDERR/TERMIDERR/ENDDATA/INVREQ conditions, recorded ignored delays, runaway guard."
bd export -o issues/issues.jsonl
git add issues/issues.jsonl
git commit -m "chore: close forge-9zb (CICS interval control)"
```

- [ ] **Step 4: Update the analysis document's status**

In `docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md`, the "Suggested order" section lists step 6 as `E, START + RETRIEVE`. Add a line to the *Status* section recording that step 6 is done, in the same form the existing entry uses for steps 1–5, and note that defect E's *policy* half (forge-p9t) and defect F (forge-5by, red-dragon-pz9g.12) remain open.

```bash
git add docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md
git commit -m "docs: record START/RETRIEVE as landed in the gap analysis"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: the queue and its records → Task 1; terminal id and `EIBTERM` → Task 2; `START` lowering, the no-`Return_` invariant and `TRANSIDERR`/`TERMIDERR` → Tasks 3, 7; `RETRIEVE` and `ENDDATA` → Task 4; ownership/bootstrap wiring → Task 5 Step 7; drain and runnable-first → Tasks 5, 6, 11; non-terminal tasks and `INVREQ` → Task 8; ignored delays → Task 9; runaway guard → Task 10; `discard_for_abend` on ABEND → Tasks 1, 5, 10. Scenarios S1–S11 all have a test: S1 Task 5, S2 Task 6, S3 Task 4, S4 Task 8, S5/S6 Task 7, S7/S9/S10 Task 9, S8 Task 10, S11 Task 2.

**Deviation from the spec, applied to both.** The spec's `StartRequest.delay_seconds: int` became `timing_text: str`. We never schedule on a delay, so parsing `hhmmss` buys nothing, and the raw operand text is a more honest record of what was requested and ignored. The spec has been updated to match.

**Known soft spots**, flagged rather than hidden:
- Task 2 Step 1 assumes `EXEC CICS RETURN COMMAREA(...)` without `TRANSID` carries the commarea. `make_set_return_context_builtin`'s no-args branch currently builds a bare `DispatchResult(kind=RETURN)` and the lowering passes no arguments in that case, so this probably needs the fix the task's note describes. Every scenario asserts through a returned commarea, so getting this right is load-bearing for the whole plan.
- Task 8 Step 5 asks the implementer to check whether the BMS lowering calls `emit_resp_writeback`; `_RESP_PRODUCING_VERBS` is currently `{"INQUIRE"}`, which suggests it does not, and `SEND MAP` will need it added.
- Task 10 Step 3's `_settle_terminal` return-type change touches code Task 5 wrote. If Task 5 landed `_settle_terminal` returning `None`, converting it to `tuple[DispatchResult, ...]` is part of Task 10, not a separate refactor.

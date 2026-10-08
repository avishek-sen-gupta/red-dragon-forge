# Dispatcher RETURN TRANSID Wait Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CICS autonomous dispatcher loop terminate with a clean `ABEND` instead of hanging forever when no further terminal input ever arrives after a `RETURN TRANSID`.

**Architecture:** Give `_peek_input_event` (`cics/dispatcher.py`) a hardcoded 30-second timeout on its underlying `queue.Queue.get()`, and have `_run_dispatcher_with_runner` catch the resulting `queue.Empty` and return `DispatchResult(kind=DispatchKind.ABEND, abcode="AZCT")` — mirroring the existing `TRNI`/`PGMI` early-return style two lines away in the same function.

**Tech Stack:** Python, `queue` (stdlib), pytest.

## Global Constraints

- CICS-layer-only fix: `cics/dispatcher.py` + tests. No changes to `cics/builtins/screen.py`, `CicsRegion`, or any RedDragon/VM core path.
- Timeout value: hardcoded to `30.0` as `_peek_input_event`'s own default parameter — do NOT thread it through `_run_dispatcher_with_runner`'s or `run_carddemo_region`'s signatures. This is a deliberate, explicit scope decision, not a placeholder to fill in later.
- Timeout abend code: `"AZCT"` — verified against real IBM CICS documentation (the actual transaction abend code for a terminal read-time-out condition). Do not use any other code.
- TDD: write the failing test before the implementation, for both new tests.
- Format before considering any task done: `uv run --no-sync python -m black cics tests`.
- Run tests via `uv run --no-sync python -m pytest ...` (never a bare `uv run`, which re-syncs and rebuilds the editable red-dragon wheel).
- Git: conservative policy — do not commit or push as part of any task step. Stage and report only; the user commits explicitly.

---

### Task 1: Unit test — `_peek_input_event` raises `queue.Empty` on a short timeout

**Files:**
- Modify (test only, add a new test function): `tests/unit/cics/test_dispatcher.py`

**Interfaces:**
- Consumes: `cics.dispatcher._peek_input_event` (existing, currently has no timeout parameter — this task's test targets the signature Task 2 will add: `_peek_input_event(input_queue, timeout: float = 30.0)`).
- Produces: nothing new — this test proves Task 2's parameter addition works, using a real (not mocked) `queue.Queue` and a short explicit override so the test runs in well under a second.

- [ ] **Step 1: Add the `pytest` import**

`tests/unit/cics/test_dispatcher.py` currently imports `queue` (line 4) but not `pytest`. `pytest.raises` is needed for this task's test. Change the top of the file from:

```python
"""Unit tests for run_cics() and the CICS dispatcher loop."""

import inspect
import queue
from unittest.mock import MagicMock
```

to:

```python
"""Unit tests for run_cics() and the CICS dispatcher loop."""

import inspect
import queue
from unittest.mock import MagicMock

import pytest
```

- [ ] **Step 2: Write the failing test**

Add to `tests/unit/cics/test_dispatcher.py` (append after `test_dispatcher_resume_leaves_event_on_queue_for_receive_map`, which is the most recently added test in this file and covers the same function). Note this uses the module-level `queue` import already present in the file (line 4), not a fresh local import:

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_peek_input_event_raises_empty_on_timeout():
    """_peek_input_event on an empty queue raises queue.Empty after its timeout,
    rather than blocking forever (red-dragon-pz9g.14)."""
    from cics.dispatcher import _peek_input_event

    empty_queue: queue.Queue = queue.Queue()
    with pytest.raises(queue.Empty):
        _peek_input_event(empty_queue, timeout=0.05)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --no-sync python -m pytest tests/unit/cics/test_dispatcher.py::test_peek_input_event_raises_empty_on_timeout -v`

Expected: FAIL with `TypeError: _peek_input_event() got an unexpected keyword argument 'timeout'` (the current signature is `_peek_input_event(input_queue: InputChannel) -> Any`, no `timeout` parameter).

- [ ] **Step 4: Commit is deferred to Task 4** (this test and Task 2's implementation land together, same pattern as the earlier `v2om`/`cicada-vcq` fixes this session — no permanently-red test sits alone).

---

### Task 2: Add the timeout to `_peek_input_event` and translate it to `ABEND` in `_run_dispatcher_with_runner`

**Files:**
- Modify: `cics/dispatcher.py:1-16` (imports) and `cics/dispatcher.py:114-161` (`_peek_input_event` and `_run_dispatcher_with_runner`).

**Interfaces:**
- Consumes: nothing new.
- Produces: `_peek_input_event(input_queue: InputChannel, timeout: float = 30.0) -> Any` (new signature — adds the `timeout` parameter Task 1's test exercises). `_run_dispatcher_with_runner` now returns `DispatchResult(kind=DispatchKind.ABEND, abcode="AZCT")` when the wait times out, in addition to its existing return paths.

- [ ] **Step 1: Add the `queue` stdlib import**

`cics/dispatcher.py` currently does not import `queue`. Add it to the import block at the top of the file. Change:

```python
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from lark import Lark, Transformer
```

to:

```python
import logging
import queue
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from lark import Lark, Transformer
```

- [ ] **Step 2: Give `_peek_input_event` a `timeout` parameter**

Change:

```python
def _peek_input_event(input_queue: InputChannel) -> Any:
    """Read the next InputEvent without consuming it — a later RECEIVE MAP still
    does the one real consume. Implemented as get-then-put-back rather than a
    protocol-level peek() because InputChannel (cics/terminal.py) is deliberately
    limited to put/get so it stays swappable with an out-of-process transport
    (socket, multiprocessing.Queue); those can't peek. Relies on the channel's
    synchronous, single-pending-item usage in this dispatcher (the driver never
    queues a second input before draining the screen produced by the first)."""
    event = input_queue.get()
    input_queue.put(event)
    return event
```

to:

```python
def _peek_input_event(input_queue: InputChannel, timeout: float = 30.0) -> Any:
    """Read the next InputEvent without consuming it — a later RECEIVE MAP still
    does the one real consume. Implemented as get-then-put-back rather than a
    protocol-level peek() because InputChannel (cics/terminal.py) is deliberately
    limited to put/get so it stays swappable with an out-of-process transport
    (socket, multiprocessing.Queue); those can't peek. Relies on the channel's
    synchronous, single-pending-item usage in this dispatcher (the driver never
    queues a second input before draining the screen produced by the first).

    Raises ``queue.Empty`` if no input arrives within ``timeout`` seconds — the
    caller (``_run_dispatcher_with_runner``) translates that into a clean ABEND
    instead of hanging forever (red-dragon-pz9g.14)."""
    event = input_queue.get(timeout=timeout)
    input_queue.put(event)
    return event
```

- [ ] **Step 3: Catch the timeout in `_run_dispatcher_with_runner` and return `ABEND`**

Change:

```python
        # On a pseudo-conversational RETURN TRANSID, the next turn's terminal
        # input arrives here (blocks). Its attention key seeds the next EIBAID;
        # the event itself is left on the queue for the resumed turn's own
        # RECEIVE MAP to consume (see _peek_input_event). CicsRegion doesn't need
        # this — see CicsRegion.dispatch.
        eibaid = context.eibaid
        if result.kind == DispatchKind.RETURN_TRANSID:
            event = _peek_input_event(input_queue)  # blocks
            eibaid = event.eibaid
```

to:

```python
        # On a pseudo-conversational RETURN TRANSID, the next turn's terminal
        # input arrives here (blocks, up to a timeout). Its attention key seeds
        # the next EIBAID; the event itself is left on the queue for the
        # resumed turn's own RECEIVE MAP to consume (see _peek_input_event).
        # CicsRegion doesn't need this — see CicsRegion.dispatch.
        eibaid = context.eibaid
        if result.kind == DispatchKind.RETURN_TRANSID:
            try:
                event = _peek_input_event(input_queue)
            except queue.Empty:
                # No further terminal input ever arrived — matches real CICS's
                # AZCT abend (terminal read-time-out condition) rather than
                # hanging the region forever (red-dragon-pz9g.14).
                return DispatchResult(kind=DispatchKind.ABEND, abcode="AZCT")
            eibaid = event.eibaid
```

- [ ] **Step 4: Run the Task 1 unit test to verify it now passes**

Run: `uv run --no-sync python -m pytest tests/unit/cics/test_dispatcher.py::test_peek_input_event_raises_empty_on_timeout -v`

Expected: PASS.

- [ ] **Step 5: Run the full unit suite to check for regressions**

Run: `uv run --no-sync python -m pytest tests/unit/ -x -q`

Expected: all tests pass (same count as before this change, plus Task 1's new test).

---

### Task 3: Unit test — `_run_dispatcher_with_runner` returns `ABEND`/`AZCT` on timeout

**Files:**
- Modify (test only, add a new test function): `tests/unit/cics/test_dispatcher.py`

**Interfaces:**
- Consumes: `cics.dispatcher._run_dispatcher_with_runner` (existing), `cics.dispatcher._peek_input_event` (Task 2's new signature — this test monkeypatches it, so the exact parameter list doesn't matter to this test, only that it raises `queue.Empty`).
- Produces: nothing new — this is the end-to-end proof (at the unit level, via monkeypatching) that a real timeout is translated into the right `DispatchResult`.

This test never waits any real time — it monkeypatches `_peek_input_event` itself to raise `queue.Empty` immediately, following the exact monkeypatching style already used for `run_cics` in `test_region_start_dispatches_entry_program` (`monkeypatch.setattr(dispatcher_mod, "run_cics", fake_run)`).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/cics/test_dispatcher.py` (append after Task 1's test):

```python
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dispatcher_return_transid_timeout_abends_azct(monkeypatch):
    """If no further terminal input ever arrives after RETURN TRANSID, the loop
    returns ABEND/AZCT instead of hanging forever (red-dragon-pz9g.14)."""

    def mock_run(program, ctx, sq, iq):
        return DispatchResult(
            kind=DispatchKind.RETURN_TRANSID, transid="CC01", commarea=b""
        )

    def fake_peek(input_queue, timeout=30.0):
        raise queue.Empty

    monkeypatch.setattr(dispatcher_mod, "_peek_input_event", fake_peek)

    program_cache = {"PROG1": MagicMock(), "PROG2": MagicMock()}
    transid_to_program = {"CC00": "PROG1", "CC01": "PROG2"}
    ctx = CicsContext(transid="CC00", commarea=b"", eibaid="\x7d")
    sq, iq = queue.Queue(), queue.Queue()

    result = _run_dispatcher_with_runner(
        mock_run, program_cache, transid_to_program, ctx, sq, iq
    )
    assert result.kind == DispatchKind.ABEND
    assert result.abcode == "AZCT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync python -m pytest tests/unit/cics/test_dispatcher.py::test_dispatcher_return_transid_timeout_abends_azct -v`

Expected: FAIL — before Task 2's `try/except queue.Empty:` is added, the `fake_peek`'s raised `queue.Empty` propagates uncaught out of `_run_dispatcher_with_runner` instead of being translated into a `DispatchResult`, so the test fails with an unhandled `queue.Empty` exception rather than reaching the `assert`.

(If Task 2 is already applied when this step runs — since these tasks land in the same working tree — this test will already PASS. That's fine; the important verification is that it's a real, meaningful assertion, confirmed either way.)

- [ ] **Step 3: Run this test with Task 2's fix in place to verify it passes**

Same command:

```bash
uv run --no-sync python -m pytest tests/unit/cics/test_dispatcher.py::test_dispatcher_return_transid_timeout_abends_azct -v
```

Expected: PASS.

- [ ] **Step 4: Run the full unit suite once more**

Run: `uv run --no-sync python -m pytest tests/unit/ -x -q`

Expected: all tests pass.

---

### Task 4: Full verification, formatting, beads bookkeeping

**Files:**
- Format: `cics/dispatcher.py`, `tests/unit/cics/test_dispatcher.py`.
- Beads: `red-dragon-pz9g.14` (close), `beads/issues.jsonl` (re-export).

- [ ] **Step 1: Format changed files**

```bash
uv run --no-sync python -m black cics tests
```

Expected: `All done!` — 0 or more files reformatted, no errors.

- [ ] **Step 2: Run the full unit suite**

```bash
uv run --no-sync python -m pytest tests/unit/ -x -q
```

Expected: all pass.

- [ ] **Step 3: Run the full CICS integration suite (regression check)**

```bash
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"
export PROLEAP_BRIDGE_JAR=~/code/cicada/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
export CARDDEMO_HOME=~/code/cicada/third-party/carddemo/app
uv run --no-sync python -m pytest tests/integration/cics/ -x -q
```

Expected: all pass, no regressions. (This change adds no new integration test — the design confirmed all existing callers of `run_carddemo_region` pre-populate their input queue before calling, so none of them reach the new timeout path; this run is purely a regression check.)

- [ ] **Step 4: Close `red-dragon-pz9g.14` in beads**

```bash
bd close red-dragon-pz9g.14 --reason="Fixed: _peek_input_event (cics/dispatcher.py) now takes a timeout parameter (hardcoded default 30.0s, not threaded/configurable per explicit scope decision) and _run_dispatcher_with_runner catches the resulting queue.Empty, returning DispatchResult(kind=DispatchKind.ABEND, abcode='AZCT') instead of hanging forever. AZCT verified against real IBM CICS documentation as the actual transaction abend code for a terminal read-time-out condition. Mirrors the existing TRNI/PGMI early-return style in the same function. TDD: tests/unit/cics/test_dispatcher.py::test_peek_input_event_raises_empty_on_timeout (direct, real queue.Queue, short override) + test_dispatcher_return_transid_timeout_abends_azct (monkeypatched, proves the ABEND/AZCT translation), both verified to fail without the fix. No existing test reaches the new timeout path (all pre-populate their input queue before calling), confirmed via full unit + integration suite regression run."
```

- [ ] **Step 5: Re-export the beads snapshot**

```bash
bd export -o beads/issues.jsonl
```

- [ ] **Step 6: Report status — do NOT commit**

Per this repo's conservative git policy, stop here. Run `git status` and `git diff --stat` and report the changed files to the user:

```bash
git status
git diff --stat
```

Report the list of modified/staged files (expected: `cics/dispatcher.py`, `tests/unit/cics/test_dispatcher.py`, `beads/issues.jsonl`) and wait for the user to explicitly request a commit/push.

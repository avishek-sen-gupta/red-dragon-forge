# Dispatcher RETURN TRANSID wait timeout — design

## Context

`red-dragon-pz9g.14` reports that the CICS autonomous dispatcher loop
(`cics/dispatcher.py`'s `_run_dispatcher_with_runner`, used by
`cics/bootstrap.py`'s `run_carddemo_region`) hangs forever on a `RETURN
TRANSID` turn transition if no further terminal input ever arrives — an
error-path re-entry with an empty input queue blocks indefinitely instead of
terminating cleanly. This was verified live and is still an open gap (unlike
several other issues investigated this session that turned out to already be
fixed): `cics/dispatcher.py:114-124`'s `_peek_input_event` helper — added
this session while fixing the unrelated `red-dragon-v2om` double-consume bug
— calls `input_queue.get()` with no timeout at all.

By contrast, `make_receive_map_builtin` (`cics/builtins/screen.py`) already
handles this correctly: it takes a `timeout: float = 30.0` parameter
(threaded from `CicsLoweringStrategy.__init__`'s `receive_timeout`), catches
`queue.Empty`, logs a warning, and returns gracefully instead of hanging.
`_peek_input_event`/`_run_dispatcher_with_runner` has no equivalent —
that asymmetry is this bug.

`CicsRegion` (the turn-by-turn API, where the caller supplies each
`InputEvent` directly and never blocks on the queue itself) is **not**
affected — this gap is specific to the autonomous, self-driving dispatcher
loop.

## Design

**1. Timeout value: hardcoded to 30.0s, not threaded from anywhere.**
`_peek_input_event` gains a `timeout: float = 30.0` parameter, matching
`receive_timeout`'s default numerically for consistency, but as a
genuinely separate, independent constant — no new parameter is added to
`_run_dispatcher_with_runner`'s or `run_carddemo_region`'s signatures. This
is a deliberate scope decision (not a placeholder): if this ever needs to
become configurable, that's a separate, future change.

**2. Timeout behavior: `DispatchKind.ABEND`, `abcode="AZCT"`.**
`_peek_input_event` passes `timeout=timeout` to `input_queue.get(...)`,
letting the stdlib's `queue.Empty` propagate naturally (mirrors
`make_receive_map_builtin`'s existing `except queue.Empty:` handling of the
identical condition). `_run_dispatcher_with_runner` wraps the call site in
`try/except queue.Empty:` and returns
`DispatchResult(kind=DispatchKind.ABEND, abcode="AZCT")` — following the
exact early-return style already used two lines away in the same function
for unknown-transid (`abcode="TRNI"`) and unknown-XCTL-program
(`abcode="PGMI"`).

`AZCT` was verified against real IBM CICS documentation (not assumed): it is
the actual transaction abend code CICS issues for "a terminal read-time-out
condition... detected when the transaction has been waiting for a terminal
input message for an interval longer than specified in the RTIMOUT value" —
an exact match for this scenario. (An earlier draft of this design proposed
`AICA`, which turned out on verification to mean something unrelated —
runaway-transaction/infinite-loop — and was corrected before this design was
finalized.)

## No downstream breakage

Confirmed by reading all current callers of `run_carddemo_region`
(`tests/unit/cics/test_bootstrap.py`, `tests/integration/cics/test_region_e2e.py`,
`tests/integration/cics/test_region_subprogram_link.py`): every one supplies
its `InputEvent`(s) synchronously via `queue.Queue.put(...)` *before* calling
`run_carddemo_region`, so by the time `_peek_input_event`'s blocking `get()`
runs, the item is already present — no existing test ever reaches the
timeout path, and none currently asserts anything other than
`DispatchKind.RETURN`, so introducing `DispatchKind.ABEND` on this new path
doesn't collide with any existing assertion.

## Testing

Neither new test waits the real 30 seconds:

1. **Direct test of `_peek_input_event`'s timeout behavior**: call it with an
   empty `queue.Queue()` and an explicit short override
   (`timeout=0.05`), assert it raises `queue.Empty` quickly. Exercises the
   real stdlib timeout path, not a mock.
2. **Test of `_run_dispatcher_with_runner`'s ABEND translation**: monkeypatch
   `_peek_input_event` (in `cics.dispatcher`) to raise `queue.Empty`
   immediately — the same monkeypatching style `tests/unit/cics/test_dispatcher.py`
   already uses for `run_cics`/`dispatcher_mod.run_cics` — and assert the
   loop returns `DispatchResult(kind=DispatchKind.ABEND, abcode="AZCT")`.

## Out of scope

- Making the 30s timeout configurable (parameter threading through
  `run_carddemo_region`/`CicsLoweringStrategy`) — explicit user decision to
  hardcode for now.
- Any change to `CicsRegion` — not affected by this bug.
- Any change to `make_receive_map_builtin`'s existing, already-correct
  timeout handling.

## Verification

- `uv run --no-sync python -m pytest tests/unit/cics/test_dispatcher.py -x -q`
  (fast, always runs — both new tests are unit-level with short/mocked
  timeouts).
- `uv run --no-sync python -m pytest tests/unit/ -x -q` for full-suite
  regression confirmation.
- With `JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home`,
  `PROLEAP_BRIDGE_JAR=vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar`,
  `CARDDEMO_HOME=third-party/carddemo/app`:
  `uv run --no-sync python -m pytest tests/integration/cics/ -x -q` — confirm
  no regressions in the real-COBOL suite.

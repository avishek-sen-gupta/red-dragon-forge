# CICS interval control: START and RETRIEVE

*2026-09-02 — design for forge-9zb*

## Why

`START` is the highest-volume unimplemented CICS verb in the production online
corpus (3,021 occurrences), and `RETRIEVE` — the verb that collects what a `START`
passed — accounts for another 920. Neither emits any IR today: both fall through
`CicsLoweringStrategy.lower`'s terminal `unimplemented verb` warning, so a `START`
schedules nothing and a `RETRIEVE` leaves its `INTO` area holding whatever was
there before. The program runs on and reports success. This is the flow-control
blocker for composing a multi-program corpus flow; see
`docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md` defect E.

The parser is not the problem. `cics_visitor.py` already maps `Start*`/`Retrieve*`
to `START`/`RETRIEVE`, and `_extract_options` already delivers `TRANSID`, `TERMID`,
`FROM`, `LENGTH`, `INTERVAL` and `REQID` (and `RETRIEVE`'s `INTO`/`LENGTH`) fully
parsed in `opts`. The work is lowering plus runtime plumbing.

## What START means

`START` is interval control: it asks CICS to run a *transaction* as a **separate
task**, while the issuing task carries on to its own `RETURN`.

* `TRANSID` names the transaction. `TERMID` attaches the new task to a terminal;
  with no `TERMID` the started task is **non-terminal** — it has no screen and
  terminal I/O is invalid for it.
* `FROM(area) LENGTH(n)` passes data, held in a start-request record. The started
  task collects it with `RETRIEVE INTO(...)`, which consumes it; data nobody
  retrieves is discarded.
* `INTERVAL`/`AFTER`/`AT` delay it; omitted or zero means as soon as possible.
  `REQID` names the request so a later `CANCEL` can kill it.

The corpus idiom is `START TRANSID(next) TERMID(EIBTRMID) FROM(state)` followed by
`RETURN` — a hand-off to the next transaction carrying data, an alternative to
`RETURN TRANSID` with a `COMMAREA`. That is why essentially every one of the 3,021
sits at a flow exit.

## Decisions

### START queues a request; the program keeps running

`__cics_start` appends to a region-held queue and emits **no** `Return_()`, so
execution falls through to the next statement as in real CICS. The alternative —
modelling `START` as a fifth terminal `DispatchKind` alongside `RETURN`,
`RETURN_TRANSID`, `XCTL` and `ABEND` — is cheaper and correct for every program
surveyed, but wrong the moment a program does work after a `START`, and 3,021
occurrences is far too many to assume none does. `START` is the first CICS verb
cicada lowers where the program is *not* ending.

### The drain lives in the drivers, not in `_advance_routing`

`_advance_routing` stays a pure function of a `DispatchResult` — it answers "given
this result, what runs next", and its docstring commits to being the single copy of
that rule. Draining the start queue is a different question: "this task has ended,
what is runnable now". It therefore lives in the two drivers,
`_run_dispatcher_with_runner` and `CicsRegion`, which already both route through
`_advance_routing` and are the only places that own a region's terminal.

### Runnable first

A task can end with `RETURN TRANSID` *and* leave a pending start-request. In real
CICS these are two schedulers converging on one terminal — a next-transid task
waits for the operator's AID, an interval-control request becomes an ATI honoured
when the terminal is free — so which runs first is a race against a human's wall
clock, and the combination is a programming error rather than a documented
ordering.

A region has no wall clock, so there is no race to reproduce; emulating one
deterministically would manufacture a certainty production does not have. The two
candidates are not symmetric, which supplies a rule that is not a coin flip:

> **Run what is runnable. What waits on input, waits.**

A started task needs no terminal input (its data comes from `RETRIEVE`), so it is
runnable the instant the issuing task ends. A next-transid task is not runnable
until an input event arrives. Hence:

```
task A: START TRANSID('MENU') TERMID(EIBTRMID)  -> queued
        RETURN TRANSID('MAIN')                  -> terminal.next_transid = 'MAIN'
        task ends
drain:  MENU is runnable now  -> dispatch, commarea=b"", start data in the slot
        MENU ends plain RETURN -> slot still holds 'MAIN'
next input arrives            -> MAIN runs
```

The terminal holds **one** `next_transid` slot (a `str`, `""` meaning unset) and a
later `RETURN TRANSID` overwrites it — matching CICS's single per-terminal
NEXTTRANSID.

### Timing is recorded, never scheduled on

Every start-request dispatches as soon as the issuing task ends, FIFO. The
timing operands are kept on the `StartRequest` verbatim as `timing_text` and any
request carrying them is surfaced on the queue as `ignored_delays`. Parsing the
`hhmmss` into seconds would buy nothing when nothing ever schedules on it; the raw
text is the more honest record of what was asked for and ignored.

A virtual clock ordering requests by expiry is the only design where two `START`s
with different delays run in the right order; it is deliberately out of scope, and
nothing else in the runtime needs a clock.

Recording rather than dropping is the forge-p9t rule applied locally: what the
runtime could not honour is a value a caller can assert on, not a log line.

### The region gets a terminal id

There is no terminal identity in the runtime today: `CicsContext` is
`(transid, commarea, eibaid)`, `EIBTERM` exists in `DFHEIBLK.cpy` and is never
written, and a region holds exactly one `ScreenChannel`/`InputChannel` pair. That
is enough to run a single flow but not to route a `START`, whose second-commonest
real use is a printer (`START TRANSID('PRNT') TERMID(printer)`). Dispatching a
printer transaction onto the user's screen, its `SEND MAP`s interleaved into their
flow, is exactly the silent-wrong-answer shape this work exists to remove.

So `CicsContext` gains `termid: str = ""` (defaulted — 36 construction sites stand
unchanged) and `make_init_eib_builtin` writes `EIBTERM`. This is also what the
corpus's own `START TERMID(EIBTRMID)` chaining idiom needs in order to work at all.

### No `None` in signatures

`.python-fp-lint/rules/` forbids `is None`, `is not None` and `None` default
parameters. Absence is therefore modelled as an empty tuple or an empty string
throughout, so callers branch on emptiness. `take_start_data` returning a tuple is
the better model regardless: CICS can have several start-requests queued for one
transaction, each with its own data, and `()` is precisely the `ENDDATA` case.

## Components

### `cics/interval.py` (new)

```python
@dataclass(frozen=True)
class StartRequest:
    transid: str
    data: bytes = b""
    termid: str = ""          # "" == non-terminal task (CICS: no TERMID coded)
    reqid: str = ""
    timing_text: str = ""     # the timing operands as written; never scheduled on

class RejectReason(Enum):
    UNKNOWN_TRANSID = "unknown_transid"    # TRANSIDERR
    NO_SUCH_TERMINAL = "no_such_terminal"  # TERMIDERR

class StartQueue:
    def queue(self, req: StartRequest) -> None
    def reject(self, req: StartRequest, reason: RejectReason) -> None
    def pop_runnable(self, region_termid: str) -> tuple[StartRequest, ...]  # 0 or 1
    def take_start_data(self) -> tuple[bytes, ...]                          # () == ENDDATA
    def discard_for_abend(self) -> None
    @property
    def rejected(self) -> tuple[tuple[StartRequest, RejectReason], ...]
    @property
    def ignored_delays(self) -> tuple[StartRequest, ...]
```

`pop_runnable` returns a request whose `termid` is either the region's terminal or
`""` (a non-terminal task); a request naming any other terminal is never queued —
see the conditions table.

### `cics/builtins/interval.py` (new)

Two builtins, wired by the `make_*_builtin(state)` closure pattern `td_queue` and
`result_holder` already use:

* `__cics_start(transid, data, termid, reqid, delay)` — validates, appends, returns.
  Emits no `Return_()`. Its factory is
  `make_start_builtin(start_queue, transid_to_program, region_termid)`: validating
  `TRANSID` needs the transid map and validating `TERMID` needs the region's own
  terminal id, both of which bootstrap holds when it constructs the strategy.
* `__cics_retrieve()` — `take_start_data()` written into the `INTO` operand through
  `_resolve_into` (`strategy.py:368`), the path `READ` and `READNEXT` already use,
  with `EIBRESP` via `emit_resp_writeback`.

### Ownership

`bootstrap` creates one `StartQueue` and hands the same object to
`CicsLoweringStrategy(start_queue=...)` — which captures it in the two builtin
factories — and to the dispatcher/region for the drain. This mirrors how
`context_holder`, `result_holder` and `td_queue` are threaded today.

### Non-terminal tasks

A started task with `termid == ""` is dispatched with no terminal. `SEND MAP` and
`RECEIVE MAP` from such a task raise `INVREQ`, as in CICS. This requires the screen
builtins to read the current `termid`, so `make_send_map_builtin` /
`make_receive_map_builtin` take `context_holder` (already threaded to other
builtins). `EIBTERM` for such a task is spaces.

## Conditions

`system.py` already carries `_RESP_NORMAL = 0` and `_RESP_PGMIDERR = 27`, which
confirms standard `DFHRESP` numbering; the codes below follow it.

| Case | `EIBRESP` | Queued? |
|---|---|---|
| `START` to an unknown transid | `TRANSIDERR` (28) | no; recorded in `rejected` |
| `START TERMID(x)`, region has no terminal `x` | `TERMIDERR` (11) | no; recorded in `rejected` |
| `START TERMID(<region's terminal>)` | `NORMAL` (0) | yes |
| `START` with no `TERMID` | `NORMAL` (0) | yes, as a non-terminal task |
| `RETRIEVE` with no start data | `ENDDATA` (29) | — |
| `SEND`/`RECEIVE MAP` in a non-terminal task | `INVREQ` (16) | — |

`HANDLE CONDITION` is a no-op today (forge-5by), so a program that does not code
`RESP` will sail past a rejection — which is why rejections are *also* recorded on
the queue for a caller to assert on. When condition raising lands, the abend-or-handler
behaviour becomes correct with no change here.

## Runaway guard

"Runnable first" means a program that `START`s its own transid loops the region
forever, with no terminal input to break it. A cap of 256 consecutive started-task
dispatches abends with a distinct code, mirroring red-dragon's `_RUNAWAY_GUARD`
precedent — and, as there, the guard being the terminating condition is logged, so
a future scheduling bug is loud rather than silent.

## ABEND

`START` requests are recoverable in CICS and back out with the unit of work. A task
that abends discards its pending start-requests via `discard_for_abend`, recorded
rather than dropped silently.

## Out of scope

Stated so the boundary is a decision rather than an omission:

* `CANCEL` and `REQID` beyond recording — `CANCEL` does not appear in the corpus at all.
* `RETRIEVE`'s `RTRANSID`, `RTERMID` and `QUEUE` options; the corpus uses
  `INTO`/`LENGTH` only. These route to the unsupported-option path, not silence.
* Multi-terminal regions, and therefore starts against another terminal.
* Any real or virtual clock, and so `INTERVAL`/`AFTER`/`AT` ordering.
* `SYSID` remote starts.

## Scenarios

No program in the in-repo corpus exercises these verbs — CardDemo's 44 programs
contain zero `EXEC CICS START` and zero `RETRIEVE` — so the scenarios below are
purpose-written. They follow the existing CICS integration harness
(`cicada/tests/integration/cics/`): inline COBOL source, `compile_cics_program`,
driven through a `CicsRegion`, asserting decoded EBCDIC rather than a branch.

Each scenario is a complete transaction pair. The region is built with
`termid='T001'` and a transid map covering the transactions named.

### S1 — the corpus idiom: hand off with data, and keep running

The headline scenario. This is the shape all 3,021 corpus `START`s take, and every
defect in this design would show up here.

```cobol
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
      * Proof the task did NOT end at the START: this must execute.
           MOVE 'RANAFTER' TO WS-AFTER.
           MOVE WS-AFTER   TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
```

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN.
           05  WS-IN-KEY   PIC X(6)  VALUE SPACES.
           05  WS-IN-AMT   PIC X(8)  VALUE SPACES.
       01  WS-LEN          PIC S9(4) COMP VALUE 14.
       01  WS-CA           PIC X(8)  VALUE SPACES.
       PROCEDURE DIVISION.
           EXEC CICS RETRIEVE INTO(WS-IN) LENGTH(WS-LEN) END-EXEC.
           MOVE WS-IN-KEY TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
```

Asserts, in order of what they would have caught:

1. `STARTB` **ran at all**, dispatched with no input event supplied.
2. Its `WS-IN` decodes to `ACCT01` / `00012345` — the data, not a branch flag.
3. `STARTA`'s `WS-AFTER` reached `RANAFTER`, proving `START` is not a task end.
4. `STARTB` entered with `EIBCALEN = 0` (a started task has no COMMAREA), which is
   the guard the corpus wraps every `RETRIEVE` in.

### S2 — runnable first

`STARTA2` issues `START TRANSID('SRTB')` and then ends with
`RETURN TRANSID('SRTC')`. Asserts `SRTB` runs **first**, with no input event, and
that `SRTC` then runs on the next input — the "run what is runnable" rule, and that
the `next_transid` slot survives the started task.

### S3 — ENDDATA on a task nobody started

A transaction entered from the terminal issues `RETRIEVE INTO(WS-IN)`. Asserts
`EIBRESP` decodes to 29 (`ENDDATA`) and `WS-IN` is **unchanged** from its `VALUE`
clause — the stale-data case that motivates the whole document.

### S4 — non-terminal started task

`START TRANSID('SRTD')` with no `TERMID`. Asserts the started task runs, and that a
`SEND MAP` inside it sets `EIBRESP` to 16 (`INVREQ`) rather than writing to the
issuing terminal's screen.

### S5–S9 — rejections, ordering and the guard

| # | Scenario | Asserts |
|---|---|---|
| S5 | `START TERMID('P001')`, region terminal is `T001` | `EIBRESP` 11 (`TERMIDERR`); not dispatched; in `rejected` |
| S6 | `START TRANSID('ZZZZ')`, not in the transid map | `EIBRESP` 28 (`TRANSIDERR`); not queued |
| S7 | `START ... INTERVAL(000005)` | dispatched immediately; recorded in `ignored_delays` |
| S8 | a transaction that `START`s its own transid | abends on the runaway guard with its distinct code, not an unbounded region |
| S9 | one task `START`s `SRTB` then `SRTC`, each with its own data | both run, in that order, each `RETRIEVE`ing **its own** bytes |

### S10 — start data is consumed once

A started task issues `RETRIEVE` twice. Asserts the first yields its data and the
second yields `ENDDATA` — `take_start_data` is a consume, not a peek.

### S11 — `EIBTERM` is readable

A program moves `EIBTRMID` into working storage and returns it in its COMMAREA;
asserts it decodes to `T001`. S1 depends on this working, since `TERMID(EIBTRMID)`
is how the corpus names its own terminal.

## Testing

TDD, and following the analysis document's own rule: a test asserts **decoded
data**, not that a branch ran. The scenarios above are the integration layer; the
unit layer below covers the queue in isolation.

* `StartQueue` FIFO ordering, and that it is FIFO *per region*, not per transid.
* The runnable/rejected split for each `termid` case, without a region.
* `take_start_data` yielding once and then `()` (S10's mechanism, isolated).
* `discard_for_abend` clearing pending requests while leaving `rejected` and
  `ignored_delays` intact — those are a record of what happened, not pending work.
* IR-level: `START` lowering emits **no** `Return_()`, asserted on the instruction
  stream. This is the one invariant that cannot be observed from a passing scenario
  — if it regressed, S1's assertion 3 would fail, but only S1 stands between a
  silent return to the old behaviour and nobody noticing.

Both drivers are covered: `CicsRegion` (what the forge integration tests drive, and
what the scenarios above run on) and `_run_dispatcher_with_runner`. S1 and S2 run
against both, since the drain is implemented separately in each — that duplication
is the price of keeping `_advance_routing` pure, and the tests are what stop the two
copies drifting.

## Follow-ups this does not close

* forge-5by — condition raising, which turns the table above from values a caller
  must inspect into control flow a program can rely on.
* forge-p9t — the unimplemented-verb policy; `START`/`RETRIEVE` leaving the
  fallthrough path does not fix the fallthrough.
* Screenless `SEND` support, a virtual clock, and multi-terminal regions, each
  listed as out of scope above.

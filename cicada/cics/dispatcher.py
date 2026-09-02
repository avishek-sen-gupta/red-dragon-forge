"""CICS transaction dispatcher — run_cics() and dispatcher loop."""

from __future__ import annotations

import logging
import queue
from dataclasses import dataclass, field
from typing import Any, Callable

from cics.csd_parse import parse_csd as parse_csd, parse_csd_files as parse_csd_files
from cics.interval import StartQueue, StartRequest
from cics.terminal import InputChannel, ScreenChannel
from cics.types import DEFAULT_TERMID, CicsContext, DispatchKind, DispatchResult
from cics.vm_init import make_cics_initial_vm, make_entry_point

logger = logging.getLogger(__name__)

_DFHENTER = "\x7d"

# Sentinel: "I was not given a queue — make my own". A plain StartQueue() default
# would be evaluated once at def time and shared by every region that omits it,
# and this code mutates the queue.
_OWN_START_QUEUE = StartQueue()

_NO_PENDING_NEXT: "tuple[str, Any, bytes]" = ("", (), b"")


@dataclass
class InputEvent:
    """Inbound terminal event — attention key + map field values."""

    eibaid: str = _DFHENTER
    fields: dict[str, str] = field(default_factory=dict)


def run_cics(
    program: Any,  # LinkedProgram — avoid circular import
    context: CicsContext,
    screen_queue: ScreenChannel,
    input_queue: InputChannel,
    *,
    context_holder: list[CicsContext],
    result_holder: list,
    max_steps: int = 50_000,
) -> DispatchResult:
    """Execute one CICS program with the given context. Returns DispatchResult."""
    from interpreter.run import run_linked  # noqa: PLC0415

    _prog_label = getattr(program, "entry_func_label", None)
    logger.info(
        "run_cics: program=%s transid=%s commarea=%d B",
        _prog_label or "?",
        context.transid,
        len(context.commarea),
    )

    context_holder[0] = context
    result_holder[0] = None

    initial_vm = make_cics_initial_vm(context, context.commarea)

    run_linked(
        program,
        make_entry_point(program),
        max_steps=max_steps,
        initial_vm=initial_vm,
    )

    result = (
        result_holder[0]
        if result_holder[0] is not None
        else DispatchResult(kind=DispatchKind.RETURN)
    )
    logger.info("run_cics done: %s", result.kind.name)
    return result


RunCicsFn = Callable[
    [Any, CicsContext, ScreenChannel, InputChannel],
    DispatchResult,
]


def _advance_routing(
    result: DispatchResult,
    current_transid: str,
    program_cache: dict[str, Any],
    transid_to_program: dict[str, str],
) -> "tuple[str, Any, bytes] | DispatchResult":
    """The single copy of the "which program/transid runs next" rule.

    Given a program's DispatchResult and the current transid, decide how routing
    proceeds. Returns either a ``(next_transid, next_program, next_commarea)``
    tuple (continue) or a terminal ``DispatchResult`` (RETURN / ABEND — stop).

      * RETURN_TRANSID: resolve the next program via ``transid_to_program``; the
        transid becomes the (stripped) returned transid. Unknown transid -> ABEND
        TRNI.
      * XCTL: switch to the named program; the transid CARRIES (same task).
        Unknown program -> ABEND PGMI.
      * anything else (RETURN / ABEND): terminal — returned unchanged.
    """
    if result.kind == DispatchKind.RETURN_TRANSID:
        next_transid = (result.transid or "").strip()
        next_prog_name = transid_to_program.get(next_transid)
        if not next_prog_name:
            logger.error("Unknown transid %r from RETURN TRANSID", result.transid)
            return DispatchResult(kind=DispatchKind.ABEND, abcode="TRNI")
        return (next_transid, program_cache[next_prog_name], result.commarea or b"")

    if result.kind == DispatchKind.XCTL:
        prog_name = (result.program or "").strip()
        if prog_name not in program_cache:
            logger.error("XCTL to unknown program %r", prog_name)
            return DispatchResult(kind=DispatchKind.ABEND, abcode="PGMI")
        return (current_transid, program_cache[prog_name], result.commarea or b"")

    return result


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


def _run_dispatcher_with_runner(
    run_fn: RunCicsFn,
    program_cache: dict[str, Any],
    transid_to_program: dict[str, str],
    initial_context: CicsContext,
    screen_queue: ScreenChannel,
    input_queue: InputChannel,
) -> DispatchResult:
    """Core dispatcher loop — separated for testability."""
    context = initial_context
    program = program_cache[transid_to_program[context.transid]]

    while True:
        result = run_fn(program, context, screen_queue, input_queue)

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

        routing = _advance_routing(
            result, context.transid, program_cache, transid_to_program
        )
        if isinstance(routing, DispatchResult):
            return routing

        next_transid, program, next_commarea = routing
        context = CicsContext(
            transid=next_transid,
            commarea=next_commarea,
            eibaid=eibaid,
            termid=initial_context.termid,
        )


class CicsRegion:
    """Turn-by-turn CICS dispatch API.

    Models a running CICS region as an explicit state machine over the same
    routing rule the dispatcher loop uses (`_advance_routing`). Instead of an
    unbounded blocking loop, the caller drives one turn at a time:

      * ``start(entry_transid, ...)`` — begin a task on ``entry_transid`` and run
        its first program.
      * ``step(...)`` — run the CURRENT (program, transid, commarea) again.

    The caller supplies an ``input_event`` on the entry turn and on each turn
    that follows a RETURN_TRANSID (a fresh terminal input), and OMITS it after an
    XCTL (same task, no new terminal input — the XCTL'd program runs immediately).
    This mirrors CICS pseudo-conversational reality.

    Unlike ``_run_dispatcher_with_runner``, this does NOT do a separate
    ``input_queue.get()`` for the EIBAID: the supplied ``input_event`` is both put
    on the queue (for RECEIVE MAP) AND used directly to seed the context's eibaid.
    """

    def __init__(
        self,
        program_cache: dict[str, Any],
        transid_to_program: dict[str, str],
        screen_queue: ScreenChannel,
        input_queue: InputChannel,
        *,
        context_holder: list,
        result_holder: list,
        max_steps: int = 50_000,
        min_commarea_len: int = 0,
        start_queue: StartQueue = _OWN_START_QUEUE,
        region_termid: str = DEFAULT_TERMID,
    ) -> None:
        self._program_cache = program_cache
        self._transid_to_program = transid_to_program
        self._screen_queue = screen_queue
        self._input_queue = input_queue
        self._context_holder = context_holder
        self._result_holder = result_holder
        self._max_steps = max_steps
        # Optional minimum commarea length applied to the commarea handed to each
        # FOLLOW-ON turn (after start). A program that XCTLs/RETURNs with a short
        # commarea but whose successor indexes a larger CARDDEMO-COMMAREA needs
        # EIBCALEN to cover those fields; pad to this length so the successor's
        # field reads land in-bounds. The entry commarea passed to start() is
        # used as-is (the entry program's own EIBCALEN is authoritative).
        self._min_commarea_len = min_commarea_len

        self._start_queue = (
            StartQueue() if start_queue is _OWN_START_QUEUE else start_queue
        )
        self._region_termid = region_termid

        self._transid: str = ""
        self._program: Any = None
        self._commarea: bytes = b""
        self._task_termid: str = region_termid
        self._last_eibaid: str = _DFHENTER
        self._done: bool = False
        # A RETURN TRANSID target parked because a started task, which needs no
        # terminal input, runs before it. The terminal holds one such slot.
        self._pending_next: "tuple[str, Any, bytes]" = _NO_PENDING_NEXT

    @property
    def transid(self) -> str:
        """The current transid (for assertions if wanted)."""
        return self._transid

    @property
    def done(self) -> bool:
        """True once a terminal (RETURN / ABEND) result has been produced."""
        return self._done

    def start(
        self,
        entry_transid: str,
        *,
        commarea: bytes = b"",
        input_event: "InputEvent | None" = None,
        max_steps: int | None = None,
    ) -> DispatchResult:
        """Begin a task on ``entry_transid`` and dispatch its first program."""
        logger.info(
            "region.start: transid=%s commarea=%d B", entry_transid, len(commarea)
        )
        self._transid = entry_transid
        self._commarea = commarea
        self._program = self._program_cache[self._transid_to_program[entry_transid]]
        self._task_termid = self._region_termid
        self._pending_next = _NO_PENDING_NEXT
        self._done = False
        return self._dispatch(input_event=input_event, max_steps=max_steps)

    def step(
        self,
        *,
        input_event: "InputEvent | None" = None,
        max_steps: int | None = None,
    ) -> DispatchResult:
        """Dispatch the CURRENT (program, transid, commarea). Requires not done."""
        if self._done:
            raise RuntimeError("step() called on a region that has terminated")
        _nfields = len(input_event.fields) if input_event is not None else 0
        _eibaid = repr(input_event.eibaid) if input_event is not None else "(none)"
        logger.info(
            "region.step: transid=%s eibaid=%s fields=%d",
            self._transid,
            _eibaid,
            _nfields,
        )
        return self._dispatch(input_event=input_event, max_steps=max_steps)

    def _dispatch(
        self,
        *,
        input_event: "InputEvent | None",
        max_steps: int | None,
    ) -> DispatchResult:
        eibaid = input_event.eibaid if input_event is not None else self._last_eibaid
        ctx = CicsContext(
            transid=self._transid,
            commarea=self._commarea,
            eibaid=eibaid,
            termid=self._task_termid,
        )
        if input_event is not None:
            # The program's RECEIVE MAP consumes this (fields + eibaid). We do NOT
            # do a separate get() for eibaid — the context already carries it.
            self._input_queue.put(input_event)
        self._last_eibaid = eibaid

        result = run_cics(
            self._program,
            ctx,
            self._screen_queue,
            self._input_queue,
            context_holder=self._context_holder,
            result_holder=self._result_holder,
            max_steps=self._max_steps if max_steps is None else max_steps,
        )

        routing = _advance_routing(
            result, self._transid, self._program_cache, self._transid_to_program
        )
        if isinstance(routing, DispatchResult):
            self._settle_terminal(routing)
        elif result.kind == DispatchKind.XCTL:
            # XCTL transfers control WITHIN the same task: the task has not ended,
            # so no started task may run yet, and the task keeps its own terminal.
            self._adopt(routing, self._task_termid)
        elif self._start_queue.pop_runnable_peek(self._region_termid):
            self._pending_next = routing
            self._adopt_started(self._start_queue.pop_runnable(self._region_termid)[0])
        else:
            self._pending_next = _NO_PENDING_NEXT
            self._adopt(routing, self._region_termid)
        return result

    def _settle_terminal(self, routing: DispatchResult) -> None:
        """A task ended. Run what is runnable before waiting on terminal input:
        a started task needs none, a next-transid task does."""
        if routing.kind == DispatchKind.ABEND:
            self._start_queue.discard_for_abend()
            self._done = True
            logger.info("dispatch → terminal %s", routing.kind.name)
            return
        started = self._start_queue.pop_runnable(self._region_termid)
        if started:
            self._adopt_started(started[0])
            return
        if self._pending_next[0]:
            self._adopt(self._pending_next, self._region_termid)
            self._pending_next = _NO_PENDING_NEXT
            return
        self._done = True
        logger.info("dispatch → terminal %s", routing.kind.name)

    def _adopt(self, routing: "tuple[str, Any, bytes]", task_termid: str) -> None:
        """``task_termid`` is the region's terminal for a fresh next-transid task,
        and the CURRENT task's terminal for an XCTL, which does not start a task."""
        self._transid, self._program, next_commarea = routing
        self._task_termid = task_termid
        if len(next_commarea) < self._min_commarea_len:
            next_commarea = next_commarea.ljust(self._min_commarea_len, b"\x00")
        self._commarea = next_commarea
        logger.info(
            "dispatch → transid=%s commarea=%d B",
            self._transid,
            len(self._commarea),
        )

    def _adopt_started(self, req: StartRequest) -> None:
        """A started task carries start data, no COMMAREA (so EIBCALEN is 0), and
        the terminal the START named — NO_TERMINAL for a non-terminal task."""
        self._transid = req.transid
        self._program = self._program_cache[self._transid_to_program[req.transid]]
        self._commarea = b""
        self._task_termid = req.termid
        self._start_queue.put_start_data(req.data)
        logger.info("dispatch → started transid=%s termid=%r", req.transid, req.termid)

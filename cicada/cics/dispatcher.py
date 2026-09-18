"""CICS transaction dispatcher — run_cics() and dispatcher loop."""

from __future__ import annotations

import logging
import queue
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from itertools import accumulate, repeat
from typing import TYPE_CHECKING, Generic, NamedTuple, TypeAlias, TypeVar

from cics.cell import Cell, Holder, held_or, hold
from cics.csd_parse import parse_csd as parse_csd
from cics.csd_parse import parse_csd_files as parse_csd_files
from cics.input_event import DFHENTER
from cics.input_event import InputEvent as InputEvent
from cics.interval import StartQueue, StartRequest
from cics.terminal import InputChannel, ScreenChannel
from cics.types import DEFAULT_TERMID, CicsContext, DispatchKind, DispatchResult
from cics.vm_init import make_cics_initial_vm, make_entry_point

if TYPE_CHECKING:
    from interpreter.project.types import LinkedProgram

logger = logging.getLogger(__name__)

P = TypeVar("P")

# A transaction that STARTs its own transid never waits for terminal input, so
# nothing in the region breaks the cycle. Mirrors red-dragon's _RUNAWAY_GUARD: a
# cap far above any real flow, logged when it is what stopped the region, so a
# scheduling bug is loud rather than a hang. The cap counts started tasks
# ADOPTED, and the guard refuses the adoption that would exceed it, so a region
# doing nothing but started tasks stops on its (cap + 1)-th such dispatch.
_MAX_CONSECUTIVE_STARTS = 256
_RUNAWAY_ABCODE = "ASTL"
_USE_REGION_MAX_STEPS = -1

_NO_OVERRIDE: tuple[DispatchResult, ...] = ()


@dataclass(frozen=True)
class NoInput:
    """No terminal input this turn, as after an XCTL. Distinct from
    ``InputEvent()``, which is a real ENTER with no fields."""


NO_INPUT = NoInput()


@dataclass(frozen=True)
class NoProgram:
    pass


NO_PROGRAM = NoProgram()


class NextTask(NamedTuple, Generic[P]):
    transid: str
    program: P
    commarea: bytes


@dataclass(frozen=True)
class NoPendingTask:
    pass


NO_PENDING_TASK = NoPendingTask()

PendingTask: TypeAlias = "NextTask[LinkedProgram] | NoPendingTask"


def run_cics(
    program: LinkedProgram,
    context: CicsContext,
    screen_queue: ScreenChannel,
    input_queue: InputChannel,
    *,
    context_holder: Holder[CicsContext],
    result_holder: Holder[DispatchResult],
    max_steps: int = 50_000,
) -> DispatchResult:
    """Execute one CICS program with the given context. Returns DispatchResult."""
    from interpreter.run import run_linked

    logger.info(
        "run_cics: program=%s transid=%s commarea=%d B",
        getattr(program, "entry_func_label", None) or "?",
        context.transid,
        len(context.commarea),
    )
    hold(context_holder, context)
    hold(result_holder, None)
    run_linked(
        program,
        make_entry_point(program),
        max_steps=max_steps,
        initial_vm=make_cics_initial_vm(context, context.commarea),
    )
    result = held_or(result_holder, DispatchResult(kind=DispatchKind.RETURN))
    logger.info("run_cics done: %s", result.kind.name)
    return result


RunCicsFn = Callable[
    ["LinkedProgram", CicsContext, ScreenChannel, InputChannel],
    DispatchResult,
]


def _route_return_transid(
    result: DispatchResult,
    program_cache: Mapping[str, P],
    transid_to_program: Mapping[str, str],
) -> NextTask[P] | DispatchResult:
    next_transid = (result.transid or "").strip()
    next_prog_name = transid_to_program.get(next_transid)
    if not next_prog_name:
        logger.error("Unknown transid %r from RETURN TRANSID", result.transid)
        return DispatchResult(kind=DispatchKind.ABEND, abcode="TRNI")
    return NextTask(next_transid, program_cache[next_prog_name], result.commarea or b"")


def _route_xctl(
    result: DispatchResult,
    current_transid: str,
    program_cache: Mapping[str, P],
) -> NextTask[P] | DispatchResult:
    prog_name = (result.program or "").strip()
    if prog_name not in program_cache:
        logger.error("XCTL to unknown program %r", prog_name)
        return DispatchResult(kind=DispatchKind.ABEND, abcode="PGMI")
    return NextTask(current_transid, program_cache[prog_name], result.commarea or b"")


def _advance_routing(
    result: DispatchResult,
    current_transid: str,
    program_cache: Mapping[str, P],
    transid_to_program: Mapping[str, str],
) -> NextTask[P] | DispatchResult:
    """The single copy of the "which program/transid runs next" rule.

    Given a program's DispatchResult and the current transid, decide how routing
    proceeds. Returns either a ``NextTask`` (continue) or a terminal
    ``DispatchResult`` (RETURN / ABEND — stop).

      * RETURN_TRANSID: resolve the next program via ``transid_to_program``; the
        transid becomes the (stripped) returned transid. Unknown transid -> ABEND
        TRNI.
      * XCTL: switch to the named program; the transid CARRIES (same task).
        Unknown program -> ABEND PGMI.
      * anything else (RETURN / ABEND): terminal — returned unchanged.
    """
    if result.kind == DispatchKind.RETURN_TRANSID:
        return _route_return_transid(result, program_cache, transid_to_program)
    if result.kind == DispatchKind.XCTL:
        return _route_xctl(result, current_transid, program_cache)
    return result


def _peek_input_event(input_queue: InputChannel, timeout: float = 30.0) -> InputEvent:
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


def _discard_pending_input(input_queue: InputChannel) -> None:
    """Drop terminal input the ending task never RECEIVEd.

    In CICS the terminal input area belongs to the task: a task that ends
    without a RECEIVE leaves nothing behind, and the next task reads the
    terminal afresh. CardDemo relies on it — COACTUPC's PF3 branch
    (COACTUPC.cbl:927-959) decides on EIBAID alone and XCTLs to COMEN01C with
    no RECEIVE MAP anywhere on that path, so the PF3 event would otherwise
    still be queued when the NEXT task's RECEIVE MAP runs and would be read in
    place of the operator's actual keystroke (forge-1zu.6).

    Drains by ``get(block=False)`` until :class:`queue.Empty` because
    ``InputChannel`` is deliberately limited to put/get (see cics/terminal.py):
    there is no ``qsize`` or ``empty`` to consult. What it drops is logged —
    silently swallowing a keystroke is exactly what made this defect hard to
    see."""
    for _ in repeat(None):
        try:
            dropped = input_queue.get(block=False)
        except queue.Empty:
            return
        logger.info(
            "task end: dropping unreceived terminal input aid=%r",
            getattr(dropped, "eibaid", None),
        )


def _runaway_abend(req: StartRequest, consecutive_starts: int) -> DispatchResult:
    """The runaway guard's refusal. Both drivers implement the RULE separately —
    what breaks a chain of started tasks differs between them — but the refusal
    itself is one thing, and the count plus the transid it refused are the only
    way to tell a runaway from a slow region in a log."""
    logger.error(
        "runaway guard: %d consecutive started tasks with no terminal "
        "input (next transid %s) — abending %s",
        consecutive_starts,
        req.transid,
        _RUNAWAY_ABCODE,
    )
    return DispatchResult(kind=DispatchKind.ABEND, abcode=_RUNAWAY_ABCODE)


@dataclass(frozen=True)
class _LoopTurn:
    program: LinkedProgram
    context: CicsContext
    pending_next: PendingTask
    consecutive_starts: int


_LoopState = _LoopTurn | DispatchResult


@dataclass(frozen=True)
class _DispatchLoop:
    run_fn: RunCicsFn
    program_cache: Mapping[str, LinkedProgram]
    transid_to_program: Mapping[str, str]
    screen_queue: ScreenChannel
    input_queue: InputChannel
    start_queue: StartQueue
    region_termid: str
    max_consecutive_starts: int
    terminal_termid: str

    def advance(self, state: _LoopState, _tick: None) -> _LoopState:
        return self.turn(state) if isinstance(state, _LoopTurn) else state

    def turn(self, state: _LoopTurn) -> _LoopState:
        result = self.run_fn(
            state.program, state.context, self.screen_queue, self.input_queue
        )
        routing = _advance_routing(
            result, state.context.transid, self.program_cache, self.transid_to_program
        )
        if isinstance(routing, DispatchResult):
            return self._after_terminal(state, routing)
        if result.kind == DispatchKind.XCTL:
            return self._xctl(state, routing)
        return self._after_task(state, routing)

    def _after_terminal(self, state: _LoopTurn, routing: DispatchResult) -> _LoopState:
        if routing.kind == DispatchKind.ABEND:
            self.start_queue.discard_for_abend()
            return routing
        pending = state.pending_next
        return self._after_task(
            state, pending if isinstance(pending, NextTask) else routing
        )

    def _xctl(self, state: _LoopTurn, routing: NextTask[LinkedProgram]) -> _LoopState:
        """XCTL transfers control WITHIN the same task: the task has not ended,
        so no started task may run yet, and the task keeps its own terminal."""
        return replace(
            state,
            program=routing.program,
            context=CicsContext(
                transid=routing.transid,
                commarea=routing.commarea,
                eibaid=state.context.eibaid,
                termid=state.context.termid,
            ),
        )

    def _after_task(
        self, state: _LoopTurn, waiting: NextTask[LinkedProgram] | DispatchResult
    ) -> _LoopState:
        started = self.start_queue.pop_runnable(self.region_termid)
        if started:
            return self._start(state, waiting, started[0])
        if isinstance(waiting, NextTask):
            return self._resume(state, waiting)
        return waiting

    def _start(
        self,
        state: _LoopTurn,
        waiting: NextTask[LinkedProgram] | DispatchResult,
        req: StartRequest,
    ) -> _LoopState:
        """A started task carries start data, no COMMAREA (so EIBCALEN is 0), and
        the terminal the START named — NO_TERMINAL for a non-terminal task."""
        if state.consecutive_starts >= self.max_consecutive_starts:
            self.start_queue.discard_for_abend()
            return _runaway_abend(req, state.consecutive_starts)
        self.start_queue.put_start_data(req.data)
        return _LoopTurn(
            program=self.program_cache[self.transid_to_program[req.transid]],
            context=CicsContext(
                transid=req.transid,
                commarea=b"",
                eibaid=state.context.eibaid,
                termid=req.termid,
            ),
            pending_next=waiting if isinstance(waiting, NextTask) else NO_PENDING_TASK,
            consecutive_starts=state.consecutive_starts + 1,
        )

    def _resume(self, state: _LoopTurn, pending: NextTask[LinkedProgram]) -> _LoopState:
        """On a pseudo-conversational RETURN TRANSID, the next turn's terminal
        input arrives here (blocks, up to a timeout). Its attention key seeds the
        next EIBAID; the event itself is left on the queue for the resumed turn's
        own RECEIVE MAP to consume (see _peek_input_event). No further input ever
        arriving matches real CICS's AZCT abend (terminal read-time-out) rather
        than hanging the region forever (red-dragon-pz9g.14). That wait is the
        only thing that breaks a chain of started tasks, so it resets the
        runaway count."""
        try:
            event = _peek_input_event(self.input_queue)
        except queue.Empty:
            return DispatchResult(kind=DispatchKind.ABEND, abcode="AZCT")
        self.start_queue.clear_start_data()
        return _LoopTurn(
            program=pending.program,
            context=CicsContext(
                transid=pending.transid,
                commarea=pending.commarea,
                eibaid=event.eibaid,
                termid=self.terminal_termid,
            ),
            pending_next=NO_PENDING_TASK,
            consecutive_starts=0,
        )


def _run_dispatcher_with_runner(
    run_fn: RunCicsFn,
    program_cache: Mapping[str, LinkedProgram],
    transid_to_program: Mapping[str, str],
    initial_context: CicsContext,
    screen_queue: ScreenChannel,
    input_queue: InputChannel,
    *,
    start_queue: StartQueue,
    region_termid: str = DEFAULT_TERMID,
    max_consecutive_starts: int = _MAX_CONSECUTIVE_STARTS,
) -> DispatchResult:
    """Core dispatcher loop — separated for testability.

    Scheduling matches CicsRegion (see ``CicsRegion._advance``): when a task
    ends, a runnable started task runs BEFORE any next-transid target, which is
    parked in ``pending_next`` and runs once nothing is startable. That order is
    not cosmetic here — a started task's data comes from RETRIEVE, never the
    terminal, so dispatching it after the blocking ``_peek_input_event`` below
    would leave it waiting on input nobody sends until the AZCT timeout.
    """
    loop = _DispatchLoop(
        run_fn=run_fn,
        program_cache=program_cache,
        transid_to_program=transid_to_program,
        screen_queue=screen_queue,
        input_queue=input_queue,
        start_queue=start_queue,
        region_termid=region_termid,
        max_consecutive_starts=max_consecutive_starts,
        terminal_termid=initial_context.termid,
    )
    first: _LoopState = _LoopTurn(
        program=program_cache[transid_to_program[initial_context.transid]],
        context=initial_context,
        pending_next=NO_PENDING_TASK,
        consecutive_starts=0,
    )
    states = accumulate(repeat(None), loop.advance, initial=first)
    return next(state for state in states if isinstance(state, DispatchResult))


@dataclass(frozen=True)
class RegionPosition:
    """Where a region stands between turns. ``pending_next`` is a RETURN TRANSID
    target parked because a started task, which needs no terminal input, runs
    before it; the terminal holds one such slot."""

    transid: str
    program: LinkedProgram | NoProgram
    commarea: bytes
    task_termid: str
    last_eibaid: str
    done: bool
    pending_next: PendingTask
    consecutive_starts: int


@dataclass(frozen=True)
class _TaskIo:
    """What every task the region runs is wired to: the terminal channels and
    the holder cells the builtins close over."""

    screen_queue: ScreenChannel
    input_queue: InputChannel
    context_holder: Holder[CicsContext]
    result_holder: Holder[DispatchResult]


def _describe_input(input_event: InputEvent | NoInput) -> tuple[str, int]:
    if isinstance(input_event, InputEvent):
        return repr(input_event.eibaid), len(input_event.fields)
    return "(none)", 0


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

    ``min_commarea_len`` pads the commarea handed to each FOLLOW-ON turn (after
    start). A program that XCTLs/RETURNs with a short commarea but whose successor
    indexes a larger CARDDEMO-COMMAREA needs EIBCALEN to cover those fields. The
    entry commarea passed to start() is used as-is (the entry program's own
    EIBCALEN is authoritative). ``max_consecutive_starts`` is lowered by tests so
    both halves of the runaway rule cost a couple of program runs.
    """

    def __init__(
        self,
        program_cache: Mapping[str, LinkedProgram],
        transid_to_program: Mapping[str, str],
        screen_queue: ScreenChannel,
        input_queue: InputChannel,
        *,
        context_holder: Holder[CicsContext],
        result_holder: Holder[DispatchResult],
        max_steps: int = 50_000,
        min_commarea_len: int = 0,
        start_queue: StartQueue,
        region_termid: str = DEFAULT_TERMID,
        max_consecutive_starts: int = _MAX_CONSECUTIVE_STARTS,
    ) -> None:
        self._program_cache = program_cache
        self._transid_to_program = transid_to_program
        self._io = _TaskIo(screen_queue, input_queue, context_holder, result_holder)
        self._max_steps = max_steps
        self._min_commarea_len = min_commarea_len
        self._start_queue = start_queue
        self._region_termid = region_termid
        self._max_consecutive_starts = max_consecutive_starts
        self._position = Cell(
            RegionPosition(
                transid="",
                program=NO_PROGRAM,
                commarea=b"",
                task_termid=region_termid,
                last_eibaid=DFHENTER,
                done=False,
                pending_next=NO_PENDING_TASK,
                consecutive_starts=0,
            )
        )

    @property
    def transid(self) -> str:
        """The current transid (for assertions if wanted)."""
        return self._position.get().transid

    @property
    def done(self) -> bool:
        """True once a terminal (RETURN / ABEND) result has been produced."""
        return self._position.get().done

    def start(
        self,
        entry_transid: str,
        *,
        commarea: bytes = b"",
        input_event: InputEvent | NoInput = NO_INPUT,
        max_steps: int = _USE_REGION_MAX_STEPS,
    ) -> DispatchResult:
        """Begin a task on ``entry_transid`` and dispatch its first program."""
        logger.info(
            "region.start: transid=%s commarea=%d B", entry_transid, len(commarea)
        )
        program = self._program_cache[self._transid_to_program[entry_transid]]
        self._position.set(
            replace(
                self._position.get(),
                transid=entry_transid,
                commarea=commarea,
                program=program,
                task_termid=self._region_termid,
                pending_next=NO_PENDING_TASK,
                consecutive_starts=0,
                done=False,
            )
        )
        self._start_queue.clear_start_data()
        return self._dispatch(input_event, max_steps)

    def step(
        self,
        *,
        input_event: InputEvent | NoInput = NO_INPUT,
        max_steps: int = _USE_REGION_MAX_STEPS,
    ) -> DispatchResult:
        """Dispatch the CURRENT (program, transid, commarea). Requires not done."""
        if self.done:
            raise RuntimeError("step() called on a region that has terminated")
        eibaid, nfields = _describe_input(input_event)
        logger.info(
            "region.step: transid=%s eibaid=%s fields=%d",
            self.transid,
            eibaid,
            nfields,
        )
        return self._dispatch(input_event, max_steps)

    def _dispatch(
        self, input_event: InputEvent | NoInput, max_steps: int
    ) -> DispatchResult:
        position = self._position.get()
        eibaid = (
            input_event.eibaid
            if isinstance(input_event, InputEvent)
            else position.last_eibaid
        )
        if isinstance(input_event, InputEvent):
            self._io.input_queue.put(input_event)
        self._position.set(replace(position, last_eibaid=eibaid))
        result = run_cics(
            _started_program(position.program),
            CicsContext(
                transid=position.transid,
                commarea=position.commarea,
                eibaid=eibaid,
                termid=position.task_termid,
            ),
            self._io.screen_queue,
            self._io.input_queue,
            context_holder=self._io.context_holder,
            result_holder=self._io.result_holder,
            max_steps=(
                self._max_steps if max_steps == _USE_REGION_MAX_STEPS else max_steps
            ),
        )
        routing = _advance_routing(
            result, position.transid, self._program_cache, self._transid_to_program
        )
        override = self._advance(result, routing)
        return override[0] if override else result

    def _update(self, **changes: str | bytes | bool | int | PendingTask) -> None:
        self._position.set(replace(self._position.get(), **changes))

    def _advance(
        self, result: DispatchResult, routing: NextTask[LinkedProgram] | DispatchResult
    ) -> tuple[DispatchResult, ...]:
        """Settle the finished task and adopt whatever runs next. Returns the
        result ``_dispatch`` must report INSTEAD of the finished task's own, or
        empty when the finished task's result stands. XCTL transfers control
        WITHIN the same task: the task has not ended, so no started task may run
        yet, the task keeps its own terminal, and terminal input it has not
        RECEIVEd yet is still its own to read. Every other outcome ends the
        task, which is where that unread input dies (see
        ``_discard_pending_input``)."""
        if result.kind == DispatchKind.XCTL and isinstance(routing, NextTask):
            self._adopt(routing, self._position.get().task_termid)
            return _NO_OVERRIDE
        _discard_pending_input(self._io.input_queue)
        return self._settle(routing)

    def _settle(
        self, routing: NextTask[LinkedProgram] | DispatchResult
    ) -> tuple[DispatchResult, ...]:
        if isinstance(routing, DispatchResult):
            return self._settle_terminal(routing)
        return self._settle_next_transid(routing)

    def _settle_next_transid(
        self, routing: NextTask[LinkedProgram]
    ) -> tuple[DispatchResult, ...]:
        started = self._start_queue.pop_runnable(self._region_termid)
        if started:
            self._update(pending_next=routing)
            return self._adopt_started(started[0])
        self._update(pending_next=NO_PENDING_TASK)
        self._adopt_next_transid(routing)
        return _NO_OVERRIDE

    def _settle_terminal(self, routing: DispatchResult) -> tuple[DispatchResult, ...]:
        """A task ended. Run what is runnable before waiting on terminal input:
        a started task needs none, a next-transid task does.

        Returns the result ``_dispatch`` must report INSTEAD of the finished
        task's own, or empty when the finished task's result stands."""
        if routing.kind == DispatchKind.ABEND:
            self._start_queue.discard_for_abend()
            return self._terminate(routing)
        started = self._start_queue.pop_runnable(self._region_termid)
        if started:
            return self._adopt_started(started[0])
        return self._resume_pending(routing)

    def _resume_pending(self, routing: DispatchResult) -> tuple[DispatchResult, ...]:
        pending = self._position.get().pending_next
        if isinstance(pending, NextTask):
            self._adopt_next_transid(pending)
            self._update(pending_next=NO_PENDING_TASK)
            return _NO_OVERRIDE
        return self._terminate(routing)

    def _terminate(self, routing: DispatchResult) -> tuple[DispatchResult, ...]:
        self._update(done=True)
        logger.info("dispatch → terminal %s", routing.kind.name)
        return _NO_OVERRIDE

    def _adopt(self, routing: NextTask[LinkedProgram], task_termid: str) -> None:
        """``task_termid`` is the region's terminal for a fresh next-transid task,
        and the CURRENT task's terminal for an XCTL, which does not start a task."""
        position = replace(
            self._position.get(),
            transid=routing.transid,
            program=routing.program,
            task_termid=task_termid,
            commarea=routing.commarea.ljust(self._min_commarea_len, b"\x00"),
        )
        self._position.set(position)
        logger.info(
            "dispatch → transid=%s commarea=%d B",
            position.transid,
            len(position.commarea),
        )

    def _adopt_next_transid(self, routing: NextTask[LinkedProgram]) -> None:
        """A next-transid task is a NEW task the caller must supply input for, so
        it owns an empty start-data slot and it breaks a chain of started tasks —
        the region cannot block on the terminal, so adopting the turn is where
        that break happens. An XCTL is a transfer within the same task and breaks
        nothing, so it does not come here — a START/XCTL cycle must still reach
        the runaway guard, and the XCTL'd program may still RETRIEVE."""
        self._update(consecutive_starts=0)
        self._start_queue.clear_start_data()
        self._adopt(routing, self._region_termid)

    def _adopt_started(self, req: StartRequest) -> tuple[DispatchResult, ...]:
        """A started task carries start data, no COMMAREA (so EIBCALEN is 0), and
        the terminal the START named — NO_TERMINAL for a non-terminal task.

        Returns the runaway-guard abend when adopting this task would take the
        chain past the region's cap, or empty when the task was adopted."""
        position = self._position.get()
        if position.consecutive_starts >= self._max_consecutive_starts:
            self._start_queue.discard_for_abend()
            self._update(done=True)
            return (_runaway_abend(req, position.consecutive_starts),)
        self._position.set(
            replace(
                position,
                consecutive_starts=position.consecutive_starts + 1,
                transid=req.transid,
                program=self._program_cache[self._transid_to_program[req.transid]],
                commarea=b"",
                task_termid=req.termid,
            )
        )
        self._start_queue.put_start_data(req.data)
        logger.info("dispatch → started transid=%s termid=%r", req.transid, req.termid)
        return _NO_OVERRIDE


def _started_program(program: LinkedProgram | NoProgram) -> LinkedProgram:
    if isinstance(program, NoProgram):
        raise RuntimeError("step() called on a region that has not started")
    return program

"""Wraps CicsLoweringStrategy as a CoprocessorSpec -- the seam
interpreter.project.coprocessor_compile.compile_program composes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, MutableSequence

from cics.builtins.system import DEFAULT_USERID
from cics.cell import Holder
from cics.interval import StartQueue
from cics.le_stubs import LE_STUBS_DIR
from cics.preprocessor import apply_cics_prepass
from cics.statements import CicsDialectParser
from cics.strategy import (
    NO_TRANSIDS,
    NOT_SUPPLIED,
    OWN_START_QUEUE,
    Absent,
    CicsLoweringStrategy,
)
from cics.terminal import InputChannel, ScreenChannel
from cics.types import DEFAULT_TERMID, CicsContext, DispatchResult
from cics.vsam.engine import VsamEngine
from interpreter.project.coprocessor_compile import CoprocessorSpec
from interpreter.project.types import LinkedProgram

_OWN_UNSUPPORTED: set[str] = set()


def _noop() -> None:
    """Default on_abend: a CICS-only region has no composed SQL runtime, so
    there is nothing to roll back when a task abends."""


def build_cics_spec(
    context_holder: Holder[CicsContext],
    *,
    program_cache: MutableMapping[str, LinkedProgram],
    result_holder: Holder[DispatchResult] | Absent = NOT_SUPPLIED,
    td_queue: MutableSequence[str] | Absent = NOT_SUPPLIED,
    applid: str = "CARDDEMO",
    sysid: str = "SYS1",
    userid: str = DEFAULT_USERID,
    screen_queue: ScreenChannel | Absent = NOT_SUPPLIED,
    input_queue: InputChannel | Absent = NOT_SUPPLIED,
    vsam_engine: VsamEngine | Absent = NOT_SUPPLIED,
    receive_timeout: float = 30.0,
    conversational: bool = False,
    start_queue: StartQueue = OWN_START_QUEUE,
    transid_to_program: Mapping[str, str] = NO_TRANSIDS,
    region_termid: str = DEFAULT_TERMID,
    unsupported_verbs: set[str] = _OWN_UNSUPPORTED,
    on_abend: Callable[[], None] = _noop,
) -> CoprocessorSpec:
    """Build the EXEC CICS CoprocessorSpec.

    ``context_holder``/``result_holder``/``program_cache`` are the same
    mutable cells CicsLoweringStrategy already uses internally -- pass the
    SAME dicts/lists across multiple compile_program() calls for programs
    that LINK to each other within one region. ``program_cache`` is required:
    every EXEC CICS LINK resolves against it, so it must be the cache the
    region fills with its compiled programs, and an empty one of the
    runtime's own would make every LINK fail silently.

    ``unsupported_verbs`` is the caller's cell for the same reason: it collects
    every EXEC CICS verb this runtime dropped while lowering, so a harness can
    assert on the set rather than scrape a log. Each such statement also
    lowers to an abend, so a program that reaches one fails there instead of
    running on as though it had executed (forge-p9t).

    ``on_abend`` is the rollback callable for an abending task (EXEC CICS
    ABEND, an unhandled condition, or an unsupported verb) -- a plain Python
    callable rather than a named hook, because a *dispatcher*-level abend
    (unknown XCTL/RETURN-TRANSID target, terminal read timeout: PGMI/TRNI/
    AZCT) is raised in Python at the routing layer, not IR, so it cannot
    emit a CallFunction hook the way SYNCPOINT does. A forge composition
    supplies squall's rollback here so cicada never imports or names squall;
    a CICS-only region keeps the default no-op, its current behaviour
    exactly.
    """
    collected = set() if unsupported_verbs is _OWN_UNSUPPORTED else unsupported_verbs
    dialect_parser = CicsDialectParser()

    def _make_strategy() -> CicsLoweringStrategy:
        return CicsLoweringStrategy(
            context_holder=context_holder,
            result_holder=result_holder,
            program_cache=program_cache,
            td_queue=td_queue,
            applid=applid,
            sysid=sysid,
            userid=userid,
            screen_queue=screen_queue,
            input_queue=input_queue,
            vsam_engine=vsam_engine,
            receive_timeout=receive_timeout,
            conversational=conversational,
            start_queue=start_queue,
            transid_to_program=transid_to_program,
            region_termid=region_termid,
            handler_source=dialect_parser.statements,
            unsupported_verbs=collected,
            on_abend=on_abend,
        )

    return CoprocessorSpec(
        name="cics",
        make_strategy=_make_strategy,
        source_prepass=apply_cics_prepass,
        owns_execution=True,
        dialect_parser=dialect_parser,
        source_search_dirs=lambda: (LE_STUBS_DIR,),
    )

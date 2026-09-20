"""Wraps CicsLoweringStrategy as a CoprocessorSpec -- the seam
interpreter.project.coprocessor_compile.compile_program composes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cics.le_stubs import LE_STUBS_DIR
from cics.preprocessor import apply_cics_prepass
from cics.statements import CicsDialectParser
from cics.strategy import CicsLoweringStrategy

from interpreter.project.coprocessor_compile import CoprocessorSpec

_OWN_UNSUPPORTED: set[str] = set()


def _noop() -> None:
    """Default on_abend: a CICS-only region has no composed SQL runtime, so
    there is nothing to roll back when a task abends."""


def build_cics_spec(
    context_holder: list,
    result_holder: list | None = None,
    program_cache: dict | None = None,
    vsam_engine: Any = None,
    screen_queue: Any = None,
    input_queue: Any = None,
    unsupported_verbs: set[str] = _OWN_UNSUPPORTED,
    on_abend: Callable[[], None] = _noop,
    **kwargs: Any,
) -> CoprocessorSpec:
    """Build the EXEC CICS CoprocessorSpec.

    ``context_holder``/``result_holder``/``program_cache`` are the same
    mutable cells CicsLoweringStrategy already uses internally -- pass the
    SAME dicts/lists across multiple compile_program() calls for programs
    that LINK to each other within one region.

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
        # One dialect_parser instance is shared across every module compile_cobol
        # lowers (main + subprograms); CicsLoweringStrategy.on_procedure_entry
        # consumes-and-clears dialect_parser.statements per module, so no clear
        # belongs here.
        return CicsLoweringStrategy(
            context_holder=context_holder,
            result_holder=result_holder,
            program_cache=program_cache,
            vsam_engine=vsam_engine,
            screen_queue=screen_queue,
            input_queue=input_queue,
            handler_source=dialect_parser.statements,
            unsupported_verbs=collected,
            on_abend=on_abend,
            **kwargs,
        )

    return CoprocessorSpec(
        name="cics",
        make_strategy=_make_strategy,
        source_prepass=apply_cics_prepass,
        owns_execution=True,
        dialect_parser=dialect_parser,
        source_search_dirs=lambda: (LE_STUBS_DIR,),
    )

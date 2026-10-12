"""Top-level CICS region bootstrap.

Assembles a running CICS region from a transid→program mapping (``parse_csd``
reads one from a CSD) and a set of COBOL program sources:

  1. construct ONE shared CICS :class:`~interpreter.project.coprocessor_compile.CoprocessorSpec`
     (via :func:`cics.coprocessor.build_cics_spec`) over the region's runtime
     state (VSAM engine, BMS loader, screen/input queues, context/result holders),
  2. eagerly compile every distinct program named in the CSD into a
     ``program_cache`` keyed by program name (fail-fast on a missing source),
  3. run the dispatcher loop at the entry transid.

Source contract: ``program_sources`` values are **raw (NOT pre-passed)** COBOL
bytes — ``compile_cics_program`` prepasses via the spec's own
``source_prepass=apply_cics_prepass`` now. Do NOT pre-pass sources by hand
before handing them here, or they will be prepassed twice.

Heavy frontend/CFG/project imports are kept lazy inside the functions so this
module stays cheap to import and side-steps any import-linter coupling concerns.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from cics.cell import Holder, fill
from cics.coprocessor import build_cics_spec
from cics.dispatcher import _run_dispatcher_with_runner, run_cics
from cics.interval import StartQueue
from cics.strategy import NOT_SUPPLIED, Absent
from cics.types import DEFAULT_TERMID, CicsContext, DispatchResult
from cics.vsam.engine import VsamEngine
from cobol_asg.cobol_parser import ProLeapCobolParser
from interpreter.project.coprocessor_compile import CoprocessorSpec
from interpreter.project.types import LinkedProgram

if TYPE_CHECKING:
    from cics.terminal import InputChannel, ScreenChannel


def _noop() -> None:
    """Default on_abend: a CICS-only region has no composed SQL runtime, so
    there is nothing to roll back when a task abends."""


def compile_cics_program(
    source: bytes,
    parser: ProLeapCobolParser,
    spec: CoprocessorSpec,
    *,
    source_search_dirs: Sequence[Path] = (),
    tolerant: bool = False,
) -> LinkedProgram:
    """Raw (NOT pre-passed) CICS COBOL ``source`` -> ``LinkedProgram`` with
    ``spec`` composed.

    ``spec`` (typically built by ``cics.coprocessor.build_cics_spec``) owns
    prepassing via its own ``source_prepass=apply_cics_prepass`` -- do NOT
    pre-pass ``source`` by hand before calling this function, or it will be
    prepassed twice.

    ``tolerant=True`` skips statements that raise during lowering (e.g. fields
    from missing or stub copybooks) rather than failing compilation.
    """
    from interpreter.project.coprocessor_compile import compile_program

    _frontend, linked = compile_program(
        source,
        parser,
        [spec],
        source_search_dirs=source_search_dirs,
        tolerant=tolerant,
    )
    return linked


def _region_programs(transid_to_program: Mapping[str, str]) -> tuple[str, ...]:
    """Each program the region names, once, in the order it is first named."""
    named = tuple(transid_to_program.values())
    return tuple(program for n, program in enumerate(named) if program not in named[:n])


def _require_sources(
    programs: Sequence[str], program_sources: Mapping[str, bytes]
) -> None:
    missing = [program for program in programs if program not in program_sources]
    if missing:
        raise ValueError(
            f"No source provided for CICS program {missing[0]!r} "
            f"(named in the CSD/transid mapping)"
        )


def _compiled(
    programs: Sequence[str],
    program_sources: Mapping[str, bytes],
    parser: ProLeapCobolParser,
    spec: CoprocessorSpec,
    source_search_dirs: Sequence[Path],
) -> Mapping[str, LinkedProgram]:
    return {
        program: compile_cics_program(
            program_sources[program],
            parser,
            spec,
            source_search_dirs=source_search_dirs,
        )
        for program in programs
    }


def run_carddemo_region(
    *,
    program_sources: Mapping[str, bytes],
    parser: ProLeapCobolParser,
    entry_transid: str,
    screen_queue: ScreenChannel,
    input_queue: InputChannel,
    transid_to_program: Mapping[str, str],
    vsam_engine: VsamEngine | Absent = NOT_SUPPLIED,
    applid: str = "CARDDEMO",
    sysid: str = "SYS1",
    max_steps: int = 50_000,
    source_search_dirs: Sequence[Path] = (),
    region_termid: str = DEFAULT_TERMID,
    on_abend: Callable[[], None] = _noop,
) -> DispatchResult:
    """Assemble and run a CICS region; return the terminal :class:`DispatchResult`.

    ``transid_to_program`` names every program the region runs; ``parse_csd``
    reads one from a CSD file.

    ``program_sources`` maps each program name to its **raw (NOT pre-passed)**
    COBOL source bytes -- ``compile_cics_program`` prepasses via the spec now.
    Every distinct program named in the mapping is compiled eagerly with a
    single shared :class:`CicsLoweringStrategy`; a missing source raises a clear
    error before the dispatcher loop starts (fail-fast). The programs are
    compiled into the same cache the spec's EXEC CICS LINK resolves against, so
    a LINK from one region program to another reaches it.

    ``source_search_dirs`` (e.g. the CardDemo ``cbl/`` dir) are threaded into
    :func:`compile_cics_program` so each region program links the subprograms
    it ``CALL``s.

    ``on_abend`` (default a no-op) is the one rollback callable a composition
    supplies for EVERY abend path -- both the IR-raised ones (EXEC CICS
    ABEND, an unhandled condition, an unsupported verb; threaded via
    ``build_cics_spec``) and the dispatcher-level ones raised in Python at
    the routing layer (PGMI, TRNI, AZCT, the runaway guard's ASTL; threaded
    via ``_run_dispatcher_with_runner``) -- so a caller never has to inspect
    the terminal :class:`DispatchResult` itself to know whether to roll back.
    """
    programs = _region_programs(transid_to_program)
    _require_sources(programs, program_sources)
    context_holder: Holder[CicsContext] = [None]
    result_holder: Holder[DispatchResult] = [None]
    start_queue = StartQueue()
    program_cache: dict[str, LinkedProgram] = {}
    spec = build_cics_spec(
        context_holder=context_holder,
        result_holder=result_holder,
        program_cache=program_cache,
        vsam_engine=vsam_engine,
        screen_queue=screen_queue,
        input_queue=input_queue,
        applid=applid,
        sysid=sysid,
        start_queue=start_queue,
        transid_to_program=transid_to_program,
        region_termid=region_termid,
        on_abend=on_abend,
    )
    fill(
        program_cache,
        _compiled(programs, program_sources, parser, spec, source_search_dirs),
    )

    def run_fn(
        program: LinkedProgram,
        context: CicsContext,
        sq: ScreenChannel,
        iq: InputChannel,
    ) -> DispatchResult:
        return run_cics(
            program,
            context,
            sq,
            iq,
            context_holder=context_holder,
            result_holder=result_holder,
            max_steps=max_steps,
        )

    return _run_dispatcher_with_runner(
        run_fn,
        program_cache,
        transid_to_program,
        CicsContext(
            transid=entry_transid, commarea=b"", eibaid="\x7d", termid=region_termid
        ),
        screen_queue,
        input_queue,
        start_queue=start_queue,
        region_termid=region_termid,
        on_abend=on_abend,
    )

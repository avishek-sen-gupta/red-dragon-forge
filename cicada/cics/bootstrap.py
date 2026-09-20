"""Top-level CICS region bootstrap.

Assembles a running CICS region from a CSD transid→program mapping and a set of
COBOL program sources:

  1. (optionally) parse a CSD file into ``transid_to_program``,
  2. construct ONE shared CICS :class:`~interpreter.project.coprocessor_compile.CoprocessorSpec`
     (via :func:`cics.coprocessor.build_cics_spec`) over the region's runtime
     state (VSAM engine, BMS loader, screen/input queues, context/result holders),
  3. eagerly compile every distinct program named in the CSD into a
     ``program_cache`` keyed by program name (fail-fast on a missing source),
  4. run the dispatcher loop at the entry transid.

Source contract: ``program_sources`` values are **raw (NOT pre-passed)** COBOL
bytes — ``compile_cics_program`` prepasses via the spec's own
``source_prepass=apply_cics_prepass`` now. Do NOT pre-pass sources by hand
before handing them here, or they will be prepassed twice.

Heavy frontend/CFG/project imports are kept lazy inside the functions so this
module stays cheap to import and side-steps any import-linter coupling concerns.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from cics.coprocessor import build_cics_spec
from cics.dispatcher import _run_dispatcher_with_runner, parse_csd, run_cics
from cics.interval import StartQueue
from cics.types import DEFAULT_TERMID, CicsContext, DispatchResult

from interpreter.project.coprocessor_compile import CoprocessorSpec

if TYPE_CHECKING:
    from cics.terminal import InputChannel, ScreenChannel


def _noop() -> None:
    """Default on_abend: a CICS-only region has no composed SQL runtime, so
    there is nothing to roll back when a task abends."""


def compile_cics_program(
    source: bytes,
    parser: Any,
    spec: CoprocessorSpec,
    *,
    program_source_dirs: Sequence[Path] = (),
    tolerant: bool = False,
) -> Any:
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
        program_source_dirs=program_source_dirs,
        tolerant=tolerant,
    )
    return linked


def run_carddemo_region(
    *,
    program_sources: dict[str, bytes],
    parser: Any,
    entry_transid: str,
    screen_queue: ScreenChannel,
    input_queue: InputChannel,
    transid_to_program: dict[str, str] | None = None,
    csd_path: Path | None = None,
    vsam_engine: Any = None,
    applid: str = "CARDDEMO",
    sysid: str = "SYS1",
    max_steps: int = 50_000,
    program_source_dirs: Sequence[Path] = (),
    region_termid: str = DEFAULT_TERMID,
    on_abend: Callable[[], None] = _noop,
) -> DispatchResult:
    """Assemble and run a CICS region; return the terminal :class:`DispatchResult`.

    Exactly one of ``transid_to_program`` or ``csd_path`` must be supplied:
    ``csd_path`` is parsed via :func:`parse_csd` into the transid→program mapping.

    ``program_sources`` maps each program name to its **raw (NOT pre-passed)**
    COBOL source bytes -- ``compile_cics_program`` prepasses via the spec now.
    Every distinct program named in the mapping is compiled eagerly with a
    single shared :class:`CicsLoweringStrategy`; a missing source raises a clear
    error before the dispatcher loop starts (fail-fast).

    ``program_source_dirs`` (e.g. the CardDemo ``cbl/`` dir) are threaded into
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
    if (transid_to_program is None) == (csd_path is None):
        raise ValueError(
            "run_carddemo_region requires exactly one of "
            "transid_to_program= or csd_path="
        )
    if csd_path is not None:
        transid_to_program = parse_csd(csd_path)
    assert transid_to_program is not None  # narrowed by the checks above

    context_holder: list[CicsContext] = [None]  # type: ignore[list-item]
    result_holder: list = [None]

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
        on_abend=on_abend,
    )

    program_cache: dict[str, Any] = {}
    for prog_name in transid_to_program.values():
        if prog_name in program_cache:
            continue
        source = program_sources.get(prog_name)
        if source is None:
            raise ValueError(
                f"No source provided for CICS program {prog_name!r} "
                f"(named in the CSD/transid mapping)"
            )
        program_cache[prog_name] = compile_cics_program(
            source,
            parser,
            spec,
            program_source_dirs=program_source_dirs,
        )

    def run_fn(
        program: Any,
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

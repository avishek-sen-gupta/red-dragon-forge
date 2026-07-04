"""Top-level CICS region bootstrap.

Assembles a running CICS region from a CSD transid→program mapping and a set of
COBOL program sources:

  1. (optionally) parse a CSD file into ``transid_to_program``,
  2. construct ONE shared :class:`CicsLoweringStrategy` over the region's runtime
     state (VSAM engine, BMS loader, screen/input queues, context/result holders),
  3. eagerly compile every distinct program named in the CSD into a
     ``program_cache`` keyed by program name (fail-fast on a missing source),
  4. run the dispatcher loop at the entry transid.

Source contract: ``program_sources`` values are **pre-passed** COBOL bytes — the
caller is responsible for running :func:`apply_cics_prepass` (and ``.encode()``)
before handing sources here. ``compile_cics_program`` likewise assumes its
``source`` argument is already pre-passed. This keeps a single, explicit prepass
step at the boundary and avoids double-prepassing.

Heavy frontend/CFG/project imports are kept lazy inside the functions so this
module stays cheap to import and side-steps any import-linter coupling concerns.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from cics.dispatcher import _run_dispatcher_with_runner, parse_csd, run_cics
from cics.strategy import CicsLoweringStrategy
from cics.types import CicsContext, DispatchResult

if TYPE_CHECKING:
    from cics.terminal import InputChannel, ScreenChannel


def compile_cics_program(
    source: bytes,
    parser: Any,
    strategy: Any,
    *,
    program_source_dir: Path | None = None,
    extra_subprogram_sources: dict[str, bytes] | None = None,
) -> Any:
    """Pre-passed CICS COBOL ``source`` -> ``LinkedProgram`` with ``strategy`` injected.

    ``source`` must already have been run through ``apply_cics_prepass`` (and
    encoded to bytes). Returns a :class:`LinkedProgram` ready for ``run_cics``.

    When ``program_source_dir`` is given, the main program's ``CALL 'X'`` targets
    are resolved (transitively) against that directory using the existing COBOL
    import resolver, each CALLed program is compiled with the SAME
    ``CicsLoweringStrategy``, and all modules are merged via the project linker
    (:func:`interpreter.project.linker.link_modules`) so the CALL resolves at
    runtime through ``CallWithMemory``'s singleton dispatch.

    ``extra_subprogram_sources`` maps a *program name* to pre-passed source bytes
    for callees that are not present on disk (e.g. a CEEDAYS stub standing in for
    an IBM Language Environment callable service). They are linked like any other
    subprogram. When there are no CALLs (and no extras), this reduces to the
    original single-module compile.
    """
    from interpreter.project.cobol_compile import compile_cobol
    from cics.cics_visitor import parse_exec_cics_text
    from cics.preprocessor import apply_cics_prepass

    # compile_cobol's program_source_dir/extra_subprogram_sources are no longer
    # Optional (red-dragon cb40bd34, "no None default params" cleanup) — their
    # non-None defaults (Path(".") / {}) are also the "no override" sentinels
    # compile_cobol itself checks for, so translate this function's None
    # ("caller didn't opt in") to those sentinels before forwarding.
    _program_source_dir = (
        program_source_dir if program_source_dir is not None else Path(".")
    )
    _extra_subprogram_sources = (
        extra_subprogram_sources if extra_subprogram_sources is not None else {}
    )

    _frontend, linked = compile_cobol(
        source,  # already CICS-prepassed by the caller
        parser=parser,
        extension_strategies=[strategy],
        cics_text_parser=parse_exec_cics_text,
        program_source_dir=_program_source_dir,
        extra_subprogram_sources=_extra_subprogram_sources,
        source_transform=apply_cics_prepass,
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
    program_source_dir: Path | None = None,
    extra_subprogram_sources: dict[str, bytes] | None = None,
) -> DispatchResult:
    """Assemble and run a CICS region; return the terminal :class:`DispatchResult`.

    Exactly one of ``transid_to_program`` or ``csd_path`` must be supplied:
    ``csd_path`` is parsed via :func:`parse_csd` into the transid→program mapping.

    ``program_sources`` maps each program name to its **pre-passed** COBOL source
    bytes. Every distinct program named in the mapping is compiled eagerly with a
    single shared :class:`CicsLoweringStrategy`; a missing source raises a clear
    error before the dispatcher loop starts (fail-fast).

    ``program_source_dir`` (the CardDemo ``cbl/`` dir) and
    ``extra_subprogram_sources`` are threaded into :func:`compile_cics_program` so
    each region program links the subprograms it ``CALL``s.
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

    strategy = CicsLoweringStrategy(
        context_holder=context_holder,
        result_holder=result_holder,
        vsam_engine=vsam_engine,
        screen_queue=screen_queue,
        input_queue=input_queue,
        applid=applid,
        sysid=sysid,
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
            strategy,
            program_source_dir=program_source_dir,
            extra_subprogram_sources=extra_subprogram_sources,
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
        CicsContext(transid=entry_transid, commarea=b"", eibaid="\x7d"),
        screen_queue,
        input_queue,
    )

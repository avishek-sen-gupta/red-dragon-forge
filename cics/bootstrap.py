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
from typing import TYPE_CHECKING, Any, Sequence

from cics.dispatcher import _run_dispatcher_with_runner, parse_csd, run_cics
from cics.le_stubs import LE_STUBS_DIR
from cics.strategy import CicsLoweringStrategy
from cics.types import CicsContext, DispatchResult

if TYPE_CHECKING:
    from cics.terminal import InputChannel, ScreenChannel


def compile_cics_program(
    source: bytes,
    parser: Any,
    strategy: Any,
    *,
    program_source_dirs: Sequence[Path] = (),
) -> Any:
    """Pre-passed CICS COBOL ``source`` -> ``LinkedProgram`` with ``strategy`` injected.

    ``source`` must already have been run through ``apply_cics_prepass`` (and
    encoded to bytes). Returns a :class:`LinkedProgram` ready for ``run_cics``.

    Builds one CoprocessorSpec around ``strategy`` and delegates to RedDragon's
    shared compile_program (interpreter.project.coprocessor_compile) — the
    same composition mechanism red-dragon-forge and Squall use. IBM Language
    Environment callable services (e.g. CEEDAYS, which have no CardDemo
    application source) resolve because LE_STUBS_DIR is always appended to
    the search path via the spec's extra_program_source_dirs, so callers
    never need to know these stubs exist.
    """
    from interpreter.project.coprocessor_compile import CoprocessorSpec, compile_program
    from cics.statements import CicsDialectParser
    from cics.preprocessor import apply_cics_prepass

    spec = CoprocessorSpec(
        name="cics",
        make_strategy=lambda: strategy,
        source_prepass=apply_cics_prepass,
        dialect_parser=CicsDialectParser(),
        extra_program_source_dirs=lambda: (LE_STUBS_DIR,),
    )
    _frontend, linked = compile_program(
        source,  # already CICS-prepassed by the caller
        parser,
        [spec],
        program_source_dirs=program_source_dirs,
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
) -> DispatchResult:
    """Assemble and run a CICS region; return the terminal :class:`DispatchResult`.

    Exactly one of ``transid_to_program`` or ``csd_path`` must be supplied:
    ``csd_path`` is parsed via :func:`parse_csd` into the transid→program mapping.

    ``program_sources`` maps each program name to its **pre-passed** COBOL source
    bytes. Every distinct program named in the mapping is compiled eagerly with a
    single shared :class:`CicsLoweringStrategy`; a missing source raises a clear
    error before the dispatcher loop starts (fail-fast).

    ``program_source_dirs`` (e.g. the CardDemo ``cbl/`` dir) are threaded into
    :func:`compile_cics_program` so each region program links the subprograms
    it ``CALL``s.
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
        CicsContext(transid=entry_transid, commarea=b"", eibaid="\x7d"),
        screen_queue,
        input_queue,
    )

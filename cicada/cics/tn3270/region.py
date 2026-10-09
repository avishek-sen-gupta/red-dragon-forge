"""Building the CICS region a TN3270 server drives, from its RegionConfig."""

from __future__ import annotations

import logging
import queue
from collections import ChainMap
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cics.bms.catalog import MapCatalog, load_catalog
from cics.bms.generate import generate_symbolic_copybooks
from cics.cell import fill
from cics.coprocessor import build_cics_spec
from cics.dispatcher import CicsRegion
from cics.interval import StartQueue
from cics.screen.driver import PseudoConversationalDriver
from cics.tn3270.config import RegionConfig, resolve_program_source
from cics.vsam.engine import VsamEngine
from cics.vsam.fct import FctConfig
from cics.vsam.format import read_flat_file
from cics.vsam.seed import seed_records

if TYPE_CHECKING:
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from interpreter.project.coprocessor_compile import CoprocessorSpec
    from interpreter.project.types import LinkedProgram

CICS_COPYBOOKS = Path(__file__).parents[1] / "copybooks"
_MAX_STEPS = 1_000_000


@dataclass(frozen=True)
class ServedRegion:
    driver: PseudoConversationalDriver
    catalog: MapCatalog
    vsam_engine: VsamEngine


def _vsam_engine(config: RegionConfig, vsam_dir: Path) -> VsamEngine:
    fct = FctConfig(datasets=dict(config.datasets))
    records = {
        name: read_flat_file(config.data_dir / ds.file, ds.record_length)
        for name, ds in fct.datasets.items()
    }
    seed_records(vsam_dir, fct, records)
    engine = VsamEngine(fct, vsam_dir)
    engine.load_all()
    return engine


@dataclass(frozen=True)
class _Wiring:
    """The channels and one-element holders run_cics shares with the builtins."""

    screen_channel: queue.Queue
    input_channel: queue.Queue
    context_holder: list
    result_holder: list
    start_queue: StartQueue


def _wiring() -> _Wiring:
    return _Wiring(queue.Queue(), queue.Queue(), [None], [None], StartQueue())


def _generate_symbolic_copybooks(config: RegionConfig, sym_dir: Path) -> None:
    # Each of config.bms_dirs is generated into the same sym_dir in order; a
    # region with only one bms_dirs entry (every config today) behaves exactly
    # as before.
    for bms_dir in config.bms_dirs:
        generate_symbolic_copybooks(
            bms_dir=bms_dir,
            out_dir=sym_dir,
            hlasm_export_bin=str(config.hlasm_export),
        )


def _catalog(config: RegionConfig) -> MapCatalog:
    # ChainMap looks up each key in its mappings in order, so an earlier
    # bms_dirs entry's mapset always wins over a later one's -- first-hit-wins,
    # matching the resolution used for source_dirs.
    catalogs = (load_catalog(d, str(config.hlasm_export)) for d in config.bms_dirs)
    return MapCatalog(maps=dict(ChainMap(*(dict(c.maps) for c in catalogs))))


def _parser(config: RegionConfig, bridge_jar: str, sym_dir: Path) -> ProLeapCobolParser:
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    _generate_symbolic_copybooks(config, sym_dir)
    return ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybook_dirs=[sym_dir, *config.copybook_dirs, CICS_COPYBOOKS],
        copybook_exts=list(config.copybook_exts),
    )


logger = logging.getLogger(__name__)


def _compile_one(
    name: str,
    ordinal: int,
    total: int,
    config: RegionConfig,
    parser: ProLeapCobolParser,
    specs: Sequence[CoprocessorSpec],
) -> LinkedProgram:
    """Compile one program, announcing which. Building a region is a minute of
    silence otherwise -- the bridge's own progress bar names no program, so a
    slow or wedged compile is indistinguishable from a finished one."""
    from interpreter.project.coprocessor_compile import compile_program

    logger.info("compiling %d/%d: %s", ordinal, total, name)
    return compile_program(
        resolve_program_source(config, name).read_bytes(),
        parser,
        specs,
        source_search_dirs=config.source_dirs,
    )[1]


def _compiled(
    config: RegionConfig,
    parser: ProLeapCobolParser,
    cics_spec: CoprocessorSpec,
    extra_specs: Sequence[CoprocessorSpec],
) -> dict[str, LinkedProgram]:
    # source_search_dirs resolves plain COBOL subprograms a transaction
    # program CALLs (e.g. COTRN02C -> CSUTLDTC) from the same cbl directory;
    # without it such a CALL is unresolved and the caller's own RESP handling
    # takes the non-NORMAL branch, not a crash.
    names = sorted(config.programs)
    specs = [cics_spec, *extra_specs]
    return {
        name: _compile_one(name, ordinal, len(names), config, parser, specs)
        for ordinal, name in enumerate(names, 1)
    }


def _region(
    config: RegionConfig, wiring: _Wiring, programs: Mapping[str, LinkedProgram]
) -> CicsRegion:
    return CicsRegion(
        programs,
        dict(config.transactions),
        wiring.screen_channel,
        wiring.input_channel,
        context_holder=wiring.context_holder,
        result_holder=wiring.result_holder,
        start_queue=wiring.start_queue,
        max_steps=_MAX_STEPS,
        min_commarea_len=config.min_commarea_len,
    )


def _region_noop() -> None:
    """Default on_abend: a CICS-only region has no composed SQL runtime to
    roll back when a task abends -- mirrors build_cics_spec's own default."""


def build_region(
    config: RegionConfig,
    bridge_jar: str,
    work_dir: Path,
    extra_specs: Sequence[CoprocessorSpec] = (),
    on_abend: Callable[[], None] = _region_noop,
) -> ServedRegion:
    wiring = _wiring()
    vsam_engine = _vsam_engine(config, work_dir / "vsam")
    # Pre-created and passed by reference, NOT left to build_cics_spec's own
    # `program_cache=None` default: CicsLoweringStrategy falls back to a
    # FRESH, unconnected `{}` per compile when it isn't a MutableMapping
    # (cics/strategy.py:1140), so every compiled program's own EXEC CICS
    # LINK builtin ends up resolving against its own private empty dict,
    # never the real one _compiled() builds -- every LINK silently no-ops
    # as "unknown program" regardless of what's in config.programs
    # (reproduced directly: one program LINKing to a correctly-configured,
    # successfully-compiled callee still logged "unknown program").
    program_cache: dict[str, LinkedProgram] = {}
    # `transid_to_program` needs NO populate-after dance (unlike
    # program_cache above): config.transactions is already fully loaded
    # from TOML before build_region runs, so it can be passed complete,
    # right now. But it DOES need to be passed AT ALL: build_cics_spec's
    # own default (`_NO_TRANSIDS`, cics/strategy.py:1186) is empty, and
    # every compiled program's own EXEC CICS START builtin bakes in
    # WHATEVER mapping it got at compile time -- completely separate from
    # the dict `_region()` below builds for CicsRegion's OWN routing.
    # Omitting this kwarg (as this function did until 2026-10-09) means
    # every EXEC CICS START TRANSID on ANY TN3270-served region rejects
    # with RejectReason.UNKNOWN_TRANSID unconditionally, regardless of
    # config -- reproduced directly against a real multi-program COBOL/
    # CICS corpus: a program's own compiled START TRANSID rejected even
    # though config.toml's [transactions] correctly mapped the target
    # transid to its program. Not specific to any one corpus: this is the
    # engine's own wiring, so it broke every program on every TN3270
    # region that uses START, same root cause and same fix shape as the
    # program_cache bug above.
    spec = build_cics_spec(
        start_queue=wiring.start_queue,
        context_holder=wiring.context_holder,
        result_holder=wiring.result_holder,
        program_cache=program_cache,
        transid_to_program=dict(config.transactions),
        vsam_engine=vsam_engine,
        screen_queue=wiring.screen_channel,
        input_queue=wiring.input_channel,
        on_abend=on_abend,
    )
    parser = _parser(config, bridge_jar, work_dir / "sym")
    fill(program_cache, _compiled(config, parser, spec, extra_specs))
    region = _region(config, wiring, program_cache)
    driver = PseudoConversationalDriver(
        region, wiring.screen_channel, frozenset(config.transactions)
    )
    return ServedRegion(driver, _catalog(config), vsam_engine)

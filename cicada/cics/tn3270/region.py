"""Building the CICS region a TN3270 server drives, from its RegionConfig."""

from __future__ import annotations

import queue
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cics.bms.catalog import MapCatalog, load_catalog
from cics.bms.generate import generate_symbolic_copybooks
from cics.bootstrap import compile_cics_program
from cics.coprocessor import build_cics_spec
from cics.dispatcher import CicsRegion
from cics.interval import StartQueue
from cics.screen.driver import PseudoConversationalDriver
from cics.tn3270.config import RegionConfig
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


def _parser(config: RegionConfig, bridge_jar: str, sym_dir: Path) -> ProLeapCobolParser:
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    generate_symbolic_copybooks(
        bms_dir=config.bms_dir,
        out_dir=sym_dir,
        hlasm_export_bin=str(config.hlasm_export),
    )
    return ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybook_dirs=[sym_dir, *config.copybook_dirs, CICS_COPYBOOKS],
    )


def _compiled(
    config: RegionConfig, parser: ProLeapCobolParser, spec: CoprocessorSpec
) -> dict[str, LinkedProgram]:
    # program_source_dirs resolves plain COBOL subprograms a transaction
    # program CALLs (e.g. COTRN02C -> CSUTLDTC) from the same cbl directory;
    # without it such a CALL is unresolved and the caller's own RESP handling
    # takes the non-NORMAL branch, not a crash.
    return {
        name: compile_cics_program(
            (config.source_dir / f"{name}.cbl").read_bytes(),
            parser,
            spec,
            program_source_dirs=(config.source_dir,),
        )
        for name in sorted(config.programs)
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


def build_region(config: RegionConfig, bridge_jar: str, work_dir: Path) -> ServedRegion:
    wiring = _wiring()
    vsam_engine = _vsam_engine(config, work_dir / "vsam")
    spec = build_cics_spec(
        start_queue=wiring.start_queue,
        context_holder=wiring.context_holder,
        result_holder=wiring.result_holder,
        vsam_engine=vsam_engine,
        screen_queue=wiring.screen_channel,
        input_queue=wiring.input_channel,
    )
    parser = _parser(config, bridge_jar, work_dir / "sym")
    region = _region(config, wiring, _compiled(config, parser, spec))
    driver = PseudoConversationalDriver(
        region, wiring.screen_channel, frozenset(config.transactions)
    )
    return ServedRegion(
        driver, load_catalog(config.bms_dir, str(config.hlasm_export)), vsam_engine
    )

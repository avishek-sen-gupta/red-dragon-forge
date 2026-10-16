"""A CICS region a TN3270 server drives: compiled into a litter package from its RegionConfig, then assembled from the package."""

from __future__ import annotations

import logging
import queue
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from catnip.system_catalog import SystemCatalog
from cics.bms.catalog import MapCatalog, catalog_from_json
from cics.bms.export import exported_mapsets, fresh_symbolic_copybooks
from cics.coprocessor import build_cics_spec
from cics.csd_parse import parse_csd_files
from cics.dispatcher import MAX_COMMAREA, CicsRegion
from cics.interval import StartQueue
from cics.runtime import install_cics_runtime
from cics.screen.driver import PseudoConversationalDriver
from cics.tn3270.config import RegionConfig, resolve_program_source
from cics.vsam.engine import VsamEngine
from cics.vsam.file_table import cics_files
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.project.coprocessor_compile import CoprocessorSpec
from interpreter.project.types import LinkedProgram
from litter.build import build
from litter.cics_file import CicsFile
from litter.package import Package
from litter.transaction import Transaction

CICS_COPYBOOKS = Path(__file__).parents[1] / "copybooks"
_MAX_STEPS = 1_000_000
_PACKAGE_NAME = "region"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServedRegion:
    driver: PseudoConversationalDriver
    catalog: MapCatalog
    vsam_engine: VsamEngine


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


def _dsnames(csd_files: Sequence[Path]) -> dict[str, str]:
    return {
        name: dsn for csd in csd_files for name, dsn in parse_csd_files(csd).items()
    }


def _copybook_dirs(config: RegionConfig, sym_dir: Path) -> tuple[Path, ...]:
    return (sym_dir, *config.copybook_dirs, CICS_COPYBOOKS)


def _parser(
    config: RegionConfig, bridge_jar: str, copybook_dirs: Sequence[Path]
) -> ProLeapCobolParser:
    return ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybook_dirs=list(copybook_dirs),
        copybook_exts=list(config.copybook_exts),
    )


def compile_region_package(
    config: RegionConfig,
    bridge_jar: str,
    work_dir: Path,
    out_dir: Path,
    extra_specs: Sequence[CoprocessorSpec] = (),
) -> Path:
    sym_dir = work_dir / "sym"
    fresh_symbolic_copybooks(config.bms_dirs, str(config.hlasm_export), sym_dir)
    copybook_dirs = _copybook_dirs(config, sym_dir)
    programs = tuple(sorted(config.programs))
    return build(
        name=_PACKAGE_NAME,
        programs=programs,
        link=programs,
        sources={name: resolve_program_source(config, name) for name in programs},
        parser=_parser(config, bridge_jar, copybook_dirs),
        specs=(build_cics_spec(), *extra_specs),
        copybook_dirs=copybook_dirs,
        work_dir=work_dir / "units",
        out_dir=out_dir,
        transactions=tuple(
            Transaction(transid, program)
            for transid, program in sorted(config.transactions.items())
        ),
        files=tuple(
            CicsFile(name, dsn) for name, dsn in _dsnames(config.csd_files).items()
        ),
        mapsets=exported_mapsets(
            config.bms_dirs, str(config.hlasm_export), work_dir / "maps"
        ),
        tolerant=False,
    )


def _region_noop() -> None:
    return None


def _region(
    program_cache: Mapping[str, LinkedProgram],
    transid_to_program: Mapping[str, str],
    wiring: _Wiring,
    min_commarea_len: int,
    on_abend: Callable[[], None],
    permit_unresolved_call_targets: bool = True,
) -> CicsRegion:
    return CicsRegion(
        program_cache,
        transid_to_program,
        wiring.screen_channel,
        wiring.input_channel,
        context_holder=wiring.context_holder,
        result_holder=wiring.result_holder,
        start_queue=wiring.start_queue,
        max_steps=_MAX_STEPS,
        min_commarea_len=min_commarea_len,
        on_abend=on_abend,
        permit_unresolved_call_targets=permit_unresolved_call_targets,
    )


def assemble_region(
    package: Package,
    system: SystemCatalog,
    *,
    min_commarea_len: int = MAX_COMMAREA,
    on_abend: Callable[[], None] = _region_noop,
    permit_unresolved_call_targets: bool = True,
) -> ServedRegion:
    wiring = _wiring()
    manifest = package.manifest
    vsam_engine = VsamEngine(
        cics_files(system, {f.name: f.dsname for f in manifest.files})
    )
    program_cache = {name: package.image for name in manifest.programs}
    transid_to_program = {t.transid: t.program for t in manifest.transactions}
    install_cics_runtime(
        wiring.context_holder,
        start_queue=wiring.start_queue,
        result_holder=wiring.result_holder,
        program_cache=program_cache,
        transid_to_program=transid_to_program,
        vsam_engine=vsam_engine,
        screen_queue=wiring.screen_channel,
        input_queue=wiring.input_channel,
        on_abend=on_abend,
        permit_unresolved_call_targets=permit_unresolved_call_targets,
    )
    region = _region(
        program_cache,
        transid_to_program,
        wiring,
        min_commarea_len,
        on_abend,
        permit_unresolved_call_targets,
    )
    driver = PseudoConversationalDriver(
        region, wiring.screen_channel, frozenset(transid_to_program)
    )
    logger.info(
        "assembled a region of %d programs and %d transactions",
        len(program_cache),
        len(transid_to_program),
    )
    return ServedRegion(
        driver, catalog_from_json(tuple(package.mapsets.values())), vsam_engine
    )

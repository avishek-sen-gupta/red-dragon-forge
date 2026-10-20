"""A CICS region a TN3270 server drives, assembled from a litter package."""

from __future__ import annotations

import logging
import queue
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from catnip.system_catalog import SystemCatalog
from cics.bms.catalog import MapCatalog, catalog_from_json
from cics.dispatcher import MAX_COMMAREA, CicsRegion
from cics.interval import StartQueue
from cics.region_clock import LOCAL_CLOCK, RegionClock
from cics.runtime import NO_HOOKS, install_cics_runtime
from cics.screen.driver import PseudoConversationalDriver
from cics.transaction_hooks import TransactionHooks
from cics.vsam.engine import VsamEngine
from cics.vsam.file_table import cics_files
from interpreter.func_name import FuncName
from interpreter.project.types import LinkedProgram
from interpreter.vm.builtin import Builtin
from litter.package import Package

CICS_COPYBOOKS = Path(__file__).parents[1] / "copybooks"
_NO_BUILTINS: Mapping[FuncName, Builtin] = MappingProxyType({})
_MAX_STEPS = 1_000_000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServedRegion:
    driver: PseudoConversationalDriver
    catalog: MapCatalog
    vsam_engine: VsamEngine
    builtins: Mapping[FuncName, Builtin]


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


def _region_noop() -> None:
    return None


@dataclass(frozen=True)
class _Tuning:
    """How the region's tasks run: the COMMAREA floor, the abend rollback and whether a CALL may reach nothing."""

    min_commarea_len: int
    on_abend: Callable[[], None]
    permit_unresolved_call_targets: bool


def _region(
    program_cache: Mapping[str, LinkedProgram],
    transid_to_program: Mapping[str, str],
    wiring: _Wiring,
    builtins: Mapping[FuncName, Builtin],
    tuning: _Tuning,
) -> CicsRegion:
    return CicsRegion(
        program_cache,
        transid_to_program,
        wiring.screen_channel,
        wiring.input_channel,
        builtins=builtins,
        context_holder=wiring.context_holder,
        result_holder=wiring.result_holder,
        start_queue=wiring.start_queue,
        max_steps=_MAX_STEPS,
        min_commarea_len=tuning.min_commarea_len,
        on_abend=tuning.on_abend,
        permit_unresolved_call_targets=tuning.permit_unresolved_call_targets,
    )


def assemble_region(
    package: Package,
    system: SystemCatalog,
    *,
    min_commarea_len: int = MAX_COMMAREA,
    on_abend: Callable[[], None] = _region_noop,
    permit_unresolved_call_targets: bool = True,
    hooks: TransactionHooks = NO_HOOKS,
    other_builtins: Mapping[FuncName, Builtin] = _NO_BUILTINS,
    clock: RegionClock = LOCAL_CLOCK,
) -> ServedRegion:
    wiring = _wiring()
    manifest = package.manifest
    vsam_engine = VsamEngine(
        cics_files(system, {f.name: f.dsname for f in manifest.files})
    )
    program_cache = {name: package.image for name in manifest.programs}
    transid_to_program = {t.transid: t.program for t in manifest.transactions}
    runtime = install_cics_runtime(
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
        hooks=hooks,
        other_builtins=other_builtins,
        clock=clock,
    )
    region = _region(
        program_cache,
        transid_to_program,
        wiring,
        runtime.builtins,
        _Tuning(min_commarea_len, on_abend, permit_unresolved_call_targets),
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
        driver,
        catalog_from_json(tuple(package.mapsets.values())),
        vsam_engine,
        runtime.builtins,
    )

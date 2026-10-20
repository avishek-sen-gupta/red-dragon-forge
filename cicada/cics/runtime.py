"""The CICS coprocessor's runtime surface: the ``__cics_*`` builtins over a region's live state, composed into the region's table."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, MutableSequence
from dataclasses import dataclass
from functools import partial
from types import MappingProxyType
from typing import TypeVar, cast

from cics.builtins.system import (
    DEFAULT_USERID,
    make_abend_builtin,
    make_abend_unhandled_builtin,
    make_abend_unsupported_builtin,
    make_asktime_builtin,
    make_assign_builtin,
    make_bif_deedit_builtin,
    make_datform_builtin,
    make_handle_abend_builtin,
    make_init_eib_builtin,
    make_inquire_builtin,
    make_runtime_noop_builtin,
    make_writeq_td_builtin,
)
from cics.cell import Holder
from cics.cics_runtime import CicsRuntime
from cics.interval import StartQueue
from cics.region_clock import LOCAL_CLOCK, RegionClock
from cics.strategy import NOT_SUPPLIED, Absent
from cics.terminal import InputChannel, ScreenChannel
from cics.transaction_hooks import TransactionHooks
from cics.types import DEFAULT_TERMID, CicsContext, DispatchResult
from cics.vsam.engine import VsamEngine
from interpreter.func_name import FuncName
from interpreter.project.types import LinkedProgram
from interpreter.vm.builtin import Builtin
from interpreter.vm.builtins import compose_builtins, core_builtins

T = TypeVar("T")

OWN_START_QUEUE = StartQueue()
NO_HOOKS = TransactionHooks()
_NO_BUILTINS: Mapping[FuncName, Builtin] = MappingProxyType({})

RegionBuiltins = Callable[[], Mapping[FuncName, Builtin]]


def _noop() -> None:
    pass


def _as_builtin_list(holder: Holder[T]) -> list[T]:
    return cast("list[T]", holder)


def _named(entries: Mapping[str, Builtin]) -> Mapping[FuncName, Builtin]:
    return {FuncName(name): builtin for name, builtin in entries.items()}


@dataclass(frozen=True)
class _Wiring:
    """The caller's shared objects, kept by identity so the builtins see later changes."""

    context_holder: list[CicsContext]
    result_holder: list[DispatchResult]
    program_cache: MutableMapping[str, LinkedProgram]
    td_queue: MutableSequence[str]
    permit_unresolved_call_targets: bool


def _system_builtins(
    wiring: _Wiring, identity: tuple[str, str, str], clock: RegionClock
) -> Mapping[FuncName, Builtin]:
    applid, sysid, userid = identity
    return _named(
        {
            "__cics_assign": make_assign_builtin(applid, sysid, userid),
            "__cics_asktime": make_asktime_builtin(clock.now),
            "__cics_datform": make_datform_builtin(clock.datform),
            "__cics_bif_deedit": make_bif_deedit_builtin(),
            "__cics_inquire": make_inquire_builtin(wiring.program_cache),
            "__cics_writeq_td": make_writeq_td_builtin(wiring.td_queue.append),
            "__cics_handle_abend": make_handle_abend_builtin(),
        }
    )


def _hook_builtins(hooks: TransactionHooks) -> Mapping[FuncName, Builtin]:
    return _named(
        {
            "__cics_task_end_hook": hooks.task_end,
            "__cics_syncpoint_hook": hooks.syncpoint,
            "__cics_rollback_hook": hooks.rollback,
        }
    )


def _flow_builtins(
    wiring: _Wiring, region_builtins: RegionBuiltins
) -> Mapping[FuncName, Builtin]:
    from cics.builtins.flow import (
        make_link_builtin,
        make_link_resolve_builtin,
        make_set_return_context_builtin,
        make_set_xctl_context_builtin,
    )
    from interpreter.run import run_linked

    return _named(
        {
            "__cics_set_return_context": make_set_return_context_builtin(
                wiring.result_holder
            ),
            "__cics_set_xctl_context": make_set_xctl_context_builtin(
                wiring.result_holder, wiring.program_cache
            ),
            "__cics_link_resolve": make_link_resolve_builtin(wiring.program_cache),
            "__cics_link": make_link_builtin(
                wiring.program_cache,
                wiring.result_holder,
                wiring.context_holder,
                2_000_000,
                region_builtins=region_builtins,
                _run_fn=partial(
                    run_linked,
                    permit_unresolved_call_targets=wiring.permit_unresolved_call_targets,
                ),
            ),
        }
    )


def _abend_builtins(
    wiring: _Wiring, on_abend: Callable[[], None]
) -> Mapping[FuncName, Builtin]:
    return _named(
        {
            "__cics_unlock": make_runtime_noop_builtin(
                "EXEC CICS UNLOCK",
                "single-task emulation holds no lock another task could see",
            ),
            "__cics_abend": make_abend_builtin(wiring.result_holder, on_abend),
            "__cics_abend_unhandled": make_abend_unhandled_builtin(
                wiring.result_holder, on_abend
            ),
            "__cics_abend_unsupported": make_abend_unsupported_builtin(
                wiring.result_holder, on_abend
            ),
        }
    )


@dataclass(frozen=True)
class _Terminal:
    screen_queue: ScreenChannel
    input_queue: InputChannel
    receive_timeout: float


def _screen_builtins(
    wiring: _Wiring, terminal: _Terminal
) -> Mapping[FuncName, Builtin]:
    from cics.builtins.screen import (
        make_apply_input_builtin,
        make_receive_map_builtin,
        make_send_map_builtin,
        make_send_text_builtin,
    )

    return _named(
        {
            "__cics_send_map": make_send_map_builtin(
                terminal.screen_queue, wiring.context_holder
            ),
            "__cics_receive_map": make_receive_map_builtin(
                terminal.input_queue,
                wiring.context_holder,
                wiring.result_holder,
                timeout=terminal.receive_timeout,
            ),
            "__cics_apply_input": make_apply_input_builtin(),
            "__cics_send_text": make_send_text_builtin(terminal.screen_queue),
        }
    )


def _vsam_builtins(engine: VsamEngine) -> Mapping[FuncName, Builtin]:
    from cics.builtins.vsam import (
        make_vsam_delete_builtin,
        make_vsam_endbr_builtin,
        make_vsam_key_length_builtin,
        make_vsam_read_builtin,
        make_vsam_readnext_builtin,
        make_vsam_readprev_builtin,
        make_vsam_resetbr_builtin,
        make_vsam_rewrite_builtin,
        make_vsam_startbr_builtin,
        make_vsam_write_builtin,
    )

    return _named(
        {
            "__cics_read": make_vsam_read_builtin(engine),
            "__cics_write": make_vsam_write_builtin(engine),
            "__cics_rewrite": make_vsam_rewrite_builtin(engine),
            "__cics_delete": make_vsam_delete_builtin(engine),
            "__cics_key_length": make_vsam_key_length_builtin(engine),
            "__cics_startbr": make_vsam_startbr_builtin(engine),
            "__cics_resetbr": make_vsam_resetbr_builtin(engine),
            "__cics_readnext": make_vsam_readnext_builtin(engine),
            "__cics_readprev": make_vsam_readprev_builtin(engine),
            "__cics_endbr": make_vsam_endbr_builtin(engine),
        }
    )


def _interval_builtins(
    start_queue: StartQueue, transid_to_program: Mapping[str, str], region_termid: str
) -> Mapping[FuncName, Builtin]:
    from cics.builtins.interval import make_retrieve_builtin, make_start_builtin

    return _named(
        {
            "__cics_start": make_start_builtin(
                start_queue, transid_to_program, region_termid
            ),
            "__cics_retrieve": make_retrieve_builtin(start_queue),
        }
    )


def _terminal_builtins(
    wiring: _Wiring,
    channels: tuple[ScreenChannel | Absent, InputChannel | Absent],
    receive_timeout: float,
) -> Mapping[FuncName, Builtin]:
    screen_queue, input_queue = channels
    if isinstance(screen_queue, ScreenChannel) and isinstance(
        input_queue, InputChannel
    ):
        return _screen_builtins(
            wiring, _Terminal(screen_queue, input_queue, receive_timeout)
        )
    return _NO_BUILTINS


def _io_builtins(
    wiring: _Wiring,
    channels: tuple[ScreenChannel | Absent, InputChannel | Absent],
    receive_timeout: float,
    vsam_engine: VsamEngine | Absent,
) -> Mapping[FuncName, Builtin]:
    terminal = _terminal_builtins(wiring, channels, receive_timeout)
    if isinstance(vsam_engine, VsamEngine):
        return {**terminal, **_vsam_builtins(vsam_engine)}
    return terminal


def _core_entries(
    wiring: _Wiring,
    region: _Region,
    on_abend: Callable[[], None],
    region_builtins: RegionBuiltins,
) -> Mapping[FuncName, Builtin]:
    return {
        FuncName("__cics_init_eib"): make_init_eib_builtin(wiring.context_holder),
        **_system_builtins(wiring, region.identity, region.clock),
        **_abend_builtins(wiring, on_abend),
        **_flow_builtins(wiring, region_builtins),
    }


def _wiring(
    context_holder: Holder[CicsContext],
    result_holder: Holder[DispatchResult] | Absent,
    program_cache: MutableMapping[str, LinkedProgram],
    td_queue: MutableSequence[str] | Absent,
    permit_unresolved_call_targets: bool,
) -> _Wiring:
    results: Holder[DispatchResult] = (
        cast("Holder[DispatchResult]", [None])
        if not result_holder
        else cast("Holder[DispatchResult]", result_holder)
    )
    return _Wiring(
        context_holder=_as_builtin_list(context_holder),
        result_holder=_as_builtin_list(results),
        program_cache=program_cache,
        td_queue=td_queue if isinstance(td_queue, MutableSequence) else [],
        permit_unresolved_call_targets=permit_unresolved_call_targets,
    )


@dataclass(frozen=True)
class _Region:
    """Where the region's tasks run: their terminal, files, START queue and identity."""

    channels: tuple[ScreenChannel | Absent, InputChannel | Absent]
    receive_timeout: float
    vsam_engine: VsamEngine | Absent
    start_queue: StartQueue
    transid_to_program: Mapping[str, str]
    region_termid: str
    identity: tuple[str, str, str]
    clock: RegionClock


def _entries(
    wiring: _Wiring,
    region: _Region,
    hooks: TransactionHooks,
    on_abend: Callable[[], None],
    region_builtins: RegionBuiltins,
) -> Mapping[FuncName, Builtin]:
    return MappingProxyType(
        {
            **_core_entries(wiring, region, on_abend, region_builtins),
            **_hook_builtins(hooks),
            **_io_builtins(
                wiring, region.channels, region.receive_timeout, region.vsam_engine
            ),
            **_interval_builtins(
                region.start_queue, region.transid_to_program, region.region_termid
            ),
        }
    )


def _runtime(
    wiring: _Wiring,
    region: _Region,
    hooks: TransactionHooks,
    on_abend: Callable[[], None],
    other_builtins: Mapping[FuncName, Builtin],
) -> CicsRuntime:
    def region_builtins() -> Mapping[FuncName, Builtin]:
        return table

    entries = _entries(wiring, region, hooks, on_abend, region_builtins)
    table = compose_builtins(core_builtins(), entries, other_builtins)
    return CicsRuntime(entries=entries, builtins=table, start_queue=region.start_queue)


def install_cics_runtime(
    context_holder: Holder[CicsContext],
    *,
    program_cache: MutableMapping[str, LinkedProgram],
    transid_to_program: Mapping[str, str],
    result_holder: Holder[DispatchResult] | Absent = NOT_SUPPLIED,
    td_queue: MutableSequence[str] | Absent = NOT_SUPPLIED,
    applid: str = "CARDDEMO",
    sysid: str = "SYS1",
    userid: str = DEFAULT_USERID,
    screen_queue: ScreenChannel | Absent = NOT_SUPPLIED,
    input_queue: InputChannel | Absent = NOT_SUPPLIED,
    vsam_engine: VsamEngine | Absent = NOT_SUPPLIED,
    receive_timeout: float = 30.0,
    start_queue: StartQueue = OWN_START_QUEUE,
    region_termid: str = DEFAULT_TERMID,
    on_abend: Callable[[], None] = _noop,
    permit_unresolved_call_targets: bool = True,
    hooks: TransactionHooks = NO_HOOKS,
    other_builtins: Mapping[FuncName, Builtin] = _NO_BUILTINS,
    clock: RegionClock = LOCAL_CLOCK,
) -> CicsRuntime:
    wiring = _wiring(
        context_holder,
        result_holder,
        program_cache,
        td_queue,
        permit_unresolved_call_targets,
    )
    region = _Region(
        channels=(screen_queue, input_queue),
        receive_timeout=receive_timeout,
        vsam_engine=vsam_engine,
        start_queue=StartQueue() if start_queue is OWN_START_QUEUE else start_queue,
        transid_to_program=transid_to_program,
        region_termid=region_termid,
        identity=(applid, sysid, userid),
        clock=clock,
    )
    return _runtime(wiring, region, hooks, on_abend, other_builtins)

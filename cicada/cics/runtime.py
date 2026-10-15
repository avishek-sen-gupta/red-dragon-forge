"""The CICS coprocessor's runtime surface: installs the ``__cics_*`` builtins over a region's live state."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, MutableSequence
from dataclasses import dataclass
from typing import TypeVar, cast

from cics.builtins.system import (
    DEFAULT_USERID,
    make_abend_builtin,
    make_abend_unhandled_builtin,
    make_abend_unsupported_builtin,
    make_asktime_builtin,
    make_assign_builtin,
    make_bif_deedit_builtin,
    make_formattime_builtin,
    make_handle_abend_builtin,
    make_handle_noop_builtin,
    make_init_eib_builtin,
    make_inquire_builtin,
    make_runtime_noop_builtin,
    make_writeq_td_builtin,
)
from cics.cell import Holder
from cics.interval import StartQueue
from cics.strategy import NOT_SUPPLIED, Absent
from cics.strategy_stores import register, register_default
from cics.terminal import InputChannel, ScreenChannel
from cics.types import DEFAULT_TERMID, CicsContext, DispatchResult
from cics.vsam.engine import VsamEngine
from interpreter.project.types import LinkedProgram

T = TypeVar("T")

OWN_START_QUEUE = StartQueue()


def _noop() -> None:
    pass


def _as_builtin_list(holder: Holder[T]) -> list[T]:
    return cast("list[T]", holder)


@dataclass(frozen=True)
class _Wiring:
    """The caller's shared objects, kept by identity so the builtins see later changes."""

    context_holder: list[CicsContext]
    result_holder: list[DispatchResult]
    program_cache: MutableMapping[str, LinkedProgram]
    td_queue: MutableSequence[str]


def _register_system_builtins(wiring: _Wiring, identity: tuple[str, str, str]) -> None:
    applid, sysid, userid = identity
    register("__cics_assign", make_assign_builtin(applid, sysid, userid))
    register("__cics_asktime", make_asktime_builtin())
    register("__cics_bif_deedit", make_bif_deedit_builtin())
    register("__cics_formattime", make_formattime_builtin())
    register("__cics_inquire", make_inquire_builtin(wiring.program_cache))
    register("__cics_writeq_td", make_writeq_td_builtin(wiring.td_queue.append))
    register("__cics_handle_abend", make_handle_abend_builtin())


def _register_flow_builtins(wiring: _Wiring, on_abend: Callable[[], None]) -> None:
    from cics.builtins.flow import (
        make_link_builtin,
        make_noop_hook_builtin,
        make_noop_task_end_hook_builtin,
        make_set_return_context_builtin,
        make_set_xctl_context_builtin,
    )

    register_default("__cics_task_end_hook", make_noop_task_end_hook_builtin())
    register_default("__cics_syncpoint_hook", make_noop_hook_builtin())
    register_default("__cics_rollback_hook", make_noop_hook_builtin())
    _register_abend_builtins(wiring, on_abend)
    register(
        "__cics_set_return_context",
        make_set_return_context_builtin(wiring.result_holder),
    )
    register(
        "__cics_set_xctl_context", make_set_xctl_context_builtin(wiring.result_holder)
    )
    register(
        "__cics_link",
        make_link_builtin(
            wiring.program_cache,
            wiring.result_holder,
            wiring.context_holder,
            2_000_000,
        ),
    )


def _register_abend_builtins(wiring: _Wiring, on_abend: Callable[[], None]) -> None:
    register("__cics_handle_aid", make_handle_noop_builtin("HANDLE AID"))
    register(
        "__cics_unlock",
        make_runtime_noop_builtin(
            "EXEC CICS UNLOCK",
            "single-task emulation holds no lock another task could see",
        ),
    )
    register("__cics_abend", make_abend_builtin(wiring.result_holder, on_abend))
    register(
        "__cics_abend_unhandled",
        make_abend_unhandled_builtin(wiring.result_holder, on_abend),
    )
    register(
        "__cics_abend_unsupported",
        make_abend_unsupported_builtin(wiring.result_holder, on_abend),
    )


@dataclass(frozen=True)
class _Terminal:
    screen_queue: ScreenChannel
    input_queue: InputChannel
    receive_timeout: float


def _register_screen_builtins(wiring: _Wiring, terminal: _Terminal) -> None:
    from cics.builtins.screen import (
        make_apply_input_builtin,
        make_receive_map_builtin,
        make_send_map_builtin,
        make_send_text_builtin,
    )

    register(
        "__cics_send_map",
        make_send_map_builtin(terminal.screen_queue, wiring.context_holder),
    )
    register(
        "__cics_receive_map",
        make_receive_map_builtin(
            terminal.input_queue,
            wiring.context_holder,
            wiring.result_holder,
            timeout=terminal.receive_timeout,
        ),
    )
    register("__cics_apply_input", make_apply_input_builtin())
    register("__cics_send_text", make_send_text_builtin(terminal.screen_queue))


def _register_vsam_builtins(engine: VsamEngine) -> None:
    from cics.builtins.vsam import (
        make_vsam_delete_builtin,
        make_vsam_endbr_builtin,
        make_vsam_read_builtin,
        make_vsam_readnext_builtin,
        make_vsam_readprev_builtin,
        make_vsam_rewrite_builtin,
        make_vsam_startbr_builtin,
        make_vsam_write_builtin,
    )

    register("__cics_read", make_vsam_read_builtin(engine))
    register("__cics_write", make_vsam_write_builtin(engine))
    register("__cics_rewrite", make_vsam_rewrite_builtin(engine))
    register("__cics_delete", make_vsam_delete_builtin(engine))
    register("__cics_startbr", make_vsam_startbr_builtin(engine))
    register("__cics_readnext", make_vsam_readnext_builtin(engine))
    register("__cics_readprev", make_vsam_readprev_builtin(engine))
    register("__cics_endbr", make_vsam_endbr_builtin(engine))


def _register_interval_builtins(
    start_queue: StartQueue, transid_to_program: Mapping[str, str], region_termid: str
) -> None:
    from cics.builtins.interval import make_retrieve_builtin, make_start_builtin

    register(
        "__cics_start",
        make_start_builtin(start_queue, transid_to_program, region_termid),
    )
    register("__cics_retrieve", make_retrieve_builtin(start_queue))


def _register_terminal_builtins(
    wiring: _Wiring,
    channels: tuple[ScreenChannel | Absent, InputChannel | Absent],
    receive_timeout: float,
) -> None:
    screen_queue, input_queue = channels
    if isinstance(screen_queue, ScreenChannel) and isinstance(
        input_queue, InputChannel
    ):
        _register_screen_builtins(
            wiring, _Terminal(screen_queue, input_queue, receive_timeout)
        )


def _register_io_builtins(
    wiring: _Wiring,
    channels: tuple[ScreenChannel | Absent, InputChannel | Absent],
    receive_timeout: float,
    vsam_engine: VsamEngine | Absent,
) -> None:
    _register_terminal_builtins(wiring, channels, receive_timeout)
    if isinstance(vsam_engine, VsamEngine):
        _register_vsam_builtins(vsam_engine)


_MULTIPLE_STRATEGIES = (
    " Installing the CICS runtime more than once in one process is unsupported."
)


def _register_core_builtins(
    wiring: _Wiring,
    identity: tuple[str, str, str],
    on_abend: Callable[[], None],
) -> None:
    register(
        "__cics_init_eib",
        make_init_eib_builtin(wiring.context_holder),
        _MULTIPLE_STRATEGIES,
    )
    _register_system_builtins(wiring, identity)
    _register_flow_builtins(wiring, on_abend)


def _wiring(
    context_holder: Holder[CicsContext],
    result_holder: Holder[DispatchResult] | Absent,
    program_cache: MutableMapping[str, LinkedProgram],
    td_queue: MutableSequence[str] | Absent,
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
    )


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
) -> StartQueue:
    used_start_queue = StartQueue() if start_queue is OWN_START_QUEUE else start_queue
    wiring = _wiring(context_holder, result_holder, program_cache, td_queue)
    _register_core_builtins(wiring, (applid, sysid, userid), on_abend)
    _register_io_builtins(
        wiring, (screen_queue, input_queue), receive_timeout, vsam_engine
    )
    _register_interval_builtins(used_start_queue, transid_to_program, region_termid)
    return used_start_queue

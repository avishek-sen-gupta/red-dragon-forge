"""Conversational CICS driver — built on the VM's suspend/resume primitive.

CardDemo is *pseudo-conversational*: each program processes one input, SENDs a
screen, and RETURNs — the task ends every turn and state lives in the COMMAREA.
A *conversational* program (e.g. zBANK) instead loops ``SEND ... RECEIVE ...``
within a single task: it stays resident across the terminal wait, its
working-storage persists naturally, and it issues a single bare ``EXEC CICS
RETURN`` only when done.

To run such a program the VM must PAUSE at each ``EXEC CICS RECEIVE`` and resume
with the supplied input — all within one execution so working-storage survives.
We do that with the core **suspend/resume primitive**: conversational RECEIVE MAP
lowers to a ``SUSPEND`` (see ``CicsLoweringStrategy(conversational=True)``), and
this region drives the task with ``run_linked_resumable`` / ``resume_linked``.
Each ``send()`` injects the terminal ``InputEvent`` as the resumed value, which
the ``__cics_apply_input`` builtin writes into the symbolic map's input fields.

This replaces the Phase-0 greenlet spike driver: it is deterministic and
single-threaded like greenlet, but the continuation is the serializable,
multi-shot ``ExecutionState`` rather than a parked stack.
"""

from __future__ import annotations

import queue
from typing import Any

from interpreter.run import Suspended, resume_linked, run_linked_resumable

from cics.types import CicsContext, DispatchKind, DispatchResult

_DFHENTER = "\x7d"


def _build_initial_vm(context: CicsContext):
    """The same initial VM run_cics() sets up: COMMAREA bound to an addressable
    region and a main frame carrying the transid / EIBCALEN / EIBAID / params."""
    from interpreter.address import Address
    from interpreter.func_name import FuncName
    from interpreter.types.type_expr import UNKNOWN
    from interpreter.types.typed_value import typed
    from interpreter.var_name import VarName
    from interpreter.vm.vm_types import StackFrame, VMState

    vm = VMState()
    commarea_addr = Address("rgn_commarea")
    vm.region_set(commarea_addr, bytearray(context.commarea))
    vm.call_stack.append(
        StackFrame(
            function_name=FuncName("main"),
            local_vars={
                VarName("__cics_transid"): typed(context.transid, UNKNOWN),
                VarName("__cics_eibcalen"): typed(len(context.commarea), UNKNOWN),
                VarName("__cics_eibaid"): typed(context.eibaid, UNKNOWN),
                VarName("__params_region"): typed(commarea_addr, UNKNOWN),
            },
        )
    )
    return vm


def _entry_point(program: Any):
    """Mirror run_cics()'s entry resolution: the program's own func label if the
    bootstrap recorded one, else the sole bare ``func_*`` (not ``func_init_params_``).
    """
    from interpreter.run import EntryPoint

    entry_label = getattr(program, "entry_func_label", None)
    if entry_label is not None:
        entry_label_str = str(entry_label)
        return EntryPoint.function(
            lambda ref, _lbl=entry_label_str: str(ref.label) == _lbl
        )
    return EntryPoint.function(
        lambda ref: str(ref.label).startswith("func_")
        and not str(ref.label).startswith("func_init_params_")
    )


class ConversationalRegion:
    """Drive a conversational CICS task one terminal exchange at a time, on the
    VM suspend/resume primitive.

    ``start()`` runs the task to its first ``RECEIVE`` (a SUSPEND) or to RETURN and
    returns the screens SENT so far; each ``send(event)`` injects the input at the
    pending RECEIVE and runs to the next one (or to RETURN). The task ends at the
    bare ``EXEC CICS RETURN``; ``done``/``result`` then report the DispatchResult.

    Requires the program to have been compiled with
    ``CicsLoweringStrategy(conversational=True)`` so RECEIVE MAP lowers to SUSPEND.
    """

    def __init__(
        self,
        program: Any,
        transid: str,
        *,
        screen_queue: "queue.Queue[Any]",
        context_holder: list,
        result_holder: list,
        max_steps: int = 2_000_000,
    ) -> None:
        self._program = program
        self._transid = transid
        self._screen_queue = screen_queue
        self._context_holder = context_holder
        self._result_holder = result_holder
        self._max_steps = max_steps
        self._state: Any = None
        self._done = False
        self._result: DispatchResult | None = None

    def start(self, *, commarea: bytes = b"", eibaid: str = _DFHENTER) -> list[dict]:
        ctx = CicsContext(transid=self._transid, commarea=commarea, eibaid=eibaid)
        self._context_holder[0] = ctx
        self._result_holder[0] = None
        vm = _build_initial_vm(ctx)
        outcome = run_linked_resumable(
            self._program,
            _entry_point(self._program),
            max_steps=self._max_steps,
            initial_vm=vm,
        )
        return self._absorb(outcome)

    def send(self, input_event: Any) -> list[dict]:
        if self._state is None:
            raise RuntimeError("send() before start(), or conversation already ended")
        outcome = resume_linked(
            self._program, self._state, input_event, max_steps=self._max_steps
        )
        return self._absorb(outcome)

    def _absorb(self, outcome: Any) -> list[dict]:
        if isinstance(outcome, Suspended):
            self._state = outcome.state
        else:  # Completed — the task reached its bare EXEC CICS RETURN
            self._done = True
            self._state = None
            self._result = (
                self._result_holder[0]
                if self._result_holder[0] is not None
                else DispatchResult(kind=DispatchKind.RETURN)
            )
        return self._drain()

    def _drain(self) -> list[dict]:
        screens: list[dict] = []
        while True:
            try:
                screens.append(self._screen_queue.get_nowait())
            except queue.Empty:
                break
        return screens

    @property
    def done(self) -> bool:
        return self._done

    @property
    def result(self) -> DispatchResult | None:
        return self._result

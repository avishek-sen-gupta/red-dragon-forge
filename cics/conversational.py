"""Conversational CICS driver.

CardDemo is *pseudo-conversational*: each program processes one input, SENDs a
screen, and RETURNs — the task ends every turn and state lives in the COMMAREA.
A *conversational* program (e.g. zBANK) instead loops ``SEND ... RECEIVE ...``
within a single task: it stays resident across the terminal wait, its
working-storage persists naturally, and it issues a single bare ``EXEC CICS
RETURN`` only when done.

To run such a program we need the VM to PAUSE at each ``EXEC CICS RECEIVE`` and
resume with the supplied input — all within one ``run_cics`` execution so
working-storage survives. We do this with a **greenlet** (a stackful coroutine):
``run_cics`` runs inside a child greenlet, and the RECEIVE builtin's
``input_queue.get`` yields control back to the driver greenlet (cooperative
suspend) rather than blocking a thread. This keeps the whole thing single
threaded and deterministic — no OS-thread races, no timeouts — and needs no
change to the VM (the suspend happens below the Python-function level, on the
greenlet's stack).

This is the Phase-0 spike mechanism; it deliberately uses greenlets rather than a
core VM suspend/resume primitive (see docs/design/conversational-suspend-resume).
"""

from __future__ import annotations

import queue
from typing import Any

from greenlet import getcurrent, greenlet

from cics.dispatcher import run_cics
from cics.types import CicsContext, DispatchResult

_DFHENTER = "\x7d"


class GreenletInputChannel:
    """InputChannel whose ``get`` cooperatively suspends the VM at RECEIVE.

    Conforms structurally to the InputChannel protocol the RECEIVE MAP builtin
    uses (``get(block=?, timeout=?)``). Instead of blocking, it switches to the
    parent (driver) greenlet; the driver resumes the VM greenlet with the next
    ``InputEvent`` via ``switch(event)``, which becomes this call's return value.
    """

    def get(self, block: bool = True, timeout: float | None = None) -> Any:
        # Running inside the VM greenlet: hand control to the driver and receive
        # the InputEvent it switches back in.
        return getcurrent().parent.switch()

    def put(self, item: Any) -> None:  # pragma: no cover - not used in this mode
        raise RuntimeError(
            "conversational input is supplied via ConversationalRegion.send(), "
            "not input_queue.put()"
        )


class ConversationalRegion:
    """Drive a conversational CICS task one terminal exchange at a time.

    The whole conversation is a single ``run_cics`` call living in a greenlet, so
    working-storage persists across screens. ``start()`` runs the program to its
    first RECEIVE (or to RETURN) and returns the screens SENT so far; each
    ``send(event)`` answers the pending RECEIVE and runs to the next one (or to
    RETURN). The task ends at the bare ``EXEC CICS RETURN``.
    """

    def __init__(
        self,
        program: Any,
        transid: str,
        *,
        screen_queue: "queue.Queue[Any]",
        input_channel: GreenletInputChannel,
        context_holder: list,
        result_holder: list,
        max_steps: int = 2_000_000,
    ) -> None:
        self._program = program
        self._transid = transid
        self._screen_queue = screen_queue
        self._input_channel = input_channel
        self._context_holder = context_holder
        self._result_holder = result_holder
        self._max_steps = max_steps
        self._g: greenlet | None = None
        self._result: DispatchResult | None = None

    def start(self, *, commarea: bytes = b"", eibaid: str = _DFHENTER) -> list[dict]:
        """Begin the task; run to the first RECEIVE (or RETURN). Returns screens."""
        ctx = CicsContext(transid=self._transid, commarea=commarea, eibaid=eibaid)

        def _run() -> DispatchResult:
            return run_cics(
                self._program,
                ctx,
                self._screen_queue,
                self._input_channel,
                context_holder=self._context_holder,
                result_holder=self._result_holder,
                max_steps=self._max_steps,
            )

        self._g = greenlet(_run)
        out = self._g.switch()
        return self._drain(out)

    def send(self, input_event: Any) -> list[dict]:
        """Answer the pending RECEIVE; run to the next RECEIVE (or RETURN)."""
        if self._g is None:
            raise RuntimeError("send() before start()")
        if self._g.dead:
            raise RuntimeError("conversation has already ended")
        out = self._g.switch(input_event)
        return self._drain(out)

    def close(self) -> None:
        """Abort a still-running conversation (terminal disconnect)."""
        if self._g is not None and not self._g.dead:
            self._g.throw()

    @property
    def done(self) -> bool:
        return self._g is not None and self._g.dead

    @property
    def result(self) -> DispatchResult | None:
        """The DispatchResult from the task's RETURN, once done."""
        return self._result

    def _drain(self, out: Any) -> list[dict]:
        # If the greenlet finished, run_cics' return value came back through switch.
        if self._g is not None and self._g.dead and isinstance(out, DispatchResult):
            self._result = out
        screens: list[dict] = []
        while True:
            try:
                screens.append(self._screen_queue.get_nowait())
            except queue.Empty:
                break
        return screens

"""run_program() — dispatches execution to whichever CoprocessorSpec owns it.

Intentionally CICS-aware (imports cics.dispatcher directly): the design's own
documented asymmetry is that CICS owns execution (dispatcher, SUSPEND/resume)
and SQL is purely synchronous, so there is no generic "runner protocol" to
build here — only a real second execution-owning coprocessor would justify one.
"""

from __future__ import annotations

from typing import Any, Sequence

from cics.dispatcher import run_cics

from red_dragon_forge.coprocessor import CoprocessorSpec


def run_program(
    linked: Any,
    specs: Sequence[CoprocessorSpec],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run a compiled program via whichever spec owns execution.

    Exactly one spec's ``owns_execution`` must be True today (the CICS
    adapter) — ``run_cics(linked, *args, **kwargs)`` is called directly.

    With no execution-owning spec (e.g. a SQL-only composition), there is
    nothing for this repo to add over Squall's own standalone synchronous run
    — raises NotImplementedError rather than guessing at a fallback shape,
    since no such case is in scope for this plan (see the design doc's
    deferred section).
    """
    owners = [s for s in specs if s.owns_execution]
    assert len(owners) <= 1, (
        f"at most one CoprocessorSpec may own execution, got {len(owners)}"
    )
    if not owners:
        raise NotImplementedError(
            "no execution-owning CoprocessorSpec present — a SQL-only "
            "composition should use squall's own standalone run, not "
            "red_dragon_forge.run_program (see design doc §2.3)"
        )
    return run_cics(linked, *args, **kwargs)

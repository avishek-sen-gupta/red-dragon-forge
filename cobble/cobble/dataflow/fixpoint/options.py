"""What the caller chose about how one member is analysed.

One value object rather than parameters threaded through four call layers: the
next knob belongs here, not in every signature between the CLI and the walk.
"""

from __future__ import annotations

from dataclasses import dataclass

ITERATION_FACTOR = 200


@dataclass(frozen=True)
class AnalysisOptions:
    """How the one worklist walk is bounded: ``sweeps`` passes over reverse
    postorder when non-zero, otherwise ``factor`` dequeues per CFG node.

    Zero rather than None because there is no such thing as a budget of no
    passes. The two budgets replace each other, and the CLI refuses both at once
    rather than silently dropping one.
    """

    sweeps: int = 0
    factor: int = ITERATION_FACTOR


DEFAULT_OPTIONS = AnalysisOptions()

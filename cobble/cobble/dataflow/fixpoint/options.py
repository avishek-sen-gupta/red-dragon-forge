"""What the caller chose about how one member is analysed.

One value object rather than parameters threaded through four call layers: the
next knob belongs here, not in every signature between the CLI and the walk.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fixpoint.scope import Scope

ITERATION_FACTOR = 150


@dataclass(frozen=True)
class AnalysisOptions:
    """``sweeps`` zero means the worklist walk; any other value bounds a sweep walk.

    Zero rather than None because there is no such thing as a budget of no
    sweeps: the two walks are different traversals, and the number is what picks
    between them. ``factor`` binds only the worklist walk, ``sweeps`` only the
    sweep walk, and the CLI refuses both at once rather than silently dropping
    one.
    """

    sweeps: int = 0
    factor: int = ITERATION_FACTOR
    scope: Scope = Scope.WHOLE


DEFAULT_OPTIONS = AnalysisOptions()

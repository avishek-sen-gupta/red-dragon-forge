"""RunReport — the facts about a run stated once, not on every value."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RunReport:
    rounds: int = 0
    discovered: int = 0
    unresolved_outside_jumps: int = 0
    without_results: tuple[str, ...] = ()
    crossed: int = 0

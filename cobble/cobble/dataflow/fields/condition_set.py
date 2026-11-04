"""SET condition TO TRUE, as the MOVE of each condition's first value into its field."""

from __future__ import annotations

from dataclasses import dataclass

from cobol_asg.cobol_statements import MoveStatement


@dataclass(frozen=True)
class ConditionSet:
    """One MOVE per target, in the order the SET names them."""

    moves: tuple[MoveStatement, ...]

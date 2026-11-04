"""One level-88 declaration, with the items enclosing it, so a qualified reference can pick it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cobol_asg.ref_mod import RefModOperand


@dataclass(frozen=True)
class DeclaredCondition:
    """``enclosing`` is the parent and then each group above it, innermost first --
    the order an ``OF`` chain is written in. ``first`` is the value SET ... TO TRUE
    moves into the parent, as the operand a MOVE of it would have, or an unnamed
    operand when the 88 has no value."""

    name: str
    enclosing: tuple[str, ...]
    first: RefModOperand

    @property
    def parent(self) -> RefModOperand:
        return RefModOperand(name=self.enclosing[0], qualifiers=self.enclosing[1:])

    def qualified_by(self, qualifiers: Sequence[str]) -> bool:
        return _in_order(tuple(q.upper() for q in qualifiers), self.enclosing)


def _in_order(wanted: tuple[str, ...], chain: tuple[str, ...]) -> bool:
    if not wanted:
        return True
    if wanted[0] not in chain:
        return False
    return _in_order(wanted[1:], chain[chain.index(wanted[0]) + 1 :])

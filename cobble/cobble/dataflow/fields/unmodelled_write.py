"""A statement with no transfer of its own, reduced to the storage it names."""

from __future__ import annotations

from dataclasses import dataclass

from cobol_asg.ref_mod import RefModOperand


@dataclass(frozen=True)
class UnmodelledWrite:
    """What lowering says the statement writes and reads, and its verb.

    The transfer cannot say how the statement changes its targets -- fully, partly,
    or not at all -- so it reads this as a weak write: every target gains the
    statement as a definer, from these sources or, with none, from the verb itself.
    """

    verb: str
    targets: tuple[RefModOperand, ...]
    sources: tuple[RefModOperand, ...]

"""The runner's four tolerance strategies, one per kind of fault a job can meet."""

from __future__ import annotations

from dataclasses import dataclass

from jackal.missing_data import MissingDataStrategy
from jackal.missing_program import MissingProgramStrategy
from jackal.unknown_return_code import UnknownReturnCodeStrategy
from jackal.unresolved import UnresolvedReferenceStrategy


@dataclass(frozen=True)
class Tolerances:
    unresolved: UnresolvedReferenceStrategy
    missing_data: MissingDataStrategy
    missing_program: MissingProgramStrategy
    unknown_return_code: UnknownReturnCodeStrategy

"""A Horn solver's three answers to a reachability goal."""

from enum import Enum


class Answer(Enum):
    SAT = "sat"
    UNSAT = "unsat"
    UNKNOWN = "unknown"

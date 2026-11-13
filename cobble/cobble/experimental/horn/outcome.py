"""What a test's outcome mark holds: the outcome the test last took, or that it has not run."""

from enum import Enum


class Outcome(Enum):
    UNRUN = 0
    TRUE = 1
    FALSE = 2

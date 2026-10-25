"""Whether a dep row is a program's own flow, or a combine link window carrying bytes into a callee or back to its caller."""

from enum import Enum


class Crossing(Enum):
    NONE = "none"
    ENTERED = "entered"
    RETURNED = "returned"

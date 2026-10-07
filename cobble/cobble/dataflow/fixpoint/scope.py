"""Which bytes a fixpoint run tracks."""

from enum import Enum


class Scope(Enum):
    """Every written byte, or only what call targets and jump areas depend on."""

    WHOLE = "whole"
    CALL_TARGETS = "call-targets"

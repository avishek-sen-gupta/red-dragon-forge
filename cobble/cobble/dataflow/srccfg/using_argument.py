"""One CALL USING argument: the caller's field, and how it is passed."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.argument_mode import ArgumentMode


@dataclass(frozen=True)
class UsingArgument:
    """``name`` is blank for a literal or OMITTED argument, which still holds its
    position: the callee's parameters bind by position."""

    name: str
    mode: ArgumentMode = ArgumentMode.REFERENCE

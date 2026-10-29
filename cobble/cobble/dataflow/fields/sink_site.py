"""One destination outside the program, and the operand whose bytes go there."""

from dataclasses import dataclass

from cobble.dataflow.fields.sink import Sink
from cobol_asg.ref_mod import RefModOperand


@dataclass(frozen=True)
class SinkSite:
    """A sink and the operand a statement sends to it."""

    sink: Sink
    operand: RefModOperand

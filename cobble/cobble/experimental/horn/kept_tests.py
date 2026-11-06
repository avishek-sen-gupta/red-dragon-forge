"""Which of a program's tests the encoding keeps; leaving a test out only lets more runs through, so it is always sound."""

from typing import Protocol

from cobble.dataflow.srccfg.cfg import Atom


class KeptTests(Protocol):
    def keeps(self, atom: Atom) -> bool: ...

"""Keep every test the program makes."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import Atom
from cobble.experimental.horn.kept_tests import KeptTests


@dataclass(frozen=True)
class EveryTest(KeptTests):
    def keeps(self, atom: Atom) -> bool:
        return True


EVERY_TEST = EveryTest()

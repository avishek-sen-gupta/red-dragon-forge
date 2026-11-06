"""Keep only the tests that read one of the named fields."""

from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import Atom
from cobble.experimental.horn.kept_tests import KeptTests


@dataclass(frozen=True)
class NamedFields(KeptTests):
    fields: frozenset[str]

    def keeps(self, atom: Atom) -> bool:
        return atom.left in self.fields or atom.right in self.fields

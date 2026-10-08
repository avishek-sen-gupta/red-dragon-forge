"""What resolving one dynamic site found: the programs it reaches, or why none are known."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.site_definition import SiteDefinition
from cobble.dataflow.fixpoint.site_doubt import SiteDoubt


@dataclass(frozen=True)
class SiteAnswer:
    """Resolved when ``callees`` is not empty; otherwise ``doubts`` says why.
    ``operand`` names what the site reads its program from, and ``definitions``
    are every write in the program touching it, wherever they are."""

    callees: tuple[str, ...] = ()
    doubts: tuple[UnresolvedReason | SiteDoubt, ...] = ()
    operand: str = ""
    definitions: tuple[SiteDefinition, ...] = ()

"""What resolving one dynamic site found: the programs it reaches, or why none are known."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.site_definition import SiteDefinition
from cobble.dataflow.fixpoint.site_doubt import SiteDoubt


@dataclass(frozen=True)
class SiteAnswer:
    """``resolved`` when every program the site can reach is in ``callees`` -- which
    may be none, for a site whose operand never names a program the combine could
    link -- otherwise unknown, ``doubts`` saying why. ``operand`` names what the
    site reads its program from, and ``definitions`` are every write in the program
    touching it, wherever they are."""

    resolved: bool = False
    callees: tuple[str, ...] = ()
    doubts: tuple[UnresolvedReason | SiteDoubt, ...] = ()
    operand: str = ""
    definitions: tuple[SiteDefinition, ...] = ()

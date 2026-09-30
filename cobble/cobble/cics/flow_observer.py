from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bms_copybook_gen.models import BmsField


@dataclass(frozen=True)
class CicsVerb:
    """One CICS verb, and the operand each downstream reader cares about.

    Every operand below is "" for a verb that does not carry it, not None: a
    consumer never needs to know which reason an absent operand is absent
    for, only whether it has one, and every reader already tests that by
    truthiness (see flow_graph_core.py).
    """

    verb: str
    program: str
    map_name: str = ""
    mapset_name: str = ""
    xctl_target: str = ""
    transid: str = ""
    # The logical CICS file name from FILE(...)/DATASET(...) on a file
    # control verb (READ/WRITE/REWRITE/DELETE/STARTBR/READNEXT/READPREV/
    # ENDBR). "" for every other verb.
    file_name: str = ""
    # XCTL/LINK's PROGRAM(...) operand, as written, when it named a data item
    # rather than a literal -- xctl_target carries the literal case, this one
    # the unresolved case, so a data-name is never mistaken for a program.
    program_operand: str = ""


@dataclass(frozen=True)
class DynamicSite:
    """One EXEC CICS XCTL/LINK PROGRAM(...) operand the walk saw with no static
    resolution -- the CICS-side half of a dynamic call site.

    Surfaced as plain data rather than through the sink a CicsVerb's edges
    reach: a program-transfer edge built from it would dedupe keep-first
    against whatever the dataflow's targets.jsonl later resolves for the same
    site, freezing the wrong answer in before the artifact ever got read.
    build_graph marks a site not-attempted from this only where the artifact
    holds no row for the same (program, expression).
    """

    program: str
    transfer: str
    expression: str


class CicsFlowObserver(Protocol):
    def on_verb(self, verb: CicsVerb) -> None: ...


class NullCicsFlowObserver:
    def on_verb(self, verb: CicsVerb) -> None:
        pass


def field_direction(field: BmsField) -> str:
    """Return "input" for unprotected fields, "output" for protected/auto-skip."""
    protected = {"PROT", "ASKIP"}
    if any(a.upper() in protected for a in field.attrb):
        return "output"
    return "input"

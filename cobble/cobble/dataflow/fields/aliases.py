"""Commarea aliases: the bytes a caller and its callee share.

A ``LINK ... COMMAREA(WS-AREA)`` passes storage, not a copy, so caller byte
``start(WS-AREA) + k`` *is* callee byte ``k`` of ``DFHCOMMAREA``. That makes the
relation a byte-identity alias with an offset rebase rather than a flow: nothing
converts, nothing pads, and there is no distribution rule to derive.

The window is the shorter of the two declared areas. Past it the two areas are
not both addressable, and a table that claimed they were would over-claim on
roughly a third of real sites. The ``LENGTH`` option does not narrow it further:
in the measured corpus it either restates the caller's own declared length or is
a variable, and a shorter runtime length does not make the alias wrong -- the
bytes are still the same storage, bounded by the callee's own declaration, which
is already one side of the ``min``.

No fixpoint and no walk. The callee is read for its LINKAGE layout only, so the
cost is one layout per distinct callee, and a single-member run still emits that
member's outbound aliases.
"""

import json
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.extent import CellIndex, cell_index
from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.side_tables import CommareaAlias
from cobble.dataflow.layout import UnsizeableFieldError, section_records
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.desugar import CALL_TRANSFER, LINK_TRANSFER
from cobble.dataflow.srccfg.link import COMMAREA_RECORD, CallSite, call_sites
from cobol_asg.asg_types import CobolASG
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

LINKAGE_ORIGIN = "LINKAGE"

NOT_IN_CACHE = "callee-not-in-cache"
DYNAMIC_TARGET = "dynamic-target"
NO_COMMAREA_OPERAND = "no-commarea-operand"
CALLEE_HAS_NO_COMMAREA = "callee-declares-no-commarea"
UNSIZEABLE = "unsizeable"
UNREADABLE = "unreadable"
CALLER_FIELD_UNKNOWN = "caller-field-unknown"
CALL_USING = "call-using-unsupported"

NO_EXTENT = FieldExtent(
    region=RegionId.LINKAGE,
    start=0,
    length=0,
    precision=Precision.EXACT,
    field_name="",
)


@dataclass(frozen=True)
class _Callee:
    """A callee's commarea window, or why there is not one to have."""

    extent: FieldExtent = NO_EXTENT
    reason: str = ""


_REFUSALS = (
    (lambda site: site.transfer == CALL_TRANSFER, CALL_USING),
    (lambda site: not site.resolved, DYNAMIC_TARGET),
    (lambda site: not site.commarea, NO_COMMAREA_OPERAND),
)


def commarea_aliases(
    asg: CobolASG, index: CellIndex, asg_dir: Path
) -> tuple[CommareaAlias, ...]:
    """Every ``LINK``/``XCTL``/``CALL`` site in ``asg``, aliased or refused.

    ``index`` is the caller's own layout, already built by the walk that calls
    this; the CFG is rebuilt here because the fixpoint returns only its flow and
    that index, and widening its result for a pass that shares none of its work
    would couple the two for no reason.
    """
    return tuple(
        row
        for site in call_sites(build_program(asg))
        for row in _site_rows(site, index, asg_dir)
    )


def _site_rows(
    site: CallSite, index: CellIndex, asg_dir: Path
) -> tuple[CommareaAlias, ...]:
    refused = _refused(site)
    if refused:
        return (_dead(site, refused),)
    callee = _callee_commarea(asg_dir, site.program)
    if callee.reason:
        return (_dead(site, callee.reason),)
    return _windows(site, index, callee.extent)


def _refused(site: CallSite) -> str:
    """The first reason this site cannot be aliased from the caller alone."""
    return next((reason for holds, reason in _REFUSALS if holds(site)), "")


def _dead(site: CallSite, reason: str) -> CommareaAlias:
    return CommareaAlias(
        caller=site.caller, node=site.node, transfer=site.transfer, reason=reason
    )


def _windows(
    site: CallSite, index: CellIndex, callee: FieldExtent
) -> tuple[CommareaAlias, ...]:
    cells = index.cells_named(site.commarea, (), 0)
    if not cells:
        return (_dead(site, CALLER_FIELD_UNKNOWN),)
    return tuple(_aliased(site, index.extent_of(cell), callee) for cell in cells)


def _aliased(site: CallSite, caller: FieldExtent, callee: FieldExtent) -> CommareaAlias:
    shared = min(caller.length, callee.length)
    return CommareaAlias(
        caller=site.caller,
        node=site.node,
        transfer=site.transfer,
        callee=site.program,
        caller_extent=extent_text(replace(caller, length=shared)),
        callee_extent=extent_text(replace(callee, length=shared)),
        returns=site.transfer == LINK_TRANSFER,
    )


@cache
def _callee_commarea(asg_dir: Path, callee: str) -> _Callee:
    """The callee's ``DFHCOMMAREA`` window, memoised per cache directory.

    ``asg_dir`` is part of the key, so a run against a different parse never
    reads another one's answer.
    """
    path = asg_dir / f"{callee}.json"
    if not path.is_file():
        return _Callee(reason=NOT_IN_CACHE)
    return _read_commarea(path)


def _read_commarea(path: Path) -> _Callee:
    try:
        return _linkage_commarea(_asg_at(path))
    except UnsizeableFieldError:
        return _Callee(reason=UNSIZEABLE)
    except (OSError, ValueError, KeyError) as error:
        return _Callee(reason=f"{UNREADABLE}: {error!r}")


def _asg_at(path: Path) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _linkage_commarea(asg: CobolASG) -> _Callee:
    """Only LINKAGE is laid out: no row here uses the callee's other sections."""
    index = cell_index(section_records(LINKAGE_ORIGIN, tuple(asg.linkage_fields)))
    cells = index.cells_named(COMMAREA_RECORD, (), 0)
    if not cells:
        return _Callee(reason=CALLEE_HAS_NO_COMMAREA)
    return _Callee(extent=index.extent_of(cells[0]))

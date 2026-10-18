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

No fixpoint and no walk, but not free either: one extra desugar per caller --
``program_cfg`` is not memoised, and the fixpoint has already run it for the
same member -- plus a full ``json.loads`` and ``CobolASG.from_dict`` of every
distinct callee's cache file, of which only the LINKAGE is then laid out.
``from_dict`` has no partial mode, so the whole member is parsed to reach one
record; the read is memoised per cache directory, so a callee a hundred sites
share is read once. A single-member run still emits that member's outbound
aliases, because the cache directory is the callee lookup whatever was selected.
"""

from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.extent import CellIndex, cell_index
from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.side_tables import CommareaAlias
from cobble.dataflow.layout import UnsizeableFieldError, section_records
from cobble.dataflow.srccfg.argument_mode import ArgumentMode
from cobble.dataflow.srccfg.desugar import CALL_TRANSFER, LINK_TRANSFER
from cobble.dataflow.srccfg.link import COMMAREA_RECORD, CallSite, call_sites
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.using_argument import UsingArgument
from cobble.parsing.asg_cache import first_program_at
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
NO_ARGUMENT_FIELD = "argument-is-not-a-field"
CALLEE_HAS_NO_PARAMETER = "callee-declares-no-parameter-there"
PARAMETER_NOT_IN_LINKAGE = "parameter-not-in-linkage"
EMPTY_WINDOW = "empty-window"
ALIAS_PHASE_FAILED = "alias-phase-failed"

COMMAREA_LEVEL = 1

_QUALIFIERS = frozenset({"OF", "IN"})


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


@dataclass(frozen=True)
class _Linkage:
    """A callee's commarea window and the window at each USING position; or why the
    callee could not be read. Only these, never the layout they came from: this is
    what a worker caches for every callee it meets."""

    commarea: _Callee = _Callee()
    parameters: tuple[_Callee, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class _Reference:
    """A commarea operand's own name, and the groups its chain qualifies it by."""

    name: str
    qualifiers: tuple[str, ...] = ()


_REFUSALS = (
    (lambda site: not site.resolved, DYNAMIC_TARGET),
    (
        lambda site: site.transfer != CALL_TRANSFER and not site.commarea.split(),
        NO_COMMAREA_OPERAND,
    ),
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
    cfg = program_cfg(asg)
    return tuple(
        row
        for site in call_sites(cfg)
        for row in _site_rows(site, cfg.node(site.node).using, index, asg_dir)
    )


def _site_rows(
    site: CallSite,
    arguments: tuple[UsingArgument, ...],
    index: CellIndex,
    asg_dir: Path,
) -> tuple[CommareaAlias, ...]:
    refused = _refused(site)
    if refused:
        return (_dead(site, refused),)
    return _callee_rows(site, arguments, index, _callee_linkage(asg_dir, site.program))


def _callee_rows(
    site: CallSite,
    arguments: tuple[UsingArgument, ...],
    index: CellIndex,
    linkage: _Linkage,
) -> tuple[CommareaAlias, ...]:
    if linkage.reason:
        return (_dead(site, linkage.reason),)
    if site.transfer == CALL_TRANSFER:
        return _argument_rows(site, arguments, index, linkage)
    return _commarea_rows(site, index, linkage)


def _commarea_rows(
    site: CallSite, index: CellIndex, linkage: _Linkage
) -> tuple[CommareaAlias, ...]:
    callee = linkage.commarea
    if callee.reason:
        return (_dead(site, callee.reason),)
    return _windows(site, site.commarea, index, callee.extent, _returns(site))


def _returns(site: CallSite) -> bool:
    return site.transfer == LINK_TRANSFER


def _argument_rows(
    site: CallSite,
    arguments: tuple[UsingArgument, ...],
    index: CellIndex,
    linkage: _Linkage,
) -> tuple[CommareaAlias, ...]:
    """One CALL USING argument against the callee parameter at its position.

    BY REFERENCE shares the caller's storage, so the alias returns the way LINK's
    commarea does; BY CONTENT and BY VALUE hand over a copy, which the callee reads
    and cannot write back through.
    """
    return tuple(
        row
        for position, argument in enumerate(arguments)
        for row in _argument_window(site, argument, index, linkage, position)
    )


def _argument_window(
    site: CallSite,
    argument: UsingArgument,
    index: CellIndex,
    linkage: _Linkage,
    position: int,
) -> tuple[CommareaAlias, ...]:
    if not argument.name:
        return (_dead(site, NO_ARGUMENT_FIELD),)
    parameter = _parameter(linkage, position)
    if parameter.reason:
        return (_dead(site, parameter.reason),)
    return _windows(
        site,
        argument.name,
        index,
        parameter.extent,
        argument.mode is ArgumentMode.REFERENCE,
    )


def _parameter(linkage: _Linkage, position: int) -> _Callee:
    """The level-01 LINKAGE record the callee's USING names at ``position``."""
    if position >= len(linkage.parameters):
        return _Callee(reason=CALLEE_HAS_NO_PARAMETER)
    return linkage.parameters[position]


def _refused(site: CallSite) -> str:
    """The first reason this site cannot be aliased from the caller alone."""
    return next((reason for holds, reason in _REFUSALS if holds(site)), "")


def _dead(site: CallSite, reason: str) -> CommareaAlias:
    return CommareaAlias(
        caller=site.caller,
        node=site.node,
        transfer=site.transfer,
        callee=_target(site),
        reason=reason,
    )


def _target(site: CallSite) -> str:
    """The callee a dead-end row can still name, which is every resolved one.

    ``unreadable: AttributeError(...)`` says nothing about *whose* cache file is
    broken, so a consumer holding the site had to go back to the ASG to find out.
    Blank now carries a fact of its own -- the target is a field, not a literal, so
    nothing short of running the program knows it.
    """
    return site.program if site.resolved else ""


def _reference(operand: str) -> _Reference:
    """``WS-AREA OF WS-BLOCK`` as the name and the qualifiers ``cells_named`` wants.

    Qualifiers keep the operand's order, outermost last, which is the order the
    text writes them in; ``cells_named`` asks only that each one name some group on
    the cell's path, so the order costs nothing there and stays readable here. A
    subscripted operand keeps its ``(...)`` in the name, matches no cell, and lands
    on ``CALLER_FIELD_UNKNOWN`` -- its arity would have to be read off the text.
    ``COMMAREA(OF)`` is all qualifier and no name, and lands there the same way: an
    empty name matches no cell either, which is the truthful reason for an operand
    naming nothing.
    """
    named = tuple(word for word in operand.split() if word.upper() not in _QUALIFIERS)
    return _Reference(name=next(iter(named), ""), qualifiers=named[1:])


def _windows(
    site: CallSite,
    operand: str,
    index: CellIndex,
    callee: FieldExtent,
    returns: bool,
) -> tuple[CommareaAlias, ...]:
    extents = area_extents(operand, index)
    if not extents:
        return (_dead(site, CALLER_FIELD_UNKNOWN),)
    return tuple(_aliased(site, extent, callee, returns) for extent in extents)


def _aliased(
    site: CallSite, caller: FieldExtent, callee: FieldExtent, returns: bool
) -> CommareaAlias:
    """The shared window, or a dead end when one side lays out at nothing.

    A zero-length window is not a narrow alias, it is no alias: ``ByteRange``
    overlap needs ``start < other.end``, so nothing can ever be crossed through
    ``[n:n]`` and a blank reason there would claim a success no consumer can use.
    """
    shared = min(caller.length, callee.length)
    if not shared:
        return _dead(site, EMPTY_WINDOW)
    return CommareaAlias(
        caller=site.caller,
        node=site.node,
        transfer=site.transfer,
        callee=site.program,
        caller_extent=extent_text(replace(caller, length=shared)),
        callee_extent=extent_text(replace(callee, length=shared)),
        returns=returns,
    )


@cache
def _callee_linkage(asg_dir: Path, callee: str) -> _Linkage:
    """The callee's LINKAGE and USING list, memoised per cache directory.

    ``asg_dir`` is part of the key, so a run against a different parse never
    reads another one's answer.
    """
    path = asg_dir / f"{callee}.json"
    if not path.is_file():
        return _Linkage(reason=NOT_IN_CACHE)
    return _read_linkage(path)


def _read_linkage(path: Path) -> _Linkage:
    """Total in the callee: whatever one cache file does costs one site's alias.

    Every exception type, not a list of them. A body that is valid JSON and not an
    object raises ``AttributeError`` from ``from_dict``, a truncated one
    ``JSONDecodeError``, and an unrecognised statement whatever its dialect parser
    raises -- an enumeration here is a guess about a file this pass did not write,
    and the cost of guessing short is the CALLER's records.
    """
    try:
        return _linkage_of(_asg_at(path))
    except UnsizeableFieldError:
        return _Linkage(reason=UNSIZEABLE)
    except Exception as error:  # noqa: BLE001 - one callee costs one alias
        return _Linkage(reason=f"{UNREADABLE}: {error!r}")


def _asg_at(path: Path) -> CobolASG:
    """The whole member, because ``from_dict`` has no partial mode to ask for.

    It is eager and raises on any statement type no dialect parser claims, so one
    unrecognised statement in a PROCEDURE DIVISION nothing here reads costs the
    alias under ``UNREADABLE`` even when the LINKAGE this pass wants is intact.
    """
    with cached_asg_dialect_parsers_registered():
        return first_program_at(path)


def _linkage_of(asg: CobolASG) -> _Linkage:
    index = cell_index(section_records(LINKAGE_ORIGIN, tuple(asg.linkage_fields)))
    return _Linkage(
        commarea=_linkage_commarea(index),
        parameters=tuple(
            _record_named(index, param.name) for param in asg.procedure_using
        ),
    )


def _linkage_commarea(index: CellIndex) -> _Callee:
    """The callee's ``DFHCOMMAREA`` record, laid out from its LINKAGE alone."""
    found = _record_named(index, COMMAREA_RECORD)
    if found.reason:
        return _Callee(reason=CALLEE_HAS_NO_COMMAREA)
    return found


def _record_named(index: CellIndex, name: str) -> _Callee:
    """The level-01 LINKAGE record ``name``.

    Only the level-01 entry counts: ``cells_named`` does not filter on level, and a
    field of that name under some other record is not the storage a caller passes.
    First declared wins among those, which is deterministic and is all a duplicate
    01 of that name could ever justify.
    """
    records = tuple(
        cell for cell in index.cells_named(name, (), 0) if cell.level == COMMAREA_LEVEL
    )
    if not records:
        return _Callee(reason=PARAMETER_NOT_IN_LINKAGE)
    return _Callee(extent=index.extent_of(records[0]))


def area_extents(operand: str, index: CellIndex) -> tuple[FieldExtent, ...]:
    reference = _reference(operand)
    return tuple(
        index.extent_of(cell)
        for cell in index.cells_named(reference.name, reference.qualifiers, 0)
    )


def receives_commarea(index: CellIndex) -> bool:
    """Whether the program is entered with a ``DFHCOMMAREA`` rather than USING parameters."""
    return not _linkage_commarea(index).reason


def received_areas(
    asg: CobolASG, index: CellIndex
) -> tuple[tuple[int, FieldExtent], ...]:
    commarea = _linkage_commarea(index)
    if not commarea.reason:
        return ((0, commarea.extent),)
    found = tuple(
        (position, _record_named(index, param.name))
        for position, param in enumerate(asg.procedure_using)
    )
    return tuple(
        (position, callee.extent) for position, callee in found if not callee.reason
    )


def callee_received_area(
    asg_dir: Path, callee: str, by_position: bool, param: int
) -> FieldExtent:
    linkage = _callee_linkage(asg_dir, callee)
    if linkage.reason:
        return NO_EXTENT
    found = _parameter(linkage, param) if by_position else linkage.commarea
    return NO_EXTENT if found.reason else found.extent

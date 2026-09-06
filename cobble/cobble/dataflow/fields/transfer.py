"""One statement plus an in-state to an out-state.

Dispatch is by statement class name, and a class this module does not name
leaves the state untouched -- visibly unhandled rather than silently
mis-analysed. There is no universal "is a statement" predicate to lean on:
cobol_asg has no statement base class, and its ``CobolStatementType`` union
excludes the dialect-parsed EXEC CICS form this module also handles.

A handler yields writes rather than threading a state through a loop, so the
order writes land in is the handler's business and the lattice's rules are
state.write's alone.

Byte-wise distribution applies only where both operands are DISPLAY and the
target extent is EXACT. A COMP operand has no digit-to-byte correspondence to
distribute along, and a CLAMPED target does not know which occurrence it lands
in, so both take the whole source into the whole target instead.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from functools import reduce
from types import MappingProxyType

from cics.statements import CicsOperand, ExecCicsStatement
from cobble.asg_walk import descend
from cobble.dataflow.fields.extent import CellIndex, OperandExtents, operand_extents
from cobble.dataflow.fields.naming import smallest_covering
from cobble.dataflow.fields.state import (
    CICS_STATE,
    LITERAL,
    NOWHERE,
    Source,
    State,
    write,
)
from cobble.dataflow.srccfg.literals import is_literal
from cobol_asg.cobol_expression import ExprNode, FieldRefNode, RefModNode
from cobol_asg.cobol_statements import (
    ArithmeticStatement,
    CallStatement,
    CobolStatementType,
    ComputeStatement,
    ComputeTarget,
    InitializeStatement,
    MoveStatement,
    ReadStatement,
    StringStatement,
)
from cobol_asg.ref_mod import RefModOperand
from cobol_memory.field_extent import FieldExtent, Precision

# cobol_asg has no statement base class, and its own union leaves out the
# dialect-parsed EXEC CICS form, so the two have to be spelled together here.
Statement = CobolStatementType | ExecCicsStatement

LITERAL_SPACES = "LITERAL SPACES"

# A group carries no PICTURE and so no usage of its own; the bridge leaves it
# empty, which is not the same thing as a non-DISPLAY item.
_DISPLAY_USAGES = frozenset({"", "DISPLAY"})

_CICS_FILE_VERBS = frozenset({"READ", "READNEXT", "READPREV"})
_CICS_CALL_VERBS = frozenset({"LINK", "XCTL"})
_CICS_RECEIVERS = ("INTO", "SET")


@dataclass(frozen=True)
class Write:
    """One extent, and everything reaching it after this statement."""

    target: FieldExtent
    sources: frozenset[Source]


def _applied(state: State, writes: Iterator[Write]) -> State:
    return reduce(
        lambda held, entry: write(held, entry.target, entry.sources), writes, state
    )


def _from_extents(extents: tuple[FieldExtent, ...], node: str) -> frozenset[Source]:
    return frozenset(Source(origin="", extent=extent, node=node) for extent in extents)


def _synthetic(origin: str, node: str) -> frozenset[Source]:
    return frozenset({Source(origin=origin, extent=NOWHERE, node=node)})


def _named(extent: FieldExtent, index: CellIndex) -> FieldExtent:
    """A byte range labelled by the smallest declared field containing it.

    A slice of a group's extent belongs to whichever member owns those bytes,
    and that member's name is the only useful thing to report about it.
    """
    return replace(extent, field_name=smallest_covering(extent, index))


def _sliced(source: FieldExtent, offset: int, wanted: int) -> FieldExtent:
    """The source bytes one receiving cell takes, clipped to what the source has."""
    return replace(
        source,
        start=source.start + offset,
        length=min(wanted, source.length - offset),
    )


def _cell_write(
    source: FieldExtent,
    target: FieldExtent,
    cell_extent: FieldExtent,
    node: str,
    index: CellIndex,
) -> Write:
    """One receiving cell's share of a group move.

    The offset is the difference of two region coordinates. ``Cell.start`` is
    record-relative and belongs to neither, which is why this reads the cell's
    extent instead.
    """
    offset = cell_extent.start - target.start
    if offset >= source.length:
        return Write(cell_extent, _synthetic(LITERAL_SPACES, node))
    taken = _sliced(source, offset, cell_extent.length)
    return Write(cell_extent, _from_extents((_named(taken, index),), node))


def _distributed(
    source: FieldExtent,
    target: FieldExtent,
    node: str,
    index: CellIndex,
) -> Iterator[Write]:
    """Left-aligned at matching relative offset; the tail past the source is spaces."""
    covered = index.elementary_within(target)
    if not covered:
        return iter((Write(target, _from_extents((source,), node)),))
    return (
        _cell_write(source, target, index.extent_of(cell), node, index)
        for cell in covered
    )


def _is_display(extent: FieldExtent, index: CellIndex) -> bool:
    return all(
        cell.usage.upper() in _DISPLAY_USAGES for cell in index.containing(extent)
    )


def _distributes(
    sources: OperandExtents, target: FieldExtent, index: CellIndex
) -> bool:
    return (
        len(sources.extents) == 1
        and target.precision is Precision.EXACT
        and _is_display(target, index)
        and _is_display(sources.extents[0], index)
    )


def _unresolved_origin(operand: RefModOperand, reason: str) -> str:
    """A literal reads no storage, and neither does LENGTH OF or a FUNCTION."""
    return LITERAL if is_literal(operand.name) else reason.upper()


def _one_move(
    operand: RefModOperand,
    sources: OperandExtents,
    target: FieldExtent,
    node: str,
    index: CellIndex,
) -> Iterator[Write]:
    if not sources.extents:
        origin = _unresolved_origin(operand, sources.reason)
        return iter((Write(target, _synthetic(origin, node)),))
    if _distributes(sources, target, index):
        return _distributed(sources.extents[0], target, node, index)
    return iter((Write(target, _from_extents(sources.extents, node)),))


def _source_operand(statement: MoveStatement) -> RefModOperand:
    """A FUNCTION source denotes no storage, so only its absence of a name matters."""
    source = statement.source
    return source if isinstance(source, RefModOperand) else RefModOperand(name="")


def _move_targets(statement: MoveStatement) -> tuple[RefModOperand, ...]:
    return tuple(statement.targets)


def _move_writes(
    statement: MoveStatement, node: str, index: CellIndex
) -> Iterator[Write]:
    sources = operand_extents(statement.source, index)
    operand = _source_operand(statement)
    return (
        entry
        for target_operand in _move_targets(statement)
        for target in operand_extents(target_operand, index).extents
        for entry in _one_move(operand, sources, target, node, index)
    )


def _initialize_targets(statement: InitializeStatement) -> tuple[RefModOperand, ...]:
    return tuple(RefModOperand(name=name) for name in statement.operands)


def _initialize_writes(
    statement: InitializeStatement, node: str, index: CellIndex
) -> Iterator[Write]:
    return (
        Write(index.extent_of(cell), _synthetic(LITERAL, node))
        for operand in _initialize_targets(statement)
        for group in operand_extents(operand, index).extents
        for cell in index.elementary_within(group) or index.containing(group)[-1:]
    )


def _union_writes(
    reads: tuple[RefModOperand, ...],
    targets: tuple[RefModOperand, ...],
    node: str,
    index: CellIndex,
) -> Iterator[Write]:
    """Every target takes every operand: no digit-level correspondence to model."""
    every = tuple(
        extent
        for operand in reads
        for extent in operand_extents(operand, index).extents
    )
    return (
        Write(target, _from_extents(every, node))
        for operand in targets
        for target in operand_extents(operand, index).extents
    )


def _remainder(statement: ArithmeticStatement) -> tuple[RefModOperand, ...]:
    match statement.remainder:
        case None:
            return ()
        case operand:
            return (operand,)


def _arithmetic_targets(statement: ArithmeticStatement) -> tuple[RefModOperand, ...]:
    """Without GIVING the second operand is both read and written."""
    given = tuple(statement.giving) or (statement.target,)
    return (*given, *_remainder(statement))


def _arithmetic_writes(
    statement: ArithmeticStatement, node: str, index: CellIndex
) -> Iterator[Write]:
    return _union_writes(
        (statement.source, statement.target),
        _arithmetic_targets(statement),
        node,
        index,
    )


def _expression_operand(node: FieldRefNode | RefModNode) -> RefModOperand:
    """A COMPUTE reads whole fields: the slice bounds are read, not the slice."""
    return RefModOperand(name=node.name, subscripts=node.subscripts)


def _expression_reads(expression: ExprNode) -> tuple[RefModOperand, ...]:
    return tuple(
        _expression_operand(found)
        for found in descend(expression)
        if isinstance(found, (FieldRefNode, RefModNode))
    )


def _compute_target(target: ComputeTarget) -> RefModOperand:
    return RefModOperand(name=target.name, subscripts=target.subscripts)


def _compute_targets(statement: ComputeStatement) -> tuple[RefModOperand, ...]:
    return tuple(_compute_target(target) for target in statement.targets)


def _compute_writes(
    statement: ComputeStatement, node: str, index: CellIndex
) -> Iterator[Write]:
    return _union_writes(
        _expression_reads(statement.expression),
        _compute_targets(statement),
        node,
        index,
    )


def _string_targets(statement: StringStatement) -> tuple[RefModOperand, ...]:
    return (statement.into,)


def _string_writes(
    statement: StringStatement, node: str, index: CellIndex
) -> Iterator[Write]:
    return _union_writes(
        tuple(sending.value for sending in statement.sendings),
        _string_targets(statement),
        node,
        index,
    )


def _origin_writes(
    operands: tuple[RefModOperand, ...], origin: str, node: str, index: CellIndex
) -> Iterator[Write]:
    return (
        Write(target, _synthetic(origin, node))
        for operand in operands
        for target in operand_extents(operand, index).extents
    )


def _read_targets(statement: ReadStatement) -> tuple[RefModOperand, ...]:
    return (RefModOperand(name=statement.into),) if statement.into else ()


def _read_writes(
    statement: ReadStatement, node: str, index: CellIndex
) -> Iterator[Write]:
    return _origin_writes(
        _read_targets(statement),
        f"FILE:{statement.file_name}",
        node,
        index,
    )


def _call_targets(statement: CallStatement) -> tuple[RefModOperand, ...]:
    """BY REFERENCE is the only linkage the callee can write back through."""
    passed = tuple(
        param.name
        for param in statement.using
        if param.param_type.upper() == "REFERENCE"
        and not param.omitted
        and not param.is_literal
    )
    given = (statement.giving,) if statement.giving else ()
    return tuple(RefModOperand(name=name) for name in (*passed, *given))


def _call_writes(
    statement: CallStatement, node: str, index: CellIndex
) -> Iterator[Write]:
    return _origin_writes(
        _call_targets(statement), f"%CALL:{statement.program}", node, index
    )


def _option(statement: ExecCicsStatement, key: str) -> str:
    value = statement.options.get(key)
    return value.text if isinstance(value, CicsOperand) else ""


def _receiver(statement: ExecCicsStatement) -> tuple[str, ...]:
    named = tuple(
        text for text in (_option(statement, key) for key in _CICS_RECEIVERS) if text
    )
    return named[:1]


def _cics_origin(statement: ExecCicsStatement) -> str:
    if statement.verb.upper() in _CICS_FILE_VERBS:
        return f"FILE:{_option(statement, 'FILE')}"
    return CICS_STATE


def _cics_targets(statement: ExecCicsStatement) -> tuple[RefModOperand, ...]:
    """LINK and XCTL write through the COMMAREA; everything else through a receiver."""
    if statement.verb.upper() in _CICS_CALL_VERBS:
        return (RefModOperand(name=_option(statement, "COMMAREA")),)
    return tuple(RefModOperand(name=text) for text in _receiver(statement))


def _cics_writes(
    statement: ExecCicsStatement, node: str, index: CellIndex
) -> Iterator[Write]:
    if statement.verb.upper() in _CICS_CALL_VERBS:
        return _origin_writes(
            _cics_targets(statement),
            f"%CALL:{_option(statement, 'PROGRAM')}",
            node,
            index,
        )
    return _origin_writes(
        _cics_targets(statement), _cics_origin(statement), node, index
    )


def _no_writes(statement: Statement, node: str, index: CellIndex) -> Iterator[Write]:
    return iter(())


def _no_targets(statement: Statement) -> tuple[RefModOperand, ...]:
    return ()


HANDLED: tuple[type, ...] = (
    MoveStatement,
    InitializeStatement,
    ArithmeticStatement,
    ComputeStatement,
    StringStatement,
    ReadStatement,
    CallStatement,
    ExecCicsStatement,
)

_WRITES_BY_KIND: Mapping[str, Callable[..., Iterator[Write]]] = MappingProxyType(
    {
        "MoveStatement": _move_writes,
        "InitializeStatement": _initialize_writes,
        "ArithmeticStatement": _arithmetic_writes,
        "ComputeStatement": _compute_writes,
        "StringStatement": _string_writes,
        "ReadStatement": _read_writes,
        "CallStatement": _call_writes,
        "ExecCicsStatement": _cics_writes,
    }
)


_TARGETS_BY_KIND: Mapping[str, Callable[..., tuple[RefModOperand, ...]]] = (
    MappingProxyType(
        {
            "MoveStatement": _move_targets,
            "InitializeStatement": _initialize_targets,
            "ArithmeticStatement": _arithmetic_targets,
            "ComputeStatement": _compute_targets,
            "StringStatement": _string_targets,
            "ReadStatement": _read_targets,
            "CallStatement": _call_targets,
            "ExecCicsStatement": _cics_targets,
        }
    )
)


def writes_of(statement: Statement, node: str, index: CellIndex) -> tuple[Write, ...]:
    """Every extent ``statement`` writes and what reaches each one.

    Public because an edge has to come from the writes themselves and not from
    diffing the state around them: a loop-carried definition is already in the
    in-state when the statement runs again, so the diff would be empty and the
    edge would vanish -- silently, which is the failure mode this whole module is
    arranged against.
    """
    handler = _WRITES_BY_KIND.get(type(statement).__name__, _no_writes)
    return tuple(handler(statement, node, index))


def transfer(statement: Statement, node: str, state: State, index: CellIndex) -> State:
    """The state after ``statement``, given the state before it.

    An unhandled statement class returns the state unchanged. ``HANDLED`` names
    what this does dispatch on, so a coverage measurement can subtract the rest
    rather than credit it as analysed.
    """
    return _applied(state, iter(writes_of(statement, node, index)))


def write_operands(statement: Statement) -> tuple[RefModOperand, ...]:
    """Every operand this statement writes, whether or not it denotes storage.

    This is the coverage denominator: a target counted here whose extents do not
    resolve is a write the analysis failed to reach, and the 3ao post-mortem is
    what a denominator derived from the answer instead of the source costs -- an
    acceptance suite passed while its walk reached 18% of nodes, because nothing
    measured what it had missed.
    """
    targets = _TARGETS_BY_KIND.get(type(statement).__name__, _no_targets)
    return targets(statement)

"""One statement plus an in-state to an out-state.

Dispatch is by statement class name, and a class this module does not name
leaves the state untouched -- visibly unhandled rather than silently
mis-analysed. There is no universal "is a statement" predicate to lean on:
cobol_asg has no statement base class, and its ``CobolStatementType`` union
excludes the dialect-parsed EXEC CICS form this module also handles.

A handler yields writes rather than threading a state through a loop, so the
order writes land in is the handler's business and the lattice's rules are
state.write's alone.

No handler splits a write across the children of a group. Which of a target's
bytes came from which of the source's is fixed by the two extents and the
declared layout: whenever either operand is a group the MOVE is an alphanumeric
byte copy, so byte k of an EXACT target comes from byte k of the source and the
tail past the source's end is spaces. That is derivable from the declared
extents, which publish every field's level and ranges, so a write per child cell
restated the layout once per flow -- and on a corpus member it was five rows in
six. A CLAMPED target has no such correspondence, because nothing knows which
occurrence it lands in, and the artefact marks it so a consumer does not assume
one.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import reduce
from types import MappingProxyType

from cics.statements import CicsOperand, ExecCicsStatement
from cobble.asg_walk import descend
from cobble.dataflow.fields.extent import CellIndex, OperandExtents, operand_extents
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
from cobol_memory.field_extent import FieldExtent

# cobol_asg has no statement base class, and its own union leaves out the
# dialect-parsed EXEC CICS form, so the two have to be spelled together here.
Statement = CobolStatementType | ExecCicsStatement

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


def _unresolved_origin(operand: RefModOperand, reason: str) -> str:
    """A literal reads no storage, and neither does LENGTH OF or a FUNCTION.

    For a field name that simply has no declared extent (e.g. a SQL host
    variable from an unparsed DCLGEN struct), embed the name so backward
    provenance queries say ``UNKNOWN:FIELD-NAME`` rather than the opaque
    ``UNKNOWN-NAME``.
    """
    if is_literal(operand.name):
        return LITERAL
    if reason == "unknown-name" and operand.name:
        return f"UNKNOWN:{operand.name}"
    return reason.upper()


def _one_move(
    operand: RefModOperand,
    sources: OperandExtents,
    target: FieldExtent,
    node: str,
) -> Iterator[Write]:
    """The whole target from the whole source, or from a named origin.

    One write however deep the target's record is. Which of the target's children
    took which of the source's bytes is offset arithmetic over the declared
    extents; see this module's docstring for the rule and side_tables for the
    layout it runs on.
    """
    if not sources.extents:
        origin = _unresolved_origin(operand, sources.reason)
        return iter((Write(target, _synthetic(origin, node)),))
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
        for entry in _one_move(operand, sources, target, node)
    )


def _initialize_targets(statement: InitializeStatement) -> tuple[RefModOperand, ...]:
    return tuple(RefModOperand(name=name) for name in statement.operands)


def _initialize_writes(
    statement: InitializeStatement, node: str, index: CellIndex
) -> Iterator[Write]:
    """The group's whole extent, from LITERAL -- not one write per child cell.

    Every child was written, and every child's write said the identical thing:
    same origin, same defining node, differing only in a target extent the
    group's own extent already contains. Which children those are is in the
    declared extents, which a consumer intersects against this one, so the
    fan-out was a per-edge restatement of the layout.
    """
    return _origin_writes(_initialize_targets(statement), LITERAL, node, index)


def _named_stubs(reads: tuple[RefModOperand, ...], index: CellIndex) -> tuple[str, ...]:
    """Names of read operands that have no resolvable extents and are not literals.

    Used to emit a ``FIELD:<name>`` synthetic source so backward provenance
    queries name the unresolvable input rather than reporting nothing.  Fields
    from unstaged copybooks are the common case.
    """
    return tuple(
        op.name
        for op in reads
        if op.name
        and not is_literal(op.name)
        and not operand_extents(op, index).extents
    )


def _union_writes(
    reads: tuple[RefModOperand, ...],
    targets: tuple[RefModOperand, ...],
    node: str,
    index: CellIndex,
) -> Iterator[Write]:
    """Every target takes every operand: no digit-level correspondence to model.

    When a read operand has no resolvable extents but carries a name that is not
    a literal, a synthetic ``FIELD:<name>`` source is emitted so backward
    provenance queries name the unresolvable input rather than reporting nothing.
    """
    every = tuple(
        extent
        for operand in reads
        for extent in operand_extents(operand, index).extents
    )
    stubs = _named_stubs(reads, index)
    stub_src = _synthetic(f"FIELD:{','.join(stubs)}", node) if stubs else frozenset()
    sources = _from_extents(every, node) | stub_src
    return (
        Write(target, sources)
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
    """Write ``origin`` to every target extent.

    When the target operand has no resolvable extents (unstaged copybook field),
    emit a single write to ``NOWHERE`` so the origin is at least recorded in the
    trace rather than silently dropped.
    """
    resolved = tuple(
        Write(target, _synthetic(origin, node))
        for operand in operands
        for target in operand_extents(operand, index).extents
    )
    if resolved:
        return iter(resolved)
    stub_targets = tuple(op for op in operands if op.name and not is_literal(op.name))
    return iter(
        Write(NOWHERE, _synthetic(f"{origin}→{op.name}", node)) for op in stub_targets
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

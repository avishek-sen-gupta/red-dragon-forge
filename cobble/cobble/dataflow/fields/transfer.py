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

from cics.statements import CicsOperand, ExecCicsStatement, operand_reference
from cobble.asg_walk import descend
from cobble.dataflow.fields.extent import CellIndex, OperandExtents, operand_extents
from cobble.dataflow.fields.move_kind import MoveKind
from cobble.dataflow.fields.state import (
    CICS_STATE,
    EMPTY,
    LITERAL,
    NOWHERE,
    Source,
    State,
    exact_values,
    weak_write,
    write,
)
from cobble.dataflow.fields.unmodelled_write import UnmodelledWrite
from cobble.dataflow.fields.values import (
    EMPTY as VALUES_EMPTY,
)
from cobble.dataflow.fields.values import (
    UnresolvedReason,
    ValueSet,
    because,
    fitted,
    merged,
    of_value,
    refitted,
)
from cobble.dataflow.layout import Cell
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
    RewriteStatement,
    StringStatement,
    WriteStatement,
)
from cobol_asg.ref_mod import (
    RefModBinOp,
    RefModExpr,
    RefModFunction,
    RefModLengthOf,
    RefModLiteral,
    RefModOperand,
    RefModReference,
)
from cobol_memory.field_extent import FieldExtent

# cobol_asg has no statement base class, and its own union leaves out the
# dialect-parsed EXEC CICS form, so the two have to be spelled together here.
Statement = CobolStatementType | ExecCicsStatement | UnmodelledWrite

_CICS_FILE_VERBS = frozenset({"READ", "READNEXT", "READPREV"})
_CICS_CALL_VERBS = frozenset({"LINK", "XCTL"})
_CICS_RECEIVERS = ("INTO", "SET")


@dataclass(frozen=True)
class Write:
    """One extent, and everything reaching it after this statement."""

    target: FieldExtent
    sources: frozenset[Source]
    values: ValueSet
    weak: bool = False
    copy_start: tuple[int, ...] = ()


def _applied(state: State, writes: Iterator[Write]) -> State:
    return reduce(_one_applied, writes, state)


def _one_applied(state: State, entry: Write) -> State:
    if entry.weak:
        return weak_write(state, entry.target, entry.sources, entry.values)
    return write(state, entry.target, entry.sources, entry.values)


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


def _literal_value(operand: RefModOperand, width: int) -> ValueSet:
    """A quoted literal's own bytes; anything else is not a literal."""
    if not is_literal(operand.name):
        return because(UnresolvedReason.NOT_A_LITERAL)
    text = operand.name.strip()
    if not (text[:1] in "'\"" and text[-1:] == text[:1]):
        return because(UnresolvedReason.NOT_A_LITERAL)
    return of_value(fitted(text[1:-1].encode("utf-8", errors="replace"), width))


def _carried(state: State, extents: tuple[FieldExtent, ...], width: int) -> ValueSet:
    return refitted(
        reduce(
            merged, (exact_values(state, extent) for extent in extents), VALUES_EMPTY
        ),
        width,
    )


def _one_move(
    operand: RefModOperand,
    sources: OperandExtents,
    target: FieldExtent,
    node: str,
    state: State,
    copy_start: tuple[int, ...],
) -> Iterator[Write]:
    """The whole target from the whole source, or from a named origin.

    One write however deep the target's record is. Which of the target's children
    took which of the source's bytes is offset arithmetic over the declared
    extents; see this module's docstring for the rule and side_tables for the
    layout it runs on.
    """
    if not sources.extents:
        origin = _unresolved_origin(operand, sources.reason)
        return iter(
            (
                Write(
                    target,
                    _synthetic(origin, node),
                    values=_literal_value(operand, target.length),
                ),
            )
        )
    return iter(
        (
            Write(
                target,
                _from_extents(sources.extents, node),
                values=_carried(state, sources.extents, target.length),
                copy_start=copy_start,
            ),
        )
    )


def _source_operand(statement: MoveStatement) -> RefModOperand:
    """A FUNCTION source denotes no storage, so only its absence of a name matters."""
    source = statement.source
    return source if isinstance(source, RefModOperand) else RefModOperand(name="")


def _move_targets(statement: MoveStatement) -> tuple[RefModOperand, ...]:
    return tuple(statement.targets)


def _move_writes(
    statement: MoveStatement, node: str, index: CellIndex, state: State
) -> Iterator[Write]:
    sources = operand_extents(statement.source, index)
    operand = _source_operand(statement)
    return (
        entry
        for target_operand in _move_targets(statement)
        for copy_start in (_copy_start(operand, target_operand, index),)
        for target in operand_extents(target_operand, index).extents
        for entry in _one_move(operand, sources, target, node, state, copy_start)
    )


_REF_MODS = (
    RefModLiteral,
    RefModReference,
    RefModLengthOf,
    RefModFunction,
    RefModBinOp,
)


def _kind(operand: RefModOperand, index: CellIndex) -> MoveKind:
    if isinstance(operand.ref_mod_start, _REF_MODS):
        return MoveKind.ALPHANUMERIC
    cells = index.cells_named(operand.name, operand.qualifiers, len(operand.subscripts))
    if not cells:
        return MoveKind.OTHER
    return _cell_kind(cells[0])


def _cell_kind(cell: Cell) -> MoveKind:
    if cell.is_group:
        return MoveKind.GROUP
    if _alphanumeric(cell.pic.upper()):
        return MoveKind.ALPHANUMERIC
    return MoveKind.OTHER


def _alphanumeric(pic: str) -> bool:
    symbols = set(pic.replace("(", "").replace(")", "").strip("0123456789"))
    return bool(pic) and symbols <= {"X", "A"}


def _constant(expression: RefModExpr, index: CellIndex) -> tuple[int, ...]:
    """A reference-modification bound's value when the compiler knows it -- a
    literal, LENGTH OF, or arithmetic over those -- or nothing when it does not."""
    if isinstance(expression, RefModBinOp):
        return _combined(
            expression.op,
            _constant(expression.left, index),
            _constant(expression.right, index),
        )
    return _leaf(expression, index)


def _leaf(expression: RefModExpr, index: CellIndex) -> tuple[int, ...]:
    match expression:
        case RefModLiteral(value=value):
            return _number(value)
        case RefModLengthOf(name=name):
            return tuple(cell.length for cell in index.cells_named(name, (), 0)[:1])
        case _:
            return ()


def _number(value: str) -> tuple[int, ...]:
    return (int(value),) if value.strip().lstrip("+-").isdigit() else ()


_ARITHMETIC: Mapping[str, Callable[[int, int], int]] = MappingProxyType(
    {
        "+": int.__add__,
        "-": int.__sub__,
        "*": int.__mul__,
        "/": int.__floordiv__,
    }
)


def _combined(
    op: str, left: tuple[int, ...], right: tuple[int, ...]
) -> tuple[int, ...]:
    if not left or not right or op not in _ARITHMETIC or (op == "/" and not right[0]):
        return ()
    return (_ARITHMETIC[op](left[0], right[0]),)


def _copy_start(
    source: RefModOperand, target: RefModOperand, index: CellIndex
) -> tuple[int, ...]:
    """The source byte that lands on the target's first byte, when the MOVE copies
    byte for byte from a fixed place: a group on either side, or both alphanumeric,
    with no subscript on the source and a reference-modification start the
    compiler knows. Nothing otherwise."""
    kinds = (_kind(source, index), _kind(target, index))
    copying = MoveKind.GROUP in kinds or kinds == (
        MoveKind.ALPHANUMERIC,
        MoveKind.ALPHANUMERIC,
    )
    cells = index.cells_named(source.name, source.qualifiers, 0)
    if source.subscripts or not copying or not cells:
        return ()
    base = index.extent_of(cells[0]).start
    if not isinstance(source.ref_mod_start, _REF_MODS):
        return (base,)
    offset = _constant(source.ref_mod_start, index)
    return (base + offset[0] - 1,) if offset else ()


def _implied_move(statement: WriteStatement | RewriteStatement) -> MoveStatement:
    """``WRITE rec FROM x`` and ``REWRITE rec FROM x`` move x into the record area
    first; without FROM the record area already holds what goes out."""
    targets = [RefModOperand(name=statement.record_name)]
    return MoveStatement(source=statement.from_field, targets=targets)


def _record_targets(
    statement: WriteStatement | RewriteStatement,
) -> tuple[RefModOperand, ...]:
    if not statement.from_field.name:
        return ()
    return (RefModOperand(name=statement.record_name),)


def _record_writes(
    statement: WriteStatement | RewriteStatement,
    node: str,
    index: CellIndex,
    state: State,
) -> Iterator[Write]:
    if not statement.from_field.name:
        return iter(())
    return _move_writes(_implied_move(statement), node, index, state)


def _initialize_targets(statement: InitializeStatement) -> tuple[RefModOperand, ...]:
    return tuple(statement.operands)


def _initialize_writes(
    statement: InitializeStatement, node: str, index: CellIndex, state: State
) -> Iterator[Write]:
    """The group's whole extent, from LITERAL -- not one write per child cell.

    Every child was written, and every child's write said the identical thing:
    same origin, same defining node, differing only in a target extent the
    group's own extent already contains. Which children those are is in the
    declared extents, which a consumer intersects against this one, so the
    fan-out was a per-edge restatement of the layout.

    ``INITIALIZE`` sets a category default this unit does not model, so the
    value is ``NOT_A_LITERAL`` rather than the literal bytes a numeric
    INITIALIZE actually zeroes.
    """
    return _origin_writes(
        _initialize_targets(statement),
        LITERAL,
        node,
        index,
        values=because(UnresolvedReason.NOT_A_LITERAL),
    )


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

    A ``STRING``/arithmetic/``COMPUTE`` result is never a literal, so the value
    is always ``NOT_A_LITERAL``.
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
        Write(target, sources, values=because(UnresolvedReason.NOT_A_LITERAL))
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
    """In-place receivers without GIVING, the GIVING receivers with it."""
    return (*statement.targets, *statement.giving, *_remainder(statement))


def _arithmetic_writes(
    statement: ArithmeticStatement, node: str, index: CellIndex, state: State
) -> Iterator[Write]:
    return _union_writes(
        (*statement.operands, *statement.targets),
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
    statement: ComputeStatement, node: str, index: CellIndex, state: State
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
    statement: StringStatement, node: str, index: CellIndex, state: State
) -> Iterator[Write]:
    return _union_writes(
        tuple(sending.value for sending in statement.sendings),
        _string_targets(statement),
        node,
        index,
    )


def _origin_writes(
    operands: tuple[RefModOperand, ...],
    origin: str,
    node: str,
    index: CellIndex,
    values: ValueSet,
) -> Iterator[Write]:
    """Write ``origin`` to every target extent.

    When the target operand has no resolvable extents (unstaged copybook field),
    emit a single write to ``NOWHERE`` so the origin is at least recorded in the
    trace rather than silently dropped.
    """
    resolved = tuple(
        Write(target, _synthetic(origin, node), values=values)
        for operand in operands
        for target in operand_extents(operand, index).extents
    )
    if resolved:
        return iter(resolved)
    stub_targets = tuple(op for op in operands if op.name and not is_literal(op.name))
    return iter(
        Write(NOWHERE, _synthetic(f"{origin}→{op.name}", node), values=values)
        for op in stub_targets
    )


def _read_targets(statement: ReadStatement) -> tuple[RefModOperand, ...]:
    return (statement.into,) if statement.into.name else ()


def _read_writes(
    statement: ReadStatement, node: str, index: CellIndex, state: State
) -> Iterator[Write]:
    return _origin_writes(
        _read_targets(statement),
        f"FILE:{statement.file_name}",
        node,
        index,
        values=because(UnresolvedReason.FROM_FILE),
    )


def _call_targets(statement: CallStatement) -> tuple[RefModOperand, ...]:
    """BY REFERENCE is the only linkage the callee can write back through."""
    passed = tuple(
        RefModOperand(
            name=param.name, qualifiers=param.qualifiers, subscripts=param.subscripts
        )
        for param in statement.using
        if param.param_type.upper() == "REFERENCE"
        and not param.omitted
        and not param.is_literal
    )
    given = (statement.giving,) if statement.giving.name else ()
    return (*passed, *given)


def _call_origin(statement: CallStatement) -> str:
    """The cross-program sink a CALL's BY REFERENCE arguments are credited to.

    The write itself is never dropped when the callee is dynamic -- the argument
    really is written by somebody, and saying otherwise would claim it still holds
    what the caller put there. What changes is the sink: ``%CALL:%DYNAMIC:WS-PROG``
    rather than ``%CALL:WS-PROG``, because the bare form is indistinguishable from a
    member actually named WS-PROG and would be joined to one. The ``%`` sigil marks
    it synthetic the way ``%CICS-STATE`` does, and keeping the field name leaves the
    reader a reaching-definitions query for the candidate callees.
    """
    target = statement.target
    match target.identifier:
        case None:
            return f"%CALL:{target.literal}"
        case identifier:
            return f"%CALL:%DYNAMIC:{identifier.name.strip().upper()}"


def _call_writes(
    statement: CallStatement, node: str, index: CellIndex, state: State
) -> Iterator[Write]:
    return _origin_writes(
        _call_targets(statement),
        _call_origin(statement),
        node,
        index,
        values=because(UnresolvedReason.FROM_CALLEE),
    )


def _option(statement: ExecCicsStatement, option: str) -> str:
    value = statement.options.get(option)
    return value.text if isinstance(value, CicsOperand) else ""


def _option_reference(statement: ExecCicsStatement, option: str) -> RefModOperand:
    """The named operand as storage: its indices and slice, not just its name.

    A receiver or commarea written as ``WS-TBL(WS-IDX)`` selects one occurrence,
    and reading the name alone resolves it at arity 0 against a field declared
    OCCURS -- which matches no cell, so the write lands nowhere (forge-zgn).
    """
    value = statement.options.get(option)
    if isinstance(value, CicsOperand):
        return operand_reference(value)
    return RefModOperand(name="")


def _receiver_options(statement: ExecCicsStatement) -> tuple[str, ...]:
    """The one option this verb receives into, INTO winning over SET."""
    named = tuple(name for name in _CICS_RECEIVERS if _option(statement, name))
    return named[:1]


def _cics_origin(statement: ExecCicsStatement) -> str:
    if statement.verb.upper() in _CICS_FILE_VERBS:
        return f"FILE:{_option(statement, 'FILE') or _option(statement, 'DATASET')}"
    return CICS_STATE


def _cics_values(statement: ExecCicsStatement) -> ValueSet:
    """A file verb's target came from the file; anything else is unmodeled CICS state."""
    if statement.verb.upper() in _CICS_FILE_VERBS:
        return because(UnresolvedReason.FROM_FILE)
    return because(UnresolvedReason.NOT_A_LITERAL)


def _cics_targets(statement: ExecCicsStatement) -> tuple[RefModOperand, ...]:
    """LINK and XCTL write through the COMMAREA; everything else through a receiver."""
    if statement.verb.upper() in _CICS_CALL_VERBS:
        return (_option_reference(statement, "COMMAREA"),)
    return tuple(
        _option_reference(statement, name) for name in _receiver_options(statement)
    )


def _cics_writes(
    statement: ExecCicsStatement, node: str, index: CellIndex, state: State
) -> Iterator[Write]:
    if statement.verb.upper() in _CICS_CALL_VERBS:
        return _origin_writes(
            _cics_targets(statement),
            f"%CALL:{_option(statement, 'PROGRAM')}",
            node,
            index,
            values=because(UnresolvedReason.FROM_CALLEE),
        )
    return _origin_writes(
        _cics_targets(statement),
        _cics_origin(statement),
        node,
        index,
        values=_cics_values(statement),
    )


def _no_writes(
    statement: Statement, node: str, index: CellIndex, state: State
) -> Iterator[Write]:
    return iter(())


def _no_targets(statement: Statement) -> tuple[RefModOperand, ...]:
    return ()


def _unmodelled_targets(statement: UnmodelledWrite) -> tuple[RefModOperand, ...]:
    return statement.targets


def _unmodelled_writes(
    statement: UnmodelledWrite, node: str, index: CellIndex, state: State
) -> Iterator[Write]:
    """A weak write to every target extent, from every source extent or the verb."""
    extents = tuple(
        extent
        for operand in statement.sources
        for extent in operand_extents(operand, index).extents
    )
    sources = (
        _from_extents(extents, node) if extents else _synthetic(statement.verb, node)
    )
    return (
        Write(
            target=target,
            sources=sources,
            values=because(UnresolvedReason.UNMODELLED),
            weak=True,
        )
        for operand in statement.targets
        for target in operand_extents(operand, index).extents
    )


HANDLED: tuple[type, ...] = (
    MoveStatement,
    InitializeStatement,
    ArithmeticStatement,
    ComputeStatement,
    StringStatement,
    ReadStatement,
    WriteStatement,
    RewriteStatement,
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
        "WriteStatement": _record_writes,
        "RewriteStatement": _record_writes,
        "CallStatement": _call_writes,
        "ExecCicsStatement": _cics_writes,
        "UnmodelledWrite": _unmodelled_writes,
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
            "WriteStatement": _record_targets,
            "RewriteStatement": _record_targets,
            "CallStatement": _call_targets,
            "ExecCicsStatement": _cics_targets,
            "UnmodelledWrite": _unmodelled_targets,
        }
    )
)


def writes_of(
    statement: Statement, node: str, index: CellIndex, state: State = EMPTY
) -> tuple[Write, ...]:
    """Every extent ``statement`` writes and what reaches each one.

    Public because an edge has to come from the writes themselves and not from
    diffing the state around them: a loop-carried definition is already in the
    in-state when the statement runs again, so the diff would be empty and the
    edge would vanish -- silently, which is the failure mode this whole module is
    arranged against.

    ``state`` defaults to empty because only a transfer needs a source field's
    current value to carry it forward; provenance-only callers (extraction, the
    trace walk) want no values and pass none.
    """
    handler = _WRITES_BY_KIND.get(type(statement).__name__, _no_writes)
    return tuple(handler(statement, node, index, state))


def transfer(statement: Statement, node: str, state: State, index: CellIndex) -> State:
    """The state after ``statement``, given the state before it.

    An unhandled statement class returns the state unchanged. ``HANDLED`` names
    what this does dispatch on, so a coverage measurement can subtract the rest
    rather than credit it as analysed.
    """
    return _applied(state, iter(writes_of(statement, node, index, state)))


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

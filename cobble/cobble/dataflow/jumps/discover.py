"""Every jump, exit, RETRIEVE and entry in one program, and what each hands over."""

from collections.abc import Mapping

from cics.statements import CicsOperand, ExecCicsStatement
from cobble.dataflow.fields.aliases import area_extents, received_areas
from cobble.dataflow.fields.extent import CellIndex, operand_occurrence_extents
from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.state import State
from cobble.dataflow.fields.transfer import Statement
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.facts import fact_at, merged
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.srccfg.cfg import Cfg, Node
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS, commarea_field
from cobol_asg.asg_types import CobolASG
from cobol_asg.cobol_statements import (
    ExitProgramStatement,
    GobackStatement,
    StopRunStatement,
)
from cobol_memory.field_extent import FieldExtent

_KINDS = {"LINK": JumpKind.LINK, "XCTL": JumpKind.XCTL, "CALL": JumpKind.CALL}
_RETURNS = frozenset({JumpKind.LINK, JumpKind.CALL})
_CICS_OPTION = {
    JumpKind.RETURN_TRANSID: "COMMAREA",
    JumpKind.START: "FROM",
    JumpKind.RETRIEVE: "INTO",
}
_CICS_VERBS = (("START", JumpKind.START), ("RETRIEVE", JumpKind.RETRIEVE))
_NO_TARGET = Fact(reasons=(UnresolvedReason.NO_EXTENT,))


def jumps_of(
    asg: CobolASG,
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    states: Mapping[str, State],
) -> tuple[Jump, ...]:
    return (
        _entry(asg, cfg, index),
        *(
            jump
            for node in cfg.nodes
            if node.id in states and node.id in statements
            for jump in _at(
                asg, cfg.program, node, statements[node.id], index, states[node.id]
            )
        ),
    )


def _entry(asg: CobolASG, cfg: Cfg, index: CellIndex) -> Jump:
    return Jump(
        program=cfg.program,
        node="",
        line=0,
        kind=JumpKind.ENTRY,
        returns=False,
        areas=tuple(
            JumpArea(param, extent_text(extent))
            for param, extent in received_areas(asg, index)
        ),
    )


def _return_kind(statement: ExecCicsStatement) -> JumpKind:
    if "TRANSID" in statement.options:
        return JumpKind.RETURN_TRANSID
    return JumpKind.EXIT


def _cics_kind(statement: ExecCicsStatement) -> tuple[JumpKind, ...]:
    verb = statement.verb.upper()
    if verb == "RETURN":
        return (_return_kind(statement),)
    return tuple(kind for name, kind in _CICS_VERBS if name == verb)


def _at(
    asg: CobolASG,
    program: str,
    node: Node,
    statement: Statement,
    index: CellIndex,
    state: State,
) -> tuple[Jump, ...]:
    if node.transfer in CALL_TRANSFERS:
        return (_cfg_jump(program, node, index, state),)
    return _statement_jumps(asg, program, node, statement, index, state)


def _statement_jumps(
    asg: CobolASG,
    program: str,
    node: Node,
    statement: Statement,
    index: CellIndex,
    state: State,
) -> tuple[Jump, ...]:
    match statement:
        case ExecCicsStatement():
            return tuple(
                _cics_jump(asg, program, node, statement, kind, index, state)
                for kind in _cics_kind(statement)
            )
        case GobackStatement() | ExitProgramStatement() | StopRunStatement():
            return (_exit(asg, program, node, index, state),)
        case _:
            return ()


def _base(program: str, node: Node, kind: JumpKind) -> Jump:
    return Jump(
        program=program,
        node=node.id,
        line=node.span.line_start,
        kind=kind,
        returns=kind in _RETURNS,
    )


def _cfg_jump(program: str, node: Node, index: CellIndex, state: State) -> Jump:
    kind = _KINDS[CALL_TRANSFERS[node.transfer]]
    base = _base(program, node, kind)
    return Jump(
        base.program,
        base.node,
        base.line,
        base.kind,
        base.returns,
        target=_target(node, index, state),
        areas=_cfg_areas(node, kind, index, state),
    )


def _target(node: Node, index: CellIndex, state: State) -> Fact:
    if node.target_resolved:
        return Fact(values=(node.target,))
    extents = operand_occurrence_extents(node.target_operand, index)
    if not extents:
        return _NO_TARGET
    return merged(tuple(fact_at(state, extent) for extent in extents))


def _cfg_areas(
    node: Node, kind: JumpKind, index: CellIndex, state: State
) -> tuple[JumpArea, ...]:
    if kind is JumpKind.CALL:
        return tuple(
            area
            for position, argument in enumerate(node.using)
            for area in _areas(position, argument.name, index, state)
        )
    return _areas(0, commarea_field(node), index, state)


def _areas(
    param: int, operand: str, index: CellIndex, state: State
) -> tuple[JumpArea, ...]:
    if not operand:
        return ()
    return tuple(
        dict.fromkeys(
            JumpArea(param, extent_text(extent), _fields(extent, index, state))
            for extent in area_extents(operand, index)
        )
    )


def _fields(extent: FieldExtent, index: CellIndex, state: State) -> tuple[Fact, ...]:
    cells = index.elementary_within(extent)
    if not cells:
        return (fact_at(state, extent),)
    return tuple(fact_at(state, index.extent_of(cell)) for cell in cells)


def _option(statement: ExecCicsStatement, name: str) -> CicsOperand:
    value = statement.options.get(name, CicsOperand(text="", is_literal=False))
    return (
        value
        if isinstance(value, CicsOperand)
        else CicsOperand(text="", is_literal=False)
    )


def _transid(statement: ExecCicsStatement, index: CellIndex, state: State) -> Fact:
    operand = _option(statement, "TRANSID")
    if operand.is_literal:
        return Fact(values=(operand.text,))
    extents = area_extents(operand.text, index)
    if not extents:
        return _NO_TARGET
    return merged(tuple(fact_at(state, extent) for extent in extents))


def _cics_jump(
    asg: CobolASG,
    program: str,
    node: Node,
    statement: ExecCicsStatement,
    kind: JumpKind,
    index: CellIndex,
    state: State,
) -> Jump:
    if kind is JumpKind.EXIT:
        return _exit(asg, program, node, index, state)
    base = _base(program, node, kind)
    return Jump(
        base.program,
        base.node,
        base.line,
        base.kind,
        base.returns,
        transid=(
            _transid(statement, index, state)
            if kind is not JumpKind.RETRIEVE
            else Fact()
        ),
        areas=_areas(0, _option(statement, _CICS_OPTION[kind]).text, index, state),
    )


def _exit(
    asg: CobolASG, program: str, node: Node, index: CellIndex, state: State
) -> Jump:
    base = _base(program, node, JumpKind.EXIT)
    return Jump(
        base.program,
        base.node,
        base.line,
        base.kind,
        base.returns,
        areas=tuple(
            JumpArea(param, extent_text(extent), _fields(extent, index, state))
            for param, extent in received_areas(asg, index)
        ),
    )

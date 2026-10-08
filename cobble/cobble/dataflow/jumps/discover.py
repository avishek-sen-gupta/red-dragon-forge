"""Every jump, exit, RETRIEVE and entry in one program, and what each hands over."""

from collections.abc import Callable, Mapping

from cics.statements import CicsOperand, ExecCicsStatement
from cobble.dataflow.fields.aliases import (
    area_extents,
    received_areas,
    receives_commarea,
)
from cobble.dataflow.fields.extent import CellIndex, operand_occurrence_extents
from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.state import EMPTY as STATE_EMPTY
from cobble.dataflow.fields.state import State
from cobble.dataflow.fields.transfer import Statement
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.area_kind import AreaKind
from cobble.dataflow.fixpoint.area_slot import AreaSlot
from cobble.dataflow.fixpoint.area_table import AreaTable
from cobble.dataflow.fixpoint.call_site import CallSite
from cobble.dataflow.fixpoint.demand import Demand
from cobble.dataflow.fixpoint.demand_parts import DemandParts, Slots
from cobble.dataflow.fixpoint.live import Live
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

Keep = Callable[[FieldExtent], bool]


def _keeper(live: Live, node: str) -> Keep:
    return lambda extent: live.keeps(node, extent)


def jumps_of(
    asg: CobolASG,
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    states: Mapping[str, State],
    settled: bool,
    live: Live,
) -> tuple[Jump, ...]:
    return (
        _entry(asg, cfg, index),
        *(
            _with_incomplete_walk(jump, settled)
            for node in cfg.nodes
            if node.id in statements
            for jump in _at(
                asg,
                cfg.program,
                node,
                statements[node.id],
                index,
                states.get(node.id, STATE_EMPTY),
                _keeper(live, node.id),
            )
        ),
    )


def _incomplete(fact: Fact) -> Fact:
    reasons = {*fact.reasons, UnresolvedReason.INCOMPLETE_WALK}
    return Fact(
        fact.extent,
        fact.values,
        fact.writers,
        tuple(reason for _, reason in sorted((r.value, r) for r in reasons)),
    )


def _with_incomplete_walk(jump: Jump, settled: bool) -> Jump:
    if settled or jump.kind is JumpKind.ENTRY:
        return jump
    return Jump(
        jump.program,
        jump.node,
        jump.line,
        jump.kind,
        jump.returns,
        target=_incomplete(jump.target),
        transid=_incomplete(jump.transid),
        areas=tuple(
            JumpArea(area.param, area.extent, tuple(map(_incomplete, area.fields)))
            for area in jump.areas
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
    keep: Keep,
) -> tuple[Jump, ...]:
    if node.transfer in CALL_TRANSFERS:
        return (_cfg_jump(program, node, index, state, keep),)
    return _statement_jumps(asg, program, node, statement, index, state, keep)


def _statement_jumps(
    asg: CobolASG,
    program: str,
    node: Node,
    statement: Statement,
    index: CellIndex,
    state: State,
    keep: Keep,
) -> tuple[Jump, ...]:
    match statement:
        case ExecCicsStatement():
            return tuple(
                _cics_jump(asg, program, node, statement, kind, index, state, keep)
                for kind in _cics_kind(statement)
            )
        case GobackStatement() | ExitProgramStatement() | StopRunStatement():
            return (_exit(asg, program, node, index, state, keep),)
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


def _cfg_jump(
    program: str, node: Node, index: CellIndex, state: State, keep: Keep
) -> Jump:
    kind = _KINDS[CALL_TRANSFERS[node.transfer]]
    base = _base(program, node, kind)
    return Jump(
        base.program,
        base.node,
        base.line,
        base.kind,
        base.returns,
        target=_target(node, index, state),
        areas=_cfg_areas(node, kind, index, state, keep),
    )


def _target(node: Node, index: CellIndex, state: State) -> Fact:
    if node.target_resolved:
        return Fact(values=(node.target,))
    extents = operand_occurrence_extents(node.target_operand, index)
    if not extents:
        return _NO_TARGET
    return merged(tuple(fact_at(state, extent) for extent in extents))


def _cfg_areas(
    node: Node, kind: JumpKind, index: CellIndex, state: State, keep: Keep
) -> tuple[JumpArea, ...]:
    if kind is JumpKind.CALL:
        return tuple(
            area
            for position, argument in enumerate(node.using)
            for area in _areas(position, argument.name, index, state, keep)
        )
    return _areas(0, commarea_field(node), index, state, keep)


def _areas(
    param: int, operand: str, index: CellIndex, state: State, keep: Keep
) -> tuple[JumpArea, ...]:
    if not operand:
        return ()
    return tuple(
        dict.fromkeys(
            JumpArea(param, extent_text(extent), _fields(extent, index, state, keep))
            for extent in area_extents(operand, index)
        )
    )


def _fields(
    extent: FieldExtent, index: CellIndex, state: State, keep: Keep
) -> tuple[Fact, ...]:
    """Facts at each elementary cell of an area the walk kept live here.

    A cell no demand reaches at this node held only pruned state, so a fact read
    from it would be invented; it is left out rather than reported wrong.
    """
    cells = index.elementary_within(extent)
    if not cells:
        return (fact_at(state, extent),) if keep(extent) else ()
    return tuple(
        fact_at(state, cell_extent)
        for cell in cells
        for cell_extent in (index.extent_of(cell),)
        if keep(cell_extent)
    )


def _option(statement: ExecCicsStatement, name: str) -> CicsOperand:
    value = statement.options.get(name, CicsOperand(text="", is_literal=False))
    return (
        value
        if isinstance(value, CicsOperand)
        else CicsOperand(text="", is_literal=False)
    )


def transid_operand(statement: ExecCicsStatement) -> CicsOperand:
    """A CICS command's TRANSID: a literal, a data name, or empty when it has none."""
    return _option(statement, "TRANSID")


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
    keep: Keep,
) -> Jump:
    if kind is JumpKind.EXIT:
        return _exit(asg, program, node, index, state, keep)
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
        areas=_areas(
            0, _option(statement, _CICS_OPTION[kind]).text, index, state, keep
        ),
    )


def _exit(
    asg: CobolASG, program: str, node: Node, index: CellIndex, state: State, keep: Keep
) -> Jump:
    base = _base(program, node, JumpKind.EXIT)
    return Jump(
        base.program,
        base.node,
        base.line,
        base.kind,
        base.returns,
        areas=tuple(
            JumpArea(param, extent_text(extent), _fields(extent, index, state, keep))
            for param, extent in received_areas(asg, index)
        ),
    )


def call_target_demand(
    asg: CobolASG,
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    table: AreaTable,
) -> Demand:
    """Every extent the jumps and targets tables read a fact at, by the node it is
    read at; of a handed-over area, only the bytes ``table`` says someone reads."""
    return demand_parts(asg, cfg, statements, index).demand(table)


_Handed = tuple[tuple[CallSite, Slots], ...]
_Parts = tuple[tuple[FieldExtent, ...], _Handed, Slots]
_NO_PARTS: _Parts = ((), (), ())
_NEXT_TRANSACTION = CallSite("", AreaKind.COMMAREA)
_COMMAREA_SLOT = AreaSlot(AreaKind.COMMAREA, 0)
_RETRIEVED_SLOT = AreaSlot(AreaKind.RETRIEVED, 0)
_HANDED: Mapping[JumpKind, CallSite] = {
    JumpKind.RETURN_TRANSID: _NEXT_TRANSACTION,
    JumpKind.START: CallSite("", AreaKind.RETRIEVED),
}
_SLOT_OF: Mapping[JumpKind, AreaSlot] = {
    JumpKind.RETURN_TRANSID: _COMMAREA_SLOT,
    JumpKind.START: _RETRIEVED_SLOT,
}


def retrieved_areas(statement: Statement, index: CellIndex) -> Slots:
    """A RETRIEVE's INTO area, in the slot a START's FROM area is handed to."""
    if not isinstance(
        statement, ExecCicsStatement
    ) or JumpKind.RETRIEVE not in _cics_kind(statement):
        return ()
    return tuple(
        (_RETRIEVED_SLOT, area)
        for area in _named(
            _option(statement, _CICS_OPTION[JumpKind.RETRIEVE]).text, index
        )
    )


def received_slots(asg: CobolASG, index: CellIndex) -> Slots:
    """The areas a program receives, each in its slot."""
    kind = AreaKind.COMMAREA if receives_commarea(index) else AreaKind.USING
    return tuple(
        (AreaSlot(kind, position), extent)
        for position, extent in received_areas(asg, index)
    )


def demand_parts(
    asg: CobolASG,
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
) -> DemandParts:
    received = received_slots(asg, index)
    rows = tuple(
        (node.id, _parts(node, statements, index, received)) for node in cfg.nodes
    )
    return DemandParts(
        local=tuple((node, parts[0]) for node, parts in rows if parts[0]),
        entry=tuple(
            (node, site, areas)
            for node, parts in rows
            for site, areas in parts[1]
            if areas
        ),
        back=tuple((node, parts[2]) for node, parts in rows if parts[2]),
    )


def _parts(
    node: Node,
    statements: Mapping[str, Statement],
    index: CellIndex,
    received: Slots,
) -> _Parts:
    if node.transfer in CALL_TRANSFERS:
        return (
            _target_extents(node, index),
            ((call_site(node), call_areas(node, index)),),
            (),
        )
    return _statement_parts(statements, node.id, index, received)


def _statement_parts(
    statements: Mapping[str, Statement],
    node: str,
    index: CellIndex,
    received: Slots,
) -> _Parts:
    match statements.get(node):
        case ExecCicsStatement() as cics:
            return _cics_parts(cics, index, received)
        case GobackStatement() | ExitProgramStatement() | StopRunStatement():
            return ((), (), received)
        case _:
            return _NO_PARTS


def _cics_parts(
    statement: ExecCicsStatement, index: CellIndex, received: Slots
) -> _Parts:
    """A transaction id is read where it is named. A RETURN TRANSID's commarea and
    a START's FROM area are handed over, charged by what the program the
    transaction runs needs of them; a RETRIEVE's INTO area is written, not read."""
    kinds = _cics_kind(statement)
    handed = tuple(
        (kind, _named(_option(statement, _CICS_OPTION[kind]).text, index))
        for kind in kinds
        if kind is not JumpKind.EXIT
    )
    return (
        tuple(
            extent
            for kind, _ in handed
            for extent in _transid_extents(statement, kind, index)
        ),
        tuple(
            (_HANDED[kind], tuple((_SLOT_OF[kind], area) for area in areas))
            for kind, areas in handed
            if kind in _HANDED
        ),
        received if JumpKind.EXIT in kinds else (),
    )


def _target_extents(node: Node, index: CellIndex) -> tuple[FieldExtent, ...]:
    if node.target_resolved:
        return ()
    return operand_occurrence_extents(node.target_operand, index)


def call_areas(node: Node, index: CellIndex) -> Slots:
    """The areas a CALL, LINK or XCTL hands over, each in its slot."""
    if _KINDS[CALL_TRANSFERS[node.transfer]] is JumpKind.CALL:
        return tuple(
            (AreaSlot(AreaKind.USING, position), extent)
            for position, argument in enumerate(node.using)
            for extent in _named(argument.name, index)
        )
    return tuple(
        (_COMMAREA_SLOT, extent) for extent in _named(commarea_field(node), index)
    )


def call_site(node: Node) -> CallSite:
    """The program a CALL, LINK or XCTL names, empty when a data item names it."""
    kind = (
        AreaKind.USING
        if _KINDS[CALL_TRANSFERS[node.transfer]] is JumpKind.CALL
        else AreaKind.COMMAREA
    )
    return CallSite(node.target if node.target_resolved else "", kind)


def returns(node: Node) -> bool:
    return _KINDS[CALL_TRANSFERS[node.transfer]] in _RETURNS


def _named(operand: str, index: CellIndex) -> tuple[FieldExtent, ...]:
    if not operand:
        return ()
    return area_extents(operand, index)


def _transid_extents(
    statement: ExecCicsStatement, kind: JumpKind, index: CellIndex
) -> tuple[FieldExtent, ...]:
    operand = _option(statement, "TRANSID")
    if kind is JumpKind.RETRIEVE or operand.is_literal:
        return ()
    return _named(operand.text, index)

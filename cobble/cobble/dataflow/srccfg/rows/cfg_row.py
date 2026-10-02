"""Every src-cfg row type -- a CFG's rows and a reachability walk's -- and their builders."""

from cobble.dataflow.srccfg.cfg import Edge, Node
from cobble.dataflow.srccfg.link import BundleCall
from cobble.dataflow.srccfg.rows.call_row import CfgCallRow
from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from cobble.dataflow.srccfg.rows.edge_row import CfgEdgeRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.outcome_row import CfgOutcomeRow
from cobble.dataflow.srccfg.rows.program_row import CfgProgramRow
from cobble.dataflow.srccfg.rows.reach_outcome import ReachOutcome
from cobble.dataflow.srccfg.rows.refused_row import CfgRefusedRow
from cobble.dataflow.srccfg.rows.summary_row import CfgSummaryRow
from cobble.dataflow.srccfg.rows.unresolved_row import CfgUnresolvedRow
from pydantic import TypeAdapter

CfgRow = (
    CfgProgramRow
    | CfgNodeRow
    | CfgEdgeRow
    | CfgCallRow
    | CfgOutcomeRow
    | CfgUnresolvedRow
    | CfgRefusedRow
    | CfgSummaryRow
)

CFG_ROWS: TypeAdapter[CfgRow] = TypeAdapter(CfgRow)


def program_row(program: str) -> CfgProgramRow:
    return CfgProgramRow(type=CfgRowType.PROGRAM, program=program)


def node_row(program: str, node: Node) -> CfgNodeRow:
    return CfgNodeRow(
        type=CfgRowType.NODE,
        program=program,
        id=node.id,
        kind=node.kind,
        paragraph=node.paragraph,
        atom=node.atom,
        writes=node.writes,
        reads=node.reads,
        transfer=node.transfer,
        target=node.target,
        target_resolved=node.target_resolved,
        target_operand=node.target_operand,
        transfer_operand=node.transfer_operand,
        using=node.using,
        span=node.span,
        resume=node.resume,
    )


def edge_row(program: str, edge: Edge) -> CfgEdgeRow:
    return CfgEdgeRow(
        type=CfgRowType.EDGE,
        program=program,
        source=edge.source,
        target=edge.target,
        kind=edge.kind,
    )


def call_row(call: BundleCall) -> CfgCallRow:
    return CfgCallRow(
        type=CfgRowType.CALL,
        caller=call.caller,
        node=call.node,
        transfer=call.transfer,
        program=call.program,
        entry=call.entry,
        resolved=call.resolved,
        commarea=call.commarea,
        expression=call.expression,
        reasons=call.reasons,
        certain=call.certain,
    )


def outcome_row(kind: ReachOutcome, node: str) -> CfgOutcomeRow:
    return CfgOutcomeRow(type=CfgRowType.OUTCOME, kind=kind, node=node)


def unresolved_row(node: str) -> CfgUnresolvedRow:
    return CfgUnresolvedRow(type=CfgRowType.UNRESOLVED, node=node)


def refused_row(node: str) -> CfgRefusedRow:
    return CfgRefusedRow(type=CfgRowType.REFUSED, node=node)


def summary_row(seed: str, states: int) -> CfgSummaryRow:
    return CfgSummaryRow(type=CfgRowType.SUMMARY, seed=seed, states=states)

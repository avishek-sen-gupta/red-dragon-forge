"""Every program's CFG -- nodes, edges, calls and entry -- as facts."""

from pathlib import Path

from cobble.dataflow.srccfg.cfg import NodeKind
from cobble.dataflow.srccfg.desugar import PERFORM_TRANSFER
from cobble.dataflow.srccfg.rows.call_row import CfgCallRow
from cobble.dataflow.srccfg.rows.cfg_row import CFG_ROWS, CfgRow
from cobble.dataflow.srccfg.rows.edge_row import CfgEdgeRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.program_row import CfgProgramRow
from cobble.experimental.datalog.column import number, symbol
from cobble.experimental.datalog.encoding import ABSENT, yes_no
from cobble.experimental.datalog.facts import Facts, Row
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import lines, matching

PROGRAM = Relation("program", (symbol("p"), symbol("where")))
CFG_NODE = Relation(
    "cfg_node",
    (
        symbol("p"),
        symbol("n"),
        symbol("kind"),
        symbol("para"),
        number("line"),
        symbol("transfer"),
    ),
)
CFG_EDGE = Relation("cfg_edge", (symbol("p"), symbol("a"), symbol("b"), symbol("kind")))
CFG_PRED = Relation(
    "cfg_pred",
    (
        symbol("p"),
        symbol("n"),
        symbol("l"),
        symbol("op"),
        symbol("r"),
        symbol("text"),
        symbol("resolved"),
    ),
)
CFG_WRITE = Relation("cfg_write", (symbol("p"), symbol("n"), symbol("f")))
CFG_READ = Relation("cfg_read", (symbol("p"), symbol("n"), symbol("f")))
CFG_TARGET = Relation(
    "cfg_target", (symbol("p"), symbol("n"), symbol("t"), symbol("resolved"))
)
CFG_FILE = Relation("cfg_file", (symbol("p"), symbol("n"), symbol("f")))
CFG_PERFORM = Relation(
    "cfg_perform", (symbol("p"), symbol("s"), symbol("resume"), symbol("rend"))
)
CFG_CALL = Relation(
    "cfg_call",
    (
        symbol("caller"),
        symbol("n"),
        symbol("transfer"),
        symbol("callee"),
        symbol("entry"),
        symbol("resolved"),
        symbol("expr"),
        symbol("certain"),
    ),
)
CFG_CALL_REASON = Relation(
    "cfg_call_reason", (symbol("caller"), symbol("n"), symbol("why"))
)
CFG_ENTRY = Relation("cfg_entry", (symbol("p"), symbol("n")))


def _rows(run: Path) -> tuple[CfgRow, ...]:
    return tuple(
        CFG_ROWS.validate_json(line)
        for path in matching(run / "srccfg", "cfg-*.jsonl")
        for line in lines(path)
    )


def _where(row: CfgProgramRow) -> str:
    return "external" if row.external else "internal"


def _or_absent(text: str) -> str:
    return text if text else ABSENT


def _node(row: CfgNodeRow) -> Row:
    return (
        row.program,
        row.id,
        row.kind.value,
        row.paragraph,
        row.span.line_start,
        row.transfer,
    )


def _pred(row: CfgNodeRow) -> Row:
    atom = row.atom
    return (
        row.program,
        row.id,
        atom.left,
        atom.op,
        atom.right,
        atom.text,
        yes_no(atom.resolved),
    )


def _call(row: CfgCallRow) -> Row:
    return (
        row.caller,
        row.node,
        row.transfer,
        row.program,
        row.entry,
        yes_no(row.resolved),
        row.expression,
        yes_no(row.certain),
    )


def _node_facts(nodes: tuple[CfgNodeRow, ...]) -> tuple[Facts, ...]:
    return (
        Facts(CFG_NODE, tuple(map(_node, nodes))),
        Facts(
            CFG_PRED, tuple(_pred(row) for row in nodes if row.kind is NodeKind.TEST)
        ),
        Facts(
            CFG_WRITE,
            tuple((row.program, row.id, name) for row in nodes for name in row.writes),
        ),
        Facts(
            CFG_READ,
            tuple((row.program, row.id, name) for row in nodes for name in row.reads),
        ),
        Facts(
            CFG_TARGET,
            tuple(
                (row.program, row.id, row.target, yes_no(row.target_resolved))
                for row in nodes
                if row.target
            ),
        ),
        Facts(
            CFG_FILE,
            tuple((row.program, row.id, row.file) for row in nodes if row.file),
        ),
        Facts(
            CFG_PERFORM,
            tuple(
                (row.program, row.id, _or_absent(row.resume), _or_absent(row.range_end))
                for row in nodes
                if row.transfer == PERFORM_TRANSFER
            ),
        ),
    )


def _program_facts(programs: tuple[CfgProgramRow, ...]) -> tuple[Facts, ...]:
    return (
        Facts(PROGRAM, tuple((row.program, _where(row)) for row in programs)),
        Facts(
            CFG_ENTRY,
            tuple((row.program, row.entry) for row in programs if row.entry),
        ),
    )


def _call_facts(calls: tuple[CfgCallRow, ...]) -> tuple[Facts, ...]:
    return (
        Facts(CFG_CALL, tuple(map(_call, calls))),
        Facts(
            CFG_CALL_REASON,
            tuple((row.caller, row.node, why) for row in calls for why in row.reasons),
        ),
    )


def cfg_facts(run: Path) -> tuple[Facts, ...]:
    rows = _rows(run)
    edges = tuple(row for row in rows if isinstance(row, CfgEdgeRow))
    return (
        *_program_facts(tuple(row for row in rows if isinstance(row, CfgProgramRow))),
        *_node_facts(tuple(row for row in rows if isinstance(row, CfgNodeRow))),
        Facts(
            CFG_EDGE,
            tuple(
                (row.program, row.source, row.target, row.kind.value) for row in edges
            ),
        ),
        *_call_facts(tuple(row for row in rows if isinstance(row, CfgCallRow))),
    )

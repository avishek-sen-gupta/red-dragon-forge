"""One program's control-flow graph as cobble's fixpoint walks it, as rows: its nodes with cobble's ids, its edges, each PERFORM's range, and the statement each node lowers."""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import groupby

from cobble.dataflow.fields.extent import denoted_cells
from cobble.dataflow.fixpoint.fallthrough import fallthroughs_pruned
from cobble.dataflow.fixpoint.fixpoint import program_statements
from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, Node
from cobble.dataflow.srccfg.paragraphs import label_id, paragraph_order
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.read import names_of
from cobble.dataflow.srccfg.read_kind import ReadKind
from cobble.dataflow.srccfg.statements import statement_index
from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.schema.ast_rows import Rows
from cobble.experimental.codeql.scope import Scope
from cobble.experimental.codeql.trap_row import TrapRow, define
from cobol_asg.asg_types import CobolASG

_SITE_MARKS = ("#", ".after.")


def walked_cfg(asg: CobolASG) -> Cfg:
    """The graph cobble's fixpoint walks: lowered, handlers joined, and the
    fall-throughs no path takes pruned."""
    unpruned = program_cfg(asg)
    return fallthroughs_pruned(
        unpruned, paragraph_order(asg), program_statements(asg, unpruned)
    )


@dataclass(frozen=True)
class CfgFacts:
    """``nodes`` labels each node by its id; ``lowered`` maps a statement's
    identity to cobble's id for it; ``sites`` each such id to the further nodes it
    lowers to and the suffix naming each."""

    nodes: Mapping[str, Label]
    lowered: Mapping[int, str]
    sites: Mapping[str, tuple[tuple[str, str], ...]]

    def statement_rows(self, statement_id: int, label: Label) -> Rows:
        """A statement's id, the node it lowers to when it has one of its own (an
        inline PERFORM lowers only to its loop's nodes), and its further nodes."""
        base = self.lowered.get(statement_id, "")
        if not base:
            return ()
        return (
            TrapRow("statement_ids", (label, base)),
            *(
                (TrapRow("cfg_statement", (self.nodes[base], label)),)
                if base in self.nodes
                else ()
            ),
            *(
                TrapRow("cfg_site", (self.nodes[node], label, suffix))
                for node, suffix in self.sites.get(base, ())
            ),
        )


def cfg_facts(asg: CobolASG, cfg: Cfg) -> CfgFacts:
    indexed = statement_index(asg)
    found = sorted(
        (base, node.id, node.id[len(base) :])
        for node in cfg.nodes
        for base in (_base(node.id),)
        if base != node.id and base in indexed
    )
    return CfgFacts(
        nodes={node.id: Label(f"n{i}") for i, node in enumerate(cfg.nodes)},
        lowered={id(statement): node for node, statement in indexed.items()},
        sites={
            base: tuple((node, suffix) for _, node, suffix in group)
            for base, group in groupby(found, key=lambda one: one[0])
        },
    )


def cfg_rows(
    asg: CobolASG, cfg: Cfg, facts: CfgFacts, scope: Scope, program: Label
) -> Rows:
    order = paragraph_order(asg)
    entry = label_id(order[0].name) if order else ""
    return (
        *(row for node in cfg.nodes for row in _node_rows(node, facts, scope, program)),
        *(
            TrapRow(
                "cfg_edges",
                (facts.nodes[e.source], facts.nodes[e.target], e.kind.value),
            )
            for e in cfg.edges
        ),
        *(
            (TrapRow("cfg_entry", (program, facts.nodes[entry])),)
            if entry in facts.nodes
            else ()
        ),
        *(row for node in cfg.nodes for row in _call_rows(node, cfg, facts)),
        *(row for node in cfg.nodes for row in _consult_rows(node, facts, scope)),
        *(
            TrapRow("cfg_resume", (facts.nodes[node.id], facts.nodes[node.resume]))
            for node in cfg.nodes
            if node.resume in facts.nodes
        ),
    )


def _node_rows(node: Node, facts: CfgFacts, scope: Scope, program: Label) -> Rows:
    label = facts.nodes[node.id]
    location, located = scope.location(label, node.span)
    row = TrapRow("cfg_nodes", (label, program, node.id, node.kind.value, location))
    return (define(label), *located, row)


def _call_rows(node: Node, cfg: Cfg, facts: CfgFacts) -> Rows:
    """A PERFORM: the range it enters and where the range ends."""
    return tuple(
        row
        for edge in cfg.successors(node.id)
        if edge.kind is EdgeKind.PERFORM and node.range_end in facts.nodes
        for row in (
            TrapRow(
                "cfg_call",
                (
                    facts.nodes[node.id],
                    facts.nodes[edge.target],
                    facts.nodes[node.range_end],
                ),
            ),
        )
    )


def _consult_rows(node: Node, facts: CfgFacts, scope: Scope) -> Rows:
    """The cells a node consults -- a test's operands, a key, a subscript -- each
    name resolved as cobble's fixpoint resolves it: by itself, unqualified."""
    return tuple(
        TrapRow("cfg_consults", (facts.nodes[node.id], scope.cells[cell]))
        for name in names_of(
            read for read in node.reads if read.kind is ReadKind.CONSULTED
        )
        for cell in denoted_cells(name, (), (), scope.index)
    )


def _base(node_id: str) -> str:
    cuts = tuple(node_id.find(mark) for mark in _SITE_MARKS if mark in node_id)
    return node_id[: min(cuts)] if cuts else node_id

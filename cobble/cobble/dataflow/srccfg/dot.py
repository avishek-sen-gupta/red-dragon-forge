"""The CFG as graphviz DOT, so a person can look at the shape of the control flow.

A rendering and not an analysis: every node and every edge the CFG holds is drawn, and
nothing is summarised or filtered. The queries in render.py answer a question about one
field; this answers "what does the flow through these programs look like", which has no
textual form that fits on a screen.

Two decisions carry the weight, and both live in presentation.py because webgl.py
makes them the same way. Node ids are qualified with the program, because every member
of a corpus has a MAIN/0 and an unqualified graph silently merges them into one wrong
graph. And a CALL whose target is in the bundle gets an edge to that program's entry,
because otherwise a closure renders as a row of disconnected islands -- and the one
thing the closure establishes is that these programs are a single path.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from cobble.dataflow.srccfg.build_corpus import load_cfgs
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.presentation import (
    CrossCall,
    label_of,
    qualified,
    resolved_calls,
)

SHAPES: Mapping[NodeKind, str] = {
    NodeKind.TEST: "diamond",
    NodeKind.ASSIGN: "box",
    NodeKind.CALL: "box3d",
    NodeKind.LABEL: "ellipse",
    NodeKind.NOP: "point",
}

FILLS: Mapping[NodeKind, str] = {
    NodeKind.TEST: "#fff2cc",
    NodeKind.ASSIGN: "#ffffff",
    NodeKind.CALL: "#d5e8d4",
    NodeKind.LABEL: "#dae8fc",
    NodeKind.NOP: "#eeeeee",
}

EDGE_COLOURS: Mapping[EdgeKind, str] = {
    EdgeKind.FLOW: "#666666",
    EdgeKind.TRUE: "#2e7d32",
    EdgeKind.FALSE: "#c62828",
    EdgeKind.PERFORM: "#1565c0",
    EdgeKind.RETURN: "#8e8e8e",
    EdgeKind.FALLTHRU: "#999999",
    EdgeKind.GOTO: "#6a1b9a",
}

# FLOW is the default and FALLTHRU is implicit: labelling either one puts a word on
# almost every edge of a four-thousand-node graph, which hides the two that matter.
UNLABELLED = (EdgeKind.FLOW, EdgeKind.FALLTHRU)

CALL_COLOUR = "#ef6c00"


def _escaped(text: str) -> str:
    """Backslash first, or the escapes this adds get escaped again.

    COBOL condition text is full of quoted literals, and one unescaped quote ends the
    label early: graphviz then fails on the rest of the line and no picture comes out.
    """
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _node_line(program: str, node: Node) -> str:
    return (
        f'    "{qualified(program, node.id)}" '
        f'[label="{_escaped(label_of(node))}", '
        f'shape={SHAPES[node.kind]}, style=filled, fillcolor="{FILLS[node.kind]}"];'
    )


def _edge_attributes(kind: EdgeKind) -> str:
    colour = f'color="{EDGE_COLOURS[kind]}"'
    if kind in UNLABELLED:
        return colour
    return f'{colour}, label="{kind.value}"'


def _arrow(source: str, target: str, attributes: str) -> str:
    return f'    "{source}" -> "{target}" [{attributes}];'


def _edge_line(program: str, edge: Edge) -> str:
    return _arrow(
        qualified(program, edge.source),
        qualified(program, edge.target),
        _edge_attributes(edge.kind),
    )


def _cluster(index: int, cfg: Cfg) -> tuple[str, ...]:
    """One subgraph per program: the box is what keeps two members' MAIN/0 apart."""
    return (
        f"  subgraph cluster_{index} {{",
        f'    label="{_escaped(cfg.program)}";',
        '    style="rounded";',
        '    color="#999999";',
        *(_node_line(cfg.program, node) for node in cfg.nodes),
        *(_edge_line(cfg.program, edge) for edge in cfg.edges),
        "  }",
    )


def _clusters(cfgs: Sequence[Cfg]) -> tuple[str, ...]:
    return tuple(
        line for index, cfg in enumerate(cfgs) for line in _cluster(index, cfg)
    )


def _call_arrow(call: CrossCall) -> str:
    return _arrow(
        call.source,
        call.target,
        f'color="{CALL_COLOUR}", style=dashed, label="{_escaped(call.transfer)}"',
    )


def _call_edges(cfgs: Sequence[Cfg]) -> tuple[str, ...]:
    return tuple(_call_arrow(call) for call in resolved_calls(cfgs))


def dot_of(cfgs: Sequence[Cfg]) -> str:
    return "\n".join(
        (
            "digraph srccfg {",
            "  rankdir=TB;",
            "  compound=true;",
            '  node [fontname="Helvetica", fontsize=10];',
            '  edge [fontname="Helvetica", fontsize=9];',
            *_clusters(cfgs),
            *_call_edges(cfgs),
            "}",
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a source CFG as graphviz DOT, for piping into `dot -Tsvg`."
    )
    parser.add_argument("--cfg", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(),
        help="write the DOT here instead of stdout",
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    arguments = _parser().parse_args(tuple(argv) or None)
    return _emitted(dot_of(load_cfgs(arguments.cfg)), arguments.output)


def _emitted(document: str, output: Path) -> int:
    if output == Path():
        sys.stdout.write(f"{document}\n")
        return 0
    output.write_text(f"{document}\n", encoding="utf-8")
    return 0

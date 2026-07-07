"""extract_cobol_file_graph() — static analysis: a batch COBOL program's
FILE-CONTROL / OPEN-mode file access as PROGRAM -> COBOL_FILE edges, using
the same ProLeap ASG jackal.cobol_step already parses for execution (see
_file_control there).
"""

from __future__ import annotations

import dataclasses
from typing import Any, Iterator

from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.cobol_statements import OpenStatement
from interpreter.cobol.file_enums import OpenMode
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind

_OPEN_MODE_TO_EDGE_KIND: dict[OpenMode, EdgeKind] = {
    OpenMode.INPUT: EdgeKind.READS,
    OpenMode.OUTPUT: EdgeKind.WRITES,
    OpenMode.IO: EdgeKind.UPDATES,
    OpenMode.EXTEND: EdgeKind.WRITES,
}


def _walk(stmt: Any) -> Iterator[Any]:
    """Yield stmt and every statement nested inside it (THEN/ELSE branches,
    PERFORM/EVALUATE bodies, AT END handlers, ...), found generically by
    walking the statement dataclass's own fields rather than hand-enumerating
    every nesting point — new statement types need no changes here."""
    yield stmt
    for f in dataclasses.fields(stmt):
        value = getattr(stmt, f.name)
        if isinstance(value, list):
            for item in value:
                if dataclasses.is_dataclass(item):
                    yield from _walk(item)
        elif dataclasses.is_dataclass(value):
            yield from _walk(value)


def _all_statements(asg: Any) -> Iterator[Any]:
    for stmt in asg.statements:
        yield from _walk(stmt)
    for para in asg.paragraphs:
        for stmt in para.statements:
            yield from _walk(stmt)
    for section in asg.sections:
        for stmt in section.statements:
            yield from _walk(stmt)
        for para in section.paragraphs:
            for stmt in para.statements:
                yield from _walk(stmt)


def extract_cobol_file_graph(
    source: bytes, parser: ProLeapCobolParser
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Parse a batch COBOL program and return PROGRAM -> COBOL_FILE edges for
    every file it OPENs.

    A COBOL_FILE node's id is the FILE-CONTROL entry's ASSIGN TO name (the DD
    name), not the COBOL-internal SELECT name — the same identity a JCL
    step's DD statement uses (see jackal.jcl_graph's STEP -> DATASET
    attrs["ddname"]), so a program's file access and a job's dataset access
    line up on a shared key even though this pass never sees any JCL.

    Edge kind is derived from OPEN mode: INPUT -> READS, OUTPUT -> WRITES,
    I-O -> UPDATES, EXTEND -> WRITES (attrs["mode"] = "EXTEND" to distinguish
    an append-open from a plain OUTPUT one). A SELECT with no ASSIGN TO, or
    an OPEN naming a file with no matching SELECT, contributes no edge — this
    pass only knows what FILE-CONTROL and OPEN both agree on.
    """
    asg = parser.parse(source)
    program_id = asg.program_id.upper()

    select_to_dd = {
        entry.file_name.upper(): entry.assign_to.upper()
        for entry in asg.file_control
        if entry.assign_to
    }

    nodes: dict[tuple[NodeKind, str], GraphNode] = {
        (NodeKind.PROGRAM, program_id): GraphNode(id=program_id, kind=NodeKind.PROGRAM)
    }
    edges: list[GraphEdge] = []

    for stmt in _all_statements(asg):
        if not isinstance(stmt, OpenStatement):
            continue
        for mode, file_names in stmt.mode_groups:
            edge_kind = _OPEN_MODE_TO_EDGE_KIND[mode]
            for file_name in file_names:
                dd_name = select_to_dd.get(file_name.upper())
                if not dd_name:
                    continue
                nodes.setdefault(
                    (NodeKind.COBOL_FILE, dd_name),
                    GraphNode(id=dd_name, kind=NodeKind.COBOL_FILE),
                )
                attrs = {"select_name": file_name.upper()}
                if mode is OpenMode.EXTEND:
                    attrs["mode"] = "EXTEND"
                edges.append(
                    GraphEdge(
                        source=program_id,
                        source_kind=NodeKind.PROGRAM,
                        target=dd_name,
                        target_kind=NodeKind.COBOL_FILE,
                        kind=edge_kind,
                        attrs=attrs,
                    )
                )

    return list(nodes.values()), edges

"""extract_cobol_file_graph() — static analysis: a batch COBOL program's
FILE-CONTROL / OPEN-mode file access as PROGRAM -> COBOL_FILE edges, using
the same ProLeap ASG jackal.cobol_step already parses for execution (see
_file_control there).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Iterator, Mapping, Sequence
from itertools import chain
from typing import TYPE_CHECKING, TypeGuard

from cobble.interpreter.cobol.asg_types import (
    CobolASG,
    CobolParagraph,
    CobolSection,
)
from cobble.interpreter.cobol.cobol_statements import OpenStatement
from cobble.interpreter.cobol.file_enums import OpenMode
from cobble.interpreter.project.graph_types import (
    AttrValue,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from cobble.corpus_index import FileLocationResolver

_OPEN_MODE_TO_EDGE_KIND: dict[OpenMode, EdgeKind] = {
    OpenMode.INPUT: EdgeKind.READS,
    OpenMode.OUTPUT: EdgeKind.WRITES,
    OpenMode.IO: EdgeKind.UPDATES,
    OpenMode.EXTEND: EdgeKind.WRITES,
}


def _is_dataclass_instance(value: object) -> TypeGuard[DataclassInstance]:
    """An instance of some dataclass — not a dataclass type itself.

    dataclasses.is_dataclass() is true of both, and the walk below only ever
    means the instances.
    """
    return dataclasses.is_dataclass(value) and not isinstance(value, type)


def _field_values(stmt: DataclassInstance) -> Iterator[object]:
    """Each of stmt's own field values, with lists flattened into their items.

    A nesting statement holds its children either directly (a PERFORM body) or
    in a list (THEN/ELSE branches, AT END handlers), and this makes the two the
    same shape so the caller need not care which it got.
    """
    return chain.from_iterable(
        value if isinstance(value, list) else (value,)
        for value in (getattr(stmt, f.name) for f in dataclasses.fields(stmt))
    )


def _walk(stmt: DataclassInstance) -> Iterator[DataclassInstance]:
    """stmt and every statement nested inside it (THEN/ELSE branches,
    PERFORM/EVALUATE bodies, AT END handlers, ...), found generically by
    walking the statement dataclass's own fields rather than hand-enumerating
    every nesting point — new statement types need no changes here."""
    return chain(
        (stmt,),
        chain.from_iterable(
            _walk(value)
            for value in _field_values(stmt)
            if _is_dataclass_instance(value)
        ),
    )


def _own_statements(
    containers: Iterable[CobolSection | CobolParagraph],
) -> Iterator[object]:
    """The statements held directly by each container, in container order."""
    return chain.from_iterable(container.statements for container in containers)


def _section_statements(section: CobolSection) -> Iterator[object]:
    """A section's own statements, then those of its paragraphs, in that order."""
    return chain(section.statements, _own_statements(section.paragraphs))


def _all_statements(asg: CobolASG) -> Iterator[DataclassInstance]:
    """Every statement in the program, nested ones included.

    The four places a statement can live, in source-ish order: bare at division
    level, in a standalone paragraph, at section level, and in a paragraph
    inside a section.
    """
    top_level = chain(
        asg.statements,
        _own_statements(asg.paragraphs),
        chain.from_iterable(_section_statements(section) for section in asg.sections),
    )
    return chain.from_iterable(
        _walk(stmt) for stmt in top_level if _is_dataclass_instance(stmt)
    )


def _select_to_dd(asg: CobolASG) -> Mapping[str, str]:
    """SELECT name -> ASSIGN TO (DD) name, for the entries that name a DD.

    A SELECT with no ASSIGN TO names nothing a JCL step could line up with, so
    it is left out here rather than checked for at every use.
    """
    return {
        entry.file_name.upper(): entry.assign_to.upper()
        for entry in asg.file_control
        if entry.assign_to
    }


def _open_statements(asg: CobolASG) -> Iterator[OpenStatement]:
    return (stmt for stmt in _all_statements(asg) if isinstance(stmt, OpenStatement))


def _mode_and_file(stmt: OpenStatement) -> Iterator[tuple[OpenMode, str]]:
    """One (mode, SELECT name) pair per file named in each mode group: OPEN
    INPUT AFILE BFILE OUTPUT CFILE is three accesses, not one."""
    return (
        (mode, file_name.upper())
        for mode, file_names in stmt.mode_groups
        for file_name in file_names
    )


def _accesses(asg: CobolASG) -> Sequence[tuple[OpenMode, str, str]]:
    """Every (mode, SELECT name, DD name) the OPENs and FILE-CONTROL agree on.

    An OPEN of a file no ASSIGN TO'd SELECT declares contributes nothing: this
    pass only knows what both halves of the program state.
    """
    select_to_dd = _select_to_dd(asg)
    return [
        (mode, select_name, select_to_dd[select_name])
        for mode, select_name in chain.from_iterable(
            _mode_and_file(stmt) for stmt in _open_statements(asg)
        )
        if select_name in select_to_dd
    ]


def _file_nodes(
    accesses: Iterable[tuple[OpenMode, str, str]], corpus_index: FileLocationResolver
) -> list[GraphNode]:
    """One COBOL_FILE node per DD name accessed.

    dict.fromkeys rather than a set: node order follows first access, which is
    the order nodes.jsonl has always had. Resolving once per unique name also
    keeps this from asking CorpusIndex the same question for every OPEN of one
    file.
    """
    dd_names = dict.fromkeys(dd_name for _mode, _select_name, dd_name in accesses)
    return [
        GraphNode(
            id=dd_name,
            kind=NodeKind.COBOL_FILE,
            location=corpus_index.resolve_file_path(NodeKind.COBOL_FILE, dd_name),
        )
        for dd_name in dd_names
    ]


def _edge_attrs(mode: OpenMode, select_name: str) -> dict[str, AttrValue]:
    """EXTEND says so because it shares an edge kind with OUTPUT: both write,
    but only one appends. The SELECT name rides along because it is how the
    program's own source names the file, even though the DD name is the id."""
    return {
        "select_name": select_name,
        **({"mode": "EXTEND"} if mode is OpenMode.EXTEND else {}),
    }


def _access_edges(
    program_id: str, accesses: Iterable[tuple[OpenMode, str, str]]
) -> list[GraphEdge]:
    return [
        GraphEdge(
            source=program_id,
            source_kind=NodeKind.PROGRAM,
            target=dd_name,
            target_kind=NodeKind.COBOL_FILE,
            kind=_OPEN_MODE_TO_EDGE_KIND[mode],
            attrs=_edge_attrs(mode, select_name),
        )
        for mode, select_name, dd_name in accesses
    ]


def extract_cobol_file_graph(
    asg: CobolASG,
    corpus_index: FileLocationResolver,
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
    program_id = asg.program_id.upper()
    accesses = _accesses(asg)
    program_node = GraphNode(
        id=program_id,
        kind=NodeKind.PROGRAM,
        location=corpus_index.resolve_file_path(NodeKind.PROGRAM, program_id),
    )
    return (
        [program_node, *_file_nodes(accesses, corpus_index)],
        _access_edges(program_id, accesses),
    )

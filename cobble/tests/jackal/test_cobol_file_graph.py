"""extract_cobol_file_graph() — a batch program's OPENs as PROGRAM -> COBOL_FILE.

The module had no tests: written here first so the pass has a guard before its
statement walk and node/edge accumulation are rewritten. Every test states a
rule from extract_cobol_file_graph's own docstring — the DD name is the key,
the OPEN mode is the edge kind, and what FILE-CONTROL and OPEN do not agree on
contributes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pytest

from cobble.corpus_index import FileLocationResolver
from cobble.file_location import FileLocation, FileLocationReason, NoFileLocation
from cobble.interpreter.cobol.asg_types import CobolASG, CobolParagraph, CobolSection
from cobble.interpreter.cobol.cobol_statements import (
    FileControlEntry,
    IfStatement,
    OpenStatement,
)
from interpreter.cobol.file_enums import OpenMode
from cobble.interpreter.project.graph_types import EdgeKind, NodeKind
from cobble.jackal.cobol_file_graph import extract_cobol_file_graph

_UNRESOLVED = NoFileLocation(FileLocationReason.UNRESOLVED)
_NO_LOCATIONS: Mapping[tuple[NodeKind, str], FileLocation] = MappingProxyType({})


@dataclass(frozen=True)
class _CorpusIndexStub(FileLocationResolver):
    """Answers the resolver's one question from a table, nothing else."""

    locations: Mapping[tuple[NodeKind, str], FileLocation] = _NO_LOCATIONS

    def resolve_file_path(self, kind: NodeKind, node_id: str) -> FileLocation:
        return self.locations.get((kind, node_id), _UNRESOLVED)


def _asg_opening(
    *mode_groups: tuple[OpenMode, list[str]],
    file_control: tuple[FileControlEntry, ...] = (
        FileControlEntry(file_name="ACCTFILE", assign_to="WORK1"),
    ),
) -> CobolASG:
    """A one-statement program whose OPEN names files from `file_control`."""
    return CobolASG(
        program_id="PROGONE",
        file_control=list(file_control),
        statements=[OpenStatement(mode_groups=list(mode_groups))],
    )


def test_an_open_becomes_an_edge_to_the_dd_name_the_select_assigns_to() -> None:
    """The COBOL_FILE id is the ASSIGN TO name, not the SELECT name — that is
    what makes it the same key a JCL step's DD statement uses."""
    _nodes, edges = extract_cobol_file_graph(
        _asg_opening((OpenMode.INPUT, ["ACCTFILE"])), _CorpusIndexStub()
    )

    assert [(e.source, e.source_kind, e.target, e.target_kind) for e in edges] == [
        ("PROGONE", NodeKind.PROGRAM, "WORK1", NodeKind.COBOL_FILE)
    ]


def test_the_select_name_is_kept_on_the_edge() -> None:
    """The DD name is the identity, but the SELECT name is how the program's own
    source refers to the file, so it stays recoverable."""
    _nodes, edges = extract_cobol_file_graph(
        _asg_opening((OpenMode.INPUT, ["ACCTFILE"])), _CorpusIndexStub()
    )

    assert edges[0].attrs == {"select_name": "ACCTFILE"}


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (OpenMode.INPUT, EdgeKind.READS),
        (OpenMode.OUTPUT, EdgeKind.WRITES),
        (OpenMode.IO, EdgeKind.UPDATES),
        (OpenMode.EXTEND, EdgeKind.WRITES),
    ],
)
def test_the_open_mode_decides_the_edge_kind(
    mode: OpenMode, expected: EdgeKind
) -> None:
    _nodes, edges = extract_cobol_file_graph(
        _asg_opening((mode, ["ACCTFILE"])), _CorpusIndexStub()
    )

    assert edges[0].kind == expected


def test_an_extend_open_says_so_since_it_shares_writes_with_output() -> None:
    _nodes, edges = extract_cobol_file_graph(
        _asg_opening((OpenMode.EXTEND, ["ACCTFILE"])), _CorpusIndexStub()
    )

    assert edges[0].attrs == {"select_name": "ACCTFILE", "mode": "EXTEND"}


def test_a_select_with_no_assign_to_contributes_no_edge() -> None:
    """This pass only knows what FILE-CONTROL and OPEN both agree on, and a
    SELECT with no ASSIGN TO names no DD for a job to match."""
    _nodes, edges = extract_cobol_file_graph(
        _asg_opening(
            (OpenMode.INPUT, ["ACCTFILE"]),
            file_control=(FileControlEntry(file_name="ACCTFILE", assign_to=""),),
        ),
        _CorpusIndexStub(),
    )

    assert edges == []


def test_an_open_of_a_file_with_no_select_contributes_no_edge() -> None:
    _nodes, edges = extract_cobol_file_graph(
        _asg_opening((OpenMode.INPUT, ["NOSUCHFILE"])), _CorpusIndexStub()
    )

    assert edges == []


def test_names_are_matched_and_emitted_uppercased() -> None:
    """Every extractor uppercases at extraction time (see graph_types), so a
    lowercase source has to line up with an uppercase SELECT."""
    _nodes, edges = extract_cobol_file_graph(
        _asg_opening(
            (OpenMode.INPUT, ["acctfile"]),
            file_control=(FileControlEntry(file_name="acctfile", assign_to="work1"),),
        ),
        _CorpusIndexStub(),
    )

    assert (edges[0].source, edges[0].target, edges[0].attrs["select_name"]) == (
        "PROGONE",
        "WORK1",
        "ACCTFILE",
    )


def test_the_program_node_carries_the_location_the_corpus_index_resolved() -> None:
    index = _CorpusIndexStub(
        MappingProxyType({(NodeKind.PROGRAM, "PROGONE"): Path("cbl/PROGONE.cbl")})
    )

    nodes, _edges = extract_cobol_file_graph(_asg_opening(), index)

    assert [(n.kind, n.id, n.location) for n in nodes] == [
        (NodeKind.PROGRAM, "PROGONE", Path("cbl/PROGONE.cbl"))
    ]


def test_a_cobol_file_node_carries_its_own_resolved_location() -> None:
    index = _CorpusIndexStub(
        MappingProxyType({(NodeKind.COBOL_FILE, "WORK1"): Path("cbl/PROGONE.cbl")})
    )

    nodes, _edges = extract_cobol_file_graph(
        _asg_opening((OpenMode.INPUT, ["ACCTFILE"])), index
    )

    assert {n.id: n.location for n in nodes} == {
        "PROGONE": _UNRESOLVED,
        "WORK1": Path("cbl/PROGONE.cbl"),
    }


def test_a_file_opened_twice_yields_one_node_and_two_edges() -> None:
    """Two OPENs of one file are two accesses but one file — and the node keeps
    the first sighting's location, as everywhere else in the graph."""
    nodes, edges = extract_cobol_file_graph(
        _asg_opening((OpenMode.INPUT, ["ACCTFILE"]), (OpenMode.OUTPUT, ["ACCTFILE"])),
        _CorpusIndexStub(),
    )

    assert [n.id for n in nodes] == ["PROGONE", "WORK1"]
    assert [e.kind for e in edges] == [EdgeKind.READS, EdgeKind.WRITES]


def test_one_mode_group_naming_several_files_yields_an_edge_each() -> None:
    _nodes, edges = extract_cobol_file_graph(
        _asg_opening(
            (OpenMode.INPUT, ["ACCTFILE", "CARDFILE"]),
            file_control=(
                FileControlEntry(file_name="ACCTFILE", assign_to="WORK1"),
                FileControlEntry(file_name="CARDFILE", assign_to="WORK2"),
            ),
        ),
        _CorpusIndexStub(),
    )

    assert [e.target for e in edges] == ["WORK1", "WORK2"]


def test_an_open_nested_inside_an_if_is_found() -> None:
    """The walk is generic over the statement dataclasses' own fields, so a new
    nesting statement needs no change — this pins that for IF/ELSE."""
    asg = CobolASG(
        program_id="PROGONE",
        file_control=[FileControlEntry(file_name="ACCTFILE", assign_to="WORK1")],
        statements=[
            IfStatement(
                condition={},
                children=[OpenStatement(mode_groups=[(OpenMode.INPUT, ["ACCTFILE"])])],
                else_children=[
                    OpenStatement(mode_groups=[(OpenMode.OUTPUT, ["ACCTFILE"])])
                ],
            )
        ],
    )

    _nodes, edges = extract_cobol_file_graph(asg, _CorpusIndexStub())

    assert [e.kind for e in edges] == [EdgeKind.READS, EdgeKind.WRITES]


def test_opens_are_found_in_every_place_a_statement_can_live() -> None:
    """Bare division-level statements, standalone paragraphs, section-level
    statements, and paragraphs inside sections — all four containers."""
    opens = [
        OpenStatement(mode_groups=[(OpenMode.INPUT, [name])])
        for name in ("BAREFILE", "PARAFILE", "SECTFILE", "SUBPFILE")
    ]
    asg = CobolASG(
        program_id="PROGONE",
        file_control=[
            FileControlEntry(file_name=name, assign_to=f"WORK{i}")
            for i, name in enumerate(("BAREFILE", "PARAFILE", "SECTFILE", "SUBPFILE"))
        ],
        statements=[opens[0]],
        paragraphs=[CobolParagraph(name="PARAONE", statements=[opens[1]])],
        sections=[
            CobolSection(
                name="SECTONE",
                statements=[opens[2]],
                paragraphs=[CobolParagraph(name="PARATWO", statements=[opens[3]])],
            )
        ],
    )

    _nodes, edges = extract_cobol_file_graph(asg, _CorpusIndexStub())

    assert sorted(e.target for e in edges) == ["WORK0", "WORK1", "WORK2", "WORK3"]


def test_a_program_that_opens_nothing_still_yields_its_own_node() -> None:
    nodes, edges = extract_cobol_file_graph(_asg_opening(), _CorpusIndexStub())

    assert ([n.id for n in nodes], edges) == (["PROGONE"], [])

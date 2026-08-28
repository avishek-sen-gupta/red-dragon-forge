"""The CICS flow pass: what it emits, and what it says about the programs it read.

A pass over thousands of members is only as useful as its account of itself: which
programs it got through, which it could not read, and -- while it runs -- where it
currently is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from cobble.cics.flow_map import extract_transaction_flow_graph
from cobble.interpreter.project.graph_types import GraphEdge, GraphNode

_CSD = """
DEFINE TRANSACTION(AAAA) GROUP(GRP) PROGRAM(PROGONE)
DEFINE TRANSACTION(BBBB) GROUP(GRP) PROGRAM(PROGTWO)
"""

_SOURCES = {"PROGONE": b"PROGONE SOURCE", "PROGTWO": b"PROGTWO SOURCE"}


class _NoFilePaths:
    """The one thing the flow pass asks of the corpus index."""

    def resolve_file_path(self, kind, node_id):
        return None


class _CollectingSink:
    def __init__(self) -> None:
        self.nodes: tuple = ()
        self.edges: tuple = ()

    def add_node(self, node: GraphNode) -> None:
        self.nodes = (*self.nodes, node)

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges = (*self.edges, edge)


@dataclass(frozen=True)
class _EmptyAsg:
    """An ASG with nothing in it: enough for the walk, which finds no EXEC CICS."""

    data_fields: tuple = ()


class _Parser:
    """Parses to an empty ASG, except for the source it is told to refuse -- what a
    member carrying a construct the bridge rejects does. Records what it was given."""

    def __init__(self, refuses: bytes = b"") -> None:
        self.refuses = refuses
        self.parsed: tuple[bytes, ...] = ()

    def parse(self, source: bytes) -> _EmptyAsg:
        self.parsed = (*self.parsed, source)
        if self.refuses and self.refuses in source:
            raise ValueError("bridge said no")
        return _EmptyAsg()


def _run(parser: _Parser, sink: _CollectingSink, csd: str = _CSD, sources=_SOURCES):
    return extract_transaction_flow_graph(
        csd,
        {},
        sources,
        parser=parser,
        sink=sink,
        corpus_index=_NoFilePaths(),
    )


def test_the_pass_reports_how_many_programs_it_read() -> None:
    """The stage's other counts are its inputs -- transactions defined, sources
    found. Only the pass itself knows how many it got through."""
    extraction = _run(_Parser(), _CollectingSink())

    assert (extraction.programs_read, extraction.failures) == (2, ())


def test_a_program_the_parser_refuses_is_reported_and_the_rest_still_stream() -> None:
    """One unreadable member must not cost the run the other members' edges, and
    must not vanish either: it comes back so the run can say what is missing."""
    parser = _Parser(refuses=b"PROGONE")
    sink = _CollectingSink()

    extraction = _run(parser, sink)

    assert extraction.programs_read == 1
    assert len(extraction.failures) == 1
    assert extraction.failures[0].startswith("CICS program PROGONE:")
    assert parser.parsed == (b"PROGONE SOURCE", b"PROGTWO SOURCE")
    assert [(edge.source, edge.target) for edge in sink.edges] == [
        ("AAAA", "PROGONE"),
        ("BBBB", "PROGTWO"),
    ]


def test_two_transactions_naming_one_program_read_it_once() -> None:
    """Reading a program is a bridge subprocess and an ASG; a CSD that names it
    twice must not pay for it twice."""
    parser = _Parser()

    extraction = _run(
        parser,
        _CollectingSink(),
        csd=(
            "DEFINE TRANSACTION(AAAA) GROUP(GRP) PROGRAM(PROGONE)\n"
            "DEFINE TRANSACTION(BBBB) GROUP(GRP) PROGRAM(PROGONE)\n"
        ),
        sources={"PROGONE": b"PROGONE SOURCE"},
    )

    assert (extraction.programs_read, len(parser.parsed)) == (1, 1)


def test_a_program_with_no_source_is_not_read() -> None:
    """The stage reports the missing source itself, before this pass runs; the pass
    has nothing to parse and must not invent a failure for it."""
    parser = _Parser()

    extraction = _run(parser, _CollectingSink(), sources={"PROGONE": b"PROGONE SOURCE"})

    assert (extraction.programs_read, extraction.failures, len(parser.parsed)) == (
        1,
        (),
        1,
    )


def test_each_program_is_named_before_it_is_read(caplog) -> None:
    """The bar over this loop counts; it does not say which member. On a corpus
    where one member takes minutes, the name is the only thing that tells a
    watching run from a stuck one."""
    caplog.set_level(logging.DEBUG)

    _run(_Parser(), _CollectingSink())

    assert [message for message in caplog.messages if "PROGTWO" in message] == [
        "CICS flow: reading PROGTWO"
    ]

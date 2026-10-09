"""The CICS flow pass: what it emits, and what it says about the programs it read.

A pass over thousands of members is only as useful as its account of itself: which
programs it got through, which it could not read, and -- while it runs -- where it
currently is.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from pathlib import Path

from cobble.cics.flow_map import extract_transaction_flow_graph
from cobble.corpus_index import CorpusIndex
from cobble.knowledge_graph.graph_types import GraphEdge, GraphNode
from cobble.parsing.asg_cache import cache_path, cached_asg
from cobol_asg.asg_types import CobolASG

_CSD = """
DEFINE TRANSACTION(AAAA) GROUP(GRP) PROGRAM(PROGONE)
DEFINE TRANSACTION(BBBB) GROUP(GRP) PROGRAM(PROGTWO)
"""

_MEMBERS = {"PROGONE": Path("PROGONE.cbl"), "PROGTWO": Path("PROGTWO.cbl")}


class _CollectingSink:
    def __init__(self) -> None:
        self.nodes: tuple = ()
        self.edges: tuple = ()

    def add_node(self, node: GraphNode) -> None:
        self.nodes = (*self.nodes, node)

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges = (*self.edges, edge)


class _Reader:
    """Reads an empty ASG for each member, except the one it is told to refuse --
    what a member missing from the cache does. Records what it was asked for."""

    def __init__(self, refuses: str = "") -> None:
        self.refuses = refuses
        self.read: tuple[Path, ...] = ()

    def __call__(self, member: Path) -> CobolASG:
        self.read = (*self.read, member)
        if self.refuses and member.stem == self.refuses:
            raise FileNotFoundError("no cached ASG")
        return CobolASG()


def _run(reader: _Reader, sink: _CollectingSink, csd: str = _CSD, members=_MEMBERS):
    return extract_transaction_flow_graph(
        csd,
        {},
        members,
        read_asg=reader,
        sink=sink,
        corpus_index=CorpusIndex(),
        max_workers=1,
    )


def test_the_pass_reports_how_many_programs_it_read() -> None:
    """The stage's other counts are its inputs -- transactions defined, sources
    found. Only the pass itself knows how many it got through."""
    extraction = _run(_Reader(), _CollectingSink())

    assert (extraction.programs_read, extraction.failures) == (2, ())


def test_a_program_whose_asg_cannot_be_read_is_reported_and_the_rest_still_stream() -> (
    None
):
    """One unreadable member must not cost the run the other members' edges, and
    must not vanish either: it comes back so the run can say what is missing."""
    reader = _Reader(refuses="PROGONE")
    sink = _CollectingSink()

    extraction = _run(reader, sink)

    assert extraction.programs_read == 1
    assert extraction.failures == ("CICS program PROGONE: no cached ASG",)
    assert reader.read == (Path("PROGONE.cbl"), Path("PROGTWO.cbl"))
    assert [(edge.source, edge.target) for edge in sink.edges] == [
        ("AAAA", "PROGONE"),
        ("BBBB", "PROGTWO"),
    ]


def test_two_transactions_naming_one_program_read_it_once() -> None:
    """Reading a program builds its ASG; a CSD that names it twice must not pay for
    it twice."""
    reader = _Reader()

    extraction = _run(
        reader,
        _CollectingSink(),
        csd=(
            "DEFINE TRANSACTION(AAAA) GROUP(GRP) PROGRAM(PROGONE)\n"
            "DEFINE TRANSACTION(BBBB) GROUP(GRP) PROGRAM(PROGONE)\n"
        ),
        members={"PROGONE": Path("PROGONE.cbl")},
    )

    assert (extraction.programs_read, reader.read) == (1, (Path("PROGONE.cbl"),))


def test_a_program_with_no_source_is_not_read() -> None:
    """The stage reports the missing source itself, before this pass runs; the pass
    has nothing to read and must not invent a failure for it."""
    reader = _Reader()

    extraction = _run(
        reader, _CollectingSink(), members={"PROGONE": Path("PROGONE.cbl")}
    )

    assert (extraction.programs_read, extraction.failures, reader.read) == (
        1,
        (),
        (Path("PROGONE.cbl"),),
    )


def test_each_program_is_named_before_it_is_read(caplog) -> None:
    """The bar over this loop counts; it does not say which member. On a corpus
    where one member takes minutes, the name is the only thing that tells a
    watching run from a stuck one."""
    caplog.set_level(logging.DEBUG)

    _run(_Reader(), _CollectingSink())

    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == "cobble.cics.verb_source_asg"
        and "PROGTWO" in record.getMessage()
    ] == ["CICS flow: reading PROGTWO"]


def test_a_program_read_from_the_parse_cache_yields_its_cics_verb_edges(
    tmp_path: Path,
) -> None:
    """The cache stores EXEC CICS already parsed -- a verb and its options, no source
    text -- and only the serialized form's dialect parser reads that back. Read with
    the bridge's, every verb comes back empty and every edge from it is lost."""
    source = tmp_path / "PROGONE.cbl"
    cached = cache_path(tmp_path, source)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(
        json.dumps(
            {
                "program_id": "PROGONE",
                "paragraphs": [
                    {
                        "name": "MAIN",
                        "statements": [
                            {
                                "type": "EXEC_CICS",
                                "verb": "XCTL",
                                "options": {
                                    "PROGRAM": {"text": "PROGTWO", "is_literal": True}
                                },
                            }
                        ],
                    }
                ],
            }
        )
    )
    sink = _CollectingSink()

    extraction = extract_transaction_flow_graph(
        "DEFINE TRANSACTION(AAAA) GROUP(GRP) PROGRAM(PROGONE)\n",
        {},
        {"PROGONE": source},
        read_asg=partial(cached_asg, tmp_path),
        sink=sink,
        corpus_index=CorpusIndex(),
        max_workers=1,
    )

    assert (extraction.programs_read, extraction.failures) == (1, ())
    assert [(edge.source, edge.target, edge.kind.value) for edge in sink.edges] == [
        ("AAAA", "PROGONE", "STARTS"),
        ("PROGONE", "PROGTWO", "XCTL"),
    ]


def _cached_xctl(asg_dir: Path, program: str, target: str) -> Path:
    source = asg_dir / f"{program}.cbl"
    cached = cache_path(asg_dir, source)
    cached.parent.mkdir(parents=True, exist_ok=True)
    statement = {
        "type": "EXEC_CICS",
        "verb": "XCTL",
        "options": {"PROGRAM": {"text": target, "is_literal": True}},
    }
    cached.write_text(
        json.dumps(
            {
                "program_id": program,
                "paragraphs": [{"name": "MAIN", "statements": [statement]}],
            }
        )
    )
    return source


def test_programs_read_across_worker_processes_stream_as_one_process_reads_them(
    tmp_path: Path,
) -> None:
    """Workers finish in any order; the graph must not. Each program's edges are
    written in CSD order whatever the worker count, so the graph file is the one a
    serial run writes."""
    members = {
        program: _cached_xctl(tmp_path, program, target)
        for program, target in (
            ("PROGA", "PROGX"),
            ("PROGB", "PROGY"),
            ("PROGC", "PROGZ"),
        )
    }
    csd = "".join(
        f"DEFINE TRANSACTION(T{n}) GROUP(GRP) PROGRAM({program})\n"
        for n, program in enumerate(members)
    )

    def edges_with(workers: int) -> tuple[tuple[str, str, str], ...]:
        sink = _CollectingSink()
        extract_transaction_flow_graph(
            csd,
            {},
            members,
            read_asg=partial(cached_asg, tmp_path),
            sink=sink,
            corpus_index=CorpusIndex(),
            max_workers=workers,
        )
        return tuple((e.source, e.target, e.kind.value) for e in sink.edges)

    assert (
        edges_with(1)
        == edges_with(3)
        == (
            ("T0", "PROGA", "STARTS"),
            ("T1", "PROGB", "STARTS"),
            ("T2", "PROGC", "STARTS"),
            ("PROGA", "PROGX", "XCTL"),
            ("PROGB", "PROGY", "XCTL"),
            ("PROGC", "PROGZ", "XCTL"),
        )
    )

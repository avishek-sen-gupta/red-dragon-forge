"""A program's neighbourhood: its own nodes, everything one edge from them, and every reader and writer of a dataset slot it reaches."""

from __future__ import annotations

from tests.experimental.partition.graphs import LINKED

from cobble.experimental.partition.graph_index import graph_index
from cobble.experimental.partition.neighbourhood import neighbourhood


def test_a_program_s_neighbourhood_is_its_nodes_their_neighbours_and_every_reader_and_writer_of_a_slot_it_reaches() -> (
    None
):
    index = graph_index(LINKED)
    hoods = {name: neighbourhood(index, name) for name in "PQS"}

    assert tuple(index.programs) == ("P", "Q", "S")
    assert {name: tuple(n.id for n in hood.nodes) for name, hood in hoods.items()} == {
        "P": (
            "DS[0:4]",
            *(f"P:REC.{name}" for name in "ABCDEFGH"),
            "P|sink|MAP:M",
            "Q:REC.A",
        ),
        "Q": (
            "DS[0:4]",
            "P:REC.A",
            *(f"Q:REC.{name}" for name in "ABCDEF"),
            "S:REC.A",
        ),
        "S": ("Q:REC.B", "S:REC.A", "S:REC.B"),
    }
    assert [(e.source, e.target) for e in hoods["P"].edges] == [
        ("P:REC.A", "P:REC.B"),
        ("P:REC.B", "P:REC.C"),
        ("P:REC.C", "P:REC.D"),
        ("P:REC.E", "P:REC.F"),
        ("P:REC.D", "P|sink|MAP:M"),
        ("P:REC.E", "P|sink|MAP:M"),
        ("P:REC.G", "P|sink|MAP:M"),
        ("P:REC.A", "DS[0:4]"),
        ("DS[0:4]", "Q:REC.A"),
    ]
    assert [(e.source, e.target) for e in hoods["S"].edges] == [
        ("S:REC.A", "S:REC.B"),
        ("Q:REC.B", "S:REC.A"),
    ]

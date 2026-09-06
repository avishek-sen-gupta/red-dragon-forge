"""Convergence, PERFORM re-entry, and the coverage counters.

Termination is not the property under test -- coverage is. The 3ao post-mortem
found an acceptance suite passing while its walk reached 18% of nodes, because
nothing measured reach.
"""

from __future__ import annotations

import pytest
from cobble.dataflow.fields import fixpoint
from cobble.dataflow.fields.fixpoint import analyse, analysed
from cobble.dataflow.layout import UnsizeableFieldError


@pytest.fixture
def fields(field):
    return [
        field(
            1,
            "REC",
            children=[
                field(5, "WS-A", "X(4)", offset=0),
                field(5, "WS-B", "X(4)", offset=4),
                field(5, "WS-C", "X(4)", offset=8),
            ],
        )
    ]


@pytest.fixture
def flow_of(program_of, index_of, fields):
    def build(paragraphs: list[dict]):
        asg = program_of([], paragraphs=paragraphs, data_fields=fields)
        return analyse(asg, index_of(asg))

    return build


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _pairs(flow) -> set[tuple[str, str]]:
    return {
        (edge.source.origin or edge.source.extent.field_name, edge.target.field_name)
        for edge in flow.edges
    }


def test_a_chain_within_one_paragraph_yields_both_edges(flow_of):
    flow = flow_of(
        [{"name": "MAIN", "statements": [_move("WS-A", "WS-B"), _move("WS-B", "WS-C")]}]
    )
    assert {("WS-A", "WS-B"), ("WS-B", "WS-C")} <= _pairs(flow)


def test_provenance_crosses_a_paragraph_boundary_by_fallthrough(flow_of):
    flow = flow_of(
        [
            {"name": "MAIN", "statements": [_move("WS-A", "WS-B")]},
            {"name": "NEXT-PARA", "statements": [_move("WS-B", "WS-C")]},
        ]
    )
    assert ("WS-B", "WS-C") in _pairs(flow)


def test_a_loop_converges_and_does_not_hang(flow_of):
    flow = flow_of(
        [
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "PERFORM",
                        "operands": ["LOOP-PARA"],
                        "perform_type": "UNTIL",
                        "until": {"text": "WS-A = SPACES"},
                    }
                ],
            },
            {"name": "LOOP-PARA", "statements": [_move("WS-A", "WS-B")]},
        ]
    )
    assert ("WS-A", "WS-B") in _pairs(flow)


def test_a_loop_carried_definition_reaches_the_read_above_it(flow_of):
    """The read comes first in the text; the write that feeds it comes after.

    Regression: deriving edges by diffing the state around a statement loses this
    entirely. On the second visit WS-B's definition is already in the in-state, so
    the diff is empty and the edge disappears without a trace.
    """
    flow = flow_of(
        [
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "PERFORM",
                        "operands": ["LOOP-PARA"],
                        "perform_type": "UNTIL",
                        "until": {"text": "WS-A = SPACES"},
                    }
                ],
            },
            {
                "name": "LOOP-PARA",
                "statements": [_move("WS-B", "WS-C"), _move("WS-A", "WS-B")],
            },
        ]
    )
    reads = tuple(edge for edge in flow.edges if edge.target.field_name == "WS-C")
    assert {edge.source.node for edge in reads} == {"LOOP-PARA/1"}


def test_a_paragraph_performed_from_two_sites_is_not_analysed_per_call_path(flow_of):
    """Keying on node entry state is what stops the ujr call-path blowup."""
    flow = flow_of(
        [
            {
                "name": "MAIN",
                "statements": [
                    {"type": "PERFORM", "operands": ["SHARED"]},
                    {"type": "PERFORM", "operands": ["SHARED"]},
                ],
            },
            {"name": "SHARED", "statements": [_move("WS-A", "WS-B")]},
        ]
    )
    assert ("WS-A", "WS-B") in _pairs(flow)
    assert flow.dequeues <= 4 * flow.nodes


def test_a_read_after_a_branch_carries_both_arms_as_definers(flow_of):
    """A node reached down two paths is one node joined, and the join is visible.

    The merge reads WS-C, which either arm may have written, so it yields one
    edge per defining node -- not one edge per path through the program, and not
    a single edge that has forgotten where the value came from.
    """
    flow = flow_of(
        [
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "IF",
                        "condition": {"text": "WS-A = SPACES"},
                        "children": [_move("WS-A", "WS-C")],
                        "else_children": [_move("WS-B", "WS-C")],
                    },
                    _move("WS-C", "WS-A"),
                ],
            }
        ]
    )
    assert {("WS-A", "WS-C"), ("WS-B", "WS-C"), ("WS-C", "WS-A")} <= _pairs(flow)
    merged = tuple(edge for edge in flow.edges if edge.node == "MAIN/1")
    assert len(merged) == 2
    assert len({edge.source.node for edge in merged}) == 2


def test_every_resolvable_write_is_covered_in_a_program_with_no_unknown_names(flow_of):
    flow = flow_of(
        [{"name": "MAIN", "statements": [_move("WS-A", "WS-B"), _move("WS-B", "WS-C")]}]
    )
    assert flow.writes > 0
    assert flow.covered == flow.writes


def test_a_write_to_an_undeclared_name_counts_against_coverage(flow_of):
    """The denominator comes from the source, so an unreached write is visible."""
    flow = flow_of(
        [
            {
                "name": "MAIN",
                "statements": [_move("WS-A", "WS-B"), _move("WS-A", "WS-GONE")],
            }
        ]
    )
    assert flow.writes == 2
    assert flow.covered == 1


def test_an_unhandled_statement_class_is_counted_not_ignored(flow_of):
    flow = flow_of(
        [
            {
                "name": "MAIN",
                "statements": [
                    _move("WS-A", "WS-B"),
                    {"type": "DISPLAY", "operands": []},
                ],
            }
        ]
    )
    assert flow.unhandled == 1


def test_reaching_the_dequeue_cap_records_a_reason(flow_of, monkeypatch):
    """The cap is a defect backstop, so a truncated answer must never look complete.

    Termination rests on monotone join over a finite lattice, not on the cap, so a
    program that trips it is beyond what this pass can claim -- and the factor is
    forced to zero here because no correct program reaches it.
    """
    monkeypatch.setattr(fixpoint, "ITERATION_FACTOR", 0)
    flow = flow_of([{"name": "MAIN", "statements": [_move("WS-A", "WS-B")]}])
    assert "cap" in flow.skipped
    assert flow.writes == 1


def test_an_unsizeable_program_is_recorded_not_dropped(program_of, field, monkeypatch):
    """layout.UnsizeableFieldError must surface as a skip with a reason.

    Building the index is where it raises, so the guard lives in analysed(), not
    in analyse() -- which is why the two entry points exist. The raise is forced
    here because no program that parses can reach it: layout only refuses a COMP
    field of more than 31 digits, and the PIC parser rejects more than 18 first.
    The guard stays because layout, not its callers, owns that limit.
    """

    def refuse(_asg):
        raise UnsizeableFieldError("COMP with 40 digits exceeds the 31-digit maximum")

    monkeypatch.setattr(fixpoint, "program_records", refuse)
    asg = program_of(
        [_move("WS-A", "WS-B")],
        data_fields=[field(1, "REC", children=[field(5, "WS-A", "X(4)", offset=0)])],
    )
    flow, index = analysed(asg)
    assert flow.skipped
    assert flow.edges == ()
    assert index.ordered == ()

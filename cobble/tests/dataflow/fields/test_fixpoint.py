"""Convergence, PERFORM re-entry, and the coverage counters.

Termination is not the property under test -- coverage is. The 3ao post-mortem
found an acceptance suite passing while its walk reached 18% of nodes, because
nothing measured reach.
"""

from __future__ import annotations

import logging
import time

import pytest
from cobble.dataflow.fixpoint import fixpoint
from cobble.dataflow.fixpoint.fixpoint import analyse, analysed
from cobble.dataflow.fixpoint.options import DEFAULT_OPTIONS, AnalysisOptions
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
    def build(paragraphs: list[dict], options: AnalysisOptions = DEFAULT_OPTIONS):
        asg = program_of([], paragraphs=paragraphs, data_fields=fields)
        return analyse(asg, index_of(asg), options)

    return build


@pytest.fixture
def loop_paragraphs():
    """A loop writing WS-B, and a read of WS-B after the loop.

    The shape a sweep budget has to be measured against, and the one that
    corrects an assumption: the read after the loop does NOT need the back edge.
    One sweep carries the body's write to it, because reverse postorder puts the
    body ahead of the loop's exit.
    """
    return [
        {
            "name": "MAIN",
            "statements": [
                {
                    "type": "PERFORM",
                    "operands": ["LOOP-PARA"],
                    "perform_type": "UNTIL",
                    "until": {"text": "WS-A = SPACES"},
                },
                _move("WS-B", "WS-C"),
            ],
        },
        {
            "name": "LOOP-PARA",
            "statements": [_move("WS-A", "WS-B")],
        },
    ]


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _pairs(flow) -> set[tuple[str, str]]:
    return {
        (
            edge.source.field_name if edge.origin.is_storage else edge.origin.text(),
            edge.target.field_name,
        )
        for edge in flow.edges
    }


def _definers(flow, name: str) -> set[str]:
    """Who could have written what the reads of ``name`` consumed.

    The join the artefact's consumers make: an edge says which node moved the
    bytes, and the defs table keyed by that node and the source range says which
    nodes could have put them there.
    """
    reads = {
        (edge.node, edge.source)
        for edge in flow.edges
        if edge.target.field_name == name
    }
    return {
        definer
        for entry in flow.defs
        if (entry.node, entry.extent) in reads
        for definer in entry.definers
    }


def _if(condition: str, then: list[dict], otherwise: list[dict]) -> dict:
    return {
        "type": "IF",
        "condition": {
            "not": False,
            "relation": {
                "left": {"kind": "ref", "name": condition},
                "op": "==",
                "right": {"kind": "lit", "value": "'Y'"},
            },
        },
        "children": then,
        "else_children": otherwise,
    }


def test_a_read_of_a_field_written_on_four_paths_is_one_edge_and_four_definers(
    flow_of,
):
    """Four arms wrote WS-A; the read of it moved one range, so it is one flow.

    The definers are the four arms, and they belong to the defs table because
    they say nothing about the bytes that moved -- the same flow four times over.
    Order matters as much as content: the sources at an extent are a frozenset
    and so are the definers of one, so an unsorted walk writes the same facts in
    a different order on every process, and an artefact that differs between
    identical runs cannot be diffed across a corpus. Four arms rather than two so
    the assertion is not one coin flip.
    """
    flow = flow_of(
        [
            {
                "name": "MAIN",
                "statements": [
                    _if(
                        "WS-C",
                        [_if("WS-C", [_move("WS-B", "WS-A")], [_move("WS-C", "WS-A")])],
                        [_if("WS-C", [_move("'X'", "WS-A")], [_move("'Y'", "WS-A")])],
                    ),
                    _move("WS-A", "WS-B"),
                ],
            }
        ]
    )
    read = tuple(edge for edge in flow.edges if edge.target.field_name == "WS-B")

    assert len(read) == 1
    assert len(_definers(flow, "WS-B")) == 4
    assert all(list(entry.definers) == sorted(entry.definers) for entry in flow.defs)
    for node in {edge.node for edge in flow.edges}:
        at_node = [edge for edge in flow.edges if edge.node == node]
        assert at_node == sorted(at_node, key=repr)


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
    assert _definers(flow, "WS-C") == {"LOOP-PARA/1"}


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

    The merge reads WS-C, which either arm may have written. One flow, because
    one range moved; both arms named, because the defs table is where a reader
    asks -- not one edge per path through the program, and not an artefact that
    has forgotten where the value came from.
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
    assert len(merged) == 1
    assert len(_definers(flow, "WS-A")) == 2


def test_every_resolvable_write_is_covered_in_a_program_with_no_unknown_names(flow_of):
    flow = flow_of(
        [{"name": "MAIN", "statements": [_move("WS-A", "WS-B"), _move("WS-B", "WS-C")]}]
    )
    assert flow.writes > 0
    assert flow.covered == flow.writes


def test_a_write_to_an_undeclared_name_counts_against_coverage_and_is_warned(
    flow_of, caplog
):
    """The denominator comes from the source, so an unreached write is visible."""
    with caplog.at_level(logging.WARNING, logger=fixpoint.__name__):
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
    assert caplog.messages == [
        "fields: PROGA MAIN/1 writes WS-GONE, which has no memory definition;"
        " the write is not tracked"
    ]


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


def test_reaching_the_dequeue_cap_keeps_what_it_found_marked_unsettled(
    loop_paragraphs, flow_of
):
    """The cap stops a walk the way a sweep budget does, so it is answered the same
    way: join is monotone, so the state at the cap is a subset of the fixpoint and
    every flow read off it is real. Discarding it threw away flows the walk had
    already proven -- here all of them -- and only ``settled`` says some may be
    missing."""
    capped = flow_of(loop_paragraphs, AnalysisOptions(factor=1))

    assert (capped.skipped, capped.settled) == ("", False)
    assert _pairs(capped) == {("WS-A", "WS-B"), ("WS-B", "WS-C")}
    assert _pairs(capped) <= _pairs(flow_of(loop_paragraphs))


def test_a_raised_factor_lifts_the_cap_for_a_member_that_tripped_it(flow_of):
    """The honest bound is nodes times lattice height, which no constant captures,
    so a member given up on can be re-run with more room rather than reworked."""
    paragraphs = [{"name": "MAIN", "statements": [_move("WS-A", "WS-B")]}]

    assert not flow_of(paragraphs, AnalysisOptions(factor=0)).settled
    assert flow_of(paragraphs, AnalysisOptions(factor=1)).settled


def test_the_first_heartbeat_has_no_rate_and_a_later_one_estimates_from_the_drain():
    """Two samples make a rate; one makes nothing, and says so rather than zero."""
    first = fixpoint._Worklist(states={}, queue=frozenset(range(40)), dequeues=2000)
    later = fixpoint._Worklist(
        states={},
        queue=frozenset(range(40)),
        dequeues=4000,
        progress=fixpoint._Progress(
            started=time.monotonic() - 10.0, dequeues=2000, queued=60
        ),
    )

    assert fixpoint._eta(first, cap=100000) == "no rate yet"
    assert "4,000 dequeues" in fixpoint._eta(later, cap=100000)


def test_an_estimate_that_runs_past_the_cap_says_so_instead_of_a_time():
    """The number worth acting on: waiting buys nothing if the cap arrives first."""
    run = fixpoint._Worklist(
        states={},
        queue=frozenset(range(40)),
        dequeues=4000,
        progress=fixpoint._Progress(
            started=time.monotonic() - 10.0, dequeues=2000, queued=60
        ),
    )

    assert "past the 5000 cap" in fixpoint._eta(run, cap=5000)


def test_a_queue_that_is_not_draining_yields_no_estimate():
    run = fixpoint._Worklist(
        states={},
        queue=frozenset(range(80)),
        dequeues=4000,
        progress=fixpoint._Progress(
            started=time.monotonic() - 10.0, dequeues=2000, queued=60
        ),
    )

    assert fixpoint._eta(run, cap=100000) == "queue not draining"


def test_a_sweep_walk_matches_the_worklist_on_acyclic_code(flow_of):
    """No back edge means nothing to drop: one sweep is the whole answer."""
    paragraphs = [
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

    swept = flow_of(paragraphs, AnalysisOptions(sweeps=1))

    assert swept.back_edges == 0
    assert swept.settled
    assert _pairs(swept) == _pairs(flow_of(paragraphs))


def test_a_sweep_walk_settles_a_loop_in_a_few_sweeps(loop_paragraphs, flow_of):
    """Settled means the fixpoint was reached, so the answer is not an
    approximation -- it is the worklist's answer, reached by a cheaper route."""
    swept = flow_of(loop_paragraphs, AnalysisOptions(sweeps=10))

    assert swept.settled
    assert swept.back_edges > 0
    assert swept.sweeps <= 4
    assert _pairs(swept) == _pairs(flow_of(loop_paragraphs))


def test_one_sweep_loses_a_definition_the_loop_carries_backwards(flow_of):
    """A read whose feeding write comes later in the body needs the back edge.

    The worklist credits the read to the write below it; one sweep has not seen
    that write yet, so it credits the read to nothing -- an uninitialised read.
    That is the shape of what a single sweep drops, and nothing is invented in
    its place.
    """
    paragraphs = [
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

    assert _definers(flow_of(paragraphs), "WS-C") == {"LOOP-PARA/1"}
    assert _definers(flow_of(paragraphs, AnalysisOptions(sweeps=1)), "WS-C") == set()


def test_a_sweep_walk_that_runs_out_of_budget_says_so(loop_paragraphs, flow_of):
    """An unsettled walk is not a skip: its edges are a subset, none invented."""
    one = flow_of(loop_paragraphs, AnalysisOptions(sweeps=1))

    assert not one.settled
    assert not one.skipped
    assert one.sweeps == 1
    assert set(_pairs(one)) <= set(_pairs(flow_of(loop_paragraphs)))
    assert one.edges


def test_a_sweep_walk_ignores_the_dequeue_cap(loop_paragraphs, flow_of):
    """The cap counts visits to a node, which is not what a sweep budget spends."""
    swept = flow_of(loop_paragraphs, AnalysisOptions(sweeps=10, factor=0))

    assert not swept.skipped
    assert swept.settled


def test_each_sweep_says_it_finished_and_whether_the_state_is_still_growing(
    loop_paragraphs, flow_of, caplog
):
    """The worklist heartbeat counts dequeues, which a sweep walk never spends.

    Without a line of its own a sweep runs silent: one pass over a few thousand
    nodes takes tens of seconds, and the run would print nothing between start and
    the member's result.
    """
    with caplog.at_level(logging.INFO, logger=fixpoint.__name__):
        flow_of(loop_paragraphs, AnalysisOptions(sweeps=10))

    done = [line for line in caplog.messages if "sweep" in line and "done" in line]
    assert done
    assert "still growing" in done[0]
    assert "settled" in done[-1]


def test_a_sweep_visits_each_reachable_node_once(flow_of):
    paragraphs = [
        {"name": "MAIN", "statements": [_move("WS-A", "WS-B")]},
        {"name": "NEXT-PARA", "statements": [_move("WS-B", "WS-C")]},
    ]

    flow = flow_of(paragraphs, AnalysisOptions(sweeps=1))

    assert flow.dequeues <= flow.nodes


def test_seeding_the_entry_state_leaves_the_coverage_counters_alone(
    program_of, field, index_of
):
    """Seeding does not change what the walk reaches -- only what it starts with.

    Task 7 is where a resolved call site proves the seeding does anything; here
    the observable claim is narrower -- the coverage counters and ``settled`` are
    identical with and without it, and ``writes > 0`` so a program that analysed
    nothing cannot satisfy this vacuously.
    """
    asg = program_of(
        [],
        paragraphs=[{"name": "MAIN", "statements": [_move("WS-PGM", "WS-COPY")]}],
        data_fields=[
            field(
                1,
                "REC",
                children=[
                    field(5, "WS-PGM", "X(8)", offset=0, value="COSGN00C"),
                    field(5, "WS-COPY", "X(8)", offset=8),
                ],
            )
        ],
    )
    index = index_of(asg)
    bare = analyse(asg, index, DEFAULT_OPTIONS)
    seeded = analysed(asg)[0]

    assert seeded.writes > 0
    assert (seeded.writes, seeded.covered, seeded.settled) == (
        bare.writes,
        bare.covered,
        bare.settled,
    )


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

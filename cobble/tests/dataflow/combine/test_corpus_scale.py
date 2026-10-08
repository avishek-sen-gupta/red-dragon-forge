"""The combine at corpus scale: thousands of programs, and walks thousands of steps deep."""

from cobble.dataflow.combine.link import link
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.walk import walked
from tests.dataflow.combine.test_link import areas


def _quiet(name: str) -> ProgramTables:
    return ProgramTables(
        program=name, facts={}, flows={}, jumps={}, received=(), sites={}
    )


def test_thousands_of_programs_link_without_one_stack_frame_each() -> None:
    tables = {name: _quiet(name) for name in (f"P{n:05d}" for n in range(3000))}

    linked = link(tables, areas(), {}, OutsideJumps())

    assert (linked.targets, linked.edges) == ((), ())


def test_a_walk_thousands_of_steps_deep_reaches_every_vertex() -> None:
    last = 5000

    state = walked(
        0,
        lambda vertex: (frozenset({vertex}), (vertex + 1,) if vertex < last else ()),
        lambda left, right: left | right,
        frozenset[int](),
    )

    assert (state.found, len(state.seen)) == (frozenset(range(last + 1)), last + 1)

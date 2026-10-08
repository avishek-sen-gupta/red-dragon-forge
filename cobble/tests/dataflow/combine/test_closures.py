"""Answering every start from one memo gives each start what its own walk would,
and expands each vertex once however many starts reach it."""

from cobble.dataflow.combine.closures import Closures
from cobble.dataflow.combine.walk import walked

# A ring 0 -> 1 -> ... -> 9 -> 0 with a tail 10 -> 11 -> 3, a diamond
# 12 -> 13, 12 -> 14, 13 -> 15, 14 -> 15, a self-loop at 16, a branching tree
# 20 -> 21 -> 23, 20 -> 22, a duplicated edge 24 -> 25 twice, and 26 above a
# branching 27 whose branches meet at 30.
_EDGES = {
    **{n: ((n + 1) % 10,) for n in range(10)},
    10: (11,),
    11: (3,),
    12: (13, 14),
    13: (15,),
    14: (15,),
    15: (),
    16: (16,),
    20: (21, 22),
    21: (23,),
    22: (),
    23: (),
    24: (25, 25),
    25: (),
    26: (27,),
    27: (28, 29),
    28: (30,),
    29: (30,),
    30: (),
}


def _no_spread(seen: frozenset[int]) -> str:
    return ""


def _found(vertex: int) -> frozenset[int]:
    return frozenset({vertex}) if vertex % 3 == 0 else frozenset()


def test_one_memo_answers_every_start_as_its_own_walk_and_expands_each_vertex_once() -> (
    None
):
    expanded: list[int] = []

    def expand(vertex: int) -> tuple[frozenset[int], tuple[int, ...]]:
        expanded.append(vertex)
        return _found(vertex), _EDGES[vertex]

    closures = Closures(expand, lambda left, right: left | right, frozenset[int]())
    starts: tuple[int, ...] = (10, 0, 5, 12, 13, 16, 11, 3, 20, 21, 24, 15, 26)

    answers = [(closures.of(start), closures.revisits(start)) for start in starts]

    walks = [
        walked(
            start,
            lambda vertex: (_found(vertex), _EDGES[vertex]),
            lambda left, right: left | right,
            frozenset[int](),
            spread=_no_spread,
        )
        for start in starts
    ]
    assert answers == [(walk.found, walk.revisited) for walk in walks]
    assert [revisits for _, revisits in answers] == [
        True,
        True,
        True,
        True,
        False,
        True,
        True,
        True,
        False,
        False,
        True,
        False,
        True,
    ]
    assert sorted(expanded) == sorted(set(expanded))
    assert sorted(expanded) == [*range(17), *range(20, 31)]

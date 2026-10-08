"""MemoResolve: every start in a program answered as resolve would, each position walked once a run."""

from collections import Counter
from dataclasses import replace

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.memo_resolve import MemoResolve
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolution import Resolution
from cobble.dataflow.combine.resolve import Step, Vertex, resolve, step
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact

P = "PROGB"


def r(text: str) -> ByteRange:
    return byte_range(text, P)


LK = r("LK-FROM@linkage[0:8]")
WS = r("WS-NEXT@working_storage[0:8]")
OTHER = r("WS-OTHER@working_storage[20:28]")
TMP = r("WS-TMP@working_storage[8:16]")


def _bytes_only(found: Resolution) -> Resolution:
    return replace(
        found,
        stops=frozenset(replace(stop, at=stop.at.bytes_only()) for stop in found.stops),
    )


class CountingStep:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Vertex]] = []

    def __call__(self, tables: ProgramTables, vertex: Vertex) -> Step:
        self.calls.append((tables.program, vertex))
        return step(tables, vertex)


def test_starts_sharing_a_chain_get_resolves_answer_and_walk_it_once() -> None:
    chain = ProgramTables(
        program=P,
        facts={
            "J": ((WS, Fact("WS-NEXT@working_storage[0:8]", writers=("M2",))),),
            "K": ((OTHER, Fact("WS-OTHER@working_storage[20:28]", writers=("M2",))),),
            "M2": ((TMP, Fact("WS-TMP@working_storage[8:16]", writers=("M1",))),),
            "M1": (
                (
                    LK,
                    Fact(
                        "LK-FROM@linkage[0:8]",
                        reasons=(UnresolvedReason.INBOUND_LINKAGE,),
                    ),
                ),
            ),
        },
        flows={
            "M2": (Flow("M2", TMP, WS), Flow("M2", TMP, OTHER)),
            "M1": (Flow("M1", LK, TMP),),
        },
        jumps={},
        received=((0, r("DFHCOMMAREA@linkage[0:20]")),),
        sites={},
    )
    counted = CountingStep()
    memo = MemoResolve({P: chain}, counted)

    answers = [memo(chain, "J", WS), memo(chain, "K", OTHER), memo(chain, "J", WS)]

    assert answers == [
        _bytes_only(resolve(chain, "J", WS)),
        _bytes_only(resolve(chain, "K", OTHER)),
        _bytes_only(resolve(chain, "J", WS)),
    ]
    assert Counter(counted.calls) == Counter(
        {
            (P, ("J", WS.bytes_only())): 1,
            (P, ("K", OTHER.bytes_only())): 1,
            (P, ("M2", TMP.bytes_only())): 1,
            (P, ("M1", LK.bytes_only())): 1,
        }
    )


def test_the_same_bytes_under_two_field_names_are_walked_once() -> None:
    alias = byte_range("WS-TMP-R@working_storage[8:16]", P)
    chain = ProgramTables(
        program=P,
        facts={
            "J": ((WS, Fact("WS-NEXT@working_storage[0:8]", writers=("M2",))),),
            "K": ((OTHER, Fact("WS-OTHER@working_storage[20:28]", writers=("M2",))),),
            "M2": ((TMP, Fact("WS-TMP@working_storage[8:16]", writers=("M1",))),),
            "M1": (
                (
                    LK,
                    Fact(
                        "LK-FROM@linkage[0:8]",
                        reasons=(UnresolvedReason.INBOUND_LINKAGE,),
                    ),
                ),
            ),
        },
        flows={
            "M2": (Flow("M2", TMP, WS), Flow("M2", alias, OTHER)),
            "M1": (Flow("M1", LK, TMP),),
        },
        jumps={},
        received=((0, r("DFHCOMMAREA@linkage[0:20]")),),
        sites={},
    )
    counted = CountingStep()
    memo = MemoResolve({P: chain}, counted)

    answers = [memo(chain, "J", WS), memo(chain, "K", OTHER)]

    assert answers == [
        _bytes_only(resolve(chain, "J", WS)),
        _bytes_only(resolve(chain, "K", OTHER)),
    ]
    assert Counter(counted.calls) == Counter(
        {
            (P, ("J", WS.bytes_only())): 1,
            (P, ("K", OTHER.bytes_only())): 1,
            (P, ("M2", TMP.bytes_only())): 1,
            (P, ("M1", LK.bytes_only())): 1,
        }
    )

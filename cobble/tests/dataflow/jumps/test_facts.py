"""A Fact is the settled state's answer for some bytes at one node."""

from cobble.dataflow.fields.state import EMPTY, NOWHERE, Source, write
from cobble.dataflow.fields.values import UnresolvedReason, ValueSet
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.facts import fact_at, merged
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

WS = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.EXACT, "WS-FROM")
LK = FieldExtent(RegionId.LINKAGE, 0, 8, Precision.EXACT, "LK-FROM")
STATE = write(
    EMPTY,
    WS,
    frozenset(
        {
            Source(origin="", extent=LK, node="MAIN/2"),
            Source(origin="LITERAL", extent=NOWHERE, node="MAIN/9"),
        }
    ),
    ValueSet(values=frozenset({b"PROGA   "})),
)


def test_a_fact_carries_unstripped_values_writers_and_reasons() -> None:
    assert (fact_at(STATE, WS), fact_at(STATE, LK)) == (
        Fact(
            extent="WS-FROM@working_storage[0:8]",
            values=("PROGA   ",),
            writers=("MAIN/2", "MAIN/9"),
        ),
        Fact(
            extent="LK-FROM@linkage[0:8]",
            reasons=(UnresolvedReason.INBOUND_LINKAGE,),
        ),
    )


def test_facts_merge_by_union_naming_an_extent_only_when_they_share_one() -> None:
    assert merged(
        (
            Fact(
                "A@working_storage[0:8]",
                ("X",),
                ("N/1",),
                (UnresolvedReason.NOT_A_LITERAL,),
            ),
            Fact(
                "A@working_storage[8:16]",
                ("Y",),
                ("N/2",),
                (UnresolvedReason.NO_EXTENT,),
            ),
        )
    ) == Fact(
        "",
        ("X", "Y"),
        ("N/1", "N/2"),
        (UnresolvedReason.NO_EXTENT, UnresolvedReason.NOT_A_LITERAL),
    )
    assert merged(
        (
            Fact("A@working_storage[0:8]", ("X",), ("N/1",)),
            Fact("A@working_storage[0:8]", ("Y",), ("N/2",)),
        )
    ) == Fact("A@working_storage[0:8]", ("X", "Y"), ("N/1", "N/2"))

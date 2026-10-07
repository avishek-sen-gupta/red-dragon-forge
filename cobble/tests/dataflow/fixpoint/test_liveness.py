"""What stays live backward across one node's writes, and how a live set is looked up."""

from cobble.dataflow.fields.state import NOWHERE, Source, State, pruned
from cobble.dataflow.fields.transfer import Write
from cobble.dataflow.fields.values import EMPTY as NO_VALUE
from cobble.dataflow.fields.values import of_value
from cobble.dataflow.fields.spans import spans_of
from cobble.dataflow.fixpoint.live import EVERYTHING, Live
from cobble.dataflow.fixpoint.liveness import entered
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId


def _ws(start: int, length: int, name: str, precision=Precision.EXACT) -> FieldExtent:
    return FieldExtent(RegionId.WORKING_STORAGE, start, length, precision, name)


def _write(target: FieldExtent, *sources: FieldExtent, weak: bool = False) -> Write:
    return Write(
        target=target,
        sources=frozenset(Source(origin="", extent=one, node="N") for one in sources),
        values=NO_VALUE,
        weak=weak,
    )


def test_a_write_kills_only_what_it_must_cover_and_makes_its_sources_live() -> None:
    pgm = _ws(0, 8, "WS-PGM")
    head = _ws(0, 4, "WS-PGM")
    table = _ws(8, 4, "WS-TAB", Precision.CLAMPED)
    staged = _ws(20, 8, "WS-STAGED")
    other = _ws(40, 8, "WS-OTHER")
    demanded = _ws(60, 4, "WS-AREA")
    literal = Write(
        target=_ws(80, 4, "WS-LIT"),
        sources=frozenset({Source(origin="LITERAL", extent=NOWHERE, node="L")}),
        values=NO_VALUE,
    )
    record = _ws(0, 12, "WS-REC")

    assert entered((_write(pgm, staged),), frozenset(), frozenset({pgm})) == {staged}
    assert entered((_write(head, staged),), frozenset(), frozenset({pgm})) == {
        pgm,
        staged,
    }
    assert entered(
        (_write(table, other, weak=True),), frozenset(), frozenset({record})
    ) == {record, table, other}
    assert entered((_write(other, staged),), frozenset({demanded}), frozenset()) == {
        demanded
    }
    assert entered((literal,), frozenset(), frozenset({_ws(80, 4, "WS-LIT")})) == set()


def test_a_live_set_keeps_exactly_the_extents_that_overlap_it() -> None:
    live = Live(
        entry={"N": spans_of((_ws(0, 4, "A"), _ws(4, 4, "B"), _ws(20, 2, "C")))}
    )
    state = State(
        sources={
            _ws(2, 4, "IN"): frozenset(),
            _ws(8, 12, "GAP"): frozenset(),
            _ws(21, 8, "EDGE"): frozenset(),
        },
        values={_ws(8, 12, "GAP"): of_value(b"X" * 12)},
    )

    kept = pruned(state, lambda extent: live.keeps("N", extent))

    assert set(kept.sources) == {_ws(2, 4, "IN"), _ws(21, 8, "EDGE")}
    assert dict(kept.values) == {}
    assert not live.keeps("M", _ws(0, 4, "A"))
    assert EVERYTHING.keeps("M", _ws(0, 4, "A"))
    assert pruned(state, lambda extent: True) is state

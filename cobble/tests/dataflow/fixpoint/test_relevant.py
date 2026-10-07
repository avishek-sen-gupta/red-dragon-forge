"""Which bytes a call-target walk tracks: the seeds closed over the program's writes."""

from cobble.dataflow.fields.relevant import EVERYTHING, Relevant
from cobble.dataflow.fields.state import NOWHERE, Source
from cobble.dataflow.fields.transfer import Write
from cobble.dataflow.fields.values import EMPTY as NO_VALUE
from cobble.dataflow.fixpoint.closure import closed
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId


def _ws(start: int, length: int, name: str) -> FieldExtent:
    return FieldExtent(RegionId.WORKING_STORAGE, start, length, Precision.EXACT, name)


def _write(target: FieldExtent, *sources: FieldExtent) -> Write:
    return Write(
        target=target,
        sources=frozenset(Source(origin="", extent=one, node="N") for one in sources),
        values=NO_VALUE,
    )


def test_the_set_follows_writes_into_the_target_and_nothing_beside_it() -> None:
    pgm = _ws(0, 8, "WS-PGM")
    head = _ws(0, 4, "WS-PGM")
    staged = _ws(8, 8, "WS-STAGED")
    record = _ws(16, 20, "WS-REC")
    part = _ws(20, 8, "WS-REC-PART")
    origin = _ws(36, 20, "WS-ORIGIN")
    sibling = _ws(56, 8, "WS-SIBLING")
    other = _ws(64, 8, "WS-OTHER")
    literal = Write(
        target=head,
        sources=frozenset({Source(origin="LITERAL", extent=NOWHERE, node="L")}),
        values=NO_VALUE,
    )
    writes = (
        _write(pgm, staged),
        _write(staged, part),
        _write(record, origin),
        _write(sibling, other),
        literal,
    )

    found = closed((pgm,), writes)

    assert found == Relevant(extents=frozenset({pgm, staged, part, origin}))
    assert found.touches(head)
    assert found.touches(record)
    assert not found.touches(sibling)
    assert not found.touches(
        FieldExtent(RegionId.LINKAGE, 0, 8, Precision.EXACT, "WS-PGM")
    )
    assert EVERYTHING.touches(sibling)

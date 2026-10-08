from cobble.dataflow.fixpoint.area_kind import AreaKind
from cobble.dataflow.fixpoint.area_need import AreaNeed
from cobble.dataflow.fixpoint.area_slot import AreaSlot
from cobble.dataflow.fixpoint.area_table import WHOLE_TABLE, area_table
from cobble.dataflow.fixpoint.call_site import CallSite
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

COMMAREA = AreaSlot(AreaKind.COMMAREA, 0)
USING = AreaSlot(AreaKind.USING, 0)
AREA = FieldExtent(
    region=RegionId.WORKING_STORAGE,
    start=100,
    length=20,
    precision=Precision.EXACT,
    field_name="WS-AREA",
)


def _bytes(extents: tuple[FieldExtent, ...]) -> list[tuple[int, int]]:
    return [(one.start, one.end) for one in extents]


def test_a_call_site_is_charged_with_its_own_callee_and_an_exit_with_its_own_callers() -> (
    None
):
    table = area_table(
        (
            (
                "PROGN",
                AreaNeed(entry=((COMMAREA, (0, 8)),), back=((COMMAREA, (4, 6)),)),
            ),
            ("PROGO", AreaNeed(entry=((COMMAREA, (8, 16)),))),
            ("PROGU", AreaNeed(entry=((USING, (2, 3)),))),
        ),
        (
            ("PROGN", (COMMAREA,)),
            ("PROGO", (COMMAREA,)),
            ("PROGU", (USING,)),
        ),
    )
    caller = table.seen_from("PROGN")

    assert [
        _bytes(caller.entry_at(CallSite("PROGN", AreaKind.COMMAREA), COMMAREA, AREA)),
        _bytes(caller.entry_at(CallSite("PROGO", AreaKind.COMMAREA), COMMAREA, AREA)),
        _bytes(caller.entry_at(CallSite("", AreaKind.COMMAREA), COMMAREA, AREA)),
        _bytes(caller.entry_at(CallSite("", AreaKind.USING), USING, AREA)),
        _bytes(caller.entry_at(CallSite("PROGQ", AreaKind.COMMAREA), COMMAREA, AREA)),
        _bytes(caller.entry_at(CallSite("PROGU", AreaKind.COMMAREA), COMMAREA, AREA)),
        _bytes(caller.back_at(COMMAREA, AREA)),
        _bytes(table.seen_from("PROGO").back_at(COMMAREA, AREA)),
        _bytes(table.seen_from("PROGQ").back_at(COMMAREA, AREA)),
        _bytes(
            WHOLE_TABLE.entry_at(CallSite("PROGO", AreaKind.COMMAREA), COMMAREA, AREA)
        ),
        _bytes(WHOLE_TABLE.seen_from("PROGN").back_at(COMMAREA, AREA)),
    ] == [
        [(100, 108)],
        [(108, 116)],
        [(100, 116)],
        [(102, 103)],
        [(100, 120)],
        [(100, 120)],
        [(104, 106)],
        [],
        [(100, 120)],
        [(100, 120)],
        [(100, 120)],
    ]

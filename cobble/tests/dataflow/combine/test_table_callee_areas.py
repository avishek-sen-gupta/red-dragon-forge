"""TableCalleeAreas answers the analysed programs from their tables and reads the rest once."""

from cobble.dataflow.combine.callee_areas import CalleeAreas
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.table_callee_areas import TableCalleeAreas
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.jumps.jump_kind import JumpKind


class RecordingAreas(CalleeAreas):
    def __init__(self) -> None:
        self.asked: list[str] = []

    def area(self, callee: str, kind: JumpKind, param: int) -> ByteRange:
        self.asked.append(callee)
        return byte_range("DFHCOMMAREA@linkage[0:7]", callee)


def _tables(name: str) -> ProgramTables:
    return ProgramTables(
        program=name,
        facts={},
        flows={},
        jumps={},
        received=((0, byte_range("DFHCOMMAREA@linkage[0:20]", name)),),
        sites={},
    )


def test_inside_callees_come_from_their_tables_and_outside_ones_are_read_once() -> None:
    outside = RecordingAreas()
    areas = TableCalleeAreas({"IN": _tables("IN")}, outside)

    inside = areas.area("IN", JumpKind.XCTL, 0)
    inside_unreceived = areas.area("IN", JumpKind.CALL, 1)
    first = [areas.area("OUT", JumpKind.XCTL, 0) for _ in range(3)]

    assert inside == byte_range("DFHCOMMAREA@linkage[0:20]", "IN")
    assert inside_unreceived == NO_RANGE
    assert first == [byte_range("DFHCOMMAREA@linkage[0:7]", "OUT")] * 3
    assert outside.asked == ["OUT"]

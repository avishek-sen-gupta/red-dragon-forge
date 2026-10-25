"""Provenance walks over hand-built fixpoint out-dirs and combine links."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from tests.dataflow.fixpoint.fixpoint_dir import (
    Row,
    defs_row,
    fixpoint_dir,
    flow_row,
    sink_row,
)

from cobble.dataflow.combine.link_row import LinkRow
from cobble.dataflow.fields.dep_row import DepRow
from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_row
from cobble.dataflow.fields.trace_query import (
    BACKWARD,
    FORWARD,
    _narrowed,
    _resolve,
    cli,
    provenance_rows,
    query,
)


def _text(found: dict) -> str:
    return f"{found['field']}@{found['region']}[{found['start']}:{found['end']}]"


def _out_dir(rows: list[dict], tmp_path: Path) -> Path:
    def node(row: dict) -> str:
        return row["site"].split("/", 1)[1]

    flows = [
        flow_row(
            row["program"],
            node(row),
            _text(row["target"]),
            _text(row["source"]) if row["source"] else "",
            row["origin"],
        )
        for row in rows
        if not row.get("sink")
    ]
    sinks = [
        sink_row(row["program"], node(row), _text(row["source"]), row["sink"])
        for row in rows
        if row.get("sink")
    ]
    return fixpoint_dir(tmp_path / "fixpoint", flows, sinks)


def _jsonl(rows: list[dict], tmp_path: Path) -> tuple[DepRow, ...]:
    return provenance_rows(_out_dir(rows, tmp_path), Path())


def _dep(
    program: str,
    target_field: str,
    target_start: int,
    target_end: int,
    source_field: str = "",
    source_start: int = 0,
    source_end: int = 0,
    origin: str = "",
    site: str = "",
    definers: list[str] | None = None,
    via: str = "",
    region: str = "working_storage",
    source_program: str = "",
) -> dict:
    source = (
        {
            "field": source_field,
            "region": region,
            "start": source_start,
            "end": source_end,
            "clamped": False,
        }
        if not origin
        else None
    )
    return {
        "kind": "dep",
        "program": program,
        "via": via,
        "target": {
            "field": target_field,
            "region": region,
            "start": target_start,
            "end": target_end,
            "clamped": False,
        },
        "origin": origin,
        "source": source,
        **({} if origin else {"source_program": source_program or program}),
        "site": site or f"{program}/PARA/0",
        "definers": definers or [],
    }


def _ws(name: str, start: int, end: int, program: str = "P") -> ByteRange:
    return ByteRange(
        program=program,
        region="working_storage",
        start=start,
        end=end,
        name=name,
        exact=True,
        known=True,
    )


def _row(
    target: ByteRange,
    source: ByteRange,
    site: str,
    definers: tuple[str, ...] = (),
    origin: str = "",
    sink: str = "",
) -> DepRow:
    return DepRow(
        program=site.split("/", 1)[0],
        via="",
        target=target,
        origin=origin,
        source=source,
        site=site,
        definers=definers,
        sink=sink,
    )


_NOWHERE = ByteRange(
    program="", region="", start=0, end=0, name="", exact=True, known=False
)

_TWO_WRITERS = (
    _row(_ws("X", 0, 4), _ws("A", 10, 14), "P/S1"),
    _row(_ws("X", 0, 4), _ws("C", 20, 24), "P/S5"),
    _row(_ws("Y", 30, 34), _ws("X", 0, 4), "P/S3", definers=("P/S1",)),
    _row(_ws("Z", 40, 44), _NOWHERE, "P/S2", origin="LITERAL"),
    _row(_ws("Y", 30, 34), _ws("Z", 40, 44), "P/S4", definers=("P/S2",)),
    _row(_ws("W", 50, 54), _ws("X", 0, 4), "P/S6", definers=("P/S5",)),
    _row(_NOWHERE, _ws("Y", 30, 34), "P/S7", definers=("P/S3",), sink="FILE:OUT"),
)


def test_backward_is_a_tree_of_the_writes_that_reach_each_read() -> None:
    """X is written at S1 and S5, but only S1 reaches the read at S3; each
    source sits under the write that read it, and an origin ends its branch."""
    assert query(_TWO_WRITERS, BACKWARD, "Y") == (
        "Y@working_storage[30:34]",
        "  <- X@working_storage[0:4]  at P/S3",
        "    <- A@working_storage[10:14]  at P/S1",
        "  <- Z@working_storage[40:44]  at P/S4",
        "    <- LITERAL  at P/S2",
    )


def test_forward_follows_a_write_only_into_the_reads_it_reaches() -> None:
    """A's bytes reach X at S1; of X's readers only S3 is reached by S1, and Y
    then leaves by the sink S3 reaches. The depth limit cuts the tree."""
    assert query(_TWO_WRITERS, FORWARD, "A") == (
        "A@working_storage[10:14]",
        "  -> X@working_storage[0:4]  at P/S1",
        "    -> Y@working_storage[30:34]  at P/S3",
        "      -> FILE:OUT  at P/S7",
    )
    assert query(_TWO_WRITERS, FORWARD, "A", max_depth=1) == (
        "A@working_storage[10:14]",
        "  -> X@working_storage[0:4]  at P/S1",
    )


def test_a_write_that_reaches_itself_is_shown_once() -> None:
    """ADD 1 TO X reads the X it wrote on the last iteration: the walk stops
    there rather than repeating, and says the branch is above."""
    rows = (
        _row(_ws("X", 0, 4), _NOWHERE, "P/INIT", origin="LITERAL"),
        _row(_ws("X", 0, 4), _ws("X", 0, 4), "P/ADD", definers=("P/ADD", "P/INIT")),
    )

    assert query(rows, BACKWARD, "X") == (
        "X@working_storage[0:4]",
        "  <- X@working_storage[0:4]  at P/ADD",
        "    <- X@working_storage[0:4]  at P/ADD  (see above)",
        "    <- LITERAL  at P/INIT",
        "  <- LITERAL  at P/INIT  (see above)",
    )


def test_qualified_field_filters_by_program() -> None:
    rows = (
        _row(_ws("FIELD-X", 10, 11), _ws("SRC", 20, 21), "P/PARA/0"),
        _row(
            _ws("FIELD-X", 10, 11, "Q"),
            _ws("SRC", 20, 21, "Q"),
            "Q/PARA/0",
        ),
    )

    assert query(rows, FORWARD, "Q.SRC") == (
        "SRC@working_storage[20:21]",
        "  -> FIELD-X@working_storage[10:11]  at Q/PARA/0",
    )


def test_field_not_found(tmp_path: Path):
    trace = _jsonl(
        [_dep("P", "FIELD-A", 10, 11, "SRC", 20, 21)],
        tmp_path,
    )
    result = query(trace, FORWARD, "NO-SUCH-FIELD")
    assert any("not found" in line for line in result)


def _range(program: str, name: str, start: int, end: int) -> ByteRange:
    return ByteRange(
        program=program,
        region="working_storage",
        start=start,
        end=end,
        name=name,
        exact=True,
        known=True,
    )


def _call(program: str, node: str, area: str, *fields: Fact) -> Row:
    jump = Jump(
        program, node, 1, JumpKind.CALL, True, areas=(JumpArea(0, area, fields),)
    )
    return (program, jump_row(jump))


def _exit(*fields: Fact) -> Row:
    area = JumpArea(0, "LS-REC@linkage[0:8]", fields)
    return (
        "CALLEE",
        jump_row(Jump("CALLEE", "X", 2, JumpKind.EXIT, False, areas=(area,))),
    )


def _link(caller: str, node: str, area: str) -> str:
    return (
        LinkRow(
            caller=caller,
            node=node,
            callee="CALLEE",
            caller_extent=area,
            callee_extent="LS-REC@linkage[0:8]",
            returns=True,
        ).model_dump_json()
        + "\n"
    )


def test_a_walk_crosses_a_link_through_the_writes_that_reach_each_side(
    tmp_path: Path,
):
    """CALLER writes WS-AREA at S1, CALLs CALLEE with WS-REC at S2, and writes
    WS-AREA again at S9, after the call. CALLEE copies LS-AREA, which it never
    wrote, into LS-OUT. The call's own jump row says S1 is the write that reaches
    it, and CALLEE's exit says R1 is the one that reaches the exit, so the walk
    crosses only through those: never S9, and never into OTHER, which calls
    CALLEE too, because the walk leaves CALLEE only by the call it came in by."""
    reaches = (UnresolvedReason.INBOUND_LINKAGE,)
    out = fixpoint_dir(
        tmp_path / "fixpoint",
        [
            flow_row("CALLER", "S1", "WS-AREA@working_storage[0:4]", "", "LITERAL"),
            flow_row("CALLER", "S9", "WS-AREA@working_storage[0:4]", "", "LITERAL"),
            flow_row("CALLER", "S2", "WS-REC@working_storage[0:8]", "", "%CALL:CALLEE"),
            flow_row(
                "CALLER",
                "C3",
                "WS-RESULT@working_storage[20:24]",
                "WS-OUT@working_storage[4:8]",
            ),
            flow_row("OTHER", "O1", "OT-REC@working_storage[0:4]", "", "LITERAL"),
            flow_row("CALLEE", "R1", "LS-OUT@linkage[4:8]", "LS-AREA@linkage[0:4]"),
        ],
        [],
        defs=[
            defs_row("CALLER", "C3", "WS-OUT@working_storage[4:8]", ["S2"]),
            defs_row(
                "CALLEE", "R1", "LS-AREA@linkage[0:4]", reasons=["inbound-linkage"]
            ),
        ],
        jumps=[
            _call(
                "CALLER",
                "S2",
                "WS-REC@working_storage[0:8]",
                Fact("WS-AREA@working_storage[0:4]", writers=("S1",)),
                Fact("WS-OUT@working_storage[4:8]"),
            ),
            _call(
                "OTHER",
                "T5",
                "OT-REC@working_storage[0:8]",
                Fact("OT-REC@working_storage[0:8]", writers=("O1",)),
            ),
            _exit(
                Fact("LS-AREA@linkage[0:4]", reasons=reaches),
                Fact("LS-OUT@linkage[4:8]", writers=("R1",)),
            ),
        ],
    )
    links = tmp_path / "links.jsonl"
    links.write_text(
        _link("CALLER", "S2", "WS-REC@working_storage[0:8]")
        + _link("OTHER", "T5", "OT-REC@working_storage[0:8]"),
        encoding="utf-8",
    )

    crossed = provenance_rows(out, links)

    assert query(crossed, BACKWARD, "CALLER.WS-RESULT") == (
        "WS-RESULT@working_storage[20:24]",
        "  <- WS-OUT@working_storage[4:8]  at CALLER/C3",
        "    <- %CALL:CALLEE  at CALLER/S2",
        "    <- LS-OUT@linkage[4:8]  at CALLER/S2",
        "      <- LS-AREA@linkage[0:4]  at CALLEE/R1",
        "        <- WS-AREA@working_storage[0:4]  at CALLER/S2",
        "          <- LITERAL  at CALLER/S1",
    )
    assert query(crossed, FORWARD, "CALLER.WS-AREA") == (
        "WS-AREA@working_storage[0:4]",
        "  -> LS-REC@linkage[0:4]  at CALLER/S2",
        "    -> LS-OUT@linkage[4:8]  at CALLEE/R1",
        "      -> WS-REC@working_storage[4:8]  at CALLER/S2",
        "        -> WS-RESULT@working_storage[20:24]  at CALLER/C3",
        "    -> WS-REC@working_storage[0:4]  at CALLER/S2",
    )


def test_a_program_the_out_dir_does_not_hold_exits_two(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = _out_dir([_dep("P", "A", 0, 8, "B", 10, 18)], tmp_path)

    with caplog.at_level(logging.ERROR):
        code = cli(["forward", "NOPE.FIELD", "--fixpoint", str(out)])

    assert code == 2
    assert [record.getMessage() for record in caplog.records] == [
        f"trace-query: no member NOPE under {out}"
    ]


def test_a_frontier_range_wider_than_the_target_narrows_to_their_overlap():
    """Tracing a group and one of its members at once puts both on the frontier.
    Offsetting the source by the wider one's start slides it off the front."""
    source = _range("CALLEE", "SUB-RESULT", 4, 8)
    target = _range("CALLER", "WS-AREA", 4, 8)

    assert _narrowed(source, target, _range("CALLER", "WS-AREA", 0, 8)) == source

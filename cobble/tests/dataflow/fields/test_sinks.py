"""Every output statement names where its bytes go and the operand that carries them."""

from __future__ import annotations

import pytest
import json

from cobble.dataflow.fields.side_tables import ProgramSink, sink_row
from cobble.dataflow.fields.sink import Sink
from cobble.dataflow.fields.sink_kind import SinkKind
from cobble.dataflow.fields.sink_site import SinkSite
from cobble.dataflow.fields.sinks import sinks_of
from cobol_asg.ref_mod import RefModOperand


def _cics(verb: str, **options: tuple[str, bool]) -> dict:
    return {
        "type": "EXEC_CICS",
        "verb": verb,
        "options": {
            name: {"text": text, "is_literal": literal}
            for name, (text, literal) in options.items()
        },
    }


FILES = {"OUT-REC": "OUTF"}


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        (
            {
                "type": "WRITE",
                "record_name": "OUT-REC",
                "from_field": {"name": "WS-REC"},
            },
            (
                SinkSite(
                    sink=Sink(SinkKind.FILE, "OUTF"),
                    operand=RefModOperand(name="OUT-REC"),
                ),
            ),
        ),
        (
            {"type": "REWRITE", "record_name": "OUT-REC"},
            (
                SinkSite(
                    sink=Sink(SinkKind.FILE, "OUTF"),
                    operand=RefModOperand(name="OUT-REC"),
                ),
            ),
        ),
        (
            _cics("WRITE", FILE=("KSDS", True), FROM=("WS-REC", False)),
            (
                SinkSite(
                    sink=Sink(SinkKind.FILE, "KSDS"),
                    operand=RefModOperand(name="WS-REC"),
                ),
            ),
        ),
        (
            _cics("REWRITE", FILE=("KSDS", True), FROM=("WS-REC", False)),
            (
                SinkSite(
                    sink=Sink(SinkKind.FILE, "KSDS"),
                    operand=RefModOperand(name="WS-REC"),
                ),
            ),
        ),
        (
            _cics("SEND MAP", MAP=("MAP1", True), FROM=("WS-OUT", False)),
            (
                SinkSite(
                    sink=Sink(SinkKind.MAP, "MAP1"),
                    operand=RefModOperand(name="WS-OUT"),
                ),
            ),
        ),
        (
            _cics("SEND MAP", MAP=("MAP1", True), MAPSET=("SET1", True)),
            (
                SinkSite(
                    sink=Sink(SinkKind.MAP, "MAP1"), operand=RefModOperand(name="MAP1O")
                ),
            ),
        ),
        (
            {
                **_cics("SEND MAP", MAP=("MAP1", True)),
                "options": {
                    "MAP": {"text": "MAP1", "is_literal": True},
                    "MAPONLY": None,
                },
            },
            (),
        ),
        (
            _cics("WRITEQ TS", QUEUE=("Q1", True), FROM=("WS-ITEM", False)),
            (
                SinkSite(
                    sink=Sink(SinkKind.TS_QUEUE, "Q1"),
                    operand=RefModOperand(name="WS-ITEM"),
                ),
            ),
        ),
        (
            _cics("WRITEQ TD", QUEUE=("CSSL", True), FROM=("WS-LINE", False)),
            (
                SinkSite(
                    sink=Sink(SinkKind.TD_QUEUE, "CSSL"),
                    operand=RefModOperand(name="WS-LINE"),
                ),
            ),
        ),
        (
            _cics("START", TRANSID=("T001", True), FROM=("WS-DATA", False)),
            (
                SinkSite(
                    sink=Sink(SinkKind.TRANSID, "T001"),
                    operand=RefModOperand(name="WS-DATA"),
                ),
            ),
        ),
        (_cics("START", TRANSID=("T001", True)), ()),
        (_cics("READ", FILE=("KSDS", True), INTO=("WS-REC", False)), ()),
        ({"type": "MOVE", "operands": [{"name": "WS-A"}, {"name": "WS-B"}]}, ()),
    ],
)
def test_an_output_statement_names_its_sink_and_what_goes_out(
    program_of, statement, expected
):
    (parsed,) = program_of([statement]).paragraphs[0].statements
    assert sinks_of(parsed, FILES) == expected


def test_a_sink_row_writes_its_sink_as_a_kind_and_a_name() -> None:
    row = ProgramSink(
        program="P",
        node="P/1",
        sink=Sink(SinkKind.FILE, "OUT"),
        source_extent="WORKING-STORAGE:0+8",
        definers=("P/0",),
    )
    assert json.loads(sink_row(row)[1])["sink"] == {"kind": "FILE", "name": "OUT"}

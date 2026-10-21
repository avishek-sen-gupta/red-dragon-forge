"""Every output statement names where its bytes go and the operand that carries them."""

from __future__ import annotations

import pytest
from cobble.dataflow.fields.sinks import Sink, sinks_of
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
            (Sink(name="FILE:OUTF", operand=RefModOperand(name="OUT-REC")),),
        ),
        (
            {"type": "REWRITE", "record_name": "OUT-REC"},
            (Sink(name="FILE:OUTF", operand=RefModOperand(name="OUT-REC")),),
        ),
        (
            _cics("WRITE", FILE=("KSDS", True), FROM=("WS-REC", False)),
            (Sink(name="FILE:KSDS", operand=RefModOperand(name="WS-REC")),),
        ),
        (
            _cics("REWRITE", FILE=("KSDS", True), FROM=("WS-REC", False)),
            (Sink(name="FILE:KSDS", operand=RefModOperand(name="WS-REC")),),
        ),
        (
            _cics("SEND MAP", MAP=("MAP1", True), FROM=("WS-OUT", False)),
            (Sink(name="MAP:MAP1", operand=RefModOperand(name="WS-OUT")),),
        ),
        (
            _cics("SEND MAP", MAP=("MAP1", True), MAPSET=("SET1", True)),
            (Sink(name="MAP:MAP1", operand=RefModOperand(name="MAP1O")),),
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
            (Sink(name="TSQ:Q1", operand=RefModOperand(name="WS-ITEM")),),
        ),
        (
            _cics("WRITEQ TD", QUEUE=("CSSL", True), FROM=("WS-LINE", False)),
            (Sink(name="TDQ:CSSL", operand=RefModOperand(name="WS-LINE")),),
        ),
        (
            _cics("START", TRANSID=("T001", True), FROM=("WS-DATA", False)),
            (Sink(name="TRANSID:T001", operand=RefModOperand(name="WS-DATA")),),
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

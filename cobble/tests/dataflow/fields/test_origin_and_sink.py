"""An origin and a sink each carry a kind and a name, read as one text form and one wire object."""

from cobble.dataflow.fields.origin import NO_ORIGIN, Origin
from cobble.dataflow.fields.origin_kind import OriginKind
from cobble.dataflow.fields.sink import NO_SINK, Sink
from cobble.dataflow.fields.sink_kind import SinkKind
from pydantic import TypeAdapter


def test_origin_and_sink_text_and_wire() -> None:
    assert Origin(OriginKind.FILE, "ACCTFILE-FILE").text() == "FILE:ACCTFILE-FILE"
    assert Origin(OriginKind.CICS_STATE, "").text() == "CICS_STATE"
    assert Origin(OriginKind.LITERAL, "'.'").text() == "LITERAL:'.'"
    assert Origin(OriginKind.MAP, "M1", unplaced="WS-X").text() == "MAP:M1"
    assert Origin(OriginKind.MAP, "M1", unplaced="WS-X").wire() == {
        "kind": "MAP",
        "name": "M1",
        "unplaced": "WS-X",
    }
    assert Origin(OriginKind.LITERAL, "").wire() == {"kind": "LITERAL", "name": ""}
    assert NO_ORIGIN.is_storage
    assert not Origin(OriginKind.LITERAL, "").is_storage
    assert Sink(SinkKind.TS_QUEUE, "Q1").text() == "TS_QUEUE:Q1"
    assert Sink(SinkKind.FILE, "OUT").wire() == {"kind": "FILE", "name": "OUT"}
    assert NO_SINK.is_none
    assert not Sink(SinkKind.FILE, "OUT").is_none
    assert TypeAdapter(Origin).validate_python(
        {"kind": "MAP", "name": "M1", "unplaced": "WS-X"}
    ) == Origin(OriginKind.MAP, "M1", "WS-X")
    assert TypeAdapter(Sink).validate_python({"kind": "FILE", "name": "OUT"}) == Sink(
        SinkKind.FILE, "OUT"
    )

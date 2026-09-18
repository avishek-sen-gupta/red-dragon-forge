import queue

import pytest

from cics.screen.channel import drain_screens
from cics.screen.cursor import NO_CURSOR, Cursor, SymbolicCursor, cursor_from_message
from cics.screen.payload import (
    FieldAttributes,
    SendMapPayload,
    SendMode,
    SendTextPayload,
    screen_payload,
)
from tests.covers import NotLanguageFeature, covers


def _payload(**overrides):
    base = dict(
        map="COSGN0A",
        mapset="COSGN00",
        mode=SendMode.FULL,
        erase=True,
        alarm=False,
        frset=False,
        freekb=True,
        cursor=NO_CURSOR,
        fields={},
        attrs={},
    )
    return SendMapPayload(**{**base, **overrides})


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cursor_messages_round_trip():
    for cursor in (Cursor(245), SymbolicCursor("USERID"), NO_CURSOR):
        assert cursor_from_message(cursor.to_message()) == cursor


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cursor_resolution():
    start = {"USERID": 1483}.__getitem__
    assert (
        Cursor(7).resolve(start, 0),
        SymbolicCursor("USERID").resolve(start, 0),
        NO_CURSOR.resolve(start, 9),
    ) == (7, 1483, 9)
    assert (Cursor(7).eibcposn(), SymbolicCursor("USERID").eibcposn()) == (7, 0)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_map_message_keeps_the_legacy_keys_and_round_trips():
    original = _payload(
        fields={"USERID": "U1"},
        attrs={"ERRMSG": FieldAttributes(0xF8, 0xF2, 0)},
        cursor=Cursor(245),
    )
    message = original.to_message()
    assert (message["map"], message["fields"]["USERID"]) == ("COSGN0A", "U1")
    assert screen_payload(message) == original


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_text_message_round_trips():
    assert screen_payload(SendTextPayload("bye").to_message()) == SendTextPayload("bye")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_malformed_message_is_loud():
    message = {**_payload().to_message(), "erase": "yes"}
    with pytest.raises(TypeError, match="erase"):
        screen_payload(message)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_drain_reads_everything_sent_so_far():
    channel: queue.Queue = queue.Queue()
    channel.put(_payload().to_message())
    channel.put({"type": "text", "text": "bye"})
    assert drain_screens(channel) == (_payload(), SendTextPayload("bye"))
    assert drain_screens(channel) == ()

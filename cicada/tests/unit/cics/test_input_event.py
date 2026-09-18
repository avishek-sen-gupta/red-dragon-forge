import dataclasses

import pytest

from cics.dispatcher import InputEvent as ReExported
from cics.input_event import InputEvent
from cics.screen.cursor import NO_CURSOR, Cursor
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_defaults_and_cursor():
    assert (InputEvent().eibaid, dict(InputEvent().fields), InputEvent().cursor) == (
        "\x7d",
        {},
        NO_CURSOR,
    )
    assert InputEvent(cursor=Cursor(3)).cursor == Cursor(3)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_frozen_and_reexported():
    assert ReExported is InputEvent
    with pytest.raises(dataclasses.FrozenInstanceError):
        InputEvent().eibaid = "x"  # type: ignore[misc]

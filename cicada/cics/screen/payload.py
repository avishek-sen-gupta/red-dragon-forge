"""What SEND MAP and SEND TEXT put on the screen channel.

The channel carries JSON-shaped dicts so an out-of-process transport can
serialise them (see ``cics.terminal``). These value objects are how a consumer
reads one: parsed once, at the boundary, failing loudly on a malformed message.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from cics.screen.cursor import CursorPosition, cursor_from_message

FieldsMessage = Mapping[str, str]
AttrsMessage = Mapping[str, Mapping[str, int]]
Scalar = str | int
MessageValue = str | bool | FieldsMessage | AttrsMessage | Mapping[str, Scalar]
ScreenMessage = Mapping[str, MessageValue]


class SendMode(Enum):
    FULL = "full"
    DATAONLY = "dataonly"
    MAPONLY = "maponly"


@dataclass(frozen=True)
class FieldAttributes:
    """A field's symbolic-map <f>A, <f>C and <f>H bytes. Zero means the program
    left the map's own value in place."""

    attr: int = 0
    color: int = 0
    hilight: int = 0

    @property
    def overrides(self) -> bool:
        return any((self.attr, self.color, self.hilight))

    def to_message(self) -> Mapping[str, int]:
        return {"attr": self.attr, "color": self.color, "hilight": self.hilight}


NO_OVERRIDE = FieldAttributes()


@dataclass(frozen=True)
class SendMapPayload:
    map: str
    mapset: str
    mode: SendMode
    erase: bool
    alarm: bool
    frset: bool
    freekb: bool
    cursor: CursorPosition
    fields: Mapping[str, str]
    attrs: Mapping[str, FieldAttributes]

    def to_message(self) -> dict[str, MessageValue]:
        return {
            "map": self.map,
            "mapset": self.mapset,
            "mode": self.mode.value,
            "erase": self.erase,
            "alarm": self.alarm,
            "frset": self.frset,
            "freekb": self.freekb,
            "cursor": self.cursor.to_message(),
            "fields": dict(self.fields),
            "attrs": {name: a.to_message() for name, a in self.attrs.items()},
        }


@dataclass(frozen=True)
class SendTextPayload:
    text: str

    def to_message(self) -> dict[str, MessageValue]:
        return {"type": "text", "text": self.text}


ScreenPayload = SendMapPayload | SendTextPayload


def _str(message: ScreenMessage, field: str) -> str:
    value = message[field]
    if not isinstance(value, str):
        raise TypeError(f"screen message {field!r} must be a string, got {value!r}")
    return value


def _bool(message: ScreenMessage, field: str) -> bool:
    value = message[field]
    if not isinstance(value, bool):
        raise TypeError(f"screen message {field!r} must be a bool, got {value!r}")
    return value


def _mapping(
    message: ScreenMessage, field: str
) -> FieldsMessage | AttrsMessage | Mapping[str, Scalar]:
    value = message[field]
    if isinstance(value, str | bool):
        raise TypeError(f"screen message {field!r} must be a mapping, got {value!r}")
    return value


def _scalar(value: Scalar | Mapping[str, int]) -> Scalar:
    if isinstance(value, Mapping):
        raise TypeError(f"expected a string or integer, got {value!r}")
    return value


def _attributes(value: Scalar | Mapping[str, int]) -> FieldAttributes:
    if not isinstance(value, Mapping):
        raise TypeError(f"field attributes must be a mapping, got {value!r}")
    return FieldAttributes(value["attr"], value["color"], value["hilight"])


def _map_payload(message: ScreenMessage) -> SendMapPayload:
    cursor = {k: _scalar(v) for k, v in _mapping(message, "cursor").items()}
    fields = {k: str(_scalar(v)) for k, v in _mapping(message, "fields").items()}
    attrs = {k: _attributes(v) for k, v in _mapping(message, "attrs").items()}
    return SendMapPayload(
        map=_str(message, "map"),
        mapset=_str(message, "mapset"),
        mode=SendMode(_str(message, "mode")),
        erase=_bool(message, "erase"),
        alarm=_bool(message, "alarm"),
        frset=_bool(message, "frset"),
        freekb=_bool(message, "freekb"),
        cursor=cursor_from_message(cursor),
        fields=MappingProxyType(fields),
        attrs=MappingProxyType(attrs),
    )


def screen_payload(message: ScreenMessage) -> ScreenPayload:
    if message.get("type") == "text":
        return SendTextPayload(text=_str(message, "text"))
    return _map_payload(message)

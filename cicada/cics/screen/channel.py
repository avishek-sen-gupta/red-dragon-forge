"""Reading every screen a region has sent so far off its screen channel."""

from __future__ import annotations

import queue
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial

from cics.screen.payload import ScreenMessage, ScreenPayload, screen_payload
from cics.terminal import ScreenChannel


@dataclass(frozen=True)
class _Drained:
    pass


_DRAINED = _Drained()


def _next_message(channel: ScreenChannel) -> ScreenMessage | _Drained:
    try:
        return channel.get(block=False)
    except queue.Empty:
        return _DRAINED


def _messages(channel: ScreenChannel) -> Iterator[ScreenMessage]:
    pending = iter(partial(_next_message, channel), _DRAINED)
    return (m for m in pending if not isinstance(m, _Drained))


def drain_screens(channel: ScreenChannel) -> tuple[ScreenPayload, ...]:
    return tuple(screen_payload(message) for message in _messages(channel))

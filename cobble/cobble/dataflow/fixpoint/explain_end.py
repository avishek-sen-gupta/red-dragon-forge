"""What a worker sends after the last explain row it has."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExplainEnd:
    """The worker has sent every row it will send for this request."""

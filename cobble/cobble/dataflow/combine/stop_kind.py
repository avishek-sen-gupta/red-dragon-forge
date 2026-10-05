"""StopKind — where a backwards walk inside one program can end."""

from enum import Enum


class StopKind(Enum):
    RECEIVED = "received"
    RETURNED = "returned"
    RETRIEVED = "retrieved"
    UNKNOWN = "unknown"

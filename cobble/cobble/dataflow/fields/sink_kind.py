"""Where bytes leave a program."""

from enum import StrEnum


class SinkKind(StrEnum):
    """The closed set of output destinations; NONE means the bytes stay in the program."""

    NONE = "NONE"
    FILE = "FILE"
    MAP = "MAP"
    TS_QUEUE = "TS_QUEUE"
    TD_QUEUE = "TD_QUEUE"
    TRANSID = "TRANSID"

"""The statement kinds of cobol.dbscheme's stmts table."""

from enum import IntEnum


class StmtKind(IntEnum):
    OTHER = 0
    MOVE = 1
    ACCEPT = 2
    DISPLAY = 3
    PERFORM = 4
    GOTO = 5
    IF = 6
    STOP_RUN = 7
    GOBACK = 8
    INLINE_PERFORM = 9

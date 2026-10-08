"""How a program receives a handed-over area: as its commarea, or as a USING parameter."""

from enum import StrEnum


class AreaKind(StrEnum):
    """LINK and XCTL hand over a commarea; CALL hands over its USING arguments."""

    COMMAREA = "commarea"
    USING = "using"

"""How a call site's callees were known when the area need charged it."""

from enum import StrEnum


class SiteResolution(StrEnum):
    """Named by a literal; dynamic and resolved to its callees; dynamic and
    unresolved, so charged every member's need; or a callee outside the corpus."""

    STATIC = "static"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    OUTSIDE = "outside"

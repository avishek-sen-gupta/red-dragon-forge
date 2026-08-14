"""STARTBR positioning modes."""

from __future__ import annotations

from enum import Enum


class BrowseStart(Enum):
    """Where STARTBR leaves the cursor. Values are access-method relops.

    EQUAL demands an exact key match and yields NOTFND otherwise; GTEQ (the CICS
    default) settles for the next higher key. A GENERIC browse needs no member of
    its own — a short KEYLENGTH already narrows the driver's key comparison.
    """

    EQUAL = "="
    GTEQ = ">="

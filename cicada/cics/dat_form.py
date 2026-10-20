"""The region's DATFORM: the order of day, month and year in a FORMATTIME DATE."""

from __future__ import annotations

from enum import Enum


class DatForm(Enum):
    MMDDYY = "MMDDYY"
    DDMMYY = "DDMMYY"
    YYMMDD = "YYMMDD"

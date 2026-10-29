"""The Souffle type of one relation column."""

from enum import StrEnum


class ColumnType(StrEnum):
    SYMBOL = "symbol"
    NUMBER = "number"

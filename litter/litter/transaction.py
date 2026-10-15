"""A CICS transaction: the transid a terminal enters and the program it starts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Transaction:
    transid: str
    program: str

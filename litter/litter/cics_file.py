"""One CSD DEFINE FILE: the name a program opens and the dataset behind it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CicsFile:
    name: str
    dsname: str

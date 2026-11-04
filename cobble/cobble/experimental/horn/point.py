"""A program point: a CFG node, named with the program it belongs to."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    program: str
    node: str

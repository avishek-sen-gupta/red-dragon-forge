"""A solver's answer with the time it took."""

from dataclasses import dataclass

from cobble.experimental.horn.answer import Answer


@dataclass(frozen=True)
class Verdict:
    answer: Answer
    seconds: float

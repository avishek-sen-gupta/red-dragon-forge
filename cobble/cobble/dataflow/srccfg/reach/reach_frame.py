"""One open PERFORM: where it resumes, and the range end it returns from."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReachFrame:
    resume: str
    end: str

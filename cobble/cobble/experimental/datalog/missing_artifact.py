"""A run artifact the facts need that the run does not hold."""

from pathlib import Path


class MissingArtifactError(Exception):
    def __init__(self, path: Path) -> None:
        super().__init__(f"missing {path}")
        self.path = path

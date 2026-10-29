"""The files of a run directory, each refused by name when absent."""

from pathlib import Path

from cobble.experimental.datalog.missing_artifact import MissingArtifactError


def required(path: Path) -> Path:
    if not path.exists():
        raise MissingArtifactError(path)
    return path


def lines(path: Path) -> tuple[str, ...]:
    text = required(path).read_text(encoding="utf-8")
    return tuple(line for line in text.split("\n") if line.strip())


def matching(directory: Path, pattern: str) -> tuple[Path, ...]:
    found = tuple(sorted(required(directory).glob(pattern)))
    if not found:
        raise MissingArtifactError(directory / pattern)
    return found

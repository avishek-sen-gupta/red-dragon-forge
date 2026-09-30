"""CopybookDir — a configured copybook directory ProLeap can scan, or why it cannot.

`File.listFiles()` returns null for anything that is not an existing directory,
and ProLeap's `CobolWordCopyBookFinderImpl` reads `.length` off it unguarded. So
a `copybook_dirs` entry that is absent, or that points at a file, is not a
missing copybook -- it is a NullPointerException on every member of the corpus,
which each JVM stage then records as that member's permanent failure. Correcting
the config afterwards does not clear those records, because a `.fail` is never
retried (red-dragon-forge-jbh).

Classified rather than merely counted, on the same grounds as FileLocation: "you
have not generated sym/ yet" and "that path is a file" are different mistakes and
want different answers from whoever reads the message.

Nothing here raises. Deciding is separate from acting on the decision; the acting
lives in parse_corpus.copybook_dirs, which is the only caller that knows a run is
about to start and can end it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class NoCopybookDirReason(Enum):
    # Nothing at that path. The usual cause is a directory an earlier stage
    # writes -- `sym`, which cobble-sym generates -- read before it was run.
    ABSENT = "absent"
    # Something is there, but it is not a directory, so listFiles() is null for
    # it exactly as for an absent path. Usually a config naming a copybook
    # rather than the directory holding it.
    NOT_A_DIRECTORY = "not_a_directory"


@dataclass(frozen=True)
class NoCopybookDir:
    path: Path
    reason: NoCopybookDirReason


CopybookDir = Path | NoCopybookDir


def classified(path: Path) -> CopybookDir:
    match (path.exists(), path.is_dir()):
        case (False, _):
            return NoCopybookDir(path, NoCopybookDirReason.ABSENT)
        case (_, False):
            return NoCopybookDir(path, NoCopybookDirReason.NOT_A_DIRECTORY)
        case _:
            return path


def unscannable(dirs: Sequence[Path]) -> tuple[NoCopybookDir, ...]:
    """Only the entries ProLeap would NPE on, each carrying why."""
    return tuple(d for d in map(classified, dirs) if isinstance(d, NoCopybookDir))

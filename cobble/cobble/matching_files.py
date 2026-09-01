"""matching_files.py — the one way cobble turns a (directory, globs) pair from
a corpus config into a file list.

Every stage that reads a configured directory (`build_graph`'s JCL/COBOL
passes, `corpus_index`'s program/JCL indexing, `generate_sym`'s BMS maps) must
select the same files in the same order, or a node resolved by one stage won't
match the node written by another. Sharing this function is what makes that
true by construction rather than by three copies staying in sync.
"""

from __future__ import annotations

from pathlib import Path


def matching_files(directory: Path, globs: tuple[str, ...]) -> list[Path]:
    """The files in *directory* matching any of *globs*, deduplicated, sorted.

    Sorted by path rather than grouped by glob, so reordering a config's globs
    doesn't reorder the corpus. A glob may name a subdirectory
    (``"SRC/*.txt"``) for a corpus whose members live under one root in
    sibling directories. A directory that doesn't exist yields nothing:
    `Path.glob` is lazy about that, and an absent optional directory is a
    config fact, not an error to raise here.
    """
    return sorted({p for pattern in globs for p in directory.glob(pattern)})

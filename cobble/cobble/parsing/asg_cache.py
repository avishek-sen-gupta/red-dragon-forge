"""asg_cache.py — the naming rule for a parsed corpus, and reading one back.

The name of a cached ASG is a pure function of the source FILENAME: MYPROG01.txt
becomes MYPROG01.json, and nothing about the program's contents takes part. That
is what lets every stage after the parse find a member's ASG from the member's
path alone -- no index to load, no map to keep in step with the directory, and a
cache directory a person can read with ls.

Not the PROGRAM-ID, deliberately. Two members declaring the same PROGRAM-ID is
normal on a real corpus (a copy taken for a release, a member and its harness),
and naming the cache after it would make one member's ASG answer for both.
"""

from __future__ import annotations

import json
from pathlib import Path

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobol_asg.asg_types import CobolASG

FAILURE_SUFFIX = ".fail"


def cache_path(asg_dir: Path, source: Path) -> Path:
    return asg_dir / f"{source.stem}.json"


def failure_path(asg_dir: Path, source: Path) -> Path:
    """Where a member that will not parse is recorded.

    Beside the ASG rather than in a log, because the next run has to skip it: a
    missing copybook is permanent until the copybook arrives, and re-paying 5
    seconds of JVM per unparseable member on every run is the cost this avoids.
    """
    return asg_dir / f"{source.stem}{FAILURE_SUFFIX}"


def is_cached(asg_dir: Path, source: Path) -> bool:
    """Whether this member has been through the parser, successfully or not."""
    return (
        cache_path(asg_dir, source).exists() or failure_path(asg_dir, source).exists()
    )


def asg_of(asg_dir: Path, source: Path) -> CobolASG:
    """One member's ASG, read from the cache.

    Raises rather than parsing on the spot. A stage that silently starts a JVM here
    turns a forgotten cobble-parse-corpus into a four-hour run that looks like a
    slow one, and the message below is the difference between "the cache is empty"
    and "this member is missing from it".
    """
    path = cache_path(asg_dir, source)
    if not path.exists():
        raise FileNotFoundError(
            f"{source.name}: no cached ASG at {path} (run cobble-parse-corpus first)"
        )
    return CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))


def cached_asg(asg_dir: Path, source: Path) -> CobolASG:
    """One member's ASG from the cache, its coprocessor statements read back.

    The cache holds EXEC CICS already parsed, which only the serialized form's
    dialect parser reconstructs; the bridge's reads it back as an empty verb.
    """
    with cached_asg_dialect_parsers_registered():
        return asg_of(asg_dir, source)

"""asg_cache.py — the naming rule for a parsed corpus, and reading one back.

The name of a cached ASG is a pure function of the source FILENAME: MYPROG01.txt
becomes MYPROG01.json, and nothing about the program's contents takes part. That
is what lets every stage after the parse find a member's ASG from the member's
path alone -- no index to load, no map to keep in step with the directory, and a
cache directory a person can read with ls.

Not the PROGRAM-ID, deliberately. Two members declaring the same PROGRAM-ID is
normal on a real corpus (a copy taken for a release, a member and its harness),
and naming the cache after it would make one member's ASG answer for both.

A member is a compilation unit: one or more programs, written one after another or
contained one in another. The cache holds the whole unit, so a reader says which it
means -- every program, in pre-order, or the first, the one the member's name means.
"""

from __future__ import annotations

import json
from pathlib import Path

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobol_asg.asg_types import CobolASG
from cobol_asg.compilation_unit import CobolCompilationUnit, programs_in_preorder
from cobol_asg.contained_programs import CONTAINED_PROGRAMS

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


def unit_json(unit: CobolCompilationUnit) -> str:
    """The text a member's cache file holds: the unit's programs, as the bridge
    writes them."""
    return json.dumps({CONTAINED_PROGRAMS: [asg.to_dict() for asg in unit.programs]})


def programs_at(path: Path) -> tuple[CobolASG, ...]:
    """Every program in one cache file, in pre-order, each without the programs
    it contains."""
    return tuple(
        CobolASG.from_dict(program)
        for program in programs_in_preorder(
            json.loads(path.read_text(encoding="utf-8"))
        )
    )


def first_program_at(path: Path) -> CobolASG:
    """The first top-level program in one cache file."""
    return CobolCompilationUnit.from_dict(
        json.loads(path.read_text(encoding="utf-8"))
    ).first_program


def _cached(asg_dir: Path, source: Path) -> Path:
    """Raises rather than parsing on the spot. A stage that silently starts a JVM
    here turns a forgotten cobble-parse-corpus into a four-hour run that looks like
    a slow one, and the message below is the difference between "the cache is
    empty" and "this member is missing from it"."""
    path = cache_path(asg_dir, source)
    if not path.exists():
        raise FileNotFoundError(
            f"{source.name}: no cached ASG at {path} (run cobble-parse-corpus first)"
        )
    return path


def programs_of(asg_dir: Path, source: Path) -> tuple[CobolASG, ...]:
    """Every program of one member, read from the cache, in pre-order."""
    return programs_at(_cached(asg_dir, source))


def first_program_of(asg_dir: Path, source: Path) -> CobolASG:
    """One member's first program, read from the cache."""
    return first_program_at(_cached(asg_dir, source))


def cached_first_program(asg_dir: Path, source: Path) -> CobolASG:
    """One member's first program from the cache, its coprocessor statements read
    back.

    The cache holds EXEC CICS already parsed, which only the serialized form's
    dialect parser reconstructs; the bridge's reads it back as an empty verb.
    """
    with cached_asg_dialect_parsers_registered():
        return first_program_of(asg_dir, source)

"""Build one CFG per cached ASG.

No JVM: the ASG cache is the whole input. A member that raises is reported and the
run continues, because the answer wanted from a corpus pass is "which members are
missing from this output", and a run that aborts answers that for one member only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.bundle import one_cfg_document
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.config import SrcCfgCorpusConfig
from cobble.dataflow.srccfg.dataflow import with_handler_edges
from cobble.path_utils import ensure_dir
from cobol_asg.asg_types import CobolASG

COLLISION_SEPARATOR = "__"


@dataclass(frozen=True)
class MemberResult:
    member: str
    cfg_path: Path = Path()  # The path where the CFG JSON was written (not input path)
    message: str = ""


def built(result: MemberResult) -> bool:
    """Whether this member produced a CFG, which is not the same as having no message.

    A name collision is a message about a file that WAS written, and it must not be
    counted with the members that produced nothing -- the count of missing members is
    the number the run exists to report.
    """
    return result.cfg_path != Path()


def asg_paths(asg_dir: Path) -> tuple[Path, ...]:
    return tuple(sorted(asg_dir.glob("*.json")))


def source_file_of(source_dir: Path, member: str) -> str:
    """The member's source file, relative to source_dir's parent; "" without one.

    Named for the member -- the file the ASG was parsed from -- never for its
    PROGRAM-ID, which is an identifier inside the source that two members can share."""
    if source_dir == Path():
        return ""
    return str((source_dir / f"{member}.txt").relative_to(source_dir.parent))


def build_one(
    path: Path,
    out_dir: Path,
    taken: frozenset[Path] = frozenset(),
    source_dir: Path = Path(),
) -> MemberResult:
    """One member's CFG, written to a file named for its PROGRAM-ID.

    ``taken`` is the set of paths this run has already written. Two members declaring
    the same PROGRAM-ID is normal on a real corpus -- a copy taken for a release, a
    member and its test harness -- and the output file is named for the program, so the
    second member silently replaced the first. Both members then answered every query
    with one member's graph, and nothing anywhere said so.
    """
    member = path.stem
    try:
        cfg = cfg_of(path, source_file=source_file_of(source_dir, member))
    except Exception as error:  # noqa: BLE001 - one member must not end the run
        return MemberResult(member=member, message=f"{member}: {error!r}")
    ensure_dir(out_dir)
    return _write(cfg, member, out_dir / f"{cfg.program or member}.json", taken)


def _write(
    cfg: Cfg, member: str, preferred: Path, taken: frozenset[Path]
) -> MemberResult:
    """Write the CFG, under a qualified name if the preferred one is already used."""
    collided = preferred in taken
    written = (
        preferred.with_name(f"{preferred.stem}{COLLISION_SEPARATOR}{member}.json")
        if collided
        else preferred
    )
    written.write_text(one_cfg_document(cfg), encoding="utf-8")
    return MemberResult(
        member=member,
        cfg_path=written,
        message=_collision(member, cfg.program, written) if collided else "",
    )


def _collision(member: str, program: str, written: Path) -> str:
    """Said in full, because the reader has to decide which member they meant.

    Overwriting is not an option: it makes one member's graph answer for two, and the
    query reports no such thing. Skipping is not either -- that drops a member from the
    output, which the next pass reads as a field written nowhere."""
    return (
        f"{member}: PROGRAM-ID {program} is already built from another member; "
        f"wrote {written.name} instead of overwriting"
    )


def cfg_of(path: Path, source_file: str = "") -> Cfg:
    """One member's CFG, with its CICS handler transfers resolved."""
    with cached_asg_dialect_parsers_registered():
        asg = CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
    return with_handler_edges(build_program(asg, source_file=source_file))


@dataclass(frozen=True)
class _Progress:
    """The results so far and the output paths they have used."""

    results: tuple[MemberResult, ...] = ()
    taken: frozenset[Path] = frozenset()


def build_corpus(config: SrcCfgCorpusConfig) -> tuple[MemberResult, ...]:
    """Every member, in cache order, no member's output overwriting another's."""
    return reduce(
        lambda progress, path: _extended(
            progress, build_one(path, config.out_dir, progress.taken, config.source_dir)
        ),
        asg_paths(config.asg_dir),
        _Progress(),
    ).results


def _extended(progress: _Progress, result: MemberResult) -> _Progress:
    return _Progress(
        results=(*progress.results, result),
        taken=progress.taken | {result.cfg_path},
    )

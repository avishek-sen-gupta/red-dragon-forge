"""cobble-dataflow-area-need: which handed-over bytes the corpus's call targets read, once per corpus."""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing
import sys
from collections.abc import Sequence
from functools import reduce
from itertools import accumulate, count, pairwise
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.emit_extents import worker_count
from cobble.dataflow.fields.extents_input import member_layout, member_rows
from cobble.dataflow.fields.spans import pairs_of
from cobble.dataflow.fixpoint.area_need import AreaNeed, joined
from cobble.dataflow.fixpoint.area_need_file import AreaNeedFile
from cobble.dataflow.fixpoint.area_needs import need_found, prepared
from cobble.dataflow.fixpoint.prepared_program import PreparedProgram
from cobble.dataflow.fixpoint.rows import Row
from cobol_asg.asg_types import CobolASG

logger = logging.getLogger(__name__)

_Job = tuple[int, str, tuple[Row, ...], Path]
_Held = tuple[int, PreparedProgram]
_Round = tuple[int, AreaNeed]
_STOP: _Round = (0, AreaNeed())


def _loaded(job: _Job, total: int) -> tuple[_Held, ...]:
    """One member loaded and prepared. A member that cannot be read adds nothing:
    its own targets go unresolved in the fixpoint anyway."""
    position, member, block, path = job
    logger.info("area need: loading [%d/%d] %s", position, total, member)
    try:
        with cached_asg_dialect_parsers_registered():
            asg = CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
            return (
                (position, prepared(member, asg, member_layout(member, block).layout)),
            )
    except Exception as error:  # noqa: BLE001 - one member must not end the run
        logger.warning("area need: %s unreadable: %r", member, error)
        return ()


def _walked(held: _Held, need: AreaNeed, number: int, total: int) -> AreaNeed:
    position, program = held
    logger.info(
        "area need round %d: [%d/%d] %s", number, position, total, program.member
    )
    return need_found(program, need)


def _shard(connection: Connection, jobs: tuple[_Job, ...], total: int) -> None:
    """One worker process: its share of the members, loaded once and kept for every
    round, so only the need crosses between processes, never a program."""
    configure_cli_logging()
    programs = tuple(held for job in jobs for held in _loaded(job, total))
    for number, need in iter(connection.recv, _STOP):
        connection.send(
            reduce(
                joined,
                (_walked(held, need, number, total) for held in programs),
                AreaNeed(),
            )
        )


def _need_bytes(bounds: tuple[tuple[int, tuple[int, ...]], ...]) -> int:
    return sum(high - low for _, one in bounds for low, high in pairs_of(one))


def _round(need: AreaNeed, number: int, pipes: Sequence[Connection]) -> AreaNeed:
    for pipe in pipes:
        pipe.send((number, need))
    found = reduce(joined, (pipe.recv() for pipe in pipes), need)
    logger.info(
        "area need round %d: %d bytes needed on entry, %d read back",
        number,
        _need_bytes(found.entry),
        _need_bytes(found.back),
    )
    return found


def _jobs(arguments: argparse.Namespace) -> tuple[_Job, ...]:
    logger.info("area need: reading the member list from %s", arguments.extents)
    present = (
        (member, block)
        for member, block in member_rows(arguments.extents)
        if (arguments.asg_dir / f"{member}.json").is_file()
    )
    jobs = tuple(
        (position, member, block, arguments.asg_dir / f"{member}.json")
        for position, (member, block) in enumerate(present, 1)
    )
    logger.info("area need: %d members to load", len(jobs))
    return jobs


_Shards = tuple[tuple[Connection, ...], tuple[BaseProcess, ...]]


def _started(jobs: tuple[_Job, ...], workers: int) -> _Shards:
    shards = min(workers, len(jobs))
    context = multiprocessing.get_context("spawn")
    pipes = tuple(context.Pipe() for _ in range(shards))
    processes = tuple(
        context.Process(
            target=_shard, args=(child, jobs[shard::shards], len(jobs)), daemon=True
        )
        for shard, (_, child) in enumerate(pipes)
    )
    for process in processes:
        process.start()
    return tuple(parent for parent, _ in pipes), processes


def _stopped(shards: _Shards) -> None:
    parents, processes = shards
    for parent in parents:
        parent.send(_STOP)
    for process in processes:
        process.join()


def _settled(parents: tuple[Connection, ...]) -> AreaNeed:
    rounds = accumulate(
        count(1),
        lambda need, number: _round(need, number, parents),
        initial=AreaNeed(),
    )
    return next(after for before, after in pairwise(rounds) if before == after)


def computed(arguments: argparse.Namespace) -> AreaNeed:
    """Rounds of liveness over every member in the extents table until one adds
    nothing: what a callee reads can make its caller forward more, which a callee
    then reads. Each worker keeps its share of the members for the whole run."""
    jobs = _jobs(arguments)
    if not jobs:
        return AreaNeed()
    shards = _started(jobs, arguments.max_workers)
    need = _settled(shards[0])
    _stopped(shards)
    return need


def _parsed(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cobble-dataflow-area-need",
        description=__doc__,
    )
    parser.add_argument("--asg-dir", type=Path, required=True)
    parser.add_argument("--extents", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-workers", type=worker_count, default=4)
    return parser.parse_args(argv)


def cli(argv: Sequence[str]) -> int:
    arguments = _parsed(argv)
    if not arguments.extents.is_file():
        sys.stderr.write(f"area need: !! no extents table at {arguments.extents}\n")
        return 2
    need = computed(arguments)
    arguments.out.write_text(
        AreaNeedFile(entry=need.entry, back=need.back).model_dump_json(),
        encoding="utf-8",
    )
    logger.info("area need written to %s", arguments.out)
    return 0


def main() -> int:
    configure_cli_logging()
    return cli(sys.argv[1:])

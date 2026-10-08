"""cobble-dataflow-area-need: which handed-over bytes the corpus's call targets read, once per corpus."""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing
import sys
from collections.abc import Sequence
from itertools import accumulate, count, pairwise
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.emit_extents import worker_count
from cobble.dataflow.fields.extents_input import member_layout, member_rows
from cobble.dataflow.fields.spans import pairs_of
from cobble.dataflow.fixpoint.area_found import AreaFound
from cobble.dataflow.fixpoint.area_need import AreaNeed, Slotted
from cobble.dataflow.fixpoint.area_need_file import rows_of, write_rows
from cobble.dataflow.fixpoint.area_needs import need_found, prepared, resolved
from cobble.dataflow.fixpoint.area_table import AreaTable, Receives, area_table
from cobble.dataflow.fixpoint.prepared_program import PreparedProgram
from cobble.dataflow.fixpoint.rows import Row
from cobble.dataflow.fixpoint.shared_count import SharedCount
from cobol_asg.asg_types import CobolASG

logger = logging.getLogger(__name__)

_Job = tuple[int, str, tuple[Row, ...], Path]
_Held = tuple[int, PreparedProgram]
_Round = tuple[int, AreaTable, int, int]
_STOP: _Round = (0, AreaTable(), 0, 0)
_Loaded = tuple[Receives, tuple[str, ...]]


def _loaded(job: _Job, total: int, done: SharedCount) -> tuple[_Held, ...]:
    """One member loaded and prepared. A member that cannot be read adds nothing:
    its own targets go unresolved in the fixpoint anyway."""
    position, member, block, path = job
    try:
        with cached_asg_dialect_parsers_registered():
            asg = CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
            logger.info("area need: loading [%d/%d] %s", done.next(), total, member)
            return (
                (position, prepared(member, asg, member_layout(member, block).layout)),
            )
    except Exception as error:  # noqa: BLE001 - one member must not end the run
        logger.warning(
            "area need: [%d/%d] %s unreadable: %r", done.next(), total, member, error
        )
        return ()


def _walked(program: PreparedProgram, round_: _Round, done: SharedCount) -> AreaFound:
    number, table, base, total = round_
    found = need_found(program, table)
    logger.info(
        "area need round %d: [%d/%d] %s, %d bytes on entry",
        number,
        done.next() - base,
        total,
        program.member,
        _need_bytes(found.entry.entry),
    )
    return found


def _named(program: PreparedProgram) -> tuple[str, ...]:
    return tuple(
        entry[1].callee for entry in program.parts.entry if not entry[1].dynamic
    )


def _receiving(programs: tuple[_Held, ...]) -> _Loaded:
    return (
        tuple(
            (program.member, tuple(slot for slot, _ in program.received))
            for _, program in programs
        ),
        tuple(callee for _, program in programs for callee in _named(program)),
    )


def _shard(
    connection: Connection, jobs: tuple[_Job, ...], total: int, done: SharedCount
) -> None:
    """One worker process: its share of the members, loaded once and kept for every
    round, so only the table and the reports cross between processes, never a
    program. What its members receive and the callees they name go first."""
    configure_cli_logging()
    programs = tuple(held for job in jobs for held in _loaded(job, total, done))
    connection.send(_receiving(programs))
    for round_ in iter(connection.recv, _STOP):
        connection.send(
            tuple(_walked(program, round_, done) for _, program in programs)
        )


def _need_bytes(bounds: Slotted) -> int:
    return sum(high - low for _, one in bounds for low, high in pairs_of(one))


def _round(
    table: AreaTable,
    number: int,
    pipes: Sequence[Connection],
    receives: Receives,
    total: int,
) -> AreaTable:
    walked = len(receives)
    for pipe in pipes:
        pipe.send((number, table, total + (number - 1) * walked, walked))
    found: tuple[AreaFound, ...] = tuple(one for pipe in pipes for one in pipe.recv())
    after = resolved(found, receives)
    logger.info(
        "area need round %d: %d bytes needed on entry, %d read back,"
        " summed over %d members",
        number,
        sum(_need_bytes(need.entry) for _, need in after.needs),
        sum(_need_bytes(need.back) for _, need in after.needs),
        len(after.needs),
    )
    return after


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


_Shards = tuple[tuple[Connection, ...], tuple[BaseProcess, ...], SharedCount]


def _started(jobs: tuple[_Job, ...], workers: int) -> _Shards:
    shards = min(workers, len(jobs))
    context = multiprocessing.get_context("spawn")
    pipes = tuple(context.Pipe() for _ in range(shards))
    done = SharedCount(context.Value("i", 0))
    processes = tuple(
        context.Process(
            target=_shard,
            args=(child, jobs[shard::shards], len(jobs), done),
            daemon=True,
        )
        for shard, (_, child) in enumerate(pipes)
    )
    for process in processes:
        process.start()
    return tuple(parent for parent, _ in pipes), processes, done


def _stopped(shards: _Shards) -> None:
    """The count is held until here: a started process lets go of its arguments,
    and a count nothing in this process holds takes its lock with it."""
    parents, processes, _ = shards
    for parent in parents:
        parent.send(_STOP)
    for process in processes:
        process.join()


def _received(parents: tuple[Connection, ...]) -> Receives:
    loaded: tuple[_Loaded, ...] = tuple(parent.recv() for parent in parents)
    receives = tuple(pair for held, _ in loaded for pair in held)
    members = {member for member, _ in receives}
    named = {callee for _, callees in loaded for callee in callees}
    logger.info(
        "area need: %d members loaded; %d named callees are not among them,"
        " and every byte handed to one counts",
        len(members),
        len(named - members),
    )
    return receives


def _settled(parents: tuple[Connection, ...], total: int) -> AreaTable:
    receives = _received(parents)
    rounds = accumulate(
        count(1),
        lambda table, number: _round(table, number, parents, receives, total),
        initial=area_table(
            tuple((member, AreaNeed()) for member, _ in receives), receives
        ),
    )
    return next(after for before, after in pairwise(rounds) if before == after)


def computed(arguments: argparse.Namespace) -> AreaTable:
    """Rounds of liveness over every member in the extents table until the table
    stops changing: what a callee reads can make its caller forward more, which
    that caller's callers then read. Every member starts needing nothing, so the
    table grows to the least one that holds. Each worker keeps its share of the
    members for the whole run."""
    jobs = _jobs(arguments)
    if not jobs:
        return AreaTable()
    shards = _started(jobs, arguments.max_workers)
    table = _settled(shards[0], len(jobs))
    _stopped(shards)
    return table


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
    write_rows(rows_of(computed(arguments)), arguments.out)
    logger.info("area need written to %s", arguments.out)
    return 0


def main() -> int:
    configure_cli_logging()
    return cli(sys.argv[1:])

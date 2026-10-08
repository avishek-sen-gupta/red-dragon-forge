"""cobble-dataflow-area-need: which handed-over bytes the corpus's call targets read, once per corpus."""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import accumulate, count, pairwise, repeat, takewhile
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import TextIO

from cics.csd_parse import parse_csd
from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import load_corpus_config
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.emit_extents import worker_count
from cobble.dataflow.fields.extents_input import member_layout, member_rows
from cobble.dataflow.fields.spans import pairs_of
from cobble.dataflow.fixpoint.area_explain import explained
from cobble.dataflow.fixpoint.area_found import AreaFound
from cobble.dataflow.fixpoint.area_need import AreaNeed, Slotted
from cobble.dataflow.fixpoint.area_need_file import rows_of, write_rows
from cobble.dataflow.fixpoint.area_needs import need_found, prepared, resolved
from cobble.dataflow.fixpoint.area_table import AreaTable, Receives, area_table
from cobble.dataflow.fixpoint.explain_end import ExplainEnd
from cobble.dataflow.fixpoint.explain_request import ExplainRequest
from cobble.dataflow.fixpoint.explain_row import ExplainRow
from cobble.dataflow.fixpoint.prepared_program import PreparedProgram
from cobble.dataflow.fixpoint.rows import Row
from cobble.dataflow.fixpoint.shared_count import SharedCount
from cobble.dataflow.fixpoint.site_row import SiteRow
from cobble.dataflow.fixpoint.target_site import Sites, resolved_sites
from cobol_asg.asg_types import CobolASG

logger = logging.getLogger(__name__)

_Job = tuple[int, str, tuple[Row, ...], Path]
_Held = tuple[int, PreparedProgram]
_Round = tuple[int, AreaTable, int, int]
_STOP: _Round = (0, AreaTable(), 0, 0)
_Loaded = tuple[Receives, tuple[str, ...], Sites, tuple[SiteRow, ...]]
_Prepared = tuple[int, PreparedProgram, tuple[SiteRow, ...]]


def _loaded(
    job: _Job, total: int, done: SharedCount, programs: Mapping[str, str]
) -> tuple[_Prepared, ...]:
    """One member loaded and prepared. A member that cannot be read adds nothing:
    its own targets go unresolved in the fixpoint anyway."""
    position, member, block, path = job
    try:
        with cached_asg_dialect_parsers_registered():
            asg = CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
            logger.info("area need: loading [%d/%d] %s", done.next(), total, member)
            layout = member_layout(member, block).layout
            program, rows = prepared(member, asg, layout, programs)
            return ((position, _logged(program), rows),)
    except Exception as error:  # noqa: BLE001 - one member must not end the run
        logger.warning(
            "area need: [%d/%d] %s unreadable: %r", done.next(), total, member, error
        )
        return ()


def _logged(program: PreparedProgram) -> PreparedProgram:
    """Every dynamic site the member could not resolve, named with its reasons."""
    for node, answer in program.unresolved:
        logger.info(
            "area need: %s %s %s unresolved: %s",
            program.member,
            program.places.at(program.graph.order.index(node)),
            program.places.transfer(node),
            ", ".join(doubt.value for doubt in answer.doubts),
        )
    return program


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


def _receiving(programs: tuple[_Held, ...], rows: tuple[SiteRow, ...]) -> _Loaded:
    return (
        tuple(
            (program.member, tuple(slot for slot, _ in program.received))
            for _, program in programs
        ),
        tuple(callee for _, program in programs for callee in _named(program)),
        tuple(
            (program.member, node, callees)
            for _, program in programs
            for node, callees in program.sites
        ),
        rows,
    )


def _shard(
    connection: Connection,
    jobs: tuple[_Job, ...],
    total: int,
    done: SharedCount,
    programs: Mapping[str, str],
) -> None:
    """One worker process: its share of the members, loaded once and kept for every
    round, so only the table and the reports cross between processes, never a
    program. What its members receive and the callees they name go first; an
    explain request, after the last round, is answered for its own members."""
    configure_cli_logging()
    loaded = tuple(one for job in jobs for one in _loaded(job, total, done, programs))
    held = tuple((position, program) for position, program, _ in loaded)
    connection.send(_receiving(held, tuple(row for one in loaded for row in one[2])))
    for message in iter(connection.recv, _STOP):
        _handled(message, held, done, connection)


def _handled(
    message: _Round | ExplainRequest,
    programs: tuple[_Held, ...],
    done: SharedCount,
    connection: Connection,
) -> None:
    match message:
        case ExplainRequest() as request:
            _explained(programs, request, connection)
        case round_:
            connection.send(
                tuple(_walked(program, round_, done) for _, program in programs)
            )


def _explained(
    programs: tuple[_Held, ...], request: ExplainRequest, connection: Connection
) -> None:
    """Each held member the request names, or that needs at least its bytes, sent
    the moment it is explained; then the end of this worker's rows."""
    needs = dict(request.table.needs)
    chosen = (
        program
        for _, program in programs
        if program.member in request.members
        or 0 < request.over <= _need_bytes(needs[program.member].entry)
    )
    for program in chosen:
        connection.send(explained(program, request.table))
    connection.send(ExplainEnd())


def _need_bytes(bounds: Slotted) -> int:
    return sum(high - low for _, one in bounds for low, high in pairs_of(one))


def _round(
    table: AreaTable,
    number: int,
    pipes: Sequence[Connection],
    receives: Receives,
    sites: Sites,
    total: int,
) -> AreaTable:
    walked = len(receives)
    for pipe in pipes:
        pipe.send((number, table, total + (number - 1) * walked, walked))
    found: tuple[AreaFound, ...] = tuple(one for pipe in pipes for one in pipe.recv())
    after = resolved(found, receives, sites)
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


def _started(
    jobs: tuple[_Job, ...], workers: int, programs: Mapping[str, str]
) -> _Shards:
    shards = min(workers, len(jobs))
    context = multiprocessing.get_context("spawn")
    pipes = tuple(context.Pipe() for _ in range(shards))
    done = SharedCount(context.Value("i", 0))
    processes = tuple(
        context.Process(
            target=_shard,
            args=(child, jobs[shard::shards], len(jobs), done, programs),
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


def _received(
    parents: tuple[Connection, ...], sites_out: str
) -> tuple[Receives, Sites]:
    loaded: tuple[_Loaded, ...] = tuple(parent.recv() for parent in parents)
    _sites_written(tuple(row for one in loaded for row in one[3]), sites_out)
    receives = tuple(pair for one in loaded for pair in one[0])
    members = {member for member, _ in receives}
    named = {callee for one in loaded for callee in one[1]}
    sites = tuple(site for one in loaded for site in one[2])
    logger.info(
        "area need: %d members loaded; %d named callees are not among them,"
        " and every byte handed to one counts; %d dynamic sites resolved by"
        " reaching definitions in their own program",
        len(members),
        len(named - members),
        len(sites),
    )
    return receives, sites


def _sites_written(rows: tuple[SiteRow, ...], sites_out: str) -> None:
    """Every dynamic site in the corpus, one JSONL row each, before the first round."""
    if not sites_out:
        return
    Path(sites_out).write_text(
        "".join(f"{row.model_dump_json()}\n" for row in rows), encoding="utf-8"
    )
    logger.info(
        "area need: %d dynamic sites written to %s, %d unresolved",
        len(rows),
        sites_out,
        sum(1 for row in rows if not row.callees),
    )


def _settled(
    parents: tuple[Connection, ...], total: int, combined: Sites, sites_out: str
) -> AreaTable:
    receives, local = _received(parents, sites_out)
    sites = (*local, *combined)
    rounds = accumulate(
        count(1),
        lambda table, number: _round(table, number, parents, receives, sites, total),
        initial=area_table(
            tuple((member, AreaNeed()) for member, _ in receives), receives, sites
        ),
    )
    return next(after for before, after in pairwise(rounds) if before == after)


def _programs(arguments: argparse.Namespace) -> Mapping[str, str]:
    """Each transaction id the corpus config's CSD files define, to its program."""
    if not arguments.config:
        return {}
    return {
        transid: program
        for csd in load_corpus_config(Path(arguments.config)).csd_files
        for transid, program in parse_csd(csd).items()
    }


def _sites(arguments: argparse.Namespace, programs: Mapping[str, str]) -> Sites:
    if not arguments.combined_dir:
        return ()
    sites = resolved_sites(
        Path(arguments.fixpoint_dir), Path(arguments.combined_dir), programs
    )
    logger.info(
        "area need: %d resolved dynamic sites read from %s",
        len(sites),
        arguments.combined_dir,
    )
    return sites


def computed(arguments: argparse.Namespace, out: TextIO) -> AreaTable:
    """Rounds of liveness over every member in the extents table until the table
    stops changing: what a callee reads can make its caller forward more, which
    that caller's callers then read. Every member starts needing nothing, so the
    table grows to the least one that holds. Each worker keeps its share of the
    members for the whole run."""
    jobs = _jobs(arguments)
    if not jobs:
        return AreaTable()
    programs = _programs(arguments)
    shards = _started(jobs, arguments.max_workers, programs)
    table = _settled(shards[0], len(jobs), _sites(arguments, programs), arguments.sites)
    request = ExplainRequest(table, arguments.explain_over, _named_members(arguments))
    _report(shards[0], request, out)
    _stopped(shards)
    return table


def _named_members(arguments: argparse.Namespace) -> tuple[str, ...]:
    return (arguments.explain,) if arguments.explain else ()


@dataclass(frozen=True)
class _Draining:
    """The workers still sending rows, and the row the last message carried."""

    pending: frozenset[Connection]
    rows: tuple[ExplainRow, ...] = ()


def _drained(state: _Draining) -> _Draining:
    ready = _ready(state.pending)
    match ready.recv():
        case ExplainEnd():
            return _Draining(pending=state.pending - {ready})
        case row:
            return _Draining(pending=state.pending, rows=(row,))


def _ready(pending: frozenset[Connection]) -> Connection:
    waiting = wait(tuple(pending))
    return next(parent for parent in pending if parent in waiting)


def _arrivals(parents: tuple[Connection, ...]) -> Iterator[ExplainRow]:
    """Each row as whichever worker has one ready sends it, until every worker ends."""
    states = accumulate(
        repeat(None),
        lambda state, _: _drained(state),
        initial=_Draining(pending=frozenset(parents)),
    )
    return (
        row
        for state in takewhile(lambda state: bool(state.pending), states)
        for row in state.rows
    )


def _report(
    parents: tuple[Connection, ...], request: ExplainRequest, out: TextIO
) -> None:
    """The members the request names or that need its bytes, one JSONL row each,
    written and flushed as each arrives."""
    if request.over <= 0 and not request.members:
        return
    for parent in parents:
        parent.send(request)
    _written(_arrivals(parents), out)


def _written(rows: Iterator[ExplainRow], out: TextIO) -> None:
    for row in rows:
        out.write(f"{row.model_dump_json()}\n")
        out.flush()


def _parsed(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cobble-dataflow-area-need",
        description=__doc__,
    )
    parser.add_argument("--asg-dir", type=Path, required=True)
    parser.add_argument("--extents", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-workers", type=worker_count, default=4)
    _reporting_arguments(parser)
    _resolution_arguments(parser)
    return parser.parse_args(argv)


def _reporting_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--explain",
        default="",
        metavar="MEMBER",
        help="after the rounds, write a JSONL row to stdout saying why MEMBER needs"
        " the bytes it does: each demand source alone, and the writes that make more"
        " live than their target keeps",
    )
    parser.add_argument(
        "--explain-over",
        type=int,
        default=0,
        metavar="BYTES",
        help="after the rounds, write a JSONL row to stdout for every member needing"
        " at least BYTES bytes on entry, each as soon as its worker finishes it",
    )
    parser.add_argument(
        "--sites",
        default="",
        metavar="FILE",
        help="right after loading, before the first round, write every dynamic site"
        " in the corpus to FILE as JSONL: how its own program resolved it, or why"
        " not, and every write in the program touching its operand",
    )


def _resolution_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fixpoint-dir",
        default="",
        help="the cobble-dataflow-fixpoint output --combined-dir was combined from",
    )
    parser.add_argument(
        "--config",
        default="",
        help="the corpus config whose CSD files map a RETURN TRANSID's transaction"
        " to the program it runs; without it no RETURN TRANSID resolves",
    )
    parser.add_argument(
        "--combined-dir",
        default="",
        help="a cobble-dataflow-combine output: a dynamic XCTL, LINK or CALL it"
        " resolved completely, and a RETURN TRANSID whose transaction resolved, are"
        " charged with the needs of the programs they reach instead of every"
        " member's",
    )


def _refusal(arguments: argparse.Namespace) -> str:
    if not arguments.extents.is_file():
        return f"area need: !! no extents table at {arguments.extents}\n"
    return _explain_refusal(arguments) or _resolution_refusal(arguments)


def _explain_refusal(arguments: argparse.Namespace) -> str:
    if (
        arguments.explain
        and not (arguments.asg_dir / f"{arguments.explain}.json").is_file()
    ):
        return f"area need: !! no cached ASG for {arguments.explain}\n"
    return ""


def _resolution_refusal(arguments: argparse.Namespace) -> str:
    if bool(arguments.fixpoint_dir) != bool(arguments.combined_dir):
        return "area need: !! --fixpoint-dir and --combined-dir go together\n"
    if arguments.combined_dir and not arguments.config:
        return "area need: !! --combined-dir needs --config for its CSD\n"
    return ""


def cli(argv: Sequence[str]) -> int:
    arguments = _parsed(argv)
    refusal = _refusal(arguments)
    if refusal:
        sys.stderr.write(refusal)
        return 2
    table = computed(arguments, sys.stdout)
    write_rows(rows_of(table), arguments.out)
    logger.info("area need written to %s", arguments.out)
    return 0


def main() -> int:
    configure_cli_logging()
    return cli(sys.argv[1:])

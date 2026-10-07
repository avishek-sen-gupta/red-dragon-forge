"""cobble-dataflow-area-need: which handed-over bytes the corpus's call targets read, once per corpus."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from functools import reduce
from itertools import accumulate, count, pairwise
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


def _prepared_in_worker(
    job: tuple[str, tuple[Row, ...], Path],
) -> tuple[PreparedProgram, ...]:
    """One member loaded and prepared, once for every round. A member that cannot
    be read adds nothing: its own targets go unresolved in the fixpoint anyway."""
    member, block, path = job
    try:
        with cached_asg_dialect_parsers_registered():
            asg = CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))
            return (prepared(asg, member_layout(member, block).layout),)
    except Exception as error:  # noqa: BLE001 - one member must not end the run
        logger.warning("area need: %s unreadable: %r", member, error)
        return ()


def _found_in_worker(job: tuple[PreparedProgram, AreaNeed]) -> AreaNeed:
    return need_found(*job)


def _need_bytes(bounds: tuple[tuple[int, tuple[int, ...]], ...]) -> int:
    return sum(high - low for _, one in bounds for low, high in pairs_of(one))


def _noted(numbered: tuple[int, AreaNeed], total: int, number: int) -> AreaNeed:
    done, found = numbered
    if not done % 50 or done == total:
        logger.info("area need round %d: [%d/%d] members", number, done, total)
    return found


def _progressed(
    results: Iterator[AreaNeed], total: int, number: int
) -> Iterator[AreaNeed]:
    return map(lambda numbered: _noted(numbered, total, number), enumerate(results, 1))


def _round(
    need: AreaNeed,
    number: int,
    programs: tuple[PreparedProgram, ...],
    pool: ProcessPoolExecutor,
) -> AreaNeed:
    found = reduce(
        joined,
        _progressed(
            pool.map(
                _found_in_worker,
                ((program, need) for program in programs),
                chunksize=16,
            ),
            len(programs),
            number,
        ),
        need,
    )
    logger.info(
        "area need round %d: %d bytes needed on entry, %d read back",
        number,
        _need_bytes(found.entry),
        _need_bytes(found.back),
    )
    return found


def _programs(
    arguments: argparse.Namespace, pool: ProcessPoolExecutor
) -> tuple[PreparedProgram, ...]:
    jobs = tuple(
        (member, block, arguments.asg_dir / f"{member}.json")
        for member, block in member_rows(arguments.extents)
        if (arguments.asg_dir / f"{member}.json").is_file()
    )
    loaded = tuple(
        program
        for done, one in enumerate(pool.map(_prepared_in_worker, jobs, chunksize=8), 1)
        for program in _loaded_note(done, len(jobs), one)
    )
    logger.info("area need: %d members prepared", len(loaded))
    return loaded


def _loaded_note(
    done: int, total: int, one: tuple[PreparedProgram, ...]
) -> tuple[PreparedProgram, ...]:
    if not done % 50 or done == total:
        logger.info("area need: loading [%d/%d] members", done, total)
    return one


def computed(arguments: argparse.Namespace, pool: ProcessPoolExecutor) -> AreaNeed:
    """Every member loaded and prepared once, then rounds of liveness over all of
    them until one adds nothing: what a callee reads can make its caller forward
    more, which a callee then reads."""
    programs = _programs(arguments, pool)
    rounds = accumulate(
        count(1),
        lambda need, number: _round(need, number, programs, pool),
        initial=AreaNeed(),
    )
    return next(after for before, after in pairwise(rounds) if before == after)


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
    with ProcessPoolExecutor(
        max_workers=arguments.max_workers, initializer=configure_cli_logging
    ) as pool:
        need = computed(arguments, pool)
    arguments.out.write_text(
        AreaNeedFile(entry=need.entry, back=need.back).model_dump_json(),
        encoding="utf-8",
    )
    logger.info("area need written to %s", arguments.out)
    return 0


def main() -> int:
    configure_cli_logging()
    return cli(sys.argv[1:])

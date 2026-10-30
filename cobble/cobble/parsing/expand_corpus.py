"""expand_corpus.py — write every member's expanded source, one file per member.

The expanded source is what the COBOL grammar is actually handed: copybooks
inlined, continuations folded, comments stripped. It is the artifact to read when
a member will NOT parse, which is exactly the case where no ASG exists to read
instead -- on one corpus that is 328 of 3779 members.

    . ../bridge-env.sh
    uv run cobble-expand-corpus --config config/carddemo.toml --out-dir out-expanded

A stage of its own rather than a flag on cobble-parse-corpus, because the two
resume on different things. parse_corpus skips a member whose ASG is cached, so a
flag there would write nothing at all for a corpus that has already been parsed --
the normal state of a working corpus -- and an empty directory alongside exit 0 is
indistinguishable from a run that worked. This stage keys its skip on what it wrote
itself: a member is done once its .cbl or its .fail exists.

Which members and which copybook directories come from the [corpus] table every
other stage reads (corpus_config.py). Where each expansion lands comes from
parsing/expanded_cache.py. The destination is --out-dir rather than a TOML key
because nothing downstream consumes expanded source, so there is no second stage
to agree with.

parse_corpus is imported from rather than copied: Job, Result, bridge_jar and
record_failure mean the same things here, and the two stages must not disagree
about the bridge JAR or about how a member's failure is recorded.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.matching_files import matching_files
from cobble.parsing.expanded_cache import expanded_path, is_expanded
from cobble.parsing.parse_corpus import (
    Job,
    Result,
    bridge_jar,
    copybook_dirs,
    record_failure,
)
from cobble.parsing.precompiled import precompiled
from cobble.path_utils import ensure_dir
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import CobolParseError, RealSubprocessRunner

logger = logging.getLogger(__name__)


def pending(config: CorpusConfig, out_dir: Path) -> tuple[list[Job], int]:
    """The members still to expand, and how many *out_dir* already accounts for."""
    sources = matching_files(config.cobol_dir, config.cobol_globs)
    todo = [
        Job(source, expanded_path(out_dir, source))
        for source in sources
        if not is_expanded(out_dir, source)
    ]
    return todo, len(sources) - len(todo)


def _write_expansion(dest: Path, expanded: str) -> None:
    """latin-1, matching RealSubprocessRunner and the bridge's SOURCE_CHARSET, so a
    high byte in a VALUE literal survives. Written beside the target and renamed,
    so an interrupted run leaves no half-written file the next run skips as done."""
    tmp = dest.with_name(dest.name + ".partial")
    tmp.write_text(expanded, encoding="latin-1")
    os.replace(tmp, dest)


def expand_with(parser: ProLeapCobolParser, job: Job) -> Result:
    """Expand one member with an already-built parser."""
    t0 = time.perf_counter()
    try:
        expanded = parser.expand(precompiled(job.source.read_bytes()))
    except CobolParseError as exc:
        return record_failure(job, exc, time.perf_counter() - t0)
    _write_expansion(job.dest, expanded)
    return Result(job.stem, True, time.perf_counter() - t0, "")


def expand_one(
    job: Job,
    jar: str,
    copybook_dirs: Sequence[Path],
    exts: Sequence[str],
) -> Result:
    """One member, one JVM. Runs in a worker process."""
    parser = ProLeapCobolParser(
        RealSubprocessRunner(),
        jar,
        copybooks=CopybookSearch(dirs=tuple(copybook_dirs), exts=tuple(exts)),
    )
    return expand_with(parser, job)


def _report_failure(result: Result) -> None:
    if result.ok:
        return
    logger.info("    FAIL %s: %s", result.stem, result.error)


def _is_milestone(n: int, total: int) -> bool:
    """Every completion for the first 20, then every 25. A JVM starts per member,
    so the first result is the only proof the pool is alive at all."""
    return n <= 20 or n % 25 == 0 or n == total


def _report_milestone(result: Result, n: int, total: int, t0: float) -> None:
    if not _is_milestone(n, total):
        return
    elapsed = time.perf_counter() - t0
    rate = n / elapsed
    logger.info(
        "[%5d/%d] %5.1f/s %5.1fs %-10s elapsed=%.1fm eta=%.1fm",
        n,
        total,
        rate,
        result.seconds,
        result.stem,
        elapsed / 60,
        (total - n) / rate / 60,
    )


def _reported(results: Iterator[Result], total: int, t0: float) -> Iterator[Result]:
    for n, result in enumerate(results, 1):
        _report_failure(result)
        _report_milestone(result, n, total, t0)
        yield result


def _expanded(
    todo: Sequence[Job],
    jar: str,
    copybook_dirs: Sequence[Path],
    exts: Sequence[str],
    workers: int,
    t0: float,
) -> list[Result]:
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(expand_one, job, jar, copybook_dirs, exts) for job in todo
        ]
        logger.info("submitted, waiting on first result...")
        done = (future.result() for future in as_completed(futures))
        return list(_reported(done, len(todo), t0))


def _summarise(results: Sequence[Result], t0: float) -> None:
    ok = sum(1 for result in results if result.ok)
    logger.info(
        "done in %.1fm  ok %d  fail %d",
        (time.perf_counter() - t0) / 60,
        ok,
        len(results) - ok,
    )
    logger.info("slowest:")
    slowest = sorted(((r.seconds, r.stem) for r in results), reverse=True)[:10]
    for seconds, stem in slowest:
        logger.info("  %7.1fs  %s", seconds, stem)


def _planned(config: CorpusConfig, args: argparse.Namespace) -> list[Job]:
    ensure_dir(args.out_dir)
    todo, done = pending(config, args.out_dir)
    logger.info(
        "%s -> %s: %d expanded, %d to expand, %d workers",
        config.cobol_dir,
        args.out_dir,
        done,
        len(todo),
        args.jobs,
    )
    return todo


def _run(
    todo: Sequence[Job],
    dirs: Sequence[Path],
    config: CorpusConfig,
    args: argparse.Namespace,
    jar: str,
) -> int:
    t0 = time.perf_counter()
    results = _expanded(
        todo,
        jar,
        dirs,
        config.copybook_extensions,
        args.jobs,
        t0,
    )
    _summarise(results, t0)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a corpus TOML config (see cobble/corpus_config.py)",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Directory to write one expanded <member>.cbl into",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="Worker processes, each running its own JVM (default: one per core)",
    )
    return parser.parse_args()


def main() -> int:
    configure_cli_logging()
    args = _parse_args()
    config = load_corpus_config(args.config)
    jar = str(bridge_jar(os.environ))
    dirs = copybook_dirs(config)
    todo = _planned(config, args)
    if not todo:
        return 0
    return _run(todo, dirs, config, args, jar)


if __name__ == "__main__":
    raise SystemExit(main())

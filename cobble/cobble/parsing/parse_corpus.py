"""parse_corpus.py — parse every program in a corpus to a cached ASG JSON.

Every stage after this one is built over ASGs, so the ASGs have to exist first,
and a parse is 4-7 seconds of JVM. Caching them turns a four-hour corpus walk into
a one-minute one for every subsequent round of every judgment loop -- the
dependency graph's pass-through set, the source CFGs, the knowledge graph. One
corpus is 3779 programs and 557 MB of cache.

    . ../bridge-env.sh
    uv run cobble-parse-corpus --config config/carddemo.toml --jobs 10

Which programs, which copybook directories and extensions, and where the cache goes
come from the [corpus] table every other stage reads (corpus_config.py), so the
parse and the build cannot disagree about them; the bridge JAR comes from
PROLEAP_BRIDGE_JAR. Where each ASG lands comes from parsing/asg_cache.py, which is
also what every reader uses, so writer and readers cannot drift.

Resumable: a program with an existing .json is skipped, so an interrupted run
costs nothing; --force parses every program regardless. A .fail is not a reason
to skip: it records the last attempt, and the copybook it lacked may have arrived
or the bridge been fixed since, so a failed program is retried on every run. Each
parse is its own JVM subprocess, so the work is embarrassingly parallel -- --jobs
defaults to one worker per core.

Failures are expected and are not errors here. A missing copybook makes the
program unparseable, and 328 of the copybooks one corpus references are stubs for
foreign applications that are not in this corpus. Each failure writes
<program>.fail where the .json would have gone. A re-parse whose outcome changes
removes the other record, so a program never has both, and a stale ASG is never
read as current.

Only failures that are about the MEMBER are recorded that way -- the bridge
rejecting the source, and bridge output that will not deserialise. Anything else
ends the run. The write in particular sits outside the catch: a full disk or an
unwritable asg_dir is not evidence about a member, and recording it as one would
mark every member failed at once (red-dragon-forge-jbh).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.matching_files import matching_files
from cobble.parsing.asg_cache import cache_path, failure_path
from cobble.parsing.copybook_dir import unscannable
from cobble.path_utils import ensure_dir
from cobol_asg.asg_types import CobolASG
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import CobolParseError, RealSubprocessRunner

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    source: Path
    dest: Path

    @property
    def stem(self) -> str:
        return self.source.stem


@dataclass(frozen=True)
class Result:
    stem: str
    ok: bool
    seconds: float
    error: str


# One parser per worker PROCESS, built on first use and cached for the life of
# that process. It cannot be built in the parent and handed over -- it holds a
# subprocess runner -- and rebuilding it per program would re-read the copybook
# directory list 3779 times.
@lru_cache(maxsize=1)
def _parser_for(
    jar: str, copybook_dirs: tuple[str, ...], exts: tuple[str, ...]
) -> ProLeapCobolParser:
    return ProLeapCobolParser(
        RealSubprocessRunner(),
        jar,
        copybook_dirs=[Path(d) for d in copybook_dirs],
        copybook_exts=list(exts),
    )


def record_failure(job: Job, exc: Exception, seconds: float) -> Result:
    """Record *exc* as this member's failure, beside where its output would have
    gone, and drop any output an earlier attempt left there. Shared with
    expand_corpus: same record, same reason."""
    detail = f"{type(exc).__name__}: {exc}"
    job.dest.unlink(missing_ok=True)
    failure_path(job.dest.parent, job.source).write_text(detail[:2000])
    return Result(job.stem, False, seconds, detail[:120])


def _asg_for(parser: ProLeapCobolParser, job: Job) -> CobolASG:
    from cobble.cics.asg_dialect_scope import asg_dialect_parsers_registered

    with asg_dialect_parsers_registered():
        return parser.parse(job.source.read_bytes())


def _write_asg(dest: Path, asg: CobolASG) -> None:
    """Written beside the target and renamed, so an interrupted run never leaves
    a half-written ASG that the next run would skip as done."""
    tmp = dest.with_name(dest.name + ".partial")
    tmp.write_text(json.dumps(asg.to_dict()))
    os.replace(tmp, dest)


def parse_with(parser: ProLeapCobolParser, job: Job) -> Result:
    """Parse one member with an already-built parser.

    CobolParseError is the bridge rejecting the source; ValueError is bridge
    output cobble cannot deserialise, either malformed JSON or a statement type
    parse_statement does not know; KeyError is an ASG missing a field from_dict
    requires. All three are statements about this member. Nothing else is.
    """
    t0 = time.perf_counter()
    try:
        asg = _asg_for(parser, job)
    except (CobolParseError, ValueError, KeyError) as exc:
        return record_failure(job, exc, time.perf_counter() - t0)
    _write_asg(job.dest, asg)
    failure_path(job.dest.parent, job.source).unlink(missing_ok=True)
    return Result(job.stem, True, time.perf_counter() - t0, "")


def parse_one(
    job: Job, jar: str, copybook_dirs: tuple[str, ...], exts: tuple[str, ...]
) -> Result:
    """One member, one JVM. Runs in a worker process."""
    return parse_with(_parser_for(jar, copybook_dirs, exts), job)


def bridge_jar(environ: Mapping[str, str]) -> Path:
    """The ProLeap bridge JAR `make setup` built, as bridge-env.sh exports it."""
    if "PROLEAP_BRIDGE_JAR" not in environ:
        raise SystemExit(
            "PROLEAP_BRIDGE_JAR not set (source bridge-env.sh at the forge root)"
        )
    jar = Path(environ["PROLEAP_BRIDGE_JAR"])
    if not jar.is_file():
        raise SystemExit(
            f"bridge JAR not built: {jar} (run `make setup` at the forge root)"
        )
    return jar


def copybook_dirs(config: CorpusConfig) -> tuple[Path, ...]:
    """The corpus's copybook directories, once ProLeap can be trusted to scan them.

    The sibling of bridge_jar: the second of the two things the bridge needs
    before a corpus walk, refused here rather than 3779 times inside the pool.
    """
    bad = unscannable(config.copybook_dirs)
    if not bad:
        return config.copybook_dirs
    named = ", ".join(f"{d.path} ({d.reason.value})" for d in bad)
    raise SystemExit(
        f"copybook_dirs ProLeap cannot scan: {named} "
        f"(`sym` is written by cobble-sym; see red-dragon-forge-jbh)"
    )


def pending(config: CorpusConfig, force: bool = False) -> tuple[list[Job], int]:
    """The programs still to parse, and how many already have an ASG: every
    program without one, failed or never tried -- or, forced, every program."""
    sources = matching_files(config.cobol_dir, config.cobol_globs)
    todo = [
        Job(source, cache_path(config.asg_dir, source))
        for source in sources
        if force or not cache_path(config.asg_dir, source).exists()
    ]
    return todo, len(sources) - len(todo)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a corpus TOML config (see cobble/corpus_config.py)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="Worker processes, each running its own JVM (default: one per core)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Parse every program, including those that already have an ASG",
    )
    return parser.parse_args()


def _report_failure(result: Result) -> None:
    if result.ok:
        return
    logger.info("    FAIL %s: %s", result.stem, result.error)


def _is_milestone(n: int, total: int) -> bool:
    """Every completion for the first 20, then every 25. A JVM starts per parse,
    so the first result is the only proof the pool is alive at all -- waiting for
    25 of them before printing anything looks identical to a hang."""
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


def _results(
    todo: Sequence[Job],
    jar: str,
    copybook_dirs: tuple[str, ...],
    exts: tuple[str, ...],
    workers: int,
    t0: float,
) -> list[Result]:
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(parse_one, job, jar, copybook_dirs, exts) for job in todo
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
    ensure_dir(config.asg_dir)
    todo, done = pending(config, args.force)
    logger.info(
        "%s -> %s: %d cached, %d to parse, %d workers",
        config.cobol_dir,
        config.asg_dir,
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
    results = _results(
        todo,
        jar,
        tuple(str(d) for d in dirs),
        tuple(config.copybook_extensions),
        args.jobs,
        t0,
    )
    _summarise(results, t0)
    return 0


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

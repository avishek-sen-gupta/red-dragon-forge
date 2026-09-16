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

Resumable: a program with an existing .json or .fail is skipped, so an
interrupted run costs nothing. Each parse is its own JVM subprocess, so the work
is embarrassingly parallel -- --jobs defaults to one worker per core.

Failures are expected and are not errors here. A missing copybook makes the
program unparseable, and 328 of the copybooks one corpus references are stubs for
foreign applications that are not in this corpus. Each failure writes
<program>.fail where the .json would have gone, which is also what makes the skip
above cheap: a program that cannot parse is not retried on every run.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.matching_files import matching_files
from cobble.parsing.asg_cache import cache_path, failure_path, is_cached

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


# One parser per worker PROCESS, built on first use. It cannot be built in the
# parent and handed over -- it holds a subprocess runner -- and rebuilding it per
# program would re-read the copybook directory list 3779 times.
_parser = None


def _parser_for(jar: str, copybook_dirs: tuple[str, ...], exts: tuple[str, ...]):
    global _parser
    if _parser is None:
        from cobol_asg.cobol_parser import ProLeapCobolParser
        from cobol_asg.subprocess_runner import RealSubprocessRunner

        _parser = ProLeapCobolParser(
            RealSubprocessRunner(),
            jar,
            copybook_dirs=list(copybook_dirs),
            copybook_exts=list(exts),
        )
    return _parser


def parse_one(
    job: Job, jar: str, copybook_dirs: tuple[str, ...], exts: tuple[str, ...]
) -> Result:
    """Parse one program to JSON. Runs in a worker process."""
    t0 = time.perf_counter()
    try:
        from cobble.cics.asg_dialect_scope import asg_dialect_parsers_registered

        source = job.source.read_bytes()
        with asg_dialect_parsers_registered():
            asg = _parser_for(jar, copybook_dirs, exts).parse(source)
        # Written beside the target and renamed, so an interrupted run never
        # leaves a half-written ASG that the next run would skip as done.
        tmp = job.dest.with_name(job.dest.name + ".partial")
        tmp.write_text(json.dumps(asg.to_dict()))
        os.replace(tmp, job.dest)
        return Result(job.stem, True, time.perf_counter() - t0, "")
    except Exception as exc:  # a corpus member that will not parse is data, not a bug
        detail = f"{type(exc).__name__}: {exc}"
        failure_path(job.dest.parent, job.source).write_text(detail[:2000])
        return Result(job.stem, False, time.perf_counter() - t0, detail[:120])


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


def pending(config: CorpusConfig) -> tuple[list[Job], int]:
    """The programs still to parse, and how many the cache already holds."""
    sources = matching_files(config.cobol_dir, config.cobol_globs)
    todo = [
        Job(source, cache_path(config.asg_dir, source))
        for source in sources
        if not is_cached(config.asg_dir, source)
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
    return parser.parse_args()


def main() -> int:
    configure_cli_logging()
    args = _parse_args()
    config = load_corpus_config(args.config)
    jar = str(bridge_jar(os.environ))
    config.asg_dir.mkdir(parents=True, exist_ok=True)
    copybook_dirs = tuple(str(d) for d in config.copybook_dirs)
    exts = tuple(config.copybook_extensions)

    todo, done = pending(config)
    logger.info(
        "%s -> %s: %d cached, %d to parse, %d workers",
        config.cobol_dir,
        config.asg_dir,
        done,
        len(todo),
        args.jobs,
    )
    if not todo:
        return 0

    t0 = time.perf_counter()
    ok = bad = 0
    timings: list[tuple[float, str]] = []
    # Every completion for the first 20, then every 25. A JVM starts per parse, so
    # the first result is the only proof the pool is alive at all -- waiting for 25
    # of them before printing anything looks identical to a hang.
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(parse_one, j, jar, copybook_dirs, exts) for j in todo]
        logger.info("submitted, waiting on first result...")
        for n, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            ok, bad = ok + r.ok, bad + (not r.ok)
            timings.append((r.seconds, r.stem))
            if not r.ok and bad <= 20:
                logger.info("    FAIL %s: %s", r.stem, r.error)
            if n <= 20 or n % 25 == 0 or n == len(todo):
                elapsed = time.perf_counter() - t0
                rate = n / elapsed
                # "ok 12 fail 0" reads as "12 fail". Bind each number to its own
                # label with = and no gap.
                logger.info(
                    "[%5d/%d] ok=%-5d fail=%-5d %5.1f/s %5.1fs %-10s "
                    "elapsed=%.1fm eta=%.1fm",
                    n,
                    len(todo),
                    ok,
                    bad,
                    rate,
                    r.seconds,
                    r.stem,
                    elapsed / 60,
                    (len(todo) - n) / rate / 60 if rate else 0,
                )

    logger.info(
        "done in %.1fm  ok %d  fail %d", (time.perf_counter() - t0) / 60, ok, bad
    )
    logger.info("slowest:")
    for secs, stem in sorted(timings, reverse=True)[:10]:
        logger.info("  %7.1fs  %s", secs, stem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

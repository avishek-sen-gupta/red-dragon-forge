"""cobble.diagnosis.cobol — which COBOL programs the ProLeap bridge will not parse.

The build's COBOL phase runs one JVM per program over thousands of programs and
dies on the first rejection, without naming it until AstParseError was added. Even
named, one name per 40-minute run is a bisect, not a report: a corpus is onboarded
by fixing rejections in batches, and to batch them you have to see them all.

This runs the same parse with the same bridge, the same copybook flags and the same
parallelism, keeps going past every rejection, and reports the lot. It writes no
cache: each program's JSON is written and unlinked immediately, because the answer
here is a yes or no per program and the ASGs are ~300KB each.

What it adds over a list of failures is the grouping. 227 programs failing one way
is a config or a corpus-shape problem with a single fix; 227 failing forty ways is
a survey. Failures are grouped on a SIGNATURE -- the parser's own exception line
with the quoted source text and the line and column numbers stripped -- which is
also what makes grouping safe to log, because a ProLeap message quotes the bytes it
choked on. The full messages stay in the JSON, whose destination the caller picks.

Invoke as: PROLEAP_BRIDGE_JAR=<path> uv run diagnose-cobol --config <path>
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.diagnosis.report import RULE, emit_json, member_label
from interpreter.cobol.ast_store import AsgJsonParser
from interpreter.cobol.cobol_parser import make_cobol_parser
from cobble.matching_files import matching_files

logger = logging.getLogger(__name__)

# program -> {"type": ..., "message": ..., "signature": ...}
Unparseable = dict[str, dict[str, str]]


@dataclass(frozen=True)
class CheckResult:
    """One program: parsed, or the error that rejected it.

    ``kind`` is the marker of failure rather than ``message``, because an exception
    always has a class name and ``str(exc)`` can be empty. Nothing is counted for a
    program that parsed: whether its ASG is any good is the build's question, not
    this module's.
    """

    path: Path
    kind: str = ""
    message: str = ""


# (corpus, programs, worker count) -> one CheckResult per program. Injected into
# main so the CLI is testable without a JVM, which is the whole cost of this
# diagnostic. It takes the config because the bridge cannot be built without it:
# the copybook dirs and extensions have to match the build's or the answer is
# worth nothing.
Checker = Callable[[CorpusConfig, Sequence[Path], int], Sequence[CheckResult]]


@dataclass(frozen=True)
class Tally:
    """Programs parsed and programs rejected. That is the whole question."""

    parsed: int = 0
    failed: int = 0


def tally(results: Sequence[CheckResult]) -> Tally:
    parsed = tuple(result for result in results if not result.kind)
    return Tally(parsed=len(parsed), failed=len(results) - len(parsed))


# A quoted run is corpus source -- ProLeap quotes the token it choked on, and a
# missing-copybook error quotes the copybook name -- and a bare number is a line,
# a column or a timestamp. Both differ between two programs that fail identically,
# so stripping them is what makes a signature group and what makes it loggable.
_SOURCE_TEXT = re.compile(r"'[^']*'|\"[^\"]*\"|\[[^]]*\]|\b\d+\b")
# ProLeap's own line, wherever java put it: a fully qualified exception and its
# message. The stack trace under it says where ProLeap noticed, not what is wrong.
_PARSER_LINE = re.compile(r"(\S+(?:Exception|Error)): (.+)")


def _interesting_line(message: str) -> str:
    """The line that says what went wrong, out of the bridge's own logging.

    Most of a bridge stderr is java.util.logging INFO, an SLF4J warning and a stack
    trace. Falls back to the last non-empty line, so a bridge that dies before
    ProLeap runs -- no JAR, killed for memory -- still groups instead of vanishing.
    """
    lines = tuple(line.strip() for line in message.splitlines() if line.strip())
    matched = tuple(line for line in lines if _PARSER_LINE.search(line))
    if matched:
        found = _PARSER_LINE.search(matched[0])
        return found.group(0) if found else matched[0]
    return lines[-1] if lines else message


def signature(message: str) -> str:
    """What two failures have in common when they are the same failure.

    Quoted source text and numbers become ``?``, so programs whose stray byte or
    line number differ land in one group -- and so the result carries no corpus
    source and can be logged.
    """
    return _SOURCE_TEXT.sub("?", _interesting_line(message)).strip()


def find_unparseable(results: Sequence[CheckResult]) -> Unparseable:
    """The rejections in ``results``, by program, with the error and its signature.

    Sorted, and an empty mapping when everything parsed: the JSON is diffed between
    runs to see whether a fix moved the number, so "none left" has to be
    expressible rather than absent.
    """
    failed = {str(result.path): result for result in results if result.kind}
    seen = Counter(Path(path).name for path in failed)
    return {
        member_label(Path(path), seen): {
            "type": failed[path].kind,
            "message": failed[path].message,
            "signature": signature(failed[path].message),
        }
        for path in sorted(failed)
    }


def _check_one(
    index: int, path: Path, parser: AsgJsonParser, scratch: Path
) -> CheckResult:
    """Parse one program and throw the ASG away. Runs on a worker thread.

    The JSON is written because that is the bridge's only bulk interface, and
    unlinked at once because 3779 ASGs is gigabytes to answer a yes or no. Peak disk
    is one ASG per worker.

    The scratch name is the program's position rather than its stem: two libraries
    can hold programs of the same name, and these run concurrently.

    Everything is caught. A diagnostic that stops at the first rejection is the
    defect it exists to work around.
    """
    out = scratch / f"{index}.ast.json"
    try:
        parser.parse_to_file(path.read_bytes(), out)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(path=path, kind=type(exc).__name__, message=str(exc))
    finally:
        out.unlink(missing_ok=True)
    return CheckResult(path=path)


def _parser_for(config: CorpusConfig) -> AsgJsonParser:
    """The build's own bridge, with the corpus's copybook dirs and extensions.

    Same flags or the answer is worth nothing: a COPY that resolves for the build
    and not here would be reported as a rejection that never happens.
    """
    return make_cobol_parser(
        copybook_dirs=list(config.copybook_dirs),
        copybook_exts=list(config.copybook_extensions),
    )


def check_programs(
    paths: Sequence[Path], parser: AsgJsonParser, max_workers: int = 4
) -> tuple[CheckResult, ...]:
    """Parse every program in parallel, in a scratch directory that dies with the run.

    The bar is not decoration: this is the same thousands of subprocesses the build
    spends its time on, and silence is indistinguishable from a hang -- which is the
    confusion that motivated this module.
    """
    with (
        tempfile.TemporaryDirectory() as scratch,
        ThreadPoolExecutor(max_workers=max_workers) as executor,
    ):
        futures = [
            executor.submit(_check_one, index, path, parser, Path(scratch))
            for index, path in enumerate(paths)
        ]
        return tuple(
            future.result()
            for future in tqdm(
                futures, total=len(futures), desc="check COBOL", unit="program"
            )
        )


def check_corpus(
    config: CorpusConfig, paths: Sequence[Path], max_workers: int = 4
) -> tuple[CheckResult, ...]:
    """The production check: this corpus's bridge over these programs."""
    return check_programs(paths, _parser_for(config), max_workers)


def _signature_lines(results: Sequence[CheckResult]) -> tuple[str, ...]:
    """Rejections grouped by signature, commonest first, and how many groups were
    not shown -- a long tail must not read as a clean report.

    Sorted on negated counts rather than with a sort-order callback, which talisman
    reads as a secret pattern.
    """
    counts = Counter(signature(result.message) for result in results if result.kind)
    ranked = sorted((-count, signed) for signed, count in counts.items())
    shown = ranked[:10]
    tail = (
        (
            f"    ... and {len(ranked) - len(shown)} more signature(s); all of them, "
            f"with the full messages, are in the JSON",
        )
        if len(ranked) > len(shown)
        else ()
    )
    return (
        f"  {len(counts)} distinct failure signature(s), source text and numbers "
        f"stripped:",
        *(f"    {-negated:6}  {signed}" for negated, signed in shown),
        *tail,
    )


def _failure_lines(results: Sequence[CheckResult]) -> tuple[str, ...]:
    counts = Counter(result.kind for result in results if result.kind)
    if not counts:
        return ()
    return (
        "  Failures by error type:",
        *(
            f"    {-negated:6}  {name}"
            for negated, name in sorted(
                (-count, kind) for kind, count in counts.items()
            )
        ),
        *_signature_lines(results),
        "  The full messages are in the JSON, not here: a ProLeap message quotes "
        "the program's own source.",
        "  !! The build's COBOL phase stops at the FIRST of these, so every one of "
        "them blocks it.",
    )


def _report_lines(results: Sequence[CheckResult]) -> tuple[str, ...]:
    counted = tally(results)
    return (
        RULE,
        f"  {counted.parsed} of {len(results)} program(s) parsed",
        f"  {counted.failed} failed",
        *_failure_lines(results),
        RULE,
    )


def _report(results: Sequence[CheckResult]) -> None:
    """Human summary, logged, with no program names and no quoted source in it.

    One record rather than one per line, so a handler that adds a prefix does not
    interleave another thread's output through the middle of a bracketed report.
    """
    logger.info("\n%s", "\n".join(_report_lines(results)))


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a corpus YAML config (see cobble/corpus_config.py)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the JSON here instead of stdout (it holds corpus identifiers "
        "and the bridge's messages, which quote corpus source)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Bridge subprocesses to run at once (default: 4, as a build uses)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] = (), check: Checker = check_corpus) -> int:
    configure_cli_logging()
    args = _parse_args(argv)
    config = load_corpus_config(args.config)
    programs = matching_files(config.cobol_dir, config.cobol_globs)
    results = check(config, programs, args.max_workers)
    emit_json(json.dumps(find_unparseable(results), indent=2), args)
    _report(results)
    return 0


def cli() -> int:
    """Entry point for the ``diagnose-cobol`` console script.

    A console script's generated wrapper calls its target with no arguments, so
    reading sys.argv has to happen here rather than as a default on ``main`` (whose
    argv parameter is what the tests drive it through).
    """
    return main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(cli())

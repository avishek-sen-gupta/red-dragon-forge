"""cobble.diagnosis.jcl — which JCL members the bridge will not parse, and nothing else.

A corpus build parses every JCL member in its own JVM subprocess, twice over
before this store existed, and only then starts drawing edges. A member the
grammar rejects therefore surfaces hours in, as one warning among thousands, and
the four numbers that say whether a grammar fix helped -- members parsed, members
failed, steps, DDs -- are buried in the same run's output.

This runs that phase and stops. It is the sweep the onboarding grammar work ran by
hand, over and over, once per candidate fix: parse the whole JCL library, count
what came back, and list what did not parse with what the bridge said about it.
The numbers it prints are exactly the columns of the table in
docs/corpus-onboarding-blockers.md.

Steps and DDs are here rather than left to the build because they are the
regression check. A grammar change that recovers members must leave every member
that already parsed with the counts it already had, so the deltas have to be
readable off two runs of the same command.

The channel split is the sibling module's, and matters more here: an ANTLR error
quotes the input it choked on, so a parse message carries corpus source text.
Messages go in the JSON, whose destination the caller chooses; the logged summary
carries counts and error types only.

Invoke as: JCL_BRIDGE_JAR=<path> uv run diagnose-jcl --config <path>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import load_corpus_config
from cobble.diagnosis.report import RULE, emit_json, member_label
from cobble.jcl.jcl_store import JclStore, temp_jcl_store
from jackal.jcl.parser import bridge_parser
from cobble.matching_files import matching_files

logger = logging.getLogger(__name__)

# member -> {"type": exception class name, "message": what it said}
Unparseable = dict[str, dict[str, str]]


@dataclass(frozen=True)
class SweepResult:
    """One member: what it contributed, or what rejected it.

    ``kind`` is the marker of failure rather than ``message``, because an
    exception always has a class name and ``str(exc)`` can be empty. A failed
    member's ``steps`` and ``dds`` stay zero: nothing in it reaches the graph.
    """

    path: Path
    steps: int = 0
    dds: int = 0
    kind: str = ""
    message: str = ""


# (members, worker count) -> one SweepResult per member. Injected into main so the
# CLI is testable without a JVM, which is the whole cost of this diagnostic.
Sweeper = Callable[[Sequence[Path], int], Sequence[SweepResult]]


@dataclass(frozen=True)
class Tally:
    """The four columns: members parsed, members failed, and the steps and DDs the
    parsed ones hold."""

    parsed: int = 0
    failed: int = 0
    steps: int = 0
    dds: int = 0


def tally(results: Sequence[SweepResult]) -> Tally:
    """Count ``results``. Steps and DDs describe the members that parsed and only
    those, so two runs' deltas are comparable across a grammar change."""
    parsed = tuple(result for result in results if not result.kind)
    return Tally(
        parsed=len(parsed),
        failed=len(results) - len(parsed),
        steps=sum(result.steps for result in parsed),
        dds=sum(result.dds for result in parsed),
    )


def find_unparseable(results: Sequence[SweepResult]) -> Unparseable:
    """The failures in ``results``, by member, with the error that rejected each.

    Sorted, and an empty mapping when everything parsed: the JSON is diffed
    between runs to see whether a grammar fix moved the number, so "none left" has
    to be expressible rather than absent.
    """
    failed = {str(result.path): result for result in results if result.kind}
    seen = Counter(Path(path).name for path in failed)
    return {
        member_label(Path(path), seen): {
            "type": failed[path].kind,
            "message": failed[path].message,
        }
        for path in sorted(failed)
    }


def _swept(path: Path, store: JclStore) -> SweepResult:
    """One member's contribution, reporting whatever rejected it rather than raising.

    Broad, like every other corpus read in cobble: onboarding a corpus means
    meeting members that do not parse, and this module exists precisely to report
    them -- one of them raising would cost the report on all the others.
    """
    try:
        job = store.get(path)
    except Exception as exc:  # noqa: BLE001
        return SweepResult(path=path, kind=type(exc).__name__, message=str(exc))
    return SweepResult(
        path=path,
        steps=len(job.steps),
        dds=sum(len(step.dds) for step in job.steps),
    )


def sweep_members(
    paths: Sequence[Path], max_workers: int = 4
) -> tuple[SweepResult, ...]:
    """Parse every member through a temporary store, in parallel, once.

    The store is the build's own, so this measures what the build will measure,
    parallelises the same way, and gets its ``parse JCL`` progress bar for free.
    Its cache dies with the sweep, so no run can be served output from a grammar
    that has since changed.
    """
    with temp_jcl_store(max_workers) as store:
        store.parse_all(paths, bridge_parser())
        return tuple(_swept(path, store) for path in paths)


def _failure_lines(results: Sequence[SweepResult]) -> tuple[str, ...]:
    """Failures counted by exception class, commonest first.

    Which failures share a cause is the question a grammar fix asks, and the class
    name is the part of an error that quotes no corpus source -- sorted on negated
    counts rather than with a sort-order callback, which talisman reads as a
    secret pattern.
    """
    counts = Counter(result.kind for result in results if result.kind)
    if not counts:
        return ()
    return (
        "  Every step and DD in a failed member is ABSENT from the graph.",
        "  Failures by error type:",
        *(
            f"    {-negated:6}  {name}"
            for negated, name in sorted(
                (-count, kind) for kind, count in counts.items()
            )
        ),
        "  The messages are in the JSON, not here: an ANTLR error quotes the "
        "member's own source.",
    )


def _report_lines(results: Sequence[SweepResult]) -> tuple[str, ...]:
    """The whole summary as lines, so what it says is testable without capturing a
    stream."""
    counted = tally(results)
    return (
        RULE,
        f"  {counted.parsed} of {len(results)} member(s) parsed",
        f"  {counted.failed} failed",
        f"  {counted.steps} steps and {counted.dds} DDs across the members that "
        f"parsed",
        *_failure_lines(results),
        RULE,
    )


def _report(results: Sequence[SweepResult]) -> None:
    """Human summary, logged, with no corpus identifiers and no parse messages in it.

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
        help="Path to a corpus TOML config (see cobble/corpus_config.py)",
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


def main(argv: Sequence[str] = (), sweep: Sweeper = sweep_members) -> int:
    configure_cli_logging()
    args = _parse_args(argv)
    config = load_corpus_config(args.config)
    results = sweep(matching_files(config.jcl_dir, config.jcl_globs), args.max_workers)
    emit_json(json.dumps(find_unparseable(results), indent=2), args)
    _report(results)
    return 0


def cli() -> int:
    """Entry point for the ``diagnose-jcl`` console script.

    A console script's generated wrapper calls its target with no arguments, so
    reading sys.argv has to happen here rather than as a default on ``main``
    (whose argv parameter is what the tests drive it through).
    """
    return main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(cli())

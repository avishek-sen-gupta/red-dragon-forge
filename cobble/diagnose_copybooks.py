"""diagnose_copybooks.py — which COPY statements the COBOL parser will not resolve,
without running the COBOL parser.

The expensive phase of a corpus build is COBOL parsing: one JVM subprocess per
member, thousands of members. A COPY the ProLeap preprocessor cannot resolve
fails that whole program -- so a corpus with widespread missing copybooks spends
hours to report what a COPY scan reports in one JVM.

COPY statements come from :func:`cobble.interpreter.project.cobol_imports
.extract_cobol_imports`, which folds fixed-format continuations and resolves
nothing. Resolution is what this module adds, and it mirrors ProLeap's
CobolWordCopyBookFinderImpl EXACTLY, because a diagnostic that disagrees with
the parser is worse than no diagnostic:

  - a candidate file matches iff its FULL FILENAME equalsIgnoreCase either the
    copy name itself (for the empty extension) or ``<name>.<ext>`` for one of the
    configured copybook_extensions;
  - copybook_dirs are scanned with listFiles(), i.e. NOT recursively.

Note this is stricter than CorpusIndex, which indexes every file in
copybook_dirs whatever its extension. A name can therefore resolve to a
file_path in the knowledge graph and still fail the parse, which is why the
graph's UNRESOLVED count is a lower bound on what this reports.

stdout (or --output) is JSON and nothing else: missing copybook name -> program
-> the lines its COPY statements are on. The human summary goes to stderr, so
the JSON stays pipeable and a run writing names to a file does not also print
them to a shared terminal.

Invoke as: uv run diagnose-copybooks --config <path>
"""

# ruff: noqa: T201 -- the JSON on stdout and the summary on stderr ARE this
# script's output; it is a diagnostic entry point, not a library.

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import chain, groupby
from operator import itemgetter
from pathlib import Path

from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.interpreter.project.cobol_imports import extract_cobol_imports
from cobble.interpreter.project.import_types import ImportKind, ImportRef
from cobble.matching_files import matching_files

logger = logging.getLogger(__name__)

# name -> program -> lines of the COPY statements naming it
MissingCopybooks = dict[str, dict[str, list[int]]]

RULE = "=" * 78


@dataclass(frozen=True)
class ScanResult:
    """One scanned member: the COPYs it named, or why it could not be read.

    ``message`` is non-empty only when the member could not be scanned at all,
    and such a member contributes nothing -- which :func:`_report` says out loud,
    because it makes every count below a lower bound rather than an answer.
    """

    path: Path
    copies: tuple[ImportRef, ...] = ()
    message: str = ""


# Sequence[Path] -> one ScanResult per member, in the order given
Scanner = Callable[[Sequence[Path]], Sequence[ScanResult]]


def _scan_member(path: Path) -> ScanResult:
    """Scan one member, reporting a failure to read it rather than raising.

    Guarded for the same reason every other corpus read in cobble is: onboarding
    a corpus means meeting members that do not read, and one of them must not
    cost the report on the other 3778.
    """
    try:
        refs = extract_cobol_imports(path.read_bytes(), path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not scan %s: %s", path.name, exc)
        return ScanResult(path=path, message=f"{type(exc).__name__}: {exc}")
    return ScanResult(
        path=path, copies=tuple(r for r in refs if r.kind == ImportKind.INCLUDE)
    )


def scan_members(paths: Sequence[Path]) -> tuple[ScanResult, ...]:
    """One ScanResult per member, in the order given."""
    return tuple(map(_scan_member, paths))


def _filenames_in(directory: Path) -> tuple[str, ...]:
    """Every filename ProLeap would see in one directory, lowercased, one level deep.

    A configured directory that does not exist is a reason every COPY against it
    is missing, not a reason to fail: a corpus can be onboarded before its
    copybook library is staged.
    """
    if not directory.is_dir():
        logger.warning("copybook dir does not exist: %s", directory)
        return ()
    return tuple(path.name.lower() for path in directory.iterdir() if path.is_file())


def _copybook_filenames(copybook_dirs: Sequence[Path]) -> frozenset[str]:
    """Every filename ProLeap would see across all configured directories."""
    return frozenset(chain.from_iterable(map(_filenames_in, copybook_dirs)))


def _candidate_filenames(name: str, extensions: Sequence[str]) -> tuple[str, ...]:
    """The filenames ProLeap accepts for a COPY of ``name``, lowercased.

    An empty extension means the bare name, matching
    isMatchingCopyBookWithExtension's ``ext == null || ext.isEmpty()`` branch.
    """
    lowered = name.lower()
    return tuple(
        lowered if not ext else f"{lowered}.{ext.lower()}" for ext in extensions
    )


def _unresolved_copies(
    result: ScanResult, available: frozenset[str], extensions: Sequence[str]
) -> tuple[tuple[str, str, int], ...]:
    """(copybook name, program, line) per COPY in one member that will not resolve.

    A ref with no line is dropped: the report exists to say where to look, and
    line numbers are 1-based, so a falsy line means the scanner had no position
    rather than a COPY on line zero.
    """
    program = result.path.stem.upper()
    return tuple(
        (copy.module_path.upper(), program, copy.line)
        for copy in result.copies
        if copy.line
        and not available.intersection(
            _candidate_filenames(copy.module_path, extensions)
        )
    )


def _lines_by_program(refs: Sequence[tuple[str, str, int]]) -> dict[str, list[int]]:
    """One copybook name's unresolved refs, grouped by the program naming it."""
    return {
        program: list(map(itemgetter(2), group))
        for program, group in groupby(refs, itemgetter(1))
    }


def find_missing_copybooks(
    config: CorpusConfig, results: Sequence[ScanResult]
) -> MissingCopybooks:
    """Group the COPYs in ``results`` that will not resolve, by copybook name.

    Pure over ``results``, so resolution is testable without a corpus on disk and
    the corpus is walked once per run rather than once per question asked of it.

    Sorted throughout: the JSON is diffed between runs to see whether staging
    copybooks actually moved the number.
    """
    available = _copybook_filenames(config.copybook_dirs)
    refs = sorted(
        chain.from_iterable(
            _unresolved_copies(result, available, config.copybook_extensions)
            for result in results
        )
    )
    return {
        name: _lines_by_program(tuple(group))
        for name, group in groupby(refs, itemgetter(0))
    }


def _suffixes_on_disk(
    names: Sequence[str], copybook_dirs: Sequence[Path]
) -> dict[str, frozenset[str]]:
    """For each missing name, the suffixes it DOES exist under, if any.

    This separates the two fixes: a name with suffixes listed here is on disk and
    the corpus config's copybook_extensions does not admit it; a name absent here
    is a member nobody has staged.
    """
    wanted = frozenset(name.lower() for name in names)
    found = sorted(
        (path.stem.upper(), path.suffix)
        for directory in copybook_dirs
        if directory.is_dir()
        for path in directory.iterdir()
        if path.is_file() and path.stem.lower() in wanted
    )
    return {
        stem: frozenset(suffix for _, suffix in group)
        for stem, group in groupby(found, itemgetter(0))
    }


def _unreadable_lines(results: Sequence[ScanResult]) -> tuple[str, ...]:
    """The members that could not be read, said before the counts rather than
    after, because it qualifies every one of them."""
    unreadable = tuple(result for result in results if result.message)
    if not unreadable:
        return (RULE,)
    return (
        RULE,
        f"  !! {len(unreadable)} of {len(results)} member(s) COULD NOT BE "
        f"READ -- they contribute nothing below",
        RULE,
    )


def _ranked(missing: MissingCopybooks) -> tuple[tuple[str, frozenset[str]], ...]:
    """Names commonest first, ties by name -- sorted on negated counts rather than
    with a sort-order callback, which talisman reads as a secret pattern."""
    return tuple(
        (name, frozenset(missing[name]))
        for _, name in sorted(
            (-len(programs), name) for name, programs in missing.items()
        )
    )


def _coverage_lines(
    ranked: Sequence[tuple[str, frozenset[str]]], blocked: frozenset[str]
) -> tuple[str, ...]:
    """Concentration: whether this is a handful of shared copybooks or a long tail
    decides whether staging files by hand is worth it."""
    covered = tuple(
        (n, len(frozenset(chain.from_iterable(p for _, p in ranked[:n]))))
        for n in (1, 5, 10, 20, 50, 100, len(ranked))
        if n <= len(ranked)
    )
    return tuple(
        f"    top {n:5}  ->  {count:6} of {len(blocked)} "
        f"({100 * count // len(blocked)}%)"
        for n, count in covered
    )


def _suffix_lines(suffixes: Mapping[str, frozenset[str]]) -> tuple[str, ...]:
    """How many missing names sit under each unlisted suffix -- one config edit
    fixes a whole group of them at once."""
    tally = Counter(chain.from_iterable(suffixes.values()))
    return tuple(
        f"           {-negated:6}  under '{suffix or '(no suffix)'}'  <- add to "
        f"copybook_extensions to fix all of these at once"
        for negated, suffix in sorted((-count, s) for s, count in tally.items())
    )


def _why_lines(missing: MissingCopybooks, config: CorpusConfig) -> tuple[str, ...]:
    """Which of the two fixes applies: stage the member, or list its suffix."""
    suffixes = _suffixes_on_disk(tuple(missing), config.copybook_dirs)
    return (
        f"{RULE}\n  Why:",
        f"    {len(missing) - len(suffixes):6}  not on disk in any configured "
        f"copybook dir -- member must be staged",
        f"    {len(suffixes):6}  ON DISK but under a suffix copybook_extensions "
        f"does not list",
        *_suffix_lines(suffixes),
        f"  configured copybook_extensions: {list(config.copybook_extensions)}",
        RULE,
    )


def _missing_lines(
    missing: MissingCopybooks, config: CorpusConfig, results: Sequence[ScanResult]
) -> tuple[str, ...]:
    """The shape of the problem: how many, how concentrated, and which fix."""
    blocked = frozenset(chain.from_iterable(missing.values()))
    return (
        f"  {len(missing)} distinct copybook name(s) will not resolve",
        f"  {len(blocked)} of {len(results)} program(s) reference at least one "
        f"-- each will FAIL to parse",
        f"{RULE}\n  Cumulative programs unblocked by fixing the commonest names:",
        *_coverage_lines(_ranked(missing), blocked),
        *_why_lines(missing, config),
    )


def _report_lines(
    missing: MissingCopybooks, config: CorpusConfig, results: Sequence[ScanResult]
) -> tuple[str, ...]:
    """The whole summary as lines, so what it says is testable without capturing
    a stream."""
    header = _unreadable_lines(results)
    if not missing:
        scanned = f"  No missing copybooks. {len(results)} members scanned."
        return (*header, scanned, RULE)
    return (*header, *_missing_lines(missing, config, results))


def _report(
    missing: MissingCopybooks, config: CorpusConfig, results: Sequence[ScanResult]
) -> None:
    """Human summary, on stderr, with no corpus identifiers in it.

    Names are the corpus's own; they belong in the JSON the caller chose where to
    put, not in a terminal. What goes here is shape only.
    """
    print("\n" + "\n".join(_report_lines(missing, config, results)), file=sys.stderr)


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
        help="Write the JSON here instead of stdout (the names are corpus identifiers)",
    )
    return parser.parse_args(argv)


def _emit_json(payload: str, args: argparse.Namespace) -> None:
    """--output if it was given, stdout otherwise.

    Takes the parsed args rather than an optional path so that "no --output" stays
    argparse's absent-flag default and does not become a None this module has to
    thread through its own signatures.
    """
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
        # Only the path, never the names: they are the corpus's own identifiers.
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(payload)


def main(argv: Sequence[str] = (), scan: Scanner = scan_members) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args(argv)
    config = load_corpus_config(args.config)

    results = scan(matching_files(config.cobol_dir, config.cobol_globs))
    missing = find_missing_copybooks(config, results)
    _emit_json(json.dumps(missing, indent=2), args)
    _report(missing, config, results)
    return 0


def cli() -> int:
    """Entry point for the ``diagnose-copybooks`` console script.

    A console script's generated wrapper calls its target with no arguments, so
    reading sys.argv has to happen here rather than as a default on ``main``
    (whose argv parameter is what the tests drive it through).
    """
    return main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(cli())

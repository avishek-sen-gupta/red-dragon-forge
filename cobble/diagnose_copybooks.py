"""diagnose_copybooks.py — which COPY statements the COBOL parser will not resolve,
without running the COBOL parser.

The expensive phase of a corpus build is COBOL parsing: one JVM subprocess per
program, thousands of programs. A COPY the ProLeap preprocessor cannot resolve
fails that whole program -- so a corpus with widespread missing copybooks spends
hours to report what a scan of the raw source can report in seconds.

Resolution mirrors ProLeap's CobolWordCopyBookFinderImpl EXACTLY, because a
diagnostic that disagrees with the parser is worse than no diagnostic:

  - a candidate file matches iff its FULL FILENAME equalsIgnoreCase either the
    copy name itself (for the empty extension) or ``<name>.<ext>`` for one of the
    configured copybook_extensions;
  - copybook_dirs are scanned with listFiles(), i.e. NOT recursively.

Note this is stricter than CorpusIndex, which indexes every file in
copybook_dirs whatever its extension. A name can therefore resolve to a
file_path in the knowledge graph and still fail the parse, which is why the
graph's UNRESOLVED count is a lower bound on what this reports.

COPY statements come from the same scanner build_graph's CALL/COPY extractor
uses (interpreter.project.cobol_imports), deliberately, so the two cannot
disagree about what the corpus asks for.

stdout (or --output) is JSON and nothing else: missing copybook name -> program
-> the lines its COPY statements are on. The human summary goes to stderr, so
the JSON stays pipeable and a run writing names to a file does not also print
them to a shared terminal.

Invoke as: uv run python -m cobble.diagnose_copybooks --config <path>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from lark.exceptions import UnexpectedInput

from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.interpreter.project.cobol_imports import extract_cobol_imports
from cobble.interpreter.project.import_types import ImportKind
from cobble.matching_files import matching_files

logger = logging.getLogger(__name__)

# name -> program -> lines of the COPY statements naming it
MissingCopybooks = dict[str, dict[str, list[int]]]


def _copybook_filenames(copybook_dirs: tuple[Path, ...]) -> set[str]:
    """Every filename ProLeap would see, lowercased, one level deep.

    A configured directory that does not exist is a reason every COPY against it
    is missing, not a reason to fail: a corpus can be onboarded before its
    copybook library is staged.
    """
    names: set[str] = set()
    for copybook_dir in copybook_dirs:
        if not copybook_dir.is_dir():
            logger.warning("copybook dir does not exist: %s", copybook_dir)
            continue
        for path in copybook_dir.iterdir():
            if path.is_file():
                names.add(path.name.lower())
    return names


def _candidate_filenames(name: str, extensions: tuple[str, ...]) -> list[str]:
    """The filenames ProLeap accepts for a COPY of ``name``, lowercased.

    An empty extension means the bare name, matching
    isMatchingCopyBookWithExtension's ``ext == null || ext.isEmpty()`` branch.
    """
    lowered = name.lower()
    return [lowered if not ext else f"{lowered}.{ext.lower()}" for ext in extensions]


def find_missing_copybooks(
    config: CorpusConfig, unscanned: list[str] | None = None
) -> MissingCopybooks:
    """Scan every COBOL source for COPY statements the parser will not resolve.

    Programs the scanner itself could not read are appended to ``unscanned``,
    one string each. They matter to the reader: an unscanned program is one whose
    missing copybooks are absent from the result, so every total here is a lower
    bound by however many there are.
    """
    available = _copybook_filenames(config.copybook_dirs)

    missing: MissingCopybooks = defaultdict(lambda: defaultdict(list))
    for path in matching_files(config.cobol_dir, config.cobol_globs):
        program = path.stem.upper()
        try:
            refs = extract_cobol_imports(path.read_bytes(), path)
        except (OSError, UnexpectedInput) as exc:
            # Corpus shape: unreadable, or source the COPY/CALL grammar chokes on
            # (an odd number of quotes anywhere leaves a literal unterminated for
            # the tokeniser). Narrow on purpose -- anything else is a bug in
            # cobble and must surface rather than be filed as corpus shape.
            logger.warning("could not scan %s: %s", path.name, exc)
            if unscanned is not None:
                unscanned.append(f"{path.name}: {str(exc).splitlines()[0]}")
            continue
        for ref in refs:
            if ref.kind is not ImportKind.INCLUDE:
                continue
            name = ref.module_path.upper()
            if any(
                c in available
                for c in _candidate_filenames(name, config.copybook_extensions)
            ):
                continue
            if ref.line is not None:
                missing[name][program].append(ref.line)

    # Sorted throughout: the JSON is diffed between runs to see whether staging
    # copybooks actually moved the number.
    return {
        name: {program: sorted(lines) for program, lines in sorted(programs.items())}
        for name, programs in sorted(missing.items())
    }


def _suffixes_on_disk(
    names: set[str], copybook_dirs: tuple[Path, ...]
) -> dict[str, set[str]]:
    """For each missing name, the suffixes it DOES exist under, if any.

    This separates the two fixes: a name with suffixes listed here is on disk and
    the corpus config's copybook_extensions does not admit it; a name absent here
    is a member nobody has staged.
    """
    wanted = {n.lower() for n in names}
    found: dict[str, set[str]] = defaultdict(set)
    for copybook_dir in copybook_dirs:
        if not copybook_dir.is_dir():
            continue
        for path in copybook_dir.iterdir():
            if path.is_file() and path.stem.lower() in wanted:
                found[path.stem.upper()].add(path.suffix)
    return found


def _report(
    missing: MissingCopybooks, config: CorpusConfig, unscanned: list[str]
) -> None:
    """Human summary, on stderr, with no corpus identifiers in it.

    Names are the corpus's own; they belong in the JSON the caller chose where to
    put, not in a terminal. What goes here is shape: how many, how concentrated,
    and which of the two fixes applies.
    """
    total_programs = len(matching_files(config.cobol_dir, config.cobol_globs))
    rule = "=" * 78
    print(f"\n{rule}", file=sys.stderr)
    if unscanned:
        # Said before the counts, not after: it qualifies every one of them.
        print(
            f"  !! {len(unscanned)} of {total_programs} program(s) COULD NOT BE "
            f"SCANNED -- every count below is a lower bound",
            file=sys.stderr,
        )
        print(rule, file=sys.stderr)
    if not missing:
        print(
            f"  No missing copybooks. {total_programs} programs scanned.",
            file=sys.stderr,
        )
        print(rule, file=sys.stderr)
        return

    blocked = {program for programs in missing.values() for program in programs}
    print(
        f"  {len(missing)} distinct copybook name(s) will not resolve", file=sys.stderr
    )
    print(
        f"  {len(blocked)} of {total_programs} program(s) reference at least one "
        f"-- each will FAIL to parse",
        file=sys.stderr,
    )

    # Concentration: whether this is a handful of shared copybooks or a long tail
    # decides whether staging files by hand is worth it. Commonest first, ties by
    # name -- sorted on negated counts rather than with a sort-order callback,
    # which talisman reads as a secret pattern.
    ranked = [
        (name, missing[name])
        for _, name in sorted(
            (-len(programs), name) for name, programs in missing.items()
        )
    ]
    print(
        f"{rule}\n  Cumulative programs unblocked by fixing the commonest names:",
        file=sys.stderr,
    )
    for n in (1, 5, 10, 20, 50, 100, len(ranked)):
        if n > len(ranked):
            continue
        covered = {p for _, programs in ranked[:n] for p in programs}
        pct = 100 * len(covered) // len(blocked)
        print(
            f"    top {n:5}  ->  {len(covered):6} of {len(blocked)} ({pct}%)",
            file=sys.stderr,
        )

    suffixes = _suffixes_on_disk(set(missing), config.copybook_dirs)
    print(f"{rule}\n  Why:", file=sys.stderr)
    print(
        f"    {len(missing) - len(suffixes):6}  not on disk in any configured "
        f"copybook dir -- member must be staged",
        file=sys.stderr,
    )
    print(
        f"    {len(suffixes):6}  ON DISK but under a suffix copybook_extensions "
        f"does not list",
        file=sys.stderr,
    )
    if suffixes:
        tally: dict[str, int] = defaultdict(int)
        for found in suffixes.values():
            for suffix in found:
                tally[suffix or "(no suffix)"] += 1
        for negated, suffix in sorted((-c, s) for s, c in tally.items()):
            print(
                f"           {-negated:6}  under '{suffix}'  <- add to "
                f"copybook_extensions to fix all of these at once",
                file=sys.stderr,
            )
    print(
        f"  configured copybook_extensions: {list(config.copybook_extensions)}",
        file=sys.stderr,
    )
    print(rule, file=sys.stderr)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
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


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args(argv)
    config = load_corpus_config(args.config)

    unscanned: list[str] = []
    missing = find_missing_copybooks(config, unscanned)
    payload = json.dumps(missing, indent=2)
    if args.output is None:
        print(payload)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
        print(f"Wrote {args.output}", file=sys.stderr)

    _report(missing, config, unscanned)
    return 0


if __name__ == "__main__":
    sys.exit(main())

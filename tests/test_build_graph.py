"""The run-level failure guards: one bad member must not abort a corpus run,
and what was skipped must be impossible to miss in the output."""

import logging
from pathlib import Path

from cobble.build_graph import (
    RULE,
    _failure_report_lines,
    _load_transid_to_program,
    _report_failures,
    _tally_lines,
)
from cobble.corpus_config import DEFAULT_COPYBOOK_EXTENSIONS, CorpusConfig


def _config(tmp_path: Path, **overrides) -> CorpusConfig:
    defaults = dict(
        cobol_dir=tmp_path / "cbl",
        cobol_globs=("*.cbl",),
        jcl_dir=tmp_path / "jcl",
        jcl_globs=("*.jcl",),
        proclib_dirs=(),
        csd_files=(),
        copybook_dirs=(tmp_path / "cpy",),
        copybook_extensions=DEFAULT_COPYBOOK_EXTENSIONS,
        out_dir=tmp_path / "out",
    )
    return CorpusConfig(**{**defaults, **overrides})


def _touch(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_csd_that_does_not_parse_does_not_abort_the_run(tmp_path: Path) -> None:
    """``_load_transid_to_program`` ran before the writer opened and did not guard
    ``parse_csd``, so a malformed CSD killed the whole run — even though the corpus
    index already guards the very same file."""
    broken = _touch(tmp_path / "csd" / "BROKEN.CSD", "this is not a DEFINE\n")

    read = _load_transid_to_program(_config(tmp_path, csd_files=(broken,)))

    assert dict(read.transid_to_program) == {}
    assert len(read.failures) == 1
    assert read.failures[0].startswith("CSD BROKEN.CSD: ")


def test_a_good_csd_still_loads_alongside_a_broken_one(tmp_path: Path) -> None:
    good = _touch(
        tmp_path / "csd" / "GOOD.CSD",
        "DEFINE TRANSACTION(CC00) PROGRAM(COSGN00C) GROUP(CARDDEMO)\n",
    )
    broken = _touch(tmp_path / "csd" / "BROKEN.CSD", "this is not a DEFINE\n")

    read = _load_transid_to_program(_config(tmp_path, csd_files=(broken, good)))

    assert dict(read.transid_to_program) == {"CC00": "COSGN00C"}
    assert len(read.failures) == 1


def test_the_failure_report_says_the_output_is_incomplete() -> None:
    """The report used to be a quiet stdout line after "Wrote ...", easy to scroll
    past on a corpus where 62 members are missing from a graph that otherwise looks
    finished."""
    lines = _failure_report_lines(["index JCL A.jcl: boom", "JCL B.jcl: boom"])

    assert lines[2] == "!!  2 FAILURE(S) -- THIS GRAPH IS INCOMPLETE"
    assert lines[-3:] == (
        "  - index JCL A.jcl: boom",
        "  - JCL B.jcl: boom",
        RULE,
    )


def test_the_failure_report_tallies_by_category() -> None:
    """62 lines of detail hide the shape. The tally is what a reader acts on.

    Commonest category first, ties by name — so a corpus whose problem is one
    kind of member reads as one line, not as sixty-two.
    """
    assert _tally_lines(
        [
            "index JCL A.jcl: boom",
            "index JCL B.jcl: boom",
            "JCL C.jcl: boom",
            "CSD D.CSD: boom",
        ]
    ) == (
        "      2  index JCL",
        "      1  CSD",
        "      1  JCL",
    )


def test_the_report_is_logged_whole_and_at_error_level(capsys, caplog) -> None:
    """One record, not one per line: a handler that prefixes or timestamps each
    record must not interleave anything through the middle of the report. ERROR
    because it says the artifact just written is wrong, which is not progress
    information -- a caller that raises the level to hide the per-stage counts
    still has to see this."""
    caplog.set_level(logging.INFO)
    failures = ["index JCL A.jcl: boom"]

    _report_failures(failures)

    assert caplog.messages == ["\n".join(_failure_report_lines(failures))]
    assert caplog.records[0].levelno == logging.ERROR
    assert capsys.readouterr() == ("", "")


def test_no_failures_logs_no_report(caplog) -> None:
    caplog.set_level(logging.INFO)
    _report_failures([])
    assert caplog.messages == []

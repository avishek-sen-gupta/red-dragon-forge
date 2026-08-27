"""The run-level failure guards: one bad member must not abort a corpus run,
and what was skipped must be impossible to miss in the output."""

from pathlib import Path

from cobble.build_graph import _load_transid_to_program, _report_failures
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
    defaults.update(overrides)
    return CorpusConfig(**defaults)


def _touch(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_csd_that_does_not_parse_does_not_abort_the_run(tmp_path: Path) -> None:
    """``_load_transid_to_program`` ran before the writer opened and did not guard
    ``parse_csd``, so a malformed CSD killed the whole run — even though
    ``CorpusIndex`` already guards the very same file."""
    broken = _touch(tmp_path / "csd" / "BROKEN.CSD", "this is not a DEFINE\n")
    failures: list[str] = []

    assert (
        _load_transid_to_program(_config(tmp_path, csd_files=(broken,)), failures) == {}
    )
    assert len(failures) == 1
    assert failures[0].startswith("CSD BROKEN.CSD: ")


def test_a_good_csd_still_loads_alongside_a_broken_one(tmp_path: Path) -> None:
    good = _touch(
        tmp_path / "csd" / "GOOD.CSD",
        "DEFINE TRANSACTION(CC00) PROGRAM(COSGN00C) GROUP(CARDDEMO)\n",
    )
    broken = _touch(tmp_path / "csd" / "BROKEN.CSD", "this is not a DEFINE\n")
    failures: list[str] = []

    config = _config(tmp_path, csd_files=(broken, good))
    assert _load_transid_to_program(config, failures) == {"CC00": "COSGN00C"}
    assert len(failures) == 1


def test_the_failure_report_says_the_output_is_incomplete(capsys) -> None:
    """The report used to be a quiet stdout line after "Wrote ...", easy to scroll
    past on a corpus where 62 members are missing from a graph that otherwise looks
    finished."""
    _report_failures(["index JCL A.jcl: boom", "JCL B.jcl: boom"])

    err = capsys.readouterr().err
    assert "2 FAILURE" in err
    assert "INCOMPLETE" in err
    assert "index JCL A.jcl: boom" in err


def test_the_failure_report_tallies_by_category(capsys) -> None:
    """62 lines of detail hide the shape. The tally is what a reader acts on."""
    _report_failures(
        [
            "index JCL A.jcl: boom",
            "index JCL B.jcl: boom",
            "JCL C.jcl: boom",
            "CSD D.CSD: boom",
        ]
    )

    err = capsys.readouterr().err
    assert "2  index JCL" in err
    assert "1  JCL" in err
    assert "1  CSD" in err


def test_no_failures_prints_no_report(capsys) -> None:
    _report_failures([])
    assert capsys.readouterr().err == ""

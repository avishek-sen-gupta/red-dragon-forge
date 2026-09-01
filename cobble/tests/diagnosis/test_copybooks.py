"""Pre-flight copybook diagnostic.

The expensive phase of a corpus build is COBOL parsing, and a COPY the ProLeap
preprocessor cannot resolve fails the whole program. Finding that out costs hours
of JVM subprocesses; finding it out from a COPY scan costs one JVM.

COPY statements come from ``cobol_imports.extract_cobol_imports``, which folds
fixed-format continuations and resolves nothing. What is left for this module is
resolution, and it mirrors ProLeap's CobolWordCopyBookFinderImpl exactly, because
an answer that disagrees with the parser is worse than no answer:

  - a candidate matches iff its FULL FILENAME equalsIgnoreCase either the copy
    name itself (for the empty extension) or ``<name>.<ext>`` for a configured
    extension;
  - directories are scanned with listFiles(), so NOT recursively.

Note this is stricter than CorpusIndex, which indexes every file in
copybook_dirs whatever its extension — so a name can resolve in the graph and
still fail the parse.
"""

import json
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.corpus_config import CorpusConfig
from cobble.diagnosis.copybooks import (
    STUB_TEXT,
    ScanResult,
    find_missing_copybooks,
    main,
    scan_members,
    write_stubs,
)
from cobble.interpreter.project.import_types import ImportKind, ImportRef


def _config(tmp_path: Path, **overrides) -> CorpusConfig:
    defaults = dict(
        cobol_dir=tmp_path / "cbl",
        cobol_globs=("*.cbl",),
        jcl_dir=tmp_path / "jcl",
        jcl_globs=("*.jcl",),
        proclib_dirs=(),
        csd_files=(),
        copybook_dirs=(tmp_path / "cpy",),
        copybook_extensions=("", "cpy"),
        out_dir=tmp_path / "out",
    )
    return CorpusConfig(**{**defaults, **overrides})


def _scanned(tmp_path: Path, program: str, *copies: tuple[str, int]) -> ScanResult:
    """A scan result as the scanner would report one, for ``<program>.cbl``."""
    path = tmp_path / "cbl" / f"{program}.cbl"
    return ScanResult(
        path=path,
        copies=tuple(
            ImportRef(
                source_file=path,
                module_path=name,
                kind=ImportKind.INCLUDE,
                line=line,
            )
            for name, line in copies
        ),
    )


def _touch(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_copybook_present_under_a_listed_extension_is_not_missing(
    tmp_path: Path,
) -> None:
    _touch(tmp_path / "cpy" / "CUSTREC.cpy", "       01 CUST-REC.\n")
    results = [_scanned(tmp_path, "PROGA", ("CUSTREC", 1))]

    assert find_missing_copybooks(_config(tmp_path), results) == {}


def test_a_copybook_absent_everywhere_is_reported_with_program_and_line(
    tmp_path: Path,
) -> None:
    (tmp_path / "cpy").mkdir()
    results = [_scanned(tmp_path, "PROGA", ("CUSTREC", 2))]

    assert find_missing_copybooks(_config(tmp_path), results) == {
        "CUSTREC": {"PROGA": [2]}
    }


def test_a_copybook_present_under_an_unlisted_extension_is_still_missing(
    tmp_path: Path,
) -> None:
    """ProLeap compares the whole filename against ``<name>.<ext>`` for the
    configured extensions only, so a member on disk as .txt with txt unlisted is
    invisible to the parser however obviously it is the right file."""
    _touch(tmp_path / "cpy" / "CUSTREC.txt", "       01 CUST-REC.\n")
    results = [_scanned(tmp_path, "PROGA", ("CUSTREC", 1))]

    assert find_missing_copybooks(_config(tmp_path), results) == {
        "CUSTREC": {"PROGA": [1]}
    }


def test_the_empty_extension_matches_a_file_with_no_suffix(tmp_path: Path) -> None:
    _touch(tmp_path / "cpy" / "CUSTREC", "       01 CUST-REC.\n")
    results = [_scanned(tmp_path, "PROGA", ("CUSTREC", 1))]

    assert find_missing_copybooks(_config(tmp_path), results) == {}


def test_matching_ignores_case_on_both_name_and_extension(tmp_path: Path) -> None:
    _touch(tmp_path / "cpy" / "CUSTREC.CPY", "       01 CUST-REC.\n")
    results = [_scanned(tmp_path, "PROGA", ("custrec", 1))]

    assert find_missing_copybooks(_config(tmp_path), results) == {}


def test_copybook_subdirectories_are_not_searched(tmp_path: Path) -> None:
    """ProLeap uses listFiles(), one level. A copybook one directory down is not
    found, so the diagnostic must not claim it is."""
    _touch(tmp_path / "cpy" / "nested" / "CUSTREC.cpy", "       01 CUST-REC.\n")
    results = [_scanned(tmp_path, "PROGA", ("CUSTREC", 1))]

    assert find_missing_copybooks(_config(tmp_path), results) == {
        "CUSTREC": {"PROGA": [1]}
    }


def test_one_copybook_needed_by_two_programs_is_deduplicated_to_one_key(
    tmp_path: Path,
) -> None:
    (tmp_path / "cpy").mkdir()
    results = [
        _scanned(tmp_path, "PROGA", ("CUSTREC", 1)),
        _scanned(tmp_path, "PROGB", ("CUSTREC", 2)),
    ]

    assert find_missing_copybooks(_config(tmp_path), results) == {
        "CUSTREC": {"PROGA": [1], "PROGB": [2]}
    }


def test_two_copies_of_one_copybook_in_one_program_report_both_lines(
    tmp_path: Path,
) -> None:
    (tmp_path / "cpy").mkdir()
    results = [_scanned(tmp_path, "PROGA", ("CUSTREC", 3), ("CUSTREC", 1))]

    assert find_missing_copybooks(_config(tmp_path), results) == {
        "CUSTREC": {"PROGA": [1, 3]}
    }


def test_a_missing_copybook_dir_is_not_fatal(tmp_path: Path) -> None:
    """A corpus can configure a copybook dir that does not exist yet; that is a
    reason every COPY is missing, not a reason to crash."""
    config = _config(tmp_path, copybook_dirs=(tmp_path / "nope",))
    results = [_scanned(tmp_path, "PROGA", ("CUSTREC", 1))]

    assert find_missing_copybooks(config, results) == {"CUSTREC": {"PROGA": [1]}}


def test_an_unreadable_member_contributes_nothing_and_does_not_hide_the_others(
    tmp_path: Path,
) -> None:
    """A member that cannot be read names no copybooks, which makes the report a
    lower bound rather than an answer -- so it must not silently vanish, and it
    must not cost the report on every member scanned after it."""
    (tmp_path / "cpy").mkdir()
    results = [
        ScanResult(path=tmp_path / "cbl" / "BAD.cbl", message="OSError: boom"),
        _scanned(tmp_path, "PROGA", ("CUSTREC", 1)),
    ]

    assert find_missing_copybooks(_config(tmp_path), results) == {
        "CUSTREC": {"PROGA": [1]}
    }


def test_a_member_that_cannot_be_read_is_reported_rather_than_raising(
    tmp_path: Path,
) -> None:
    """Onboarding a corpus means meeting members that do not read. One of them
    must not cost the scan of the other 3778."""
    good = _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    absent = tmp_path / "cbl" / "GONE.cbl"

    results = scan_members([absent, good])

    assert results[0].message
    assert results[0].copies == ()
    assert [r.module_path for r in results[1].copies] == ["CUSTREC"]
    assert results[1].message == ""


def test_fix_writes_one_stub_per_missing_copybook(tmp_path: Path) -> None:
    """The point of --fix: a member nobody staged becomes a file ProLeap resolves,
    so the parse gets past it instead of failing the whole program."""
    missing = {"ACCTREC": {"PROGA": [2]}, "CUSTREC": {"PROGA": [1]}}
    target = tmp_path / "cpy"

    result = write_stubs(missing, _config(tmp_path), target)

    assert result.written == (target / "ACCTREC.cpy", target / "CUSTREC.cpy")
    assert (target / "CUSTREC.cpy").read_text() == STUB_TEXT


def test_a_stub_is_a_fixed_format_comment_and_says_it_is_a_stub(tmp_path: Path) -> None:
    """A zero-byte file is indistinguishable from a truncated real member. Every
    line is a comment (asterisk in column 7), so the stub parses and still tells
    whoever finds it in a copybook dir what it is."""
    write_stubs({"CUSTREC": {"PROGA": [1]}}, _config(tmp_path), tmp_path / "cpy")

    lines = (tmp_path / "cpy" / "CUSTREC.cpy").read_text().splitlines()

    assert lines
    assert all(line.startswith("      *") for line in lines)
    assert "STUB" in lines[0]


def test_the_stub_carries_the_first_extension_the_config_lists(tmp_path: Path) -> None:
    """Named for the corpus's own convention, not a hardcoded .cpy -- the whole
    reason copybook_extensions is configurable is corpora that do not use it."""
    config = _config(tmp_path, copybook_extensions=("txt", "cpy"))

    result = write_stubs({"CUSTREC": {"PROGA": [1]}}, config, tmp_path / "cpy")

    assert result.written == (tmp_path / "cpy" / "CUSTREC.txt",)


def test_a_corpus_whose_copybooks_carry_no_extension_gets_a_bare_stub(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, copybook_extensions=("",))

    result = write_stubs({"CUSTREC": {"PROGA": [1]}}, config, tmp_path / "cpy")

    assert result.written == (tmp_path / "cpy" / "CUSTREC",)


def test_a_name_already_on_disk_under_an_unlisted_suffix_is_not_stubbed(
    tmp_path: Path,
) -> None:
    """The dangerous case. CUSTREC.txt is the real member; copybook_extensions
    does not list txt, so it reads as missing. Writing CUSTREC.cpy beside it would
    resolve -- to a stub declaring nothing -- and the real member would never be
    read again. That name needs a config edit, not a file."""
    _touch(tmp_path / "cpy" / "CUSTREC.txt", "       01 CUST-REC.\n")
    missing = {"ACCTREC": {"PROGA": [2]}, "CUSTREC": {"PROGA": [1]}}

    result = write_stubs(missing, _config(tmp_path), tmp_path / "cpy")

    assert result.written == (tmp_path / "cpy" / "ACCTREC.cpy",)
    assert result.shadowed == ("CUSTREC",)
    assert not (tmp_path / "cpy" / "CUSTREC.cpy").exists()


def test_a_target_dir_the_config_does_not_list_is_refused_before_any_write(
    tmp_path: Path,
) -> None:
    """copybook_dirs is what ProLeap lists, so a stub anywhere else is a file nobody
    reads -- and it was written anyway, with the mismatch reported afterwards.

    Reporting is too late when the target is a path something else owns: `--fix
    out-corpus/synthetic.csd` created a DIRECTORY over where the generated CSD goes,
    put 328 stubs nobody would read inside it, and cost the next build every
    TRANSACTION node. So the check happens first, and nothing is created.
    """
    target = tmp_path / "elsewhere"

    result = write_stubs({"CUSTREC": {"PROGA": [1]}}, _config(tmp_path), target)

    assert result.written == ()
    assert result.configured is False
    assert not target.exists()


def test_a_refusal_still_reports_what_was_missing_rather_than_pretending_to_fix(
    tmp_path: Path,
) -> None:
    """The refusal is about where, not about what: the names it would have stubbed
    are the same, so re-running against a listed dir needs no second scan."""
    _touch(tmp_path / "cpy" / "CUSTREC.txt", "       01 CUST-REC.\n")
    missing = {"ACCTREC": {"PROGA": [2]}, "CUSTREC": {"PROGA": [1]}}

    result = write_stubs(missing, _config(tmp_path), tmp_path / "elsewhere")

    assert result.written == ()
    assert result.shadowed == ("CUSTREC",)


def test_a_target_dir_that_is_a_configured_copybook_dir_is_written(
    tmp_path: Path,
) -> None:
    result = write_stubs(
        {"CUSTREC": {"PROGA": [1]}}, _config(tmp_path), tmp_path / "cpy"
    )

    assert result.configured is True
    assert result.written == (tmp_path / "cpy" / "CUSTREC.cpy",)


def test_a_configured_target_dir_is_created_when_it_does_not_exist(
    tmp_path: Path,
) -> None:
    """A corpus can list a staging dir it has not populated yet -- that is the
    normal way to start stubbing, so listed-but-absent is created, not refused."""
    target = tmp_path / "staged" / "cpy"
    config = _config(tmp_path, copybook_dirs=(tmp_path / "cpy", target))

    result = write_stubs({"CUSTREC": {"PROGA": [1]}}, config, target)

    assert result.written == (target / "CUSTREC.cpy",)
    assert target.is_dir()


def test_a_target_spelled_a_different_way_than_the_config_is_still_configured(
    tmp_path: Path,
) -> None:
    """The comparison is on resolved paths, so `--fix ./cpy/../cpy` from the repo
    root is the dir the config lists, and a refusal here would be a false one."""
    (tmp_path / "cpy").mkdir()

    result = write_stubs(
        {"CUSTREC": {"PROGA": [1]}}, _config(tmp_path), tmp_path / "cpy" / ".." / "cpy"
    )

    assert result.configured is True
    assert (tmp_path / "cpy" / "CUSTREC.cpy").exists()


def _write_config_yaml(tmp_path: Path) -> Path:
    return _touch(
        tmp_path / "corpus.yaml",
        f"""
corpus:
  cobol_dir: {tmp_path}/cbl
  cobol_globs: ["*.cbl"]
  jcl_dir: {tmp_path}/jcl
  jcl_globs: ["*.jcl"]
  copybook_dirs: [{tmp_path}/cpy]
  copybook_extensions: ["", "cpy"]
  out_dir: {tmp_path}/out
""",
    )


def _fake_scan(tmp_path: Path):
    """Stands in for the scanner, so the CLI tests assert on plumbing only."""

    def scan(paths: Sequence[Path]) -> list[ScanResult]:
        return [_scanned(tmp_path, path.stem, ("CUSTREC", 1)) for path in paths]

    return scan


def test_the_json_goes_to_stdout_when_no_output_is_given(
    tmp_path: Path, capsys
) -> None:
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    (tmp_path / "cpy").mkdir()
    (tmp_path / "jcl").mkdir()

    exit_code = main(
        ["--config", str(_write_config_yaml(tmp_path))], scan=_fake_scan(tmp_path)
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"CUSTREC": {"PROGA": [1]}}


def test_an_output_path_receives_the_json_and_stdout_stays_clean(
    tmp_path: Path, capsys
) -> None:
    """The names are corpus identifiers, so a run that writes them to a file must
    not also leak them to a terminal someone is screen-sharing."""
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    (tmp_path / "cpy").mkdir()
    (tmp_path / "jcl").mkdir()
    out = tmp_path / "missing.json"

    exit_code = main(
        ["--config", str(_write_config_yaml(tmp_path)), "--output", str(out)],
        scan=_fake_scan(tmp_path),
    )

    assert exit_code == 0
    assert json.loads(out.read_text()) == {"CUSTREC": {"PROGA": [1]}}
    assert capsys.readouterr().out == ""


def test_fix_through_the_cli_writes_the_stubs_and_logs_what_it_did(
    tmp_path: Path, capsys, caplog
) -> None:
    """The JSON stays what was missing BEFORE the fix -- it is diffed between runs
    to see whether a fix moved the number, so it cannot describe the tree the fix
    just left behind. The summary is a log record, so stdout stays only the JSON.
    """
    caplog.set_level(logging.INFO)
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    (tmp_path / "cpy").mkdir()
    (tmp_path / "jcl").mkdir()

    exit_code = main(
        [
            "--config",
            str(_write_config_yaml(tmp_path)),
            "--fix",
            str(tmp_path / "cpy"),
        ],
        scan=_fake_scan(tmp_path),
    )

    assert exit_code == 0
    assert (tmp_path / "cpy" / "CUSTREC.cpy").read_text() == STUB_TEXT
    assert json.loads(capsys.readouterr().out) == {"CUSTREC": {"PROGA": [1]}}
    assert "1 empty stub" in caplog.text


def _fix_into_an_unlisted_dir(tmp_path: Path) -> tuple[int, Path]:
    """Run --fix at a path this config's copybook_dirs does not list, and return
    the exit code and the target it was pointed at."""
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    (tmp_path / "cpy").mkdir()
    (tmp_path / "jcl").mkdir()
    target = tmp_path / "out" / "synthetic.csd"
    exit_code = main(
        ["--config", str(_write_config_yaml(tmp_path)), "--fix", str(target)],
        scan=_fake_scan(tmp_path),
    )
    return exit_code, target


def test_fix_into_an_unlisted_dir_writes_nothing_and_exits_non_zero(
    tmp_path: Path,
) -> None:
    """A run that fixed nothing must not exit 0: this one is reached by a typo in a
    path, and the next thing the caller does is a build that would silently lack
    whatever the mistyped target was standing in for. Nothing is created either --
    the target may be a path another tool owns.
    """
    exit_code, target = _fix_into_an_unlisted_dir(tmp_path)

    assert exit_code == 2
    assert not target.exists()


def test_a_refused_fix_still_reports_the_scan_and_names_the_listed_dirs(
    tmp_path: Path, capsys, caplog
) -> None:
    """The JSON still goes out -- the scan happened and its answer is good -- and
    the summary names the dirs the stubs could have gone into, since the way here
    is a mistyped path the config already has the right spelling of."""
    caplog.set_level(logging.INFO)

    _fix_into_an_unlisted_dir(tmp_path)

    assert json.loads(capsys.readouterr().out) == {"CUSTREC": {"PROGA": [1]}}
    assert "wrote nothing" in caplog.text
    assert str(tmp_path / "cpy") in caplog.text


def test_the_summary_is_logged_rather_than_printed(
    tmp_path: Path, capsys, caplog
) -> None:
    """stdout is the machine channel and carries the JSON alone, so a run piped to
    jq cannot be broken by adding a line to the human summary."""
    caplog.set_level(logging.INFO)
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    (tmp_path / "cpy").mkdir()
    (tmp_path / "jcl").mkdir()

    main(["--config", str(_write_config_yaml(tmp_path))], scan=_fake_scan(tmp_path))

    assert json.loads(capsys.readouterr().out) == {"CUSTREC": {"PROGA": [1]}}
    assert "will not resolve" in caplog.text


def test_the_output_path_is_logged_and_the_names_are_not(
    tmp_path: Path, caplog
) -> None:
    """--output logs the path it wrote and nothing else: the copybook names are the
    corpus's own identifiers and belong in the file, not in a log someone tails."""
    caplog.set_level(logging.INFO)
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    (tmp_path / "cpy").mkdir()
    (tmp_path / "jcl").mkdir()
    out = tmp_path / "missing.json"

    main(
        ["--config", str(_write_config_yaml(tmp_path)), "--output", str(out)],
        scan=_fake_scan(tmp_path),
    )

    assert f"Wrote {out}" in caplog.text
    assert "CUSTREC" not in caplog.text


def test_without_fix_nothing_is_written(tmp_path: Path) -> None:
    """The diagnostic stays read-only unless asked: it is pointed at corpora
    nobody has permission to add files to."""
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    (tmp_path / "cpy").mkdir()
    (tmp_path / "jcl").mkdir()

    main(["--config", str(_write_config_yaml(tmp_path))], scan=_fake_scan(tmp_path))

    assert list((tmp_path / "cpy").iterdir()) == []

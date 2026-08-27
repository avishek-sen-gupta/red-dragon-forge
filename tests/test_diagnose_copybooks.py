"""Pre-flight copybook diagnostic.

The expensive phase of a corpus build is COBOL parsing, and a COPY the ProLeap
preprocessor cannot resolve fails the whole program. Finding that out costs hours
of JVM subprocesses; finding it out from a COPY scan costs one JVM.

COPY statements come from the bridge's ``-scan-copy`` mode, which parses with
ProLeap's own ``CobolPreprocessor.g4`` and resolves nothing. What is left for
this module is resolution, and it mirrors ProLeap's CobolWordCopyBookFinderImpl
exactly, because an answer that disagrees with the parser is worse than no
answer:

  - a candidate matches iff its FULL FILENAME equalsIgnoreCase either the copy
    name itself (for the empty extension) or ``<name>.<ext>`` for a configured
    extension;
  - directories are scanned with listFiles(), so NOT recursively.

Note this is stricter than CorpusIndex, which indexes every file in
copybook_dirs whatever its extension — so a name can resolve in the graph and
still fail the parse.
"""

import json
from pathlib import Path
from typing import Sequence

from cobble.copy_scan import CopyRef, ScanResult
from cobble.corpus_config import CorpusConfig
from cobble.diagnose_copybooks import find_missing_copybooks, main


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
    defaults.update(overrides)
    return CorpusConfig(**defaults)


def _scanned(tmp_path: Path, program: str, *copies: tuple[str, int]) -> ScanResult:
    """A scan result as the bridge would report one, for ``<program>.cbl``."""
    return ScanResult(
        path=tmp_path / "cbl" / f"{program}.cbl",
        copies=tuple(CopyRef(name, line) for name, line in copies),
        errors=0,
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


def test_a_member_with_syntax_errors_still_contributes_the_copies_it_named(
    tmp_path: Path,
) -> None:
    """ANTLR recovers and keeps reporting COPYs after a syntax error. Dropping
    such a member would lose real answers to make the totals look tidier."""
    (tmp_path / "cpy").mkdir()
    results = [
        ScanResult(
            path=tmp_path / "cbl" / "PROGA.cbl",
            copies=(CopyRef("CUSTREC", 1),),
            errors=4,
        )
    ]

    assert find_missing_copybooks(_config(tmp_path), results) == {
        "CUSTREC": {"PROGA": [1]}
    }


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
    """Stands in for the bridge, so the CLI tests need no JVM."""

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

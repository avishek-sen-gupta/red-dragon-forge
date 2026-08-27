"""Pre-flight copybook diagnostic.

The expensive phase of a corpus build is COBOL parsing, and a COPY the ProLeap
preprocessor cannot resolve fails the whole program. Finding that out costs
hours of JVM subprocesses; finding it out from the raw COPY scan costs seconds.

Resolution here mirrors ProLeap's CobolWordCopyBookFinderImpl exactly, because
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
from pathlib import Path

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


def _touch(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_copybook_present_under_a_listed_extension_is_not_missing(
    tmp_path: Path,
) -> None:
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    _touch(tmp_path / "cpy" / "CUSTREC.cpy", "       01 CUST-REC.\n")
    assert find_missing_copybooks(_config(tmp_path)) == {}


def test_a_copybook_absent_everywhere_is_reported_with_program_and_line(
    tmp_path: Path,
) -> None:
    _touch(
        tmp_path / "cbl" / "PROGA.cbl",
        "       PROGRAM-ID. PROGA.\n       COPY CUSTREC.\n",
    )
    (tmp_path / "cpy").mkdir()
    assert find_missing_copybooks(_config(tmp_path)) == {"CUSTREC": {"PROGA": [2]}}


def test_a_copybook_present_under_an_unlisted_extension_is_still_missing(
    tmp_path: Path,
) -> None:
    """ProLeap compares the whole filename against ``<name>.<ext>`` for the
    configured extensions only, so a member on disk as .txt with txt unlisted is
    invisible to the parser however obviously it is the right file."""
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    _touch(tmp_path / "cpy" / "CUSTREC.txt", "       01 CUST-REC.\n")
    assert find_missing_copybooks(_config(tmp_path)) == {"CUSTREC": {"PROGA": [1]}}


def test_the_empty_extension_matches_a_file_with_no_suffix(tmp_path: Path) -> None:
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    _touch(tmp_path / "cpy" / "CUSTREC", "       01 CUST-REC.\n")
    assert find_missing_copybooks(_config(tmp_path)) == {}


def test_matching_ignores_case_on_both_name_and_extension(tmp_path: Path) -> None:
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY custrec.\n")
    _touch(tmp_path / "cpy" / "CUSTREC.CPY", "       01 CUST-REC.\n")
    assert find_missing_copybooks(_config(tmp_path)) == {}


def test_copybook_subdirectories_are_not_searched(tmp_path: Path) -> None:
    """ProLeap uses listFiles(), one level. A copybook one directory down is not
    found, so the diagnostic must not claim it is."""
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    _touch(tmp_path / "cpy" / "nested" / "CUSTREC.cpy", "       01 CUST-REC.\n")
    assert find_missing_copybooks(_config(tmp_path)) == {"CUSTREC": {"PROGA": [1]}}


def test_one_copybook_needed_by_two_programs_is_deduplicated_to_one_key(
    tmp_path: Path,
) -> None:
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    _touch(tmp_path / "cbl" / "PROGB.cbl", "\n       COPY CUSTREC.\n")
    (tmp_path / "cpy").mkdir()
    assert find_missing_copybooks(_config(tmp_path)) == {
        "CUSTREC": {"PROGA": [1], "PROGB": [2]}
    }


def test_two_copies_of_one_copybook_in_one_program_report_both_lines(
    tmp_path: Path,
) -> None:
    _touch(
        tmp_path / "cbl" / "PROGA.cbl",
        "       COPY CUSTREC.\n       DISPLAY 'X'.\n       COPY CUSTREC.\n",
    )
    (tmp_path / "cpy").mkdir()
    assert find_missing_copybooks(_config(tmp_path)) == {"CUSTREC": {"PROGA": [1, 3]}}


def test_a_call_is_not_reported_as_a_missing_copybook(tmp_path: Path) -> None:
    """The scanner yields CALL refs too; only COPY resolves against copybook_dirs."""
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       CALL 'SUBPROG'.\n")
    (tmp_path / "cpy").mkdir()
    assert find_missing_copybooks(_config(tmp_path)) == {}


def test_a_missing_copybook_dir_is_not_fatal(tmp_path: Path) -> None:
    """A corpus can configure a copybook dir that does not exist yet; that is a
    reason every COPY is missing, not a reason to crash."""
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    config = _config(tmp_path, copybook_dirs=(tmp_path / "nope",))
    assert find_missing_copybooks(config) == {"CUSTREC": {"PROGA": [1]}}


def test_a_program_the_scanner_cannot_read_is_reported_not_only_logged(
    tmp_path: Path,
) -> None:
    """An unscanned program is one whose missing copybooks are absent from this
    report, so the totals are a lower bound and the reader has to be told. The
    COPY/CALL grammar does reject real corpus members -- an odd number of quotes
    anywhere in a program leaves a literal unterminated for the tokeniser."""
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    _touch(tmp_path / "cbl" / "PROGB.cbl", "       DISPLAY 'unterminated.\n")
    (tmp_path / "cpy").mkdir()

    unscanned: list[str] = []
    missing = find_missing_copybooks(_config(tmp_path), unscanned)

    assert missing == {"CUSTREC": {"PROGA": [1]}}
    assert len(unscanned) == 1
    assert unscanned[0].startswith("PROGB.cbl: ")


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


def test_the_json_goes_to_stdout_when_no_output_is_given(
    tmp_path: Path, capsys
) -> None:
    _touch(tmp_path / "cbl" / "PROGA.cbl", "       COPY CUSTREC.\n")
    (tmp_path / "cpy").mkdir()
    (tmp_path / "jcl").mkdir()

    assert main(["--config", str(_write_config_yaml(tmp_path))]) == 0

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

    assert (
        main(["--config", str(_write_config_yaml(tmp_path)), "--output", str(out)]) == 0
    )

    assert json.loads(out.read_text()) == {"CUSTREC": {"PROGA": [1]}}
    assert capsys.readouterr().out == ""

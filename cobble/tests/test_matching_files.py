from pathlib import Path

from cobble.matching_files import matching_files


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


def test_selects_only_the_files_a_glob_matches(tmp_path: Path) -> None:
    _touch(tmp_path / "ACCT.cbl")
    _touch(tmp_path / "README.md")
    assert matching_files(tmp_path, ("*.cbl",)) == [tmp_path / "ACCT.cbl"]


def test_a_file_matched_by_two_globs_appears_once(tmp_path: Path) -> None:
    _touch(tmp_path / "ACCT.cbl")
    assert matching_files(tmp_path, ("*.cbl", "ACCT.*")) == [tmp_path / "ACCT.cbl"]


def test_results_are_sorted_across_globs_not_grouped_by_glob(tmp_path: Path) -> None:
    # Order must be a property of the paths, not of the glob list, so a config
    # that reorders its globs still yields the same corpus order.
    _touch(tmp_path / "ZEBRA.cbl")
    _touch(tmp_path / "ALPHA.jcl")
    assert matching_files(tmp_path, ("*.cbl", "*.jcl")) == [
        tmp_path / "ALPHA.jcl",
        tmp_path / "ZEBRA.cbl",
    ]


def test_a_glob_may_name_a_subdirectory(tmp_path: Path) -> None:
    # A corpus may span sibling program directories under one cobol_dir, so patterns
    # carry the subdirectory rather than the config carrying several dirs.
    _touch(tmp_path / "SRC" / "P1.txt")
    _touch(tmp_path / "ONLINE" / "P2.txt")
    _touch(tmp_path / "SRC" / "skip.dat")
    assert matching_files(tmp_path, ("SRC/*.txt", "ONLINE/*.txt")) == [
        tmp_path / "ONLINE" / "P2.txt",
        tmp_path / "SRC" / "P1.txt",
    ]


def test_no_globs_selects_nothing(tmp_path: Path) -> None:
    _touch(tmp_path / "ACCT.cbl")
    assert matching_files(tmp_path, ()) == []


def test_a_missing_directory_selects_nothing_rather_than_raising(
    tmp_path: Path,
) -> None:
    assert matching_files(tmp_path / "absent", ("*.cbl",)) == []

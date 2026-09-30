from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from cobble.parsing.copybook_dir import (
    NoCopybookDir,
    NoCopybookDirReason,
    classified,
    unscannable,
)
from cobble.corpus_config import CorpusConfig
from cobble.parsing.parse_corpus import copybook_dirs
from tests.parsing.test_parse_corpus import _config


def _with_copybook_dirs(config: CorpusConfig, dirs: Sequence[Path]) -> CorpusConfig:
    return replace(config, copybook_dirs=tuple(dirs))


def test_a_directory_classifies_as_itself_and_anything_else_says_why(
    tmp_path: Path,
) -> None:
    """Both non-directory cases are a Java NullPointerException inside ProLeap's
    copybook finder rather than a missing copybook, so they are one behaviour --
    but they want different answers from the reader, so they stay distinct."""
    present = tmp_path / "sym"
    present.mkdir()
    a_file = tmp_path / "COPYBOOK.cpy"
    a_file.write_text("       01 WS-X PIC X.\n")

    assert classified(present) == present
    assert classified(tmp_path / "absent") == NoCopybookDir(
        tmp_path / "absent", NoCopybookDirReason.ABSENT
    )
    assert classified(a_file) == NoCopybookDir(
        a_file, NoCopybookDirReason.NOT_A_DIRECTORY
    )


def test_unscannable_keeps_only_the_ones_proleap_cannot_read(tmp_path: Path) -> None:
    (tmp_path / "sym").mkdir()

    assert unscannable((tmp_path / "sym", tmp_path / "gone")) == (
        NoCopybookDir(tmp_path / "gone", NoCopybookDirReason.ABSENT),
    )


def test_a_corpus_whose_copybook_dirs_all_exist_hands_them_back(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    sym = tmp_path / "sym"
    sym.mkdir()

    assert copybook_dirs(_with_copybook_dirs(config, (sym,))) == (sym,)


def test_a_copybook_dir_that_is_not_a_directory_ends_the_run_naming_it(
    tmp_path: Path,
) -> None:
    """Before any JVM starts, so nothing is written and no .fail can be cached
    against a member for what is a configuration fault (red-dragon-forge-jbh)."""
    config = _with_copybook_dirs(_config(tmp_path), (tmp_path / "sym",))

    with pytest.raises(SystemExit, match=r"sym \(absent\)"):
        copybook_dirs(config)

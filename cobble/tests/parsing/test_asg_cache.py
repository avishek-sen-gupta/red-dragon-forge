import json
from pathlib import Path

import pytest

from cobble.parsing.asg_cache import asg_of, cache_path, failure_path


def test_a_cached_asg_is_named_for_its_source_file(tmp_path: Path) -> None:
    """The name is a pure function of the source filename, so a reader who has the
    program and the cache directory can find its ASG without an index."""
    assert cache_path(tmp_path, Path("/corpus/MYPROG01.txt")) == (
        tmp_path / "MYPROG01.json"
    )


def test_a_failure_marker_sits_where_the_asg_would_have(tmp_path: Path) -> None:
    """A member that cannot parse must not be retried on every run, and the marker
    is only cheap to look for if its name follows the same rule."""
    assert failure_path(tmp_path, Path("/corpus/MYPROG01.txt")) == (
        tmp_path / "MYPROG01.fail"
    )


def test_reading_a_cached_asg_gives_back_the_program(tmp_path: Path) -> None:
    (tmp_path / "PGM.json").write_text(
        json.dumps({"program_id": "PGM", "paragraphs": []}), encoding="utf-8"
    )

    assert asg_of(tmp_path, Path("/corpus/PGM.txt")).program_id == "PGM"


def test_reading_an_uncached_program_says_which_one(tmp_path: Path) -> None:
    """The whole point of a shared cache is that every stage after the parse reads
    it, so the error a stage hits first has to name the member and the directory --
    otherwise it reads as "the cache is empty" rather than "this member failed"."""
    with pytest.raises(FileNotFoundError, match="PGM"):
        asg_of(tmp_path, Path("/corpus/PGM.txt"))

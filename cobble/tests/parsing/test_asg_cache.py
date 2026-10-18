import json
from pathlib import Path

import pytest

from cobble.parsing.asg_cache import (
    cache_path,
    failure_path,
    first_program_of,
    programs_of,
    unit_json,
)
from cobol_asg.compilation_unit import CobolCompilationUnit


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


def _nested_and_batch(tmp_path: Path) -> None:
    (tmp_path / "PGM.json").write_text(
        json.dumps(
            {
                "programs": [
                    {
                        "program_id": "PGM",
                        "programs": [{"program_id": "INNER", "paragraphs": []}],
                    },
                    {"program_id": "NEXT", "paragraphs": []},
                ]
            }
        ),
        encoding="utf-8",
    )


def test_a_cached_member_gives_back_every_program_or_its_first(tmp_path: Path) -> None:
    """A member is a compilation unit: a reader covering the member gets every
    program in pre-order, each without those it contains, and a reader meaning the
    program the member is named for gets the first."""
    _nested_and_batch(tmp_path)
    source = Path("/corpus/PGM.txt")

    assert (
        tuple(
            (asg.program_id, len(asg.programs)) for asg in programs_of(tmp_path, source)
        ),
        first_program_of(tmp_path, source).program_id,
    ) == ((("PGM", 0), ("INNER", 0), ("NEXT", 0)), "PGM")


def test_a_written_unit_reads_back_as_the_same_programs(tmp_path: Path) -> None:
    _nested_and_batch(tmp_path)
    path = tmp_path / "PGM.json"
    unit = CobolCompilationUnit.from_dict(json.loads(path.read_text(encoding="utf-8")))
    path.write_text(unit_json(unit), encoding="utf-8")

    assert CobolCompilationUnit.from_dict(json.loads(path.read_text())) == unit


def test_reading_an_uncached_program_says_which_one(tmp_path: Path) -> None:
    """The whole point of a shared cache is that every stage after the parse reads
    it, so the error a stage hits first has to name the member and the directory --
    otherwise it reads as "the cache is empty" rather than "this member failed"."""
    with pytest.raises(FileNotFoundError, match="PGM"):
        programs_of(tmp_path, Path("/corpus/PGM.txt"))

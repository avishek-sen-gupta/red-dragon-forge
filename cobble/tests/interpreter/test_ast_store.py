"""AstStore — parse each COBOL program once, without holding every ASG in RAM.

Written as a safety net before refactoring the store, which had no tests and one
production call site. Every assertion here pins behaviour that already held, so
the file is the evidence the refactor changed nothing a caller can see: the
parser runs once per program, the ASG comes back off disk, the preprocessor is
applied on load rather than at parse time, and same-named programs in different
directories stay distinct.
"""

from collections.abc import Mapping
from pathlib import Path

import pytest

from interpreter.cobol.asg_types import CobolASG
from interpreter.cobol.ast_store import AstParseError, AstStore, temp_ast_store
from interpreter.cobol.subprocess_runner import CobolParseError


class CountingParser:
    """A bridge stand-in that counts invocations and never launches a JVM.

    Indexed by source bytes, so a test states what the bridge would write for a
    program's contents.
    """

    def __init__(self, responses: Mapping[bytes, str]):
        self._responses = responses
        self.calls: tuple[bytes, ...] = ()

    def parse_to_file(self, source: bytes, out: Path) -> None:
        self.calls = (*self.calls, source)
        out.write_text(self._responses[source], encoding="utf-8")


def _program(directory: Path, name: str, source: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(source)
    return path


def test_get_returns_the_asg_the_parser_wrote(tmp_path: Path) -> None:
    path = _program(tmp_path, "A.cbl", b"PROGRAM A")
    store = AstStore(tmp_path / "cache")
    store.parse_all(
        {path: b"PROGRAM A"},
        CountingParser({b"PROGRAM A": '{"program_id": "PAYROLL"}'}),
    )
    assert store.get(path).program_id == "PAYROLL"


def test_the_parser_runs_once_per_program_however_often_get_is_called(
    tmp_path: Path,
) -> None:
    """The point of the store: get() deserializes, it does not re-parse."""
    path = _program(tmp_path, "A.cbl", b"PROGRAM A")
    parser = CountingParser({b"PROGRAM A": '{"program_id": "PAYROLL"}'})
    store = AstStore(tmp_path / "cache")
    store.parse_all({path: b"PROGRAM A"}, parser)
    store.get(path)
    store.get(path)
    store.get(path)
    assert parser.calls == (b"PROGRAM A",)


def test_the_preprocessor_is_applied_on_load_not_at_parse_time(tmp_path: Path) -> None:
    """The bridge writes raw JSON; the preprocessor shapes it when get() reads it.
    So a store built with a preprocessor returns a transformed ASG from bytes the
    parser never saw transformed."""
    path = _program(tmp_path, "A.cbl", b"PROGRAM A")
    parser = CountingParser({b"PROGRAM A": '{"program_id": "raw"}'})
    store = AstStore(tmp_path / "cache")
    store.parse_all(
        {path: b"PROGRAM A"},
        parser,
        preprocessor=lambda d: {**d, "program_id": "SHAPED"},
    )
    assert store.get(path).program_id == "SHAPED"


def test_without_a_preprocessor_the_json_is_used_as_written(tmp_path: Path) -> None:
    path = _program(tmp_path, "A.cbl", b"PROGRAM A")
    store = AstStore(tmp_path / "cache")
    store.parse_all(
        {path: b"PROGRAM A"}, CountingParser({b"PROGRAM A": '{"program_id": "AS_IS"}'})
    )
    assert store.get(path).program_id == "AS_IS"


def test_two_programs_with_the_same_stem_do_not_collide(tmp_path: Path) -> None:
    """The cache is indexed by the full md5 digest of the path, so same-named
    programs in different directories stay distinct — the cache filename carries
    the stem, which would otherwise be the collision."""
    one = _program(tmp_path / "libA", "SAME.cbl", b"ONE")
    two = _program(tmp_path / "libB", "SAME.cbl", b"TWO")
    parser = CountingParser(
        {b"ONE": '{"program_id": "ONE"}', b"TWO": '{"program_id": "TWO"}'}
    )
    store = AstStore(tmp_path / "cache")
    store.parse_all({one: b"ONE", two: b"TWO"}, parser)
    assert (store.get(one).program_id, store.get(two).program_id) == ("ONE", "TWO")


def test_an_empty_program_set_is_not_an_error(tmp_path: Path) -> None:
    store = AstStore(tmp_path / "cache")
    store.parse_all({}, CountingParser({}))
    assert isinstance(CobolASG.from_dict({}), CobolASG)


# --- what a rejected program looks like from the outside ----------------------


class RejectingParser:
    """A bridge stand-in that rejects the sources named, and parses the rest."""

    def __init__(self, rejected: Mapping[bytes, Exception]):
        self._rejected = rejected

    def parse_to_file(self, source: bytes, out: Path) -> None:
        if source in self._rejected:
            raise self._rejected[source]
        out.write_text('{"program_id": "OK"}', encoding="utf-8")


def test_a_rejected_program_is_named_in_the_error(tmp_path: Path) -> None:
    """A corpus parse is thousands of JVM subprocesses deep when one program is
    rejected, and the bridge's own message says nothing about which file it read --
    it reads from stdin via a temp file whose name is the bridge's, not the
    corpus's. Without the name here, the only way to identify the program is to
    bisect the corpus.
    """
    path = _program(tmp_path, "BADPROG.cbl", b"junk")
    store = AstStore(tmp_path / "cache")
    with pytest.raises(AstParseError, match=r"BADPROG\.cbl"):
        store.parse_all(
            {path: b"junk"},
            RejectingParser({b"junk": CobolParseError("syntax error in line 1:7")}),
        )


def test_the_bridge_message_survives_and_the_original_is_chained(
    tmp_path: Path,
) -> None:
    """Naming the program must not cost the diagnosis: the bridge's text is what
    says WHY, and the cause chain keeps the original traceback."""
    path = _program(tmp_path, "BADPROG.cbl", b"junk")
    store = AstStore(tmp_path / "cache")
    original = CobolParseError("syntax error in line 1:7 mismatched input")
    with pytest.raises(AstParseError) as caught:
        store.parse_all({path: b"junk"}, RejectingParser({b"junk": original}))
    assert "syntax error in line 1:7 mismatched input" in str(caught.value)
    assert "CobolParseError" in str(caught.value)
    assert caught.value.__cause__ is original


def test_the_program_named_is_the_one_that_was_rejected(tmp_path: Path) -> None:
    """Three programs, one bad: the error names the bad one and no other. The
    parses run on a thread pool, so the name has to travel with the failure rather
    than be inferred from where the sweep stopped."""
    good = _program(tmp_path, "GOODONE.cbl", b"fine")
    bad = _program(tmp_path, "BADPROG.cbl", b"junk")
    other = _program(tmp_path, "ALSOFINE.cbl", b"also fine")
    store = AstStore(tmp_path / "cache")
    with pytest.raises(AstParseError) as caught:
        store.parse_all(
            {good: b"fine", bad: b"junk", other: b"also fine"},
            RejectingParser({b"junk": CobolParseError("rejected")}),
        )
    assert "BADPROG.cbl" in str(caught.value)
    assert "GOODONE" not in str(caught.value)
    assert "ALSOFINE" not in str(caught.value)


def test_a_cache_write_failure_is_named_too_and_says_what_it_was(
    tmp_path: Path,
) -> None:
    """Not every failure is a parse failure -- a full disk raises OSError from the
    write. The class name is in the message so the two are told apart without the
    traceback."""
    path = _program(tmp_path, "BADPROG.cbl", b"junk")
    store = AstStore(tmp_path / "cache")
    with pytest.raises(AstParseError) as caught:
        store.parse_all(
            {path: b"junk"}, RejectingParser({b"junk": OSError("no space")})
        )
    assert "BADPROG.cbl" in str(caught.value)
    assert "OSError" in str(caught.value)


def test_temp_ast_store_removes_its_cache_on_the_way_out() -> None:
    with temp_ast_store() as store:
        cache_dir = store.cache_dir
        assert cache_dir.exists()
    assert not cache_dir.exists()


def test_a_cache_directory_the_caller_supplied_is_the_callers_to_remove(
    tmp_path: Path,
) -> None:
    supplied = tmp_path / "cache"
    store = AstStore(supplied)
    store.parse_all({}, CountingParser({}))
    assert supplied.exists()

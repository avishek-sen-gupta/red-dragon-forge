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

from cobble.interpreter.cobol.asg_types import CobolASG
from cobble.interpreter.cobol.ast_store import AstStore, temp_ast_store


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

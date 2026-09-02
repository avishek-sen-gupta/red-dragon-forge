"""JclStore — parse each JCL member once, without holding every Job in RAM.

A corpus build parses every member twice, each time in a fresh JVM: once
indexing (``corpus_index_builder._index_jcl``) and once building the graph
(``build_graph._build_jcl_graph``). Keeping the parsed ``Job`` for the second
pass is the obvious fix and the wrong one at corpus scale — hundreds of resident
Jobs.

So this keeps the bridge's raw JSON on disk and deserializes exactly one ``Job``
at a time, on ``get()``, the way ``AstStore`` does for COBOL ASGs. The test that
matters most here is the invocation count: it is the whole point of the store.
"""

from collections.abc import Mapping
from pathlib import Path

import pytest

from jackal.jcl.bridge_parser import JclParseError
from cobble.jcl.jcl_store import JclStore, temp_jcl_store


def _job_json(name: str, step: str = "STEP1", pgm: str = "IEFBR14") -> str:
    return (
        '{"name": "' + name + '", "steps": [{"name": "' + step + '", '
        '"pgm": "' + pgm + '", "dds": []}]}'
    )


class CountingParser:
    """A bridge stand-in that counts invocations and never launches a JVM.

    Keyed by source text, so a test states what the bridge would return for a
    member's contents. A source listed in ``rejects`` raises the way the real
    runner does on a non-zero exit.
    """

    def __init__(
        self, responses: Mapping[str, str], rejects: frozenset[str] = frozenset()
    ):
        self._responses = responses
        self._rejects = rejects
        self.calls: tuple[str, ...] = ()

    def parse_to_json(self, text: str) -> str:
        self.calls = (*self.calls, text)
        if text in self._rejects:
            raise JclParseError(f"jcl-bridge failed (exit 1): rejected {text!r}")
        return self._responses[text]


def _member(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_get_returns_the_parsed_job(tmp_path: Path) -> None:
    path = _member(tmp_path, "A.jcl", "//A JOB")
    store = JclStore(tmp_path / "cache")
    store.parse_all([path], CountingParser({"//A JOB": _job_json("PAYROLL")}))
    assert store.get(path).name == "PAYROLL"


def test_the_bridge_runs_once_per_member_however_often_get_is_called(
    tmp_path: Path,
) -> None:
    """The whole point: both corpus passes call get(), the JVM runs once."""
    path = _member(tmp_path, "A.jcl", "//A JOB")
    parser = CountingParser({"//A JOB": _job_json("PAYROLL")})
    store = JclStore(tmp_path / "cache")
    store.parse_all([path], parser)
    store.get(path)
    store.get(path)
    store.get(path)
    assert parser.calls == ("//A JOB",)


def test_a_member_the_bridge_rejects_is_reraised_on_get(tmp_path: Path) -> None:
    """parse_all must not raise: a member cobble cannot read is corpus shape,
    reported per member by both existing callers. The failure is held and
    resurfaces at the point the caller already handles it."""
    path = _member(tmp_path, "BAD.jcl", "//BAD")
    store = JclStore(tmp_path / "cache")
    store.parse_all([path], CountingParser({}, rejects=frozenset({"//BAD"})))
    with pytest.raises(JclParseError, match="rejected"):
        store.get(path)


def test_a_rejected_member_does_not_stop_the_others(tmp_path: Path) -> None:
    bad = _member(tmp_path, "BAD.jcl", "//BAD")
    good = _member(tmp_path, "GOOD.jcl", "//GOOD JOB")
    parser = CountingParser(
        {"//GOOD JOB": _job_json("GOODJOB")}, rejects=frozenset({"//BAD"})
    )
    store = JclStore(tmp_path / "cache")
    store.parse_all([bad, good], parser)
    assert store.get(good).name == "GOODJOB"


def test_a_member_never_handed_to_parse_all_is_a_caller_bug(tmp_path: Path) -> None:
    """Not corpus shape and not silently parsed here: the two passes must walk
    the same member set, and a mismatch is a bug in the caller."""
    store = JclStore(tmp_path / "cache")
    store.parse_all([], CountingParser({}))
    with pytest.raises(KeyError, match="parse_all"):
        store.get(tmp_path / "NEVER.jcl")


def test_two_members_with_the_same_stem_do_not_collide(tmp_path: Path) -> None:
    """The key is the full md5 of the path, so same-named members in different
    directories stay distinct — and the cache filename carries the stem, which
    would otherwise be the collision."""
    one = _member(tmp_path / "libA", "SAME.jcl", "//ONE JOB")
    two = _member(tmp_path / "libB", "SAME.jcl", "//TWO JOB")
    parser = CountingParser(
        {"//ONE JOB": _job_json("JOBONE"), "//TWO JOB": _job_json("JOBTWO")}
    )
    store = JclStore(tmp_path / "cache")
    store.parse_all([one, two], parser)
    assert (store.get(one).name, store.get(two).name) == ("JOBONE", "JOBTWO")


def test_a_member_that_is_not_valid_utf_8_still_parses(tmp_path: Path) -> None:
    """Members are 8-bit text; the store decodes them the way the callers did."""
    path = tmp_path / "A.jcl"
    path.write_bytes(b"//A JOB \xa6")
    store = JclStore(tmp_path / "cache")
    store.parse_all([path], CountingParser({"//A JOB ¦": _job_json("PAYROLL")}))
    assert store.get(path).name == "PAYROLL"


def test_temp_jcl_store_removes_its_cache_on_the_way_out() -> None:
    """Why a run cannot be served output from a different grammar."""
    with temp_jcl_store() as store:
        cache_dir = store.cache_dir
        assert cache_dir.exists()
    assert not cache_dir.exists()


def test_a_cache_directory_the_caller_supplied_is_the_callers_to_remove(
    tmp_path: Path,
) -> None:
    supplied = tmp_path / "cache"
    store = JclStore(supplied)
    store.parse_all([], CountingParser({}))
    assert supplied.exists()

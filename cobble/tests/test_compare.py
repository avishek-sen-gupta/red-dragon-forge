"""The identity diff's reporting: the count it returns drives the exit code, and
the detail it emits is what someone reads when 448/832 does not reproduce."""

import logging

import cobble.compare
from cobble.compare import _absent_inputs, _edge_key, _node_key, _report


def test_identical_sets_report_no_differences(caplog) -> None:
    caplog.set_level(logging.INFO)
    both = {("PROGRAM", "A"), ("PROGRAM", "B")}

    assert _report("NODES", both, both) == 0
    assert "identical (2)" in caplog.text


def test_a_missing_node_is_counted_and_named(caplog) -> None:
    """MISSING means the extraction lost something the reference has -- the whole
    point of the diff, so the key has to be in the output, not just the count."""
    caplog.set_level(logging.INFO)

    diff = _report("NODES", {("PROGRAM", "A")}, set())

    assert diff == 1
    assert "MISSING (1)" in caplog.text
    assert "PROGRAM" in caplog.text


def test_an_extra_node_is_counted_and_named(caplog) -> None:
    caplog.set_level(logging.INFO)

    diff = _report("NODES", set(), {("PROGRAM", "A")})

    assert diff == 1
    assert "EXTRA (1)" in caplog.text


def test_missing_and_extra_are_summed_into_one_count(caplog) -> None:
    """The count is summed into the exit code, so a run that both lost and gained
    a node must not report as clean."""
    caplog.set_level(logging.INFO)

    assert _report("NODES", {("PROGRAM", "A")}, {("PROGRAM", "B")}) == 2


def test_the_report_is_logged_rather_than_printed(capsys, caplog) -> None:
    """Nothing on stdout: `cobble-compare`'s output is a human report, and keeping it
    on one stream (stderr, via logging) means it cannot interleave with itself."""
    caplog.set_level(logging.INFO)

    _report("EDGES", {("A", "PROGRAM", "B", "PROGRAM", "CALLS")}, set())

    assert capsys.readouterr() == ("", "")
    assert caplog.messages


def test_an_unextracted_tree_names_the_command_that_extracts(
    tmp_path, monkeypatch, caplog
) -> None:
    """`cobble-compare` on a clean checkout used to raise FileNotFoundError from
    _load, which tells the reader nothing about what to run first."""
    caplog.set_level(logging.ERROR)
    (tmp_path / "reference").mkdir()
    for name in ("nodes.jsonl", "edges.jsonl"):
        (tmp_path / "reference" / name).write_text("")
    monkeypatch.setattr(cobble.compare, "_REPO_ROOT", tmp_path)

    assert cobble.compare.main() == 1
    assert "out/nodes.jsonl" in caplog.text
    assert "cobble-build --config" in caplog.text


def test_absent_inputs_names_both_sides(tmp_path) -> None:
    absent = _absent_inputs(tmp_path / "reference", tmp_path / "out")

    assert {p.name for p in absent} == {"nodes.jsonl", "edges.jsonl"}
    assert len(absent) == 4


def test_the_keys_are_the_documented_identities() -> None:
    """Node identity is (kind, id) and edge identity is the 5-tuple; the diff means
    nothing if these drift from what the reference was built with."""
    assert _node_key({"kind": "PROGRAM", "id": "A", "file_path": "x"}) == (
        "PROGRAM",
        "A",
    )
    assert _edge_key(
        {
            "source": "A",
            "source_kind": "PROGRAM",
            "target": "B",
            "target_kind": "PROGRAM",
            "kind": "CALLS",
            "attrs": {"line": 1},
        }
    ) == ("A", "PROGRAM", "B", "PROGRAM", "CALLS")

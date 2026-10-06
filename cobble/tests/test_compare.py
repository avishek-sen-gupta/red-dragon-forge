"""The identity diff's reporting: the count it returns drives the exit code, and
the detail it emits is what someone reads when 448/843 does not reproduce."""

import logging
from pathlib import Path

from cobble.compare import (
    REFERENCE,
    _absent_inputs,
    _edge_identity,
    _node_identity,
    _parse_args,
    _report,
    _run,
)
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


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


def test_an_unextracted_tree_names_the_command_that_extracts(tmp_path, caplog) -> None:
    """`cobble-compare` on a clean checkout used to raise FileNotFoundError from
    _load, which tells the reader nothing about what to run first."""
    caplog.set_level(logging.ERROR)
    reference = tmp_path / "graph.jsonl"
    reference.write_text("")
    absent = tmp_path / "out" / "carddemo.jsonl"

    assert _run(_parse_args(["--graph", str(absent)]), reference) == 1
    assert str(absent) in caplog.text
    assert "cobble-build --config config/carddemo.toml --output" in caplog.text


def test_absent_inputs_names_both_sides(tmp_path) -> None:
    reference = tmp_path / "reference" / "graph.jsonl"
    graph = tmp_path / "out" / "carddemo.jsonl"

    assert _absent_inputs(reference, graph) == (reference, graph)


def test_the_committed_reference_matches_itself() -> None:
    """The whole diff, end to end, over the real reference file: read, keyed, and
    compared on both sides -- so the file parses and the keys are total over it."""
    assert _run(_parse_args(["--graph", str(REFERENCE)]), REFERENCE) == 0


def test_the_keys_are_the_documented_identities() -> None:
    """Node identity is (kind, id) and edge identity is the 5-tuple; the diff means
    nothing if these drift from what the reference was built with."""
    assert _node_identity(
        GraphNode(id="A", kind=NodeKind.PROGRAM, location=Path("x"))
    ) == (
        "PROGRAM",
        "A",
    )
    assert _edge_identity(
        GraphEdge(
            source="A",
            source_kind=NodeKind.PROGRAM,
            target="B",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
            attrs={"line": 1},
        )
    ) == ("A", "PROGRAM", "B", "PROGRAM", "CALL")


def test_a_graph_missing_one_reference_edge_is_one_difference(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)
    graph = tmp_path / "carddemo.jsonl"
    graph.write_text(
        "".join(f"{line}\n" for line in REFERENCE.read_text().splitlines()[:-1])
    )

    assert _run(_parse_args(["--graph", str(graph)]), REFERENCE) == 1
    assert "MISSING (1)" in caplog.text
    assert "RESULT: 1 difference(s)." in caplog.text

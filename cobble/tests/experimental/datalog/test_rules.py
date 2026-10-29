"""The generic Soufflé rule library, run on small hand-written fact sets."""

from __future__ import annotations

import csv
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from importlib import import_module
from pathlib import Path

import pytest
from cobble.experimental.datalog.facts_writer import schema_text
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_facts import FAMILIES

pytestmark = pytest.mark.skipif(
    shutil.which("souffle") is None, reason="the rule tests run souffle"
)

COBBLE = Path(__file__).resolve().parents[3]
LIBRARY = COBBLE / "cobble" / "experimental" / "datalog" / "rules"

Row = tuple[str | int, ...]
Facts = Mapping[str, Sequence[Row]]


@pytest.fixture
def schema() -> str:
    return schema_text(
        tuple(
            relation
            for family in FAMILIES
            for relation in vars(import_module(family.__module__)).values()
            if isinstance(relation, Relation)
        )
    )


def evaluate(
    tmp_path: Path, schema: str, facts: Facts, question: str
) -> dict[str, set[tuple[str, ...]]]:
    facts_dir = tmp_path / "facts"
    out_dir = tmp_path / "out"
    facts_dir.mkdir()
    out_dir.mkdir()
    (facts_dir / "schema.dl").write_text(schema)
    inputs = [
        line.split()[1] for line in schema.splitlines() if line.startswith(".input ")
    ]
    for name in inputs:
        (facts_dir / f"{name}.facts").write_text(
            "".join("\t".join(map(str, row)) + "\n" for row in facts.get(name, ()))
        )
    (tmp_path / "question.dl").write_text(question)
    subprocess.run(
        [
            "souffle",
            "--include-dir",
            str(facts_dir),
            "--include-dir",
            str(LIBRARY),
            "-F",
            str(facts_dir),
            "-D",
            str(out_dir),
            str(tmp_path / "question.dl"),
        ],
        check=True,
    )
    return {
        path.stem: {
            tuple(row)
            for row in csv.reader(path.read_text().splitlines(), delimiter="\t")
        }
        for path in out_dir.glob("*.csv")
    }


def test_a_perform_returns_to_its_caller_and_its_range_end_does_not_fall_through(
    tmp_path: Path, schema: str
) -> None:
    facts: Facts = {
        "cfg_entry": [("P", "a")],
        "cfg_edge": [
            ("P", "a", "l", "PERFORM"),
            ("P", "l", "e", "FLOW"),
            ("P", "e", "x", "FALLTHRU"),
            ("P", "e", "r", "RETURN"),
            ("P", "l", "q", "RETURN"),
            ("P", "r", "z", "FLOW"),
        ],
        "cfg_perform": [("P", "a", "r", "e")],
    }
    out = evaluate(tmp_path, schema, facts, '#include "reach.dl"\n.output reach\n')
    assert out["reach"] == {("P", n) for n in ("a", "l", "e", "r", "z")}


def test_a_guard_holds_only_for_the_site_every_path_to_which_takes_it(
    tmp_path: Path, schema: str
) -> None:
    facts: Facts = {
        "cfg_entry": [("P", "a")],
        "cfg_node": [("P", "a", "TEST", "PARA", 10, "")],
        "cfg_edge": [
            ("P", "a", "b", "TRUE"),
            ("P", "a", "w1", "FALSE"),
            ("P", "b", "w1", "FLOW"),
            ("P", "b", "w2", "FLOW"),
        ],
        "cfg_pred": [("P", "a", "X", "==", "'Y'", "X == 'Y'", "yes")],
        "access": [("P", "a", "X", "working_storage", 0, 1)],
        "cfg_read": [("P", "a", "Z")],
    }
    question = (
        '#include "guard_reads.dl"\n'
        'site("P","w1").\nsite("P","w2").\n'
        ".output guard\n.output guard_reads\n"
    )
    out = evaluate(tmp_path, schema, facts, question)
    assert out["guard"] == {("P", "w2", "a", "TRUE", "X == 'Y'", "yes")}
    assert out["guard_reads"] == {("P", "a", "X"), ("P", "a", "Z")}


def test_a_writer_is_a_setter_when_its_bytes_are_new_and_a_write_back_otherwise(
    tmp_path: Path, schema: str
) -> None:
    facts: Facts = {
        "slot": [
            ("D", "dataset", "", "", "", 0, 4),
            ("F1", "field", "P1", "R", "F1", 0, 4),
            ("O1", "origin", "P1", "", "", 0, 4),
            ("F2", "field", "P2", "R", "F2", 0, 4),
            ("R2", "field", "P2", "R", "R2", 0, 4),
            ("O2", "origin", "P2", "", "", 0, 4),
            ("F3", "field", "P3", "R", "F3", 0, 4),
            ("O3", "origin", "P3", "", "", 0, 4),
        ],
        "slot_edge": [
            ("F1", "D", "certain", "yes", "no"),
            ("O1", "F1", "certain", "no", "no"),
            ("F2", "D", "certain", "yes", "no"),
            ("R2", "F2", "certain", "no", "no"),
            ("D", "R2", "certain", "yes", "no"),
            ("O2", "R2", "certain", "no", "no"),
            ("F3", "D", "certain", "yes", "no"),
            ("O3", "F3", "certain", "no", "no"),
        ],
        "slot_align": [
            ("F1", "D", 0, 0, 4),
            ("O1", "F1", 0, 0, 4),
            ("F2", "D", 0, 0, 4),
            ("R2", "F2", 0, 0, 4),
            ("D", "R2", 0, 0, 4),
            ("O2", "R2", 0, 0, 4),
            ("O3", "F3", 0, 0, 4),
        ],
        "origin": [
            ("O1", "P1", "FILE", "IN-FILE"),
            ("O2", "P2", "FILE", "D-FILE"),
            ("O3", "P3", "UNMODELLED", "ACCEPT"),
        ],
    }
    question = (
        '#include "writers.dl"\ntarget_slot("D").\n'
        ".output writer\n.output new_source\n.output setter\n.output writes_back\n"
    )
    out = evaluate(tmp_path, schema, facts, question)
    assert out["writer"] == {("P1", "F1", "D"), ("P2", "F2", "D"), ("P3", "F3", "D")}
    assert out["new_source"] == {
        ("P1", "F1", "O1", "0", "4"),
        ("P3", "F3", "O3", "0", "4"),
    }
    assert out["setter"] == {("P1", "F1"), ("P3", "F3")}
    assert out["writes_back"] == {("P2", "F2")}


def test_a_byte_walk_keeps_offsets_through_an_aligned_edge_and_takes_the_whole_field_otherwise(
    tmp_path: Path, schema: str
) -> None:
    facts: Facts = {
        "slot": [
            (s, "field", "P", "R", s, 0, z)
            for s, z in (("A", 8), ("B", 16), ("C", 8), ("N", 2), ("U", 6), ("V", 5))
        ],
        "slot_edge": [
            (a, b, "certain", "no", "no")
            for a, b in (("A", "B"), ("A", "C"), ("A", "N"), ("U", "A"), ("V", "A"))
        ],
        "slot_align": [
            ("A", "B", 0, 10, 6),
            ("A", "N", 6, 0, 2),
            ("U", "A", 1, 0, 4),
        ],
    }
    question = (
        '#include "bytes.dl"\ntarget_bytes("A", 2, 4).\n'
        ".output downstream\n.output upstream\n.output flows\n"
    )
    out = evaluate(tmp_path, schema, facts, question)
    assert out["downstream"] == {("A", "2", "4"), ("B", "12", "14"), ("C", "0", "8")}
    assert out["upstream"] == {("A", "2", "4"), ("U", "3", "5"), ("V", "0", "5")}
    assert out["flows"] == {
        ("A", "B"),
        ("A", "C"),
        ("A", "N"),
        ("U", "A"),
        ("U", "B"),
        ("U", "C"),
        ("U", "N"),
        ("V", "A"),
        ("V", "B"),
        ("V", "C"),
        ("V", "N"),
    }


def test_a_transaction_runs_a_program_two_xctls_away(
    tmp_path: Path, schema: str
) -> None:
    facts: Facts = {
        "kg_node": [("T", "TRANSACTION")],
        "kg_edge": [
            ("T", "STARTS", "P1"),
            ("P1", "XCTL", "P2"),
            ("P2", "XCTL", "P3"),
        ],
        "link": [("P1", "n1", "CALL", "P4", "", "", "yes", "")],
        "target": [("P2", "n2", "program", "XCTL", "WS-PGM", "P5")],
    }
    question = '#include "programs.dl"\n.output hands_to\n.output runs\n'
    out = evaluate(tmp_path, schema, facts, question)
    assert out["hands_to"] == {
        ("P1", "P2", "XCTL"),
        ("P2", "P3", "XCTL"),
        ("P1", "P4", "CALL"),
        ("P2", "P5", "XCTL"),
    }
    assert out["runs"] == {("T", p) for p in ("P1", "P2", "P3", "P4", "P5")}


def test_an_unsettled_program_with_an_unresolved_guard_has_every_gap_and_a_settled_one_none(
    tmp_path: Path, schema: str
) -> None:
    facts: Facts = {
        "cfg_entry": [("P", "a"), ("Q", "a")],
        "cfg_node": [("P", "a", "TEST", "PARA", 10, "")],
        "cfg_edge": [("P", "a", "w", "TRUE"), ("P", "a", "z", "FALSE")],
        "cfg_pred": [("P", "a", "X", "==", "Y", "X == Y", "no")],
        "fp_counts": [("P", "no", 5, 2, 0, 3, 0, 0), ("Q", "yes", 5, 5, 0, 0, 0, 0)],
        "fp_dead_end": [("P", "dynamic-target")],
    }
    question = '#include "gaps.dl"\nsite("P","w").\nsite("Q","a").\n.output gap\n'
    out = evaluate(tmp_path, schema, facts, question)
    assert out["gap"] == {
        ("P", "not-settled", ""),
        ("P", "dead-end", "dynamic-target"),
        ("P", "unresolved-guard", "a"),
        ("P", "unmodelled-writes", "3"),
    }


def test_a_question_may_include_the_schema_and_the_library_together(
    tmp_path: Path, schema: str
) -> None:
    question = '#include "schema.dl"\n#include "guards.dl"\n#include "gaps.dl"\n.output reach\n'
    assert evaluate(tmp_path, schema, {}, question) == {"reach": set()}

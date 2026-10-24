"""The paragraph x field matrix over the paragraphs each graph field is read or written in."""

from __future__ import annotations

import re
from pathlib import Path

from cobble.experimental.aggregates.def_line import DefLine
from cobble.experimental.aggregates.matrix import (
    incidence_matrix,
    load_matrix,
    paragraph_fields,
    save_matrix,
)
from cobble.experimental.partition.extent_row import ExtentRow
from cobble.experimental.partition.leaf_index import leaf_index


def _row(path: tuple[str, ...], start: int, end: int) -> ExtentRow:
    return ExtentRow(
        program="P",
        extents=(f"{path[-1]}@working_storage[{start}:{end}]",),
        records=(path[0],),
        paths=(path,),
        pics=("X",),
        indexes=((),),
    )


INDEX = leaf_index(
    (
        _row(("REC",), 0, 8),
        _row(("REC", "X"), 0, 2),
        _row(("REC", "Y"), 2, 4),
        _row(("REC", "Z"), 4, 6),
        _row(("REC", "W"), 6, 8),
    )
)


def _def(node: str, extent: str, definers: tuple[str, ...] = ()) -> DefLine:
    return DefLine(program="P", node=node, extent=extent, definers=definers)


DEFS = (
    _def("P1/0", "X@working_storage[0:2]", ("P2/1",)),
    _def("P1/1", "Y@working_storage[2:4]"),
    _def("P2/0", "Y@working_storage[2:4]"),
    _def("P3/0", "Z@working_storage[4:6]"),
    _def("P3/1", "W@working_storage[6:8]"),
    _def("P4/0", "Z@working_storage[4:6]"),
)


def test_paragraphs_mark_the_unified_fields_they_touch(tmp_path: Path) -> None:
    paragraphs = paragraph_fields(DEFS, INDEX, {"P:REC.W": "Q:REC.W"}, ())
    trimmed = paragraph_fields(
        DEFS, INDEX, {"P:REC.W": "Q:REC.W"}, (re.compile(r"REC\.[YW]$"),)
    )
    every = incidence_matrix(paragraphs)
    save_matrix(every, tmp_path / "m.npz", tmp_path / "meta.json")
    loaded = load_matrix(tmp_path / "m.npz", tmp_path / "meta.json")

    assert paragraphs == {
        ("P", "P1"): frozenset({"P:REC.X", "P:REC.Y"}),
        ("P", "P2"): frozenset({"P:REC.X", "P:REC.Y"}),
        ("P", "P3"): frozenset({"P:REC.Z", "Q:REC.W"}),
        ("P", "P4"): frozenset({"P:REC.Z"}),
    }
    assert trimmed == {
        ("P", "P1"): frozenset({"P:REC.X"}),
        ("P", "P2"): frozenset({"P:REC.X"}),
        ("P", "P3"): frozenset({"P:REC.Z"}),
        ("P", "P4"): frozenset({"P:REC.Z"}),
    }
    assert (every.fields, every.paragraphs) == (
        ("P:REC.X", "P:REC.Y", "P:REC.Z", "Q:REC.W"),
        (("P", "P1"), ("P", "P2"), ("P", "P3"), ("P", "P4")),
    )
    assert every.matrix.toarray().tolist() == [
        [1, 1, 0, 0],
        [1, 1, 0, 0],
        [0, 0, 1, 1],
        [0, 0, 1, 0],
    ]
    assert loaded.matrix.toarray().tolist() == [
        [1, 1, 0, 0],
        [1, 1, 0, 0],
        [0, 0, 1, 1],
        [0, 0, 1, 0],
    ]
    assert (
        loaded.fields,
        loaded.paragraphs,
        loaded.occurrences,
    ) == (
        ("P:REC.X", "P:REC.Y", "P:REC.Z", "Q:REC.W"),
        (("P", "P1"), ("P", "P2"), ("P", "P3"), ("P", "P4")),
        (2, 2, 2, 1),
    )


def test_table_occurrences_count_as_their_declared_field() -> None:
    table = leaf_index(
        (
            _row(("TAB",), 0, 4),
            ExtentRow(
                program="P",
                extents=(
                    "T@working_storage[0:2]",
                    "T@working_storage[2:4]",
                ),
                records=("TAB", "TAB"),
                paths=(("TAB", "T"), ("TAB", "T")),
                pics=("X", "X"),
                indexes=((1,), (2,)),
            ),
        )
    )

    assert paragraph_fields(
        (
            _def("P1/0", "T@working_storage[0:2]"),
            _def("P1/1", "T@working_storage[2:4]"),
            _def("P2/0", "TAB@working_storage[0:4]"),
        ),
        table,
        {},
        (),
    ) == {
        ("P", "P1"): frozenset({"P:TAB.T"}),
        ("P", "P2"): frozenset({"P:TAB.T"}),
    }

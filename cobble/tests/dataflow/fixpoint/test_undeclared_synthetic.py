"""Names a program uses but never declares, as when a copybook is missing: with
synthesis on, each is declared as nominal ten-byte text and tracked like any field."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from cobble.dataflow.fields.extents_input import declared_layouts
from cobble.dataflow.fields.origin import Origin
from cobble.dataflow.fields.origin_kind import OriginKind
from cobble.dataflow.fixpoint.provenance import provenance
from cobble.dataflow.srccfg.literals import is_literal

PROGRAM = "MISSING"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MISSING.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC X(10).
       01  WS-B                 PIC X(10).
       01  WS-C                 PIC X(20).
       01  WS-REC.
           05  WS-R1            PIC X(4).
           05  WS-R2            PIC X(8).
       01  WS-FLAG              PIC X.
           88  WS-DONE          VALUE 'Y'.
       01  WS-TAB.
           05  WS-ROW           PIC X OCCURS 3 INDEXED BY WS-IX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-A TO CPY-AMT.
           MOVE CPY-AMT TO WS-B.
           MOVE WS-A TO CPY-NAME OF CPY-REC.
           MOVE CPY-REC TO WS-C.
           MOVE WS-A TO CPY-ROW(2).
           IF WS-DONE
               MOVE WS-B TO WS-A
           END-IF.
           MOVE WS-A TO CPY-PART OF WS-REC.
           MOVE WS-B TO WS-A OF WS-REC.
           SET WS-DONE TO TRUE.
           SET WS-IX TO 1.
           DISPLAY 'NOT A FIELD' WS-A.
           MOVE -1 TO WS-C.
           STRING FUNCTION TRIM(WS-A) DELIMITED BY SIZE INTO WS-C.
           EXEC CICS RECEIVE INTO(CPY-INBOX) END-EXEC.
           ACCEPT CPY-TODAY FROM DATE.
           IF WS-A = SPACES
               SET CPY-FLAG TO TRUE
           END-IF.
           STOP RUN.
"""


def _declared(out: Path) -> dict[str, tuple[str, int, int, tuple[str, ...]]]:
    (member,) = tuple(declared_layouts(out.parent / "extents.jsonl"))
    return {
        cell.name: (record.origin, cell.length, cell.occurs, cell.path)
        for record in member.layout.records
        for cell in record.cells
        if cell.name.startswith("CPY-") and all(i in (0, 1) for i in cell.index)
    }


def _cells_named(out: Path, name: str) -> int:
    (member,) = tuple(declared_layouts(out.parent / "extents.jsonl"))
    return sum(
        cell.name == name for record in member.layout.records for cell in record.cells
    )


def _literal_cells(out: Path) -> list[str]:
    (member,) = tuple(declared_layouts(out.parent / "extents.jsonl"))
    return [
        cell.name
        for record in member.layout.records
        for cell in record.cells
        if is_literal(cell.name)
    ]


def _flows(out: Path) -> dict[str, tuple[str, str, tuple[str, ...]]]:
    return {
        dep.site.rsplit("/", 1)[1]: (dep.source.name, dep.target.name, dep.definers)
        for dep in provenance(out)
        if dep.target.known and dep.source.known
    }


def test_undeclared_names_are_declared_as_ten_byte_text_and_their_moves_tracked(
    fixpoint_out_undeclared: Callable[[str, str], Path],
) -> None:
    """A plain name is an 01 of its own, a qualified one sits under its qualifier,
    a subscripted one is a table of ten; a condition name stays a condition. A name qualified by a declared
    record is a view of all of it, unless the name is declared elsewhere. Writes to them
    reach the reads after them, through the record that holds them. Two writes stay
    untracked: WS-A OF WS-REC, a name declared elsewhere, and SET of an index name, which
    the layout gives no storage."""
    out = fixpoint_out_undeclared(PROGRAM, SOURCE)

    assert _declared(out) == {
        "CPY-AMT": ("WORKING-STORAGE", 10, 0, ("CPY-AMT",)),
        "CPY-REC": ("WORKING-STORAGE", 10, 0, ("CPY-REC",)),
        "CPY-NAME": ("WORKING-STORAGE", 10, 0, ("CPY-REC", "CPY-NAME")),
        "CPY-ROW": ("WORKING-STORAGE", 10, 10, ("CPY-ROW",)),
        "CPY-PART": ("WORKING-STORAGE", 12, 0, ("WS-REC", "CPY-PART")),
        "CPY-INBOX": ("WORKING-STORAGE", 10, 0, ("CPY-INBOX",)),
        "CPY-TODAY": ("WORKING-STORAGE", 10, 0, ("CPY-TODAY",)),
        "CPY-FLAG": ("WORKING-STORAGE", 10, 0, ("CPY-FLAG",)),
    }
    flows = _flows(out)
    assert flows["0"] == ("WS-A", "CPY-AMT", ())
    assert flows["1"] == ("CPY-AMT", "WS-B", ("MISSING/MAIN-PARA/0",))
    assert flows["2"] == ("WS-A", "CPY-NAME", ())
    assert flows["3"] == ("CPY-REC", "WS-C", ("MISSING/MAIN-PARA/2",))
    assert flows["4"] == ("WS-A", "CPY-ROW", ())
    assert flows["6"] == ("WS-A", "CPY-PART", ("MISSING/MAIN-PARA/5.then.0",))
    assert "7" not in flows
    assert [
        _cells_named(out, name) for name in ("WS-A", "WS-DONE", "WS-IX", "TRIM", "TRUE")
    ] == [1, 0, 0, 0, 0]
    assert _literal_cells(out) == []
    counts = json.loads((out / "members" / PROGRAM / "counts.json").read_text())
    assert counts["writes"] - counts["covered"] == 2
    assert [
        dep.target.name for dep in provenance(out) if dep.target.name == "CPY-INBOX"
    ] == ["CPY-INBOX"]


def test_without_synthesis_an_undeclared_name_is_an_unknown_origin(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    out = fixpoint_out(PROGRAM, SOURCE)

    assert _declared(out) == {}
    assert {
        dep.origin
        for dep in provenance(out)
        if dep.target.name == "WS-B" and not dep.source.known
    } == {Origin(OriginKind.UNKNOWN_FIELD, "CPY-AMT")}

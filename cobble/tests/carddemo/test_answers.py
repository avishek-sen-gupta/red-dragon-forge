"""cobble's rows on CardDemo against answers read from the CardDemo source by hand."""

from __future__ import annotations

import json

from tests.carddemo.conftest import CardDemoRun

WRITE = "9600-WRITE-PROCESSING"


def _start(run: CardDemoRun, field_id: str) -> int:
    (row,) = (
        row
        for row in map(json.loads, run.extents.read_text().splitlines())
        if row["id"] == field_id
    )
    (start,) = row["starts"]
    return start


def test_each_field_coactupc_rewrites_to_the_account_file_names_its_own_last_write(
    carddemo: CardDemoRun,
) -> None:
    """COACTUPC.cbl:3956-3999, then the REWRITE FROM(ACCT-UPDATE-RECORD) at :4065,
    the paragraph's statement 40. INITIALIZE (:3956, statement 8) is overwritten by
    a MOVE or STRING into every named field. The REISSUE-DATE MOVE (:3989, 18) is
    dead: the STRING after it (:3990, 19) sends 4+1+2+1+2 bytes into all ten. The
    trailing FILLER X(188) is written by no statement: INITIALIZE without the
    FILLER phrase skips FILLER items (Enterprise COBOL, INITIALIZE rules, 1a), and
    nothing else in the program writes the record."""
    base = _start(carddemo, "COACTUPC.ACCT-UPDATE-RECORD")
    rows = [
        row
        for row in map(
            json.loads, (carddemo.fixpoint / "sinks.jsonl").read_text().splitlines()
        )
        if row["program"] == "COACTUPC" and row["node"] == f"{WRITE}/40"
    ]

    assert [(row["source_extent"], row["definers"]) for row in rows] == [
        (f"ACCT-UPDATE-RECORD@working_storage[{base + a}:{base + b}]", definers)
        for a, b, definers in (
            (0, 11, [f"{WRITE}/9"]),
            (11, 12, [f"{WRITE}/10"]),
            (12, 24, [f"{WRITE}/11"]),
            (24, 36, [f"{WRITE}/12"]),
            (36, 48, [f"{WRITE}/13"]),
            (48, 58, [f"{WRITE}/16"]),
            (58, 68, [f"{WRITE}/17"]),
            (68, 78, [f"{WRITE}/19"]),
            (78, 90, [f"{WRITE}/14"]),
            (90, 102, [f"{WRITE}/15"]),
            (102, 112, [f"{WRITE}/20"]),
            (112, 300, []),
        )
    ]
    assert {row["sink"]["name"] for row in rows} == {"LIT-ACCTFILENAME"}

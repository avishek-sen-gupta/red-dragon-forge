"""A batch READ fills its file's record area, which the program reaches through the
FD's records, whatever they are named; READ ... INTO fills the INTO field as well."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from cobble.dataflow.fields.origin import Origin
from cobble.dataflow.fields.origin_kind import OriginKind
from cobble.dataflow.fixpoint.provenance import provenance

PROGRAM = "FILEREC"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILEREC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CARD-INPUT ASSIGN TO CARDFILE.
       DATA DIVISION.
       FILE SECTION.
       FD  CARD-INPUT.
       01  FD-CARD-REC.
           05  FD-CARD-NUM      PIC X(16).
       WORKING-STORAGE SECTION.
       01  WS-NUM               PIC X(16).
       01  WS-COPY              PIC X(16).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CARD-INPUT.
           READ CARD-INPUT.
           MOVE FD-CARD-NUM TO WS-NUM.
           READ CARD-INPUT INTO WS-COPY.
           STOP RUN.
"""


def test_a_read_fills_the_record_area_of_its_file_and_its_into_field(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    out = fixpoint_out(PROGRAM, SOURCE)

    written = sorted(
        (
            dep.site.rsplit("/", 1)[1],
            dep.target.name,
            dep.source.name if dep.origin.is_storage else dep.origin,
        )
        for dep in provenance(out)
        if dep.target.known
    )
    assert written == [
        ("1", "FD-CARD-REC", Origin(OriginKind.FILE, "CARD-INPUT")),
        ("2", "WS-NUM", "FD-CARD-NUM"),
        ("3", "FD-CARD-REC", Origin(OriginKind.FILE, "CARD-INPUT")),
        ("3", "WS-COPY", Origin(OriginKind.FILE, "CARD-INPUT")),
    ]

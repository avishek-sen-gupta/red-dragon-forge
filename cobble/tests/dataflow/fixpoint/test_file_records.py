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


SORT_PROGRAM = "SORTREC"

SORT_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTREC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
           SELECT SORT-WORK ASSIGN TO SORTWK.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC               PIC X(16).
       SD  SORT-WORK.
       01  SW-REC.
           05  SW-KEY           PIC X(16).
       WORKING-STORAGE SECTION.
       01  WS-COPY              PIC X(16).
       01  WS-IN                PIC X(16).
       01  WS-EOF               PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SORT SORT-WORK ON ASCENDING KEY SW-KEY
               INPUT PROCEDURE IS FEED-PARA
               OUTPUT PROCEDURE IS TAKE-PARA.
           STOP RUN.
       FEED-PARA.
           MOVE 'K' TO WS-IN.
           RELEASE SW-REC FROM WS-IN.
       TAKE-PARA.
           RETURN SORT-WORK INTO WS-COPY
               AT END MOVE 'Y' TO WS-EOF
           END-RETURN.
"""


def test_a_sort_releases_records_in_and_returns_them_from_its_sd_record(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    """SORT runs its procedures as calls. RELEASE ... FROM moves its field into
    the SD's record, as WRITE ... FROM does; RETURN is READ for a sort file, so
    the next sorted record lands in the SD's record and in INTO."""
    out = fixpoint_out(SORT_PROGRAM, SORT_SOURCE)

    written = sorted(
        (
            dep.site.removeprefix(f"{SORT_PROGRAM}/"),
            dep.target.name,
            dep.source.name if dep.origin.is_storage else dep.origin,
        )
        for dep in provenance(out)
        if dep.target.known and "#" not in dep.site
    )
    assert written == [
        ("FEED-PARA/0", "WS-IN", Origin(OriginKind.LITERAL, "'K'")),
        ("FEED-PARA/1", "SW-REC", "WS-IN"),
        ("TAKE-PARA/0", "SW-REC", Origin(OriginKind.FILE, "SORT-WORK")),
        ("TAKE-PARA/0", "WS-COPY", Origin(OriginKind.FILE, "SORT-WORK")),
        ("TAKE-PARA/0.at_end.0", "WS-EOF", Origin(OriginKind.LITERAL, "'Y'")),
    ]

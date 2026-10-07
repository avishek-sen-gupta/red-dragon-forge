"""A run restricted to call targets, compiled by the real bridge, against a full run."""

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from cobble.dataflow.combine.cli import cli as combine_cli
from cobble.dataflow.fixpoint.build_corpus import cli
from cobble.dataflow.fixpoint.member_counts import MemberCounts
from cobble.dataflow.fixpoint.query import cli as query_cli
from cobble.dataflow.fixpoint.scope import Scope
from tests.dataflow.combine.corpus_toml import CONFIG
from tests.dataflow.combine.linked_rows import link_rows, target_rows
from tests.dataflow.fixpoint.test_combine_synthetic import PROGA, PROGB

LOCAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CTL.
           05  WS-MODE          PIC X(1).
           05  WS-PGM           PIC X(8).
           05  WS-NOISE         PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'ABC' TO WS-NOISE.
           IF WS-MODE = 'A'
               MOVE 'PROGX' TO WS-PGM
           ELSE
               MOVE 'PROGY' TO WS-PGM
           END-IF.
           CALL WS-PGM.
           GOBACK.
"""


def _counts(out: Path, member: str) -> MemberCounts:
    return MemberCounts.model_validate_json(
        (out / "members" / member / "counts.json").read_text(encoding="utf-8")
    )


def test_a_restricted_run_records_its_scope_and_refuses_a_full_one_beside_it(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
) -> None:
    out = fixpoint_corpus_with({"PROGL": LOCAL}, ("--call-targets-only",))
    counts = _counts(out, "PROGL")

    assert (counts.scope, counts.tracked, counts.relevant) == (
        Scope.CALL_TARGETS,
        2,
        1,
    )
    assert (
        cli(
            [
                "--asg-dir",
                str(out.parent / "parsed"),
                "--out-dir",
                str(out),
                "--extents",
                str(out.parent / "extents.jsonl"),
                "--all",
                "--max-workers",
                "1",
            ]
        )
        == 2
    )


CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-NEXT          PIC X(8).
           05  WS-PAD           PIC X(12).
       01  WS-NOISE             PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'ABC' TO WS-NOISE.
           EXEC CICS LINK PROGRAM('PROGW') COMMAREA(WS-AREA) END-EXEC.
           CALL WS-NEXT.
           GOBACK.
"""

CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGW.
       DATA DIVISION.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-NEXT          PIC X(8).
           05  LK-PAD           PIC X(12).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGZ' TO LK-NEXT.
           EXEC CICS RETURN END-EXEC.
"""


def _combined(out: Path, tmp_path: Path, name: str) -> Path:
    config = tmp_path / f"{name}.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"), encoding="utf-8")
    combined = tmp_path / name
    assert (
        combine_cli(
            [
                "--config",
                str(config),
                "--fixpoint-dir",
                str(out),
                "--out-dir",
                str(combined),
                "--all",
            ]
        )
        == 0
    )
    return combined


def _both(
    run: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    sources: Mapping[str, str],
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path]:
    full = run(sources, ())
    restricted = run(sources, ("--call-targets-only",))
    return (
        full,
        restricted,
        _combined(full, tmp_path, "full"),
        _combined(restricted, tmp_path, "restricted"),
    )


def test_a_local_target_resolves_the_same_from_fewer_extents(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    tmp_path: Path,
) -> None:
    full, restricted, full_combined, restricted_combined = _both(
        fixpoint_corpus_with, {"PROGL": LOCAL}, tmp_path
    )
    (row,) = target_rows(restricted / "targets.jsonl")

    assert target_rows(restricted / "targets.jsonl") == target_rows(
        full / "targets.jsonl"
    )
    assert row.candidates == ("PROGX", "PROGY")
    assert target_rows(restricted_combined / "targets.jsonl") == target_rows(
        full_combined / "targets.jsonl"
    )
    assert (_counts(restricted, "PROGL").relevant, _counts(full, "PROGL").relevant) == (
        1,
        2,
    )


def test_a_target_through_a_commarea_resolves_the_same(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    tmp_path: Path,
) -> None:
    _, _, full_combined, restricted_combined = _both(
        fixpoint_corpus_with, {"PROGA": PROGA, "PROGB": PROGB}, tmp_path
    )
    (row,) = target_rows(restricted_combined / "targets.jsonl")

    assert row.candidates == ("PROGA", "PROGM")
    assert target_rows(restricted_combined / "targets.jsonl") == target_rows(
        full_combined / "targets.jsonl"
    )
    assert link_rows(restricted_combined / "links.jsonl") == link_rows(
        full_combined / "links.jsonl"
    )


def test_a_target_handed_back_by_a_callee_resolves_the_same(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    tmp_path: Path,
) -> None:
    _, _, full_combined, restricted_combined = _both(
        fixpoint_corpus_with, {"PROGC": CALLER, "PROGW": CALLEE}, tmp_path
    )
    (row,) = target_rows(full_combined / "targets.jsonl")

    assert (row.candidates, row.reasons) == (("PROGZ",), ())
    assert target_rows(restricted_combined / "targets.jsonl") == target_rows(
        full_combined / "targets.jsonl"
    )
    assert link_rows(restricted_combined / "links.jsonl") == link_rows(
        full_combined / "links.jsonl"
    )


def test_the_query_refuses_a_restricted_run(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = fixpoint_corpus_with({"PROGL": LOCAL}, ("--call-targets-only",))

    assert (
        query_cli(
            [
                "writers",
                "PROGL.WS-NOISE",
                "--fixpoint-dir",
                str(out),
                "--extents",
                str(out.parent / "extents.jsonl"),
            ]
        )
        == 2
    )
    assert capsys.readouterr().err == (
        f"fields: !! {out} holds a run restricted to call targets (PROGL);"
        " rerun cobble-dataflow-fixpoint without --call-targets-only to query it\n"
    )


SIBLING_WEAK = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-PGM           PIC X(8).
           05  WS-FLAG          PIC X(1).
               88  FLAG-ON      VALUE 'Y'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS READ FILE('F') INTO(WS-REC) END-EXEC.
           SET FLAG-ON TO TRUE.
           CALL WS-PGM.
           GOBACK.
"""

SIBLING_CLAMPED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-PGM           PIC X(8).
           05  WS-TAB           PIC X(1) OCCURS 4.
       01  WS-I                 PIC 9(1).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGXXXX1234' TO WS-REC.
           MOVE 'Z' TO WS-TAB(WS-I).
           CALL WS-PGM.
           GOBACK.
"""

SIBLING_IMAGED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME              PIC X(12) VALUE 'PROGXXXX1234'.
       01  WS-PARTS REDEFINES WS-NAME.
           05  WS-PGM           PIC X(8).
           05  WS-TAB           PIC X(1) OCCURS 4.
       01  WS-I                 PIC 9(1).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'Z' TO WS-TAB(WS-I).
           CALL WS-PGM.
           GOBACK.
"""


def test_a_sibling_write_inside_a_record_the_target_was_read_from_counts_the_same(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
) -> None:
    sources = {
        "PROGF": SIBLING_WEAK,
        "PROGT": SIBLING_CLAMPED,
        "PROGV": SIBLING_IMAGED,
    }
    full = fixpoint_corpus_with(sources, ())
    restricted = fixpoint_corpus_with(sources, ("--call-targets-only",))
    rows = target_rows(restricted / "targets.jsonl")

    assert rows == target_rows(full / "targets.jsonl")
    assert [(row.caller, row.candidates, row.reasons) for row in rows] == [
        ("PROGF", (), ("from-file", "unmodelled")),
        ("PROGT", (), ("not-a-literal",)),
        ("PROGV", (), ("not-a-literal",)),
    ]

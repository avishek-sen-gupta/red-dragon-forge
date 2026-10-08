"""A run restricted to call targets, compiled by the real bridge, against a full run."""

import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from cobble.dataflow.combine.cli import cli as combine_cli
from cobble.dataflow.fixpoint.area_kind import AreaKind
from cobble.dataflow.fixpoint.area_need_cli import cli as area_cli
from cobble.dataflow.fixpoint.area_need_file import read_rows
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


def _jumps(out: Path) -> list[str]:
    return (out / "jumps.jsonl").read_text(encoding="utf-8").splitlines()


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
    full, restricted, full_combined, restricted_combined = _both(
        fixpoint_corpus_with, {"PROGA": PROGA, "PROGB": PROGB}, tmp_path
    )
    (row,) = target_rows(restricted_combined / "targets.jsonl")

    assert _jumps(restricted) == _jumps(full)

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
    full, restricted, full_combined, restricted_combined = _both(
        fixpoint_corpus_with, {"PROGC": CALLER, "PROGW": CALLEE}, tmp_path
    )
    (row,) = target_rows(full_combined / "targets.jsonl")

    assert _jumps(restricted) == _jumps(full)

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

WEAKLY_OVERWRITTEN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGU.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM               PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGA' TO WS-PGM.
           ACCEPT WS-PGM.
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
        "PROGU": WEAKLY_OVERWRITTEN,
    }
    full = fixpoint_corpus_with(sources, ())
    restricted = fixpoint_corpus_with(sources, ("--call-targets-only",))
    rows = target_rows(restricted / "targets.jsonl")

    assert rows == target_rows(full / "targets.jsonl")
    assert _jumps(restricted) == _jumps(full)
    assert [(row.caller, row.candidates, row.reasons) for row in rows] == [
        ("PROGF", (), ("from-file", "unmodelled")),
        ("PROGT", (), ("not-a-literal",)),
        ("PROGU", ("PROGA",), ("unmodelled",)),
        ("PROGV", (), ("not-a-literal",)),
    ]


def _restricted_again(out: Path) -> int:
    return cli(
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
            "--call-targets-only",
        ]
    )


def test_a_member_that_fails_in_a_restricted_run_is_recorded_in_that_scope(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
) -> None:
    out = fixpoint_corpus_with(
        {"PROGL": LOCAL, "PROGQ": LOCAL.replace("PROGL", "PROGQ")},
        ("--call-targets-only",),
    )
    (out.parent / "parsed" / "PROGQ.json").write_text("not json", encoding="utf-8")
    shutil.rmtree(out / "members" / "PROGQ")

    first = _restricted_again(out)
    failed = _counts(out, "PROGQ")

    assert (failed.skipped[:12], failed.scope) == ("unreadable: ", Scope.CALL_TARGETS)
    assert (first, _restricted_again(out)) == (3, 3)


COUNTED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SRC.
           05  WS-SRC-A         PIC X(8).
       01  WS-DST.
           05  WS-PGM           PIC X(8).
       01  WS-OTHER             PIC X(8).
       01  WS-SIB               PIC X(8).
       01  WS-NOISE             PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'X' TO WS-NOISE.
           MOVE WS-SRC TO WS-DST.
           CALL WS-PGM.
           GOBACK.
       DEAD-PARA.
           MOVE WS-OTHER TO WS-SIB.
           CALL WS-SIB.
"""


def test_relevant_and_tracked_count_the_same_written_extents(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
) -> None:
    out = fixpoint_corpus_with({"PROGK": COUNTED}, ("--call-targets-only",))
    counts = _counts(out, "PROGK")

    assert (counts.tracked, counts.relevant) == (3, 2)


CHAIN_START = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-FROM          PIC X(8).
           05  WS-NEXT          PIC X(8).
           05  WS-NOTE          PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGH' TO WS-FROM.
           MOVE 'PROGK' TO WS-NEXT.
           MOVE 'NOTE' TO WS-NOTE.
           EXEC CICS XCTL PROGRAM('PROGI') COMMAREA(WS-AREA) END-EXEC.
"""

CHAIN_MIDDLE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGI.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COPY              PIC X(24).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(24).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE DFHCOMMAREA TO WS-COPY.
           EXEC CICS XCTL PROGRAM('PROGJ') COMMAREA(WS-COPY) END-EXEC.
"""

CHAIN_END = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGJ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TARGET            PIC X(8).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-FROM          PIC X(8).
           05  LK-NEXT          PIC X(8).
           05  LK-NOTE          PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE LK-NEXT TO WS-TARGET.
           EXEC CICS XCTL PROGRAM(WS-TARGET) END-EXEC.
"""


SLICE_CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-FIRST         PIC X(8).
           05  WS-SECOND        PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGP' TO WS-FIRST.
           MOVE 'PROGQ' TO WS-SECOND.
           EXEC CICS LINK PROGRAM('PROGN') COMMAREA(WS-AREA) END-EXEC.
           EXEC CICS LINK PROGRAM('PROGO') COMMAREA(WS-AREA) END-EXEC.
           GOBACK.
"""


def _slice_callee(name: str, read: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TARGET            PIC X(8).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-FIRST         PIC X(8).
           05  LK-SECOND        PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE {read} TO WS-TARGET.
           EXEC CICS XCTL PROGRAM(WS-TARGET) END-EXEC.
"""


DYNAMIC_FORWARDER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM               PIC X(8).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-FIRST         PIC X(8).
           05  LK-SECOND        PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGN' TO WS-PGM.
           EXEC CICS LINK PROGRAM(WS-PGM)
               COMMAREA(DFHCOMMAREA) END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""


NEXT_TRANSACTION = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGE.
       DATA DIVISION.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-FIRST         PIC X(8).
           05  LK-SECOND        PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS RETURN TRANSID('PETX')
               COMMAREA(DFHCOMMAREA) END-EXEC.
"""


def _combined_with_csd(out: Path, tmp_path: Path, name: str) -> Path:
    csd = tmp_path / "PROGS.CSD"
    csd.write_text(
        "DEFINE TRANSACTION(PETX) PROGRAM(PROGN) GROUP(TEST)\n", encoding="utf-8"
    )
    config = tmp_path / f"{name}.toml"
    config.write_text(
        CONFIG.format(asg=out.parent / "parsed") + f'csd_files = ["{csd}"]\n',
        encoding="utf-8",
    )
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


def _narrow_run(parsed: Path, extents: Path, out: Path, stored: Path) -> int:
    return cli(
        [
            "--asg-dir",
            str(parsed),
            "--out-dir",
            str(out),
            "--extents",
            str(extents),
            "--all",
            "--max-workers",
            "1",
            "--call-targets-only",
            "--narrow-areas",
            str(stored),
        ]
    )


def test_narrowed_areas_resolve_the_same_through_the_combine(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    tmp_path: Path,
) -> None:
    sources = {
        "PROGA": PROGA,
        "PROGB": PROGB,
        "PROGC": CALLER,
        "PROGW": CALLEE,
        "PROGL": LOCAL,
        "PROGF": SIBLING_WEAK,
        "PROGT": SIBLING_CLAMPED,
        "PROGV": SIBLING_IMAGED,
        "PROGU": WEAKLY_OVERWRITTEN,
        "PROGH": CHAIN_START,
        "PROGI": CHAIN_MIDDLE,
        "PROGJ": CHAIN_END,
        "PROGM": SLICE_CALLER,
        "PROGN": _slice_callee("PROGN", "LK-FIRST"),
        "PROGO": _slice_callee("PROGO", "LK-SECOND"),
        "PROGD": DYNAMIC_FORWARDER,
        "PROGE": NEXT_TRANSACTION,
    }
    full = fixpoint_corpus_with(sources, ())
    parsed, extents = full.parent / "parsed", full.parent / "extents.jsonl"
    stored = tmp_path / "area-need.jsonl"
    missing = _narrow_run(parsed, extents, full.parent / "early", stored)
    area_cli(
        ["--asg-dir", str(parsed), "--extents", str(extents), "--out", str(stored)]
    )
    narrow = full.parent / "narrow"
    assert (missing, _narrow_run(parsed, extents, narrow, stored)) == (2, 0)
    full_combined = _combined_with_csd(full, tmp_path, "full")
    narrow_combined = _combined_with_csd(narrow, tmp_path, "narrow")
    combined = target_rows(narrow_combined / "targets.jsonl")

    assert target_rows(narrow / "targets.jsonl") == target_rows(full / "targets.jsonl")
    assert combined == target_rows(full_combined / "targets.jsonl")
    assert link_rows(narrow_combined / "links.jsonl") == link_rows(
        full_combined / "links.jsonl"
    )
    assert [
        (row.caller, row.candidates) for row in combined if row.caller == "PROGJ"
    ] == [("PROGJ", ("PROGK",))]
    assert _counts(narrow, "PROGH").scope is Scope.NARROW_CALL_TARGETS
    commarea = ((AreaKind.COMMAREA, 0),)
    assert {
        row.member: (row.receives, row.entry, row.back)
        for row in read_rows(stored)
        if row.member in {"PROGI", "PROGJ", "PROGN", "PROGO", "PROGW"}
    } == {
        "PROGI": (commarea, (((AreaKind.COMMAREA, 0), (8, 16)),), ()),
        "PROGJ": (commarea, (((AreaKind.COMMAREA, 0), (8, 16)),), ()),
        "PROGN": (
            commarea,
            (((AreaKind.COMMAREA, 0), (0, 8)),),
            (((AreaKind.COMMAREA, 0), (8, 16)),),
        ),
        "PROGO": (commarea, (((AreaKind.COMMAREA, 0), (8, 16)),), ()),
        "PROGW": (commarea, (), (((AreaKind.COMMAREA, 0), (0, 8)),)),
    }
    targeted = tmp_path / "area-need-targeted.jsonl"
    area_cli(
        [
            "--asg-dir",
            str(parsed),
            "--extents",
            str(extents),
            "--out",
            str(targeted),
            "--fixpoint-dir",
            str(full),
            "--combined-dir",
            str(full_combined),
            "--config",
            str(tmp_path / "full.toml"),
        ]
    )
    retargeted = full.parent / "retargeted"
    assert _narrow_run(parsed, extents, retargeted, targeted) == 0
    assert target_rows(retargeted / "targets.jsonl") == target_rows(
        full / "targets.jsonl"
    )
    assert [
        (stored_rows.member, stored_rows.entry)
        for path in (stored, targeted)
        for stored_rows in read_rows(path)
        if stored_rows.member in {"PROGD", "PROGE"}
    ] == [
        ("PROGD", (((AreaKind.COMMAREA, 0), (0, 16)),)),
        ("PROGE", (((AreaKind.COMMAREA, 0), (0, 16)),)),
        ("PROGD", (((AreaKind.COMMAREA, 0), (0, 8)),)),
        ("PROGE", (((AreaKind.COMMAREA, 0), (0, 8)),)),
    ]


STRUNG = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TARGET            PIC X(8).
       01  WS-PGM               PIC X(8).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-FIRST         PIC X(8).
           05  LK-SECOND        PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STRING LK-FIRST LK-SECOND DELIMITED BY SIZE
               INTO WS-TARGET.
           MOVE 'PROGN' TO WS-PGM.
           EXEC CICS LINK PROGRAM(WS-PGM)
               COMMAREA(DFHCOMMAREA) END-EXEC.
           EXEC CICS XCTL PROGRAM(WS-TARGET) END-EXEC.
"""


def test_explain_names_what_each_source_pins_and_the_writes_that_widen(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    full = fixpoint_corpus_with(
        {"PROGX": STRUNG, "PROGN": _slice_callee("PROGN", "LK-FIRST")}, ()
    )
    parsed, extents = full.parent / "parsed", full.parent / "extents.jsonl"
    capsys.readouterr()

    report = (
        "PROGX: 16 bytes needed on entry\n"
        "  by source, each alone:\n"
        "      16  call-target reads\n"
        "      16  MAIN-PARA line 16 LINK, dynamic, unresolved: every member's need\n"
        "  writes that read more than their target keeps live:\n"
        "    MAIN-PARA line 13: WS-TARGET@working_storage[0:8] keeps 8 bytes live,"
        " reads 16 from LK-FIRST@linkage[0:8], LK-SECOND@linkage[8:16]\n"
    )
    common = [
        "--asg-dir",
        str(parsed),
        "--extents",
        str(extents),
        "--out",
        str(tmp_path / "need.jsonl"),
    ]

    assert [
        (area_cli([*common, *chosen]), capsys.readouterr().out)
        for chosen in (["--explain", "PROGX"], ["--explain-over", "9"])
    ] == [(0, report), (0, report)]

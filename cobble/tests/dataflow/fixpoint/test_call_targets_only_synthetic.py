"""A run restricted to call targets, compiled by the real bridge, against a full run."""

from collections.abc import Callable, Mapping
from pathlib import Path

from cobble.dataflow.fixpoint.build_corpus import cli
from cobble.dataflow.fixpoint.member_counts import MemberCounts
from cobble.dataflow.fixpoint.scope import Scope

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

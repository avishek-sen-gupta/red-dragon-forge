"""Which paragraph-end fall-throughs the fixpoint keeps, compiled by the real bridge."""

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fixpoint.fallthrough import fallthroughs_pruned
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_from_row
from cobble.dataflow.srccfg.build import paragraph_order
from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.statements import statement_index
from cobble.parsing.asg_cache import first_program_at

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC X(4).
       PROCEDURE DIVISION.
"""

ONLY_PERFORMED = """\
       MAIN-PARA.
           PERFORM INIT-PARA.
           STOP RUN.
       INIT-PARA.
           MOVE 'A' TO WS-A.
       NEXT-PARA.
           MOVE 'B' TO WS-A.
       LAST-PARA.
           MOVE 'C' TO WS-A.
"""

ALSO_FALLEN_INTO = """\
       MAIN-PARA.
           PERFORM WORK-PARA.
       WORK-PARA.
           MOVE 'A' TO WS-A.
       TAIL-PARA.
           STOP RUN.
"""

THRU_RANGE = """\
       MAIN-PARA.
           PERFORM A-PARA THRU C-PARA.
           STOP RUN.
       A-PARA.
           MOVE 'A' TO WS-A.
       B-PARA.
           MOVE 'B' TO WS-A.
       C-PARA.
           MOVE 'C' TO WS-A.
       D-PARA.
           MOVE 'D' TO WS-A.
"""

GONE_TO = """\
       MAIN-PARA.
           PERFORM JUMP-PARA.
           PERFORM LAND-PARA.
           STOP RUN.
       JUMP-PARA.
           GO TO LAND-PARA.
       LAND-PARA.
           MOVE 'A' TO WS-A.
       TAIL-PARA.
           STOP RUN.
"""

SECTIONS = """\
       MAIN-SECTION SECTION.
       MAIN-PARA.
           PERFORM WORK-SECTION.
           STOP RUN.
       WORK-SECTION SECTION.
       W1-PARA.
           MOVE 'A' TO WS-A.
       W2-PARA.
           MOVE 'B' TO WS-A.
       TAIL-SECTION SECTION.
       TAIL-PARA.
           STOP RUN.
"""

OVERLAPPING = """\
       MAIN-PARA.
           PERFORM A-PARA THRU C-PARA.
           PERFORM B-PARA THRU D-PARA.
           STOP RUN.
       A-PARA.
           IF WS-A = 'X'
               GO TO C-PARA
           END-IF.
       B-PARA.
           GO TO D-PARA.
       C-PARA.
           MOVE 'C' TO WS-A.
       D-PARA.
           MOVE 'D' TO WS-A.
       E-PARA.
           STOP RUN.
"""

UNRESOLVED = """\
       MAIN-PARA.
           PERFORM INIT-PARA.
{construct}
           STOP RUN.
       INIT-PARA.
           MOVE 'A' TO WS-A.
       NEXT-PARA.
           MOVE 'B' TO WS-A.
       SWITCH-PARA.
           GO TO{switch}.
"""

UNRESOLVED_CONSTRUCTS = {
    "FTGOTO": ("           GO TO NOWHERE-PARA.", " NEXT-PARA"),
    "FTPERF": ("           PERFORM NOWHERE-PARA.", " NEXT-PARA"),
    "FTALTER": ("           ALTER SWITCH-PARA TO PROCEED TO INIT-PARA.", " NEXT-PARA"),
    "FTABENDNO": (
        "           EXEC CICS HANDLE ABEND LABEL(NOWHERE-PARA) END-EXEC.",
        " NEXT-PARA",
    ),
    "FTHANDLE": (
        "           EXEC CICS HANDLE CONDITION ERROR(NOWHERE-PARA) END-EXEC.\n"
        "           EXEC CICS RECEIVE INTO(WS-A) END-EXEC.",
        " NEXT-PARA",
    ),
}

THRU_FELL_BACK = """\
       MAIN-PARA.
           PERFORM B-PARA THRU {last}.
           STOP RUN.
       A-PARA.
           MOVE 'A' TO WS-A.
       B-PARA.
           MOVE 'B' TO WS-A.
       C-PARA.
           MOVE 'C' TO WS-A.
       D-PARA.
           MOVE 'D' TO WS-A.
"""

THRU_ENDS = {"FTTHRUBACK": "A-PARA", "FTTHRUNONE": "NOWHERE-PARA"}

ENTERED = """\
       MAIN-PARA.
           PERFORM B-PARA.
           STOP RUN.
       B-PARA.
           ENTRY 'ALTENT'.
           MOVE 'B' TO WS-A.
       C-PARA.
           MOVE 'C' TO WS-A.
"""

ABEND_LABEL = """\
       MAIN-PARA.
           EXEC CICS HANDLE ABEND LABEL(B-PARA) END-EXEC.
           PERFORM B-PARA.
           STOP RUN.
       B-PARA.
           MOVE 'B' TO WS-A.
       C-PARA.
           MOVE 'C' TO WS-A.
"""

RETURNING = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FTBACK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-TO-PGM        PIC X(8).
           05  WS-OTHER         PIC X(10).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE DFHCOMMAREA TO WS-OTHER.
           EVALUATE WS-OTHER
               WHEN 'A'
                   MOVE 'PGMA' TO WS-TO-PGM
                   PERFORM BACK-PARA
               WHEN 'B'
                   MOVE 'PGMB' TO WS-TO-PGM
                   PERFORM BACK-PARA
               WHEN OTHER
                   PERFORM INIT-PARA
           END-EVALUATE.
           EXEC CICS RETURN END-EXEC.
       INIT-PARA.
           MOVE SPACES TO WS-OTHER.
       BACK-PARA.
           EXEC CICS XCTL PROGRAM(WS-TO-PGM) COMMAREA(WS-REC) END-EXEC.
"""

SOURCES = {
    "FTONLY": HEADER.format(name="FTONLY") + ONLY_PERFORMED,
    "FTALSO": HEADER.format(name="FTALSO") + ALSO_FALLEN_INTO,
    "FTTHRU": HEADER.format(name="FTTHRU") + THRU_RANGE,
    "FTGONE": HEADER.format(name="FTGONE") + GONE_TO,
    "FTSECT": HEADER.format(name="FTSECT") + SECTIONS,
    "FTOVER": HEADER.format(name="FTOVER") + OVERLAPPING,
    **{
        name: HEADER.format(name=name)
        + UNRESOLVED.format(construct=construct, switch=switch)
        for name, (construct, switch) in UNRESOLVED_CONSTRUCTS.items()
    },
    **{
        name: HEADER.format(name=name) + THRU_FELL_BACK.format(last=last)
        for name, last in THRU_ENDS.items()
    },
    "FTENTRY": HEADER.format(name="FTENTRY") + ENTERED,
    "FTABEND": HEADER.format(name="FTABEND") + ABEND_LABEL,
    "FTBACK": RETURNING,
}

Pairs = frozenset[tuple[str, str]]


@pytest.fixture(scope="module")
def out(fixpoint_corpus: Callable[[Mapping[str, str]], Path]) -> Path:
    return fixpoint_corpus(SOURCES)


def _fallthroughs(cfg: Cfg) -> Pairs:
    return frozenset(
        (edge.source, edge.target)
        for edge in cfg.edges
        if edge.kind is EdgeKind.FALLTHRU
    )


def _before_and_after(out: Path, member: str) -> tuple[Pairs, Pairs]:
    with cached_asg_dialect_parsers_registered():
        asg = first_program_at(out.parent / "parsed" / f"{member}.json")
    cfg = program_cfg(asg)
    return _fallthroughs(cfg), _fallthroughs(
        fallthroughs_pruned(cfg, paragraph_order(asg), statement_index(asg))
    )


def test_a_paragraph_only_performed_does_not_fall_through(out: Path) -> None:
    assert _before_and_after(out, "FTONLY") == (
        frozenset(
            {
                ("MAIN-PARA#end", "INIT-PARA#label"),
                ("INIT-PARA#end", "NEXT-PARA#label"),
                ("NEXT-PARA#end", "LAST-PARA#label"),
            }
        ),
        frozenset(),
    )


def test_a_paragraph_also_reached_without_a_perform_falls_through(out: Path) -> None:
    assert _before_and_after(out, "FTALSO")[1] == frozenset(
        {
            ("MAIN-PARA#end", "WORK-PARA#label"),
            ("WORK-PARA#end", "TAIL-PARA#label"),
        }
    )


def test_a_thru_range_falls_through_up_to_its_last_paragraph(out: Path) -> None:
    assert _before_and_after(out, "FTTHRU")[1] == frozenset(
        {("A-PARA#end", "B-PARA#label"), ("B-PARA#end", "C-PARA#label")}
    )


def test_a_paragraph_gone_to_from_another_activation_falls_through(
    out: Path,
) -> None:
    assert _before_and_after(out, "FTGONE")[1] == frozenset(
        {("LAND-PARA#end", "TAIL-PARA#label")}
    )


def test_a_performed_section_falls_through_between_its_paragraphs(
    out: Path,
) -> None:
    assert _before_and_after(out, "FTSECT") == (
        frozenset(
            {
                ("MAIN-SECTION#end", "WORK-SECTION#label"),
                ("W1-PARA#end", "W2-PARA#label"),
                ("WORK-SECTION#end", "TAIL-SECTION#label"),
            }
        ),
        frozenset({("W1-PARA#end", "W2-PARA#label")}),
    )


def test_overlapping_ranges_keep_every_fall_through_in_the_overlap(
    out: Path,
) -> None:
    assert _before_and_after(out, "FTOVER")[1] == frozenset(
        {
            ("A-PARA#end", "B-PARA#label"),
            ("B-PARA#end", "C-PARA#label"),
            ("C-PARA#end", "D-PARA#label"),
            ("D-PARA#end", "E-PARA#label"),
        }
    )


@pytest.mark.parametrize("member", sorted(UNRESOLVED_CONSTRUCTS))
def test_unresolved_control_flow_leaves_the_program_untouched(
    out: Path, member: str
) -> None:
    every = frozenset(
        {
            ("MAIN-PARA#end", "INIT-PARA#label"),
            ("INIT-PARA#end", "NEXT-PARA#label"),
            ("NEXT-PARA#end", "SWITCH-PARA#label"),
        }
    )
    assert _before_and_after(out, member) == (every, every)


@pytest.mark.parametrize("member", sorted(THRU_ENDS))
def test_a_thru_end_that_fell_back_leaves_the_program_untouched(
    out: Path, member: str
) -> None:
    every = frozenset(
        {
            ("MAIN-PARA#end", "A-PARA#label"),
            ("A-PARA#end", "B-PARA#label"),
            ("B-PARA#end", "C-PARA#label"),
            ("C-PARA#end", "D-PARA#label"),
        }
    )
    assert _before_and_after(out, member) == (every, every)


def test_a_paragraph_holding_an_entry_falls_through(out: Path) -> None:
    assert _before_and_after(out, "FTENTRY") == (
        frozenset({("MAIN-PARA#end", "B-PARA#label"), ("B-PARA#end", "C-PARA#label")}),
        frozenset({("B-PARA#end", "C-PARA#label")}),
    )


def test_a_handle_abend_label_falls_through(out: Path) -> None:
    assert _before_and_after(out, "FTABEND") == (
        frozenset({("MAIN-PARA#end", "B-PARA#label"), ("B-PARA#end", "C-PARA#label")}),
        frozenset({("B-PARA#end", "C-PARA#label")}),
    )


def _jumps(out: Path, program: str) -> tuple[Jump, ...]:
    lines = (
        (out / "members" / program / "jumps.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    return tuple(jump_from_row(line) for line in lines)


def test_every_performer_writes_the_xctl_target_so_only_their_literals_reach_it(
    out: Path,
) -> None:
    (xctl,) = (j for j in _jumps(out, "FTBACK") if j.kind is JumpKind.XCTL)
    assert (xctl.target.values, xctl.target.reasons) == (
        ("PGMA    ", "PGMB    "),
        (),
    )

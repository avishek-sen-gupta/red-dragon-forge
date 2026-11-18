"""cobble-experimental-codeql-facts: invented COBOL, compiled by the real bridge, written as TRAP."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from cobble.experimental.codeql.facts_cli import cli
from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.trap_row import TrapRow, define, trap_text
from cobble.parsing.parse_corpus import Job, parse_one

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

SHAPES = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SHAPES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 REC.
          05 KEY-A PIC X(4).
          05 AMT   PIC S9(5) COMP-3.
       01 OTHER-REC.
          05 KEY-A PIC X(4).
       01 TBL.
          05 ROW-X PIC X(2) OCCURS 3 TIMES.
       01 N PIC 9.
       01 IN-1 PIC X(4).
       PROCEDURE DIVISION.
       MAIN-SECTION SECTION.
       MAIN-PARA.
           ACCEPT IN-1.
           MOVE IN-1 TO KEY-A OF REC.
           MOVE IN-1(1:2) TO ROW-X(2).
           MOVE 'LIT' TO KEY-A OF OTHER-REC.
           PERFORM STEP-1 THRU STEP-2.
           PERFORM WORK-SECTION.
           PERFORM STEP-1 3 TIMES.
           PERFORM UNTIL N = 1
               MOVE 1 TO N
           END-PERFORM.
           IF N = 1
               DISPLAY KEY-A OF REC
           ELSE
               COMPUTE AMT = AMT + 1
           END-IF.
           GO TO STEP-1 STEP-2 DEPENDING ON N.
           GO TO DONE-PARA.
       STEP-1.
           DISPLAY 'ONE'.
       STEP-2.
           DISPLAY 'TWO'.
       DONE-PARA.
           STOP RUN.
       WORK-SECTION SECTION.
       WORK-1.
           DISPLAY N.
       WORK-2.
           GOBACK.
"""

ROW = re.compile(r"^(\w+)\((.*)\)$")
Tables = dict[str, set[tuple[str, ...]]]


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def _tables(text: str) -> Tables:
    rows = [ROW.match(line) for line in text.splitlines()]
    found = [(m.group(1), tuple(m.group(2).split(", "))) for m in rows if m]
    return {
        table: {columns for name, columns in found if name == table}
        for table in {name for name, _ in found}
    }


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("codeql")
    (root / "src").mkdir()
    (root / "asg").mkdir()
    source = root / "src" / "SHAPES.cbl"
    source.write_text(SHAPES, encoding="utf-8")
    parsed = parse_one(
        Job(source, root / "asg" / "SHAPES.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert parsed.ok, parsed.error
    (root / "src" / "BROKEN.cbl").write_text("not cobol\n", encoding="utf-8")
    (root / "asg" / "BROKEN.fail").write_text("parse failed\n", encoding="utf-8")
    config = root / "corpus.toml"
    config.write_text(
        "[corpus]\n"
        f'cobol_dir = "{root / "src"}"\n'
        'cobol_globs = ["*.cbl"]\n'
        f'jcl_dir = "{root}"\n'
        "jcl_globs = []\n"
        f'asg_dir = "{root / "asg"}"\n'
        "copybook_dirs = []\n",
        encoding="utf-8",
    )
    assert (
        cli(
            (
                "--config",
                str(config),
                "--trap-dir",
                str(root / "trap"),
                "--archive-dir",
                str(root / "archive"),
            )
        )
        == 0
    )
    return root


def test_a_member_is_written_as_its_fields_paragraphs_and_statements(
    corpus: Path,
) -> None:
    tables = _tables((corpus / "trap" / "SHAPES.trap").read_text(encoding="utf-8"))
    source = str((corpus / "src" / "SHAPES.cbl").resolve())
    locations = tables.pop("locations_default")
    assert {
        row for row in locations if row[0] in {"#lprogram", "#lp0", "#ls0_0_1"}
    } == {
        ("#lprogram", "#file", "0", "0", "0", "0"),
        ("#lp0", "#file", "16", "7", "33", "26"),
        ("#ls0_0_1", "#file", "18", "11", "18", "33"),
    }
    assert tables == {
        "files": {("#file", f'"{source}"')},
        "programs": {("#program", '"SHAPES"', "#lprogram")},
        "fields": {
            ("#f0", "#program", '"REC"', '"REC"', "0", "7", "#lf0"),
            ("#f1", "#program", '"KEY-A"', '"REC"', "0", "4", "#lf1"),
            ("#f2", "#program", '"AMT"', '"REC"', "4", "3", "#lf2"),
            ("#f3", "#program", '"OTHER-REC"', '"OTHER-REC"', "0", "4", "#lf3"),
            ("#f4", "#program", '"KEY-A"', '"OTHER-REC"', "0", "4", "#lf4"),
            ("#f5", "#program", '"TBL"', '"TBL"', "0", "6", "#lf5"),
            ("#f6", "#program", '"ROW-X"', '"TBL"', "0", "2", "#lf6"),
            ("#f7", "#program", '"ROW-X"', '"TBL"', "2", "2", "#lf7"),
            ("#f8", "#program", '"ROW-X"', '"TBL"', "4", "2", "#lf8"),
            ("#f9", "#program", '"N"', '"N"', "0", "1", "#lf9"),
            ("#f10", "#program", '"IN-1"', '"IN-1"', "0", "4", "#lf10"),
        },
        "numeric_fields": {("#f2",), ("#f9",)},
        "paragraphs": {
            ("#p0", "#program", '"MAIN-PARA"', '"MAIN-SECTION"', "0", "#lp0"),
            ("#p1", "#program", '"STEP-1"', '"MAIN-SECTION"', "1", "#lp1"),
            ("#p2", "#program", '"STEP-2"', '"MAIN-SECTION"', "2", "#lp2"),
            ("#p3", "#program", '"DONE-PARA"', '"MAIN-SECTION"', "3", "#lp3"),
            ("#p4", "#program", '"WORK-1"', '"WORK-SECTION"', "4", "#lp4"),
            ("#p5", "#program", '"WORK-2"', '"WORK-SECTION"', "5", "#lp5"),
        },
        "stmts": {
            ("#s0_0_0", "2", "#p0", "0", "0", "#ls0_0_0"),
            ("#s0_0_1", "1", "#p0", "0", "1", "#ls0_0_1"),
            ("#s0_0_2", "1", "#p0", "0", "2", "#ls0_0_2"),
            ("#s0_0_3", "1", "#p0", "0", "3", "#ls0_0_3"),
            ("#s0_0_4", "4", "#p0", "0", "4", "#ls0_0_4"),
            ("#s0_0_5", "4", "#p0", "0", "5", "#ls0_0_5"),
            ("#s0_0_6", "4", "#p0", "0", "6", "#ls0_0_6"),
            ("#s0_0_7", "9", "#p0", "0", "7", "#ls0_0_7"),
            ("#s0_0_7_1_0", "1", "#s0_0_7", "1", "0", "#ls0_0_7_1_0"),
            ("#s0_0_8", "6", "#p0", "0", "8", "#ls0_0_8"),
            ("#s0_0_8_1_0", "3", "#s0_0_8", "1", "0", "#ls0_0_8_1_0"),
            ("#s0_0_8_2_0", "0", "#s0_0_8", "2", "0", "#ls0_0_8_2_0"),
            ("#s0_0_9", "5", "#p0", "0", "9", "#ls0_0_9"),
            ("#s0_0_10", "5", "#p0", "0", "10", "#ls0_0_10"),
            ("#s1_0_0", "3", "#p1", "0", "0", "#ls1_0_0"),
            ("#s2_0_0", "3", "#p2", "0", "0", "#ls2_0_0"),
            ("#s3_0_0", "7", "#p3", "0", "0", "#ls3_0_0"),
            ("#s4_0_0", "3", "#p4", "0", "0", "#ls4_0_0"),
            ("#s5_0_0", "8", "#p5", "0", "0", "#ls5_0_0"),
        },
        "stmt_reads": {
            ("#s0_0_1", "#f10"),
            ("#s0_0_2", "#f10"),
            ("#s0_0_8_1_0", "#f1"),
            ("#s4_0_0", "#f9"),
        },
        "stmt_writes": {
            ("#s0_0_0", "#f10"),
            ("#s0_0_1", "#f1"),
            ("#s0_0_2", "#f6"),
            ("#s0_0_2", "#f7"),
            ("#s0_0_2", "#f8"),
            ("#s0_0_3", "#f4"),
            ("#s0_0_7_1_0", "#f9"),
        },
        "partial_accesses": {
            ("#s0_0_2", "#f10"),
            ("#s0_0_2", "#f6"),
            ("#s0_0_2", "#f7"),
            ("#s0_0_2", "#f8"),
        },
        "perform_ranges": {
            ("#s0_0_4", "#p1", "#p2"),
            ("#s0_0_5", "#p4", "#p5"),
            ("#s0_0_6", "#p1", "#p1"),
        },
        "perform_repeats": {("#s0_0_6",)},
        "goto_targets": {
            ("#s0_0_9", "#p1"),
            ("#s0_0_9", "#p2"),
            ("#s0_0_10", "#p3"),
        },
    }


def test_the_corpus_writes_its_prefix_skips_failures_and_archives_sources(
    corpus: Path,
) -> None:
    source = (corpus / "src" / "SHAPES.cbl").resolve()
    assert sorted(p.name for p in (corpus / "trap").iterdir()) == [
        "SHAPES.trap",
        "prefix.trap",
    ]
    assert (corpus / "trap" / "prefix.trap").read_text(encoding="utf-8") == (
        f'sourceLocationPrefix("{(corpus / "src").resolve()}")\n'
    )
    assert (corpus / "archive" / str(source).lstrip("/")).read_text(
        encoding="utf-8"
    ) == SHAPES


def test_a_trap_row_quotes_text_and_names_labels() -> None:
    rows = (define(Label("p0")), TrapRow("paragraphs", (Label("p0"), 'A "B"', 3)))
    assert trap_text(rows) == '#p0=*\nparagraphs(#p0, "A ""B""", 3)\n'

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


def _under(generated: Tables, label: str) -> set[tuple[str, ...]]:
    """The rows of the node ``label`` names and of every node below it, other
    than their locations."""
    return {
        (table, *row)
        for table, rows in generated.items()
        for row in rows
        if row[0] == label or row[0].startswith(label + "_")
        if not table.endswith("_span")
    }


def test_a_member_is_written_as_its_fields_paragraphs_and_statements(
    corpus: Path,
) -> None:
    tables = _tables((corpus / "trap" / "SHAPES.trap").read_text(encoding="utf-8"))
    source = str((corpus / "src" / "SHAPES.cbl").resolve())
    main = "#c0_1_0_1"
    locations = tables.pop("locations_default")
    generated = {
        table: tables.pop(table)
        for table in tuple(tables)
        if table.startswith(("cobol_", "program_"))
    }
    assert {
        row
        for row in locations
        if row[0] in {"#lprogram", "#lc0_1_0_2", "#lc0_1_0_1_1_2"}
    } == {
        ("#lprogram", "#file", "0", "0", "0", "0"),
        ("#lc0_1_0_2", "#file", "16", "7", "33", "26"),
        ("#lc0_1_0_1_1_2", "#file", "18", "11", "18", "33"),
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
        "units": {
            ("#program", "0", "#c0_1_0", '"MAIN-PARA"', '"MAIN-SECTION"'),
            ("#program", "1", "#c0_1_1", '"STEP-1"', '"MAIN-SECTION"'),
            ("#program", "2", "#c0_1_2", '"STEP-2"', '"MAIN-SECTION"'),
            ("#program", "3", "#c0_1_3", '"DONE-PARA"', '"MAIN-SECTION"'),
            ("#program", "4", "#c1_1_0", '"WORK-1"', '"WORK-SECTION"'),
            ("#program", "5", "#c1_1_1", '"WORK-2"', '"WORK-SECTION"'),
        },
        "names_cell": {
            (f"{main}_0_0", "#f10"),
            (f"{main}_1_0", "#f10"),
            (f"{main}_1_1_0", "#f1"),
            (f"{main}_2_0", "#f10"),
            (f"{main}_2_1_0", "#f7"),
            (f"{main}_3_1_0", "#f4"),
            (f"{main}_7_2_0_1_0", "#f9"),
            (f"{main}_7_3_0_0", "#f9"),
            (f"{main}_8_0_0", "#f9"),
            (f"{main}_8_1_0_0_0", "#f1"),
            (f"{main}_8_2_0_0_1", "#f2"),
            (f"{main}_8_2_0_1_0", "#f2"),
            (f"{main}_9_0_1", "#f9"),
            ("#c1_1_0_1_0_0_0", "#f9"),
        },
        "perform_range": {
            (f"{main}_4", "#c0_1_1", "#c0_1_2"),
            (f"{main}_5", "#c1_1_0", "#c1_1_1"),
            (f"{main}_6", "#c0_1_1", "#c0_1_1"),
        },
        "procedure_unit": {
            (f"{main}_9_0_0_0", "#c0_1_1"),
            (f"{main}_9_0_0_1", "#c0_1_2"),
            (f"{main}_10_0_0", "#c0_1_3"),
        },
    }
    assert generated["program_sections"] == {
        ("#program", "0", "#c0"),
        ("#program", "1", "#c1"),
    }
    until = f"{main}_7"
    assert _under(generated, until) == {
        ("cobol_perform_statement_def", until, '""', '""', '""', '""'),
        ("cobol_perform_statement_spec", until, f"{until}_3"),
        ("cobol_perform_until_spec_def", f"{until}_3", f"{until}_3_0", "true"),
        (
            "cobol_relation_test_def",
            f"{until}_3_0",
            f"{until}_3_0_0",
            '"=="',
            f"{until}_3_0_2",
            "false",
        ),
        ("cobol_field_ref_node_def", f"{until}_3_0_0", '"N"'),
        ("cobol_literal_node_def", f"{until}_3_0_2", '"1"', "true"),
        ("cobol_perform_statement_children", until, "0", f"{until}_2_0"),
        ("cobol_move_statement_def", f"{until}_2_0", f"{until}_2_0_0"),
        (
            "cobol_ref_mod_operand_def",
            f"{until}_2_0_0",
            '"1"',
            f"{until}_2_0_0_3",
            "false",
            '"lit"',
        ),
        ("cobol_ref_mod_length_of_def", f"{until}_2_0_0_3", '""'),
        ("cobol_move_statement_targets", f"{until}_2_0", "0", f"{until}_2_0_1_0"),
        (
            "cobol_ref_mod_operand_def",
            f"{until}_2_0_1_0",
            '"N"',
            f"{until}_2_0_1_0_3",
            "false",
            '"ref"',
        ),
        ("cobol_ref_mod_length_of_def", f"{until}_2_0_1_0_3", '""'),
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

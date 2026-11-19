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

ORIGINS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORIGINS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE.
       01 IN-REC PIC X(4).
       WORKING-STORAGE SECTION.
       01 FLAG PIC X.
          88 IS-ON VALUE 'Y'.
       01 ARG PIC X(4).
       01 RESP-CD PIC S9(8) COMP.
       01 ACCT PIC X(4).
       01 MAPI.
          05 FLD PIC X(4).
       01 GRP.
          05 G1 PIC X(2).
          05 FILLER PIC X(1).
          05 G2 PIC X(2).
       01 MAPO.
          05 FLD PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ IN-FILE.
           SET IS-ON TO TRUE.
           CALL 'SUB' USING ARG.
           EXEC CICS RECEIVE MAP('MAP') RESP(RESP-CD) END-EXEC.
           EXEC CICS READ FILE('ACCTS') INTO(ACCT) RIDFLD(ARG) END-EXEC.
           INITIALIZE GRP.
           EXEC CICS SEND MAP('MAP') END-EXEC.
           GOBACK.
"""

VALS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 PGM PIC X(8) VALUE 'SUBPGM'.
       01 NAME PIC X(4).
       01 RIGHT-NAME PIC X(10) JUSTIFIED RIGHT.
       01 N PIC 9(2).
       01 COPY-LK PIC X(4).
       LINKAGE SECTION.
       01 LK PIC X(4).
       PROCEDURE DIVISION USING LK.
       MAIN-PARA.
           MOVE 'AB' TO NAME.
           MOVE PGM TO RIGHT-NAME.
           MOVE 1 TO N.
           MOVE LK(1:N) TO COPY-LK.
           GOBACK.
"""

JUMPS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. JUMPS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 PGM PIC X(8).
       01 TID PIC X(4).
       01 AREA-1.
          05 A1 PIC X(2).
          05 A2 PIC X(2).
       LINKAGE SECTION.
       01 DFHCOMMAREA PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS XCTL PROGRAM(PGM) COMMAREA(AREA-1) END-EXEC.
           CALL 'SUB' USING AREA-1 A2.
           EXEC CICS RETURN TRANSID(TID) COMMAREA(AREA-1) END-EXEC.
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
    for name, text in (
        ("SHAPES", SHAPES),
        ("ORIGINS", ORIGINS),
        ("VALS", VALS),
        ("JUMPS", JUMPS),
    ):
        source = root / "src" / f"{name}.cbl"
        source.write_text(text, encoding="utf-8")
        parsed = parse_one(
            Job(source, root / "asg" / f"{name}.json"),
            str(_bridge_jar()),
            (),
            ("cpy",),
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
    assert {row[1] for row in tables.pop("field_region")} == {'"working_storage"'}
    generated = {
        table: tables.pop(table)
        for table in tuple(tables)
        if table.startswith(("cobol_", "program_", "cfg_", "statement_ids"))
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
        "group_field": {("#f0",), ("#f3",), ("#f5",)},
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
        "names_slice": {(f"{main}_2_0", "#f10", "0", "2")},
        "procedure_unit": {
            (f"{main}_9_0_0_0", "#c0_1_1"),
            (f"{main}_9_0_0_1", "#c0_1_2"),
            (f"{main}_10_0_0", "#c0_1_3"),
        },
    }
    assert {
        table: generated[table] for table in ("cfg_entry", "cfg_call", "cfg_resume")
    } == {
        "cfg_entry": {("#program", "#n0")},
        "cfg_call": {
            ("#n5", "#n19", "#n24"),
            ("#n6", "#n36", "#n37"),
            ("#n8", "#n19", "#n21"),
        },
        "cfg_resume": {("#n5", "#n6"), ("#n6", "#n7"), ("#n8", "#n7")},
    }
    assert generated["cfg_consults"] == {
        ("#n9", "#f9"),
        ("#n11", "#f9"),
        ("#n14", "#f9"),
    }
    assert generated["cfg_site"] == {
        ("#n7", f"{main}_6", '"#loop"'),
        ("#n9", f"{main}_7", '"#loop#test"'),
        ("#n11", f"{main}_8", '"#test"'),
        ("#n15", f"{main}_9", '"#goto.0"'),
        ("#n16", f"{main}_9", '"#goto.1"'),
    }
    assert {
        row
        for row in generated["statement_ids"]
        if row[0] in (f"{main}_7", f"{main}_7_2_0")
    } == {(f"{main}_7", '"MAIN-PARA/7"'), (f"{main}_7_2_0", '"MAIN-PARA/7.body.0"')}
    assert generated["program_sections"] == {
        ("#program", "0", "#c0"),
        ("#program", "1", "#c1"),
    }
    until = f"{main}_7"
    assert _under(generated, until) == {
        ("cobol_perform_statement_def", until, '""', '""', '""', '""'),
        ("statement_ids", until, '"MAIN-PARA/7"'),
        ("statement_ids", f"{until}_2_0", '"MAIN-PARA/7.body.0"'),
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


def test_a_read_a_condition_set_a_call_and_cics_operands_name_their_cells(
    corpus: Path,
) -> None:
    """READ fills its file's records, SET ... TO TRUE the field its condition tests,
    INITIALIZE its items but the FILLER; a CALL argument and a CICS operand that is
    not a literal name cells, a RECEIVE MAP with no INTO names its map's input
    record and a SEND MAP with no FROM its output record."""
    tables = _tables((corpus / "trap" / "ORIGINS.trap").read_text(encoding="utf-8"))
    main = "#d0_1"
    named = (
        "names_cell",
        "field_names_cell",
        "file_record_cell",
        "condition_set_cell",
        "initialized_cell",
    )
    assert {table: tables[table] for table in named} == {
        "file_record_cell": {(f"{main}_0", "#f13")},
        "condition_set_cell": {(f"{main}_1", "#f0")},
        "names_cell": {
            (f"{main}_2_1_0", "#f1"),
            (f"{main}_3_1_1", "#f2"),
            (f"{main}_4_1_1", "#f3"),
            (f"{main}_4_1_2", "#f1"),
            (f"{main}_5_0_0", "#f6"),
        },
        "field_names_cell": {
            (f"{main}_3", '"map_input"', "#f4"),
            (f"{main}_6", '"map_output"', "#f10"),
        },
        "initialized_cell": {(f"{main}_5", "#f7"), (f"{main}_5", "#f9")},
    }
    assert {row[0]: row[2] for row in tables["fields"]} == {
        "#f0": '"FLAG"',
        "#f1": '"ARG"',
        "#f2": '"RESP-CD"',
        "#f3": '"ACCT"',
        "#f4": '"MAPI"',
        "#f5": '"FLD"',
        "#f6": '"GRP"',
        "#f7": '"G1"',
        "#f8": '"FILLER_1"',
        "#f9": '"G2"',
        "#f10": '"MAPO"',
        "#f11": '"FLD"',
        "#f12": '"%HANDLER[ANY]"',
        "#f13": '"IN-REC"',
    }


def test_storage_values_are_the_initial_image_and_what_each_write_puts(
    corpus: Path,
) -> None:
    """A VALUE is the initial image; a quoted literal lands fitted in its target, a
    MOVE from a field carries the source's values, right-justified into a JUSTIFIED
    field, and a numeric literal is not a literal; a MOVE from LINKAGE bytes no
    constant locates carries only that a caller owns them; each cell says its
    region."""
    tables = _tables((corpus / "trap" / "VALS.trap").read_text(encoding="utf-8"))
    cells = {row[0]: row[2] for row in tables["fields"]}
    named = {
        "initial_value": {(cells[row[0]], *row[1:]) for row in tables["initial_value"]},
        **{
            table: {(cells[row[1]], *row[2:]) for row in tables[table]}
            for table in ("cfg_value", "cfg_value_reason")
        },
    }
    assert named == {
        "initial_value": {('"PGM"', "0", "8", '"SUBPGM  "')},
        "cfg_value": {('"NAME"', "0", "4", '"AB  "')},
        "cfg_value_reason": {
            ('"N"', "0", "2", '"not-a-literal"'),
            ('"COPY-LK"', "0", "4", '"inbound-linkage"'),
        },
    }
    assert {
        (cells[row[1]], row[2], row[3], cells[row[4]], row[5], row[6], row[7])
        for row in tables["cfg_carries"]
    } == {('"RIGHT-NAME"', "0", "10", '"PGM"', "0", "8", "true")}
    assert {(cells[row[0]], row[1]) for row in tables["field_region"]} == {
        ('"PGM"', '"working_storage"'),
        ('"NAME"', '"working_storage"'),
        ('"RIGHT-NAME"', '"working_storage"'),
        ('"N"', '"working_storage"'),
        ('"COPY-LK"', '"working_storage"'),
        ('"LK"', '"linkage"'),
    }


def test_jumps_name_what_they_hand_over_and_what_a_program_is_entered_with(
    corpus: Path,
) -> None:
    """A CICS operand or CALL argument names the storage it hands over, unsubscripted;
    a program with a DFHCOMMAREA is entered with it; a cell with cells under it is a
    group."""
    tables = _tables((corpus / "trap" / "JUMPS.trap").read_text(encoding="utf-8"))
    cells = {row[0]: row[2] for row in tables["fields"]}
    assert sorted(cells[row[1]] for row in tables["names_area"]) == [
        '"A2"',
        '"AREA-1"',
        '"AREA-1"',
        '"AREA-1"',
        '"PGM"',
        '"TID"',
    ]
    assert {(row[1], cells[row[2]]) for row in tables["received_area"]} == {
        ("0", '"DFHCOMMAREA"')
    }
    assert {cells[row[0]] for row in tables["group_field"]} == {'"AREA-1"'}


def test_the_corpus_writes_its_prefix_skips_failures_and_archives_sources(
    corpus: Path,
) -> None:
    source = (corpus / "src" / "SHAPES.cbl").resolve()
    assert sorted(p.name for p in (corpus / "trap").iterdir()) == [
        "JUMPS.trap",
        "ORIGINS.trap",
        "SHAPES.trap",
        "VALS.trap",
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

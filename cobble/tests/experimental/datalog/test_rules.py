"""The Datalog rule library, run on real CardDemo fact rows and checked against what the CardDemo source does."""

from __future__ import annotations

import csv
import shutil
import subprocess
from importlib import import_module
from pathlib import Path

import pytest
from cobble.experimental.datalog.facts_writer import schema_text
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_facts import FAMILIES

pytestmark = pytest.mark.skipif(
    shutil.which("souffle") is None, reason="the rule tests run souffle"
)

COBBLE = Path(__file__).resolve().parents[3]
LIBRARY = COBBLE / "cobble" / "experimental" / "datalog" / "rules"
CARDDEMO_FACTS = Path(__file__).resolve().parent / "carddemo_facts"
MASTER = "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"
BALANCE_TRACE = (
    '#include "sinks.dl"\n#include "combine.dl"\n'
    f'trace_target(p, n, r, s+12, s+24) :- sink_dataset(p, n, r, s, _, _, "{MASTER}").\n'
    ".decl sources(p:symbol, kind:symbol, name:symbol)\n"
    'sources(p, "file", f) :- origin_hit(p, _, "FILE", on), named(p, on, f).\n'
    'sources(p, "screen", m) :- origin_hit(p, _, "MAP", on), named(p, on, m).\n'
    'sources(p, "literal", "-") :- origin_hit(p, d, "LITERAL", _), pure(p, d).\n'
)


def _relations() -> tuple[Relation, ...]:
    return tuple(
        relation
        for family in FAMILIES
        for relation in vars(import_module(family.__module__)).values()
        if isinstance(relation, Relation)
    )


def evaluate(tmp_path: Path, question: str) -> dict[str, set[tuple[str, ...]]]:
    facts_dir = tmp_path / "facts"
    out_dir = tmp_path / "out"
    facts_dir.mkdir()
    out_dir.mkdir()
    relations = _relations()
    (facts_dir / "schema.dl").write_text(schema_text(relations))
    for relation in relations:
        fixture = CARDDEMO_FACTS / f"{relation.name}.facts"
        target = facts_dir / f"{relation.name}.facts"
        target.write_text(fixture.read_text() if fixture.is_file() else "")
    (tmp_path / "question.dl").write_text(question)
    subprocess.run(
        [
            "souffle",
            "--include-dir",
            str(facts_dir),
            "--include-dir",
            str(LIBRARY),
            "-F",
            str(facts_dir),
            "-D",
            str(out_dir),
            str(tmp_path / "question.dl"),
        ],
        check=True,
    )
    return {
        path.stem: {
            tuple(row)
            for row in csv.reader(path.read_text().splitlines(), delimiter="\t")
        }
        for path in out_dir.glob("*.csv")
    }


def _of(rows: set[tuple[str, ...]], program: str) -> set[tuple[str, ...]]:
    return {row for row in rows if row[0] == program}


def test_an_operand_names_the_file_or_map_its_field_holds_with_trailing_spaces_stripped(
    tmp_path: Path,
) -> None:
    """COACTUPC.cbl:573-574 and :537-540 give LIT-ACCTFILENAME 'ACCTDAT ' and
    LIT-THISMAP 'CACTUPA'; COBIL00C.cbl:41 gives WS-ACCTDAT-FILE 'ACCTDAT '. A
    batch SELECT name has no VALUE and names itself."""
    question = (
        '#include "names.dl"\n.decl picked(p:symbol, o:symbol, n:symbol)\n'
        "picked(p, o, n) :- named(p, o, n), "
        '(o = "LIT-ACCTFILENAME" ; o = "LIT-THISMAP" ; o = "WS-ACCTDAT-FILE" ; o = "ACCOUNT-FILE").\n'
        ".output picked\n"
    )
    assert evaluate(tmp_path, question)["picked"] == {
        ("COACTUPC", "LIT-ACCTFILENAME", "ACCTDAT"),
        ("COACTUPC", "LIT-THISMAP", "CACTUPA"),
        ("COBIL00C", "WS-ACCTDAT-FILE", "ACCTDAT"),
        ("CBACT04C", "ACCOUNT-FILE", "ACCOUNT-FILE"),
        ("CBTRN02C", "ACCOUNT-FILE", "ACCOUNT-FILE"),
    }


def test_a_file_write_lands_in_the_dataset_its_name_resolves_to(
    tmp_path: Path,
) -> None:
    """Batch: SELECT ACCOUNT-FILE ASSIGN TO ACCTFILE, and the INTCALC and POSTTRAN
    steps bind ACCTFILE to the KSDS; CBIMPORT's ACCOUNT-OUTPUT is ACCTOUT, bound
    to the .IMPORT dataset (CBIMPORT.jcl). CICS: the CSD defines ACCTDAT on the
    KSDS."""
    question = (
        '#include "sinks.dl"\n.decl account_write(p:symbol, f:symbol, dsn:symbol)\n'
        "account_write(p, f, d) :- sink_dataset(p, _, _, _, _, f, d), "
        'substr(d, 0, 23) = "AWS.M2.CARDDEMO.ACCTDAT".\n.output account_write\n'
    )
    assert evaluate(tmp_path, question)["account_write"] == {
        ("CBACT04C", "ACCOUNT-FILE", MASTER),
        ("CBTRN02C", "ACCOUNT-FILE", MASTER),
        ("COACTUPC", "ACCTDAT", MASTER),
        ("COBIL00C", "ACCTDAT", MASTER),
        ("CBIMPORT", "ACCOUNT-OUTPUT", "AWS.M2.CARDDEMO.ACCTDATA.IMPORT"),
    }


def test_the_trace_finds_the_files_and_screen_a_new_balance_comes_from(
    tmp_path: Path,
) -> None:
    """CBACT04C.cbl:352 adds interest computed at :464-467 from TCATBAL and
    DISCGRP to the old balance; CBTRN02C.cbl:547 adds DALYTRAN-AMT; COACTUPC.cbl
    :1105-1108 converts the typed ACURBALI and :3964 moves it into the record."""
    sources = evaluate(tmp_path, BALANCE_TRACE + ".output sources\n")["sources"]

    assert _of(sources, "CBACT04C") == {
        ("CBACT04C", "file", "ACCOUNT-FILE"),
        ("CBACT04C", "file", "TCATBAL-FILE"),
        ("CBACT04C", "file", "DISCGRP-FILE"),
    }
    assert _of(sources, "CBTRN02C") == {
        ("CBTRN02C", "file", "ACCOUNT-FILE"),
        ("CBTRN02C", "file", "DALYTRAN-FILE"),
    }
    assert {row for row in _of(sources, "COACTUPC") if row[1] == "screen"} == {
        ("COACTUPC", "screen", "CACTUPA")
    }


def test_a_definition_every_path_overwrites_is_not_a_source(tmp_path: Path) -> None:
    """COBIL00C's READPREV value (:214) is overwritten at :218 and :224 before the
    COMPUTE at :234 on every path that returns each PERFORM to its own call site."""
    sources = evaluate(tmp_path, BALANCE_TRACE + ".output sources\n")["sources"]

    assert _of(sources, "COBIL00C") == {("COBIL00C", "file", "ACCTDAT")}


def test_a_constant_counts_only_on_a_plain_copy_chain_not_behind_arithmetic(
    tmp_path: Path,
) -> None:
    """CBACT04C seeds its interest accumulator with 0 and ADDs into it (:467),
    then ADDs the total into the balance (:352): the 0 is behind combining
    nodes, so it is no source. The combining nodes are those ADDs and COMPUTEs:
    CBACT04C :352, :464, :467; CBTRN02C :547; COBIL00C :234."""
    question = BALANCE_TRACE + (
        ".decl combining(p:symbol, d:symbol)\ncombining(p, d) :- multi(p, d).\n"
        ".output sources\n.output combining\n"
    )
    out = evaluate(tmp_path, question)

    assert {
        row for row in out["sources"] if row[1] == "literal" and row[0] != "COACTUPC"
    } == set()
    assert out["combining"] == {
        ("CBACT04C", "1050-UPDATE-ACCOUNT/0"),
        ("CBACT04C", "1300-COMPUTE-INTEREST/0"),
        ("CBACT04C", "1300-COMPUTE-INTEREST/1"),
        ("CBTRN02C", "2800-UPDATE-ACCOUNT-REC/0"),
        ("COBIL00C", "PROCESS-ENTER-KEY/4.then.0.then.22"),
    }


def test_navigation_reaches_each_menus_programs_and_stops_where_told(
    tmp_path: Path,
) -> None:
    """The admin menu's table (COADM02Y) and the main menu's (COMEN02Y), their
    programs' own XCTLs, and PF3 back to sign-on, which the question stops at.
    COPAUS1C and COPAUS2C sit behind COPAUS0C's EXEC DLI, which the facts do not
    cover."""
    question = (
        '#include "navigation.dl"\nnav_start("A", "COADM01C").\n'
        'nav_start("U", "COMEN01C").\nnav_stop("COSGN00C").\n.output reaches\n'
    )
    admin = (
        "COSGN00C",
        "COADM01C",
        "COUSR00C",
        "COUSR01C",
        "COUSR02C",
        "COUSR03C",
        "COTRTLIC",
        "COTRTUPC",
    )
    user = (
        "COSGN00C",
        "COMEN01C",
        "COACTVWC",
        "COACTUPC",
        "COCRDLIC",
        "COCRDSLC",
        "COCRDUPC",
        "COTRN00C",
        "COTRN01C",
        "COTRN02C",
        "CORPT00C",
        "COBIL00C",
        "COPAUS0C",
    )
    assert evaluate(tmp_path, question)["reaches"] == {
        *(("A", p) for p in admin),
        *(("U", p) for p in user),
    }


def test_each_outcome_of_a_test_leads_to_its_own_transfer(tmp_path: Path) -> None:
    """COSGN00C.cbl:230-239: IF CDEMO-USRTYP-ADMIN XCTL COADM01C ELSE XCTL COMEN01C."""
    question = (
        '#include "branches.dl"\nbranch_test(p, n) :- '
        'cfg_pred(p, n, "CDEMO-USER-TYPE", _, _, _, _), p = "COSGN00C".\n.output branch\n'
    )
    assert evaluate(tmp_path, question)["branch"] == {
        ("COSGN00C", "READ-USER-SEC-FILE/1.when.0.0.then.5#test", "TRUE", "COADM01C"),
        ("COSGN00C", "READ-USER-SEC-FILE/1.when.0.0.then.5#test", "FALSE", "COMEN01C"),
    }

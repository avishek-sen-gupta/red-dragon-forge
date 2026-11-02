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

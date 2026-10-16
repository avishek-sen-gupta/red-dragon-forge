"""A jackal batch step whose program has EXEC SQL runs with squall's spec composed in."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from catnip.system_catalog import SystemCatalog
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed, StepOutcome
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from litter.build import build
from litter.open import open_package
from litter.package import Package
from squall.backends.sqlite import SqliteBackend
from squall.coprocessor import build_sql_spec
from squall.runtime import install_sql_runtime

CBL = Path(__file__).parent / "fixtures" / "cbl"


def _package(tmp_path: Path, bridge_jar: str) -> Package:
    return open_package(
        build(
            name="sql",
            programs=("SQLRPT",),
            link=("SQLRPT",),
            sources={"SQLRPT": CBL / "SQLRPT.cbl"},
            parser=ProLeapCobolParser(
                runner=RealSubprocessRunner(), bridge_jar=bridge_jar, copybook_dirs=[]
            ),
            specs=(build_sql_spec(),),
            copybook_dirs=(),
            work_dir=tmp_path / "work",
            out_dir=tmp_path / "out",
            transactions=(),
            files=(),
            mapsets={},
            tolerant=False,
        )
    )


def _report(
    tmp_path: Path, bridge_jar: str, step: str
) -> tuple[list[StepOutcome], bytes]:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)")
    conn.execute("INSERT INTO ACCOUNT VALUES (11, 500)")
    conn.commit()
    packaged = _package(tmp_path / "package", bridge_jar)
    install_sql_runtime({"SAMPLE": SqliteBackend(conn)})
    system = SystemCatalog(tmp_path / "system")
    runner = JobRunner(
        package=packaged,
        system=system,
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    jcl = f"//J JOB 1\n{step}//RPTDD DD DSN=J.RPT,DISP=(NEW,CATLG)\n"
    result = runner.run(parse_jcl(jcl), scratch)
    return (
        [s.outcome for s in result.steps],
        SystemCatalog(tmp_path / "system").lookup("J.RPT").path.read_bytes(),
    )


def test_a_batch_step_with_exec_sql_writes_what_it_selected(
    tmp_path: Path, bridge_jar: str
) -> None:
    assert _report(tmp_path, bridge_jar, "//S1 EXEC PGM=SQLRPT\n") == (
        [Completed(0)],
        "000000500 ".encode("cp037"),
    )


def test_a_tso_step_runs_its_db2_program_with_squall_composed_in(
    tmp_path: Path, bridge_jar: str
) -> None:
    """IKJEFT01 with DSN RUN PROGRAM(SQLRPT): the program's EXEC SQL is served by
    the coprocessor the runner was given (record 2026-10-12 TSO, T1)."""
    step = (
        "//S1 EXEC PGM=IKJEFT01\n"
        "//SYSTSIN DD *\n"
        "  DSN SYSTEM(DB2P)\n"
        "  RUN PROGRAM(SQLRPT) PLAN(RPTPLAN)\n"
        "  END\n"
        "/*\n"
    )
    assert _report(tmp_path, bridge_jar, step) == (
        [Completed(0)],
        "000000500 ".encode("cp037"),
    )

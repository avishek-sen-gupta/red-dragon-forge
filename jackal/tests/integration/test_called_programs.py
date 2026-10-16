"""A COBOL step enters the image at its program, which CALLs others linked beside it, each with its own files."""

from pathlib import Path

import pytest
from catnip.labels import LabelPending, RecordFormat, SequentialLabel
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from litter.package import Package
from tests.covers import NotLanguageFeature, covers
from tests.package_build import package
from tests.system_build import job_catalog, system
from interpreter.vm.builtins import core_builtins

MESSAGE = "WRITTEN BY THE CALLED PROGRAM".ljust(80).encode("cp037")


@pytest.fixture(autouse=True)
def _require(bridge_jar, jcl_bridge_jar):
    """Both JARs are required for every test in this module."""


@pytest.fixture(scope="module")
def packaged(tmp_path_factory: pytest.TempPathFactory, bridge_jar: str) -> Package:
    return package(
        tmp_path_factory.mktemp("package"),
        bridge_jar,
        ("CALLMAIN", "DYNMAIN", "SHRMAIN", "CALLSUB", "SHRSUB"),
    )


def _runner(tmp_path: Path, packaged: Package) -> JobRunner:
    return JobRunner(
        package=packaged,
        system=system(tmp_path),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        builtins=core_builtins(),
    )


def _ran(
    tmp_path: Path,
    packaged: Package,
    jcl_bridge_jar: str,
    pgm: str,
):
    jcl = (
        "//J JOB 1\n" f"//S1 EXEC PGM={pgm}\n" "//SUBDD DD DSN=J.SUB,DISP=(NEW,CATLG)\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    catalog = job_catalog(tmp_path)
    result = _runner(tmp_path, packaged).run_job(job, catalog)
    return (
        [s.outcome for s in result.steps],
        system(tmp_path).lookup("J.SUB").path.read_bytes(),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_statically_called_program_writes_to_its_own_dd(
    tmp_path: Path, packaged: Package, jcl_bridge_jar: str
) -> None:
    assert _ran(tmp_path, packaged, jcl_bridge_jar, "CALLMAIN") == (
        [Completed(0)],
        MESSAGE,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_dynamically_called_program_on_the_link_list_writes_to_its_own_dd(
    tmp_path: Path, packaged: Package, jcl_bridge_jar: str
) -> None:
    assert _ran(tmp_path, packaged, jcl_bridge_jar, "DYNMAIN") == (
        [Completed(0)],
        MESSAGE,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_select_name_the_main_and_its_callee_share_is_each_programs_own(
    tmp_path: Path, packaged: Package, jcl_bridge_jar: str
) -> None:
    jcl = (
        "//J JOB 1\n"
        "//S1 EXEC PGM=SHRMAIN\n"
        "//MAINDD DD DSN=J.MAIN,DISP=(NEW,CATLG)\n"
        "//SUBDD DD DSN=J.SUB,DISP=(NEW,CATLG)\n"
    )
    job = JclBridgeParser(JclSubprocessRunner(), jcl_bridge_jar).parse(jcl)
    result = _runner(tmp_path, packaged).run_job(job, job_catalog(tmp_path))
    reloaded = system(tmp_path)
    main, sub = reloaded.lookup("J.MAIN"), reloaded.lookup("J.SUB")

    assert (
        [s.outcome for s in result.steps],
        (main.label, main.path.read_bytes()),
        (sub.label, sub.path.read_bytes()),
    ) == (
        [Completed(0)],
        (
            SequentialLabel(RecordFormat.F, 80),
            "WRITTEN BY THE MAIN PROGRAM".ljust(80).encode("cp037"),
        ),
        (LabelPending(), b""),
    )

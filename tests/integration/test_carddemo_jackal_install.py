"""CardDemo's datasets, installed into a jackal system catalog with the labels its README declares."""

from __future__ import annotations

from pathlib import Path

from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.data_layout import record_length
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.dataset import Dataset
from jackal.jcl.parser import parse_jcl
from jackal.labels import KsdsLabel
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed
from jackal.runner import JobRunner
from jackal.system_catalog import SystemCatalog
from jackal.unresolved import RaiseErrorStrategy

from red_dragon_forge.carddemo_jackal_install import (
    CARDDEMO_DATASETS,
    UNDECLARED,
    install,
)


def _copybook_length(parser: ProLeapCobolParser, copybook: str) -> int:
    source = (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SZ.\n"
        "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
        f"       COPY {copybook}.\n       PROCEDURE DIVISION.\n           GOBACK.\n"
    )
    records = parser.parse(source.encode()).data_fields
    return record_length(records[0])


def test_every_declared_carddemo_dataset_agrees_with_its_copybook_and_its_file(
    carddemo_home: Path, bridge_jar: str
) -> None:
    parser = ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[carddemo_home / "cpy"]
    )
    data = carddemo_home / "data" / "EBCDIC"
    checks = [
        (
            d.dsn,
            _copybook_length(parser, d.copybook) - d.label.lrecl,
            (data / d.dsn).stat().st_size % d.label.lrecl,
        )
        for d in CARDDEMO_DATASETS
    ]
    declared = {d.dsn for d in CARDDEMO_DATASETS} | {u.dsn for u in UNDECLARED}
    data_files = sorted(p.name for p in data.iterdir() if not p.name.startswith("."))
    assert (checks, data_files) == (
        [(d.dsn, 0, 0) for d in CARDDEMO_DATASETS],
        sorted(declared),
    )


def test_an_installed_carddemo_system_holds_each_dataset_and_runs_acctfile(
    tmp_path: Path, carddemo_home: Path, bridge_jar: str
) -> None:
    data = carddemo_home / "data" / "EBCDIC"
    root = tmp_path / "system"
    install(SystemCatalog(root), data)
    system = SystemCatalog(root)
    runner = JobRunner(
        source_dir=carddemo_home / "cbl",
        bridge_jar=bridge_jar,
        system=system,
        copybook_dir=carddemo_home / "cpy",
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = runner.run(
        parse_jcl((carddemo_home / "jcl" / "ACCTFILE.jcl").read_text()), scratch
    )
    ksds = "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"
    assert (
        [system.lookup(d.dsn) for d in CARDDEMO_DATASETS],
        [(root / "datasets" / d.dsn).read_bytes() for d in CARDDEMO_DATASETS],
        [s.outcome for s in result.steps],
        SystemCatalog(root).lookup(ksds),
    ) == (
        [Dataset(d.dsn, root / "datasets" / d.dsn, d.label) for d in CARDDEMO_DATASETS],
        [(data / d.dsn).read_bytes() for d in CARDDEMO_DATASETS],
        [Completed(0), Completed(0), Completed(0)],
        Dataset(ksds, root / "datasets" / ksds, KsdsLabel(300, 0, 11)),
    )

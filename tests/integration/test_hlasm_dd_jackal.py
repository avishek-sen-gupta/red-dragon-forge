"""A jackal step's dataset DDs reach HLASM: an HLASM step writes a dataset, new or DISP=MOD, fixed or variable, that a later step reads."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from catnip.dataset import Dataset
from catnip.labels import DatasetLabel, RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged, SystemCatalog
from interpreter.vm.builtins import core_builtins
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import StrictAllocation
from jackal.missing_program import AbendMissingProgram
from jackal.results import Completed, StepOutcome
from jackal.runner import JobRunner
from jackal.unknown_return_code import RaiseUnknownReturnCode
from jackal.unresolved import RaiseErrorStrategy
from litter.open import open_package

from red_dragon_forge.build_command import run as forge_build

_FIXTURES = Path(__file__).parent / "fixtures" / "hlasm_dd"
_FIXED = ("FIRST RECORD", "SECOND RECORD", "THIRD RECORD")


def _runner(tmp_path: Path) -> JobRunner:
    build = tmp_path / "build.toml"
    build.write_text(
        f'[cobol]\nsource_dirs = ["{_FIXTURES}"]\nprograms = ["DDREAD"]\n'
        f'[hlasm]\nsource_dirs = ["{_FIXTURES}"]\n'
        'programs = ["DDWRITE", "DDWRITEV"]\n'
        '[build]\nname = "ddjob"\n'
        'link = ["DDREAD", "DDWRITE", "DDWRITEV"]\nout_dir = "out"\n'
    )
    assert forge_build([str(build)], os.environ) == 0
    return JobRunner(
        package=open_package(tmp_path / "out" / "ddjob.zip"),
        system=SystemCatalog(tmp_path / "system"),
        unresolved=RaiseErrorStrategy(),
        missing_data=StrictAllocation(),
        missing_program=AbendMissingProgram(),
        unknown_return_code=RaiseUnknownReturnCode(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        builtins=core_builtins(),
    )


def _ran(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], jcl: str
) -> tuple[list[StepOutcome], list[str]]:
    runner = _runner(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    capsys.readouterr()
    outcomes: list[StepOutcome] = [
        s.outcome for s in runner.run(parse_jcl(jcl), scratch).steps
    ]
    return outcomes, capsys.readouterr().out.splitlines()


def _job(writer: str, out_dd: str, reader: str) -> str:
    return (
        f"//J JOB 1\n//S1 EXEC PGM={writer}\n//OUTDD DD {out_dd}\n"
        f"//S2 EXEC PGM={reader}\n//INDD DD DSN=APP.OUT,DISP=SHR\n"
    )


def test_an_hlasm_step_writes_fixed_records_a_cobol_step_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    jcl = _job("DDWRITE", "DSN=APP.OUT,DISP=(NEW,CATLG),RECFM=FB,LRECL=80", "DDREAD")

    assert _ran(tmp_path, capsys, jcl) == (
        [Completed(0), Completed(0)],
        [text.ljust(80) for text in _FIXED],
    )


def _dataset(tmp_path: Path, dsn: str) -> tuple[DatasetLabel, bytes]:
    match SystemCatalog(tmp_path / "system").lookup(dsn):
        case Dataset(label=label, path=path):
            return label, path.read_bytes()
        case NotCataloged():
            raise AssertionError(f"{dsn} is not cataloged")


def test_each_hlasm_step_writes_by_its_own_dds_variable_records_keeping_their_length(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    jcl = (
        "//J JOB 1\n//S1 EXEC PGM=DDWRITE\n"
        "//OUTDD DD DSN=APP.FIXED,DISP=(NEW,CATLG),RECFM=FB,LRECL=80\n"
        "//S2 EXEC PGM=DDWRITEV\n"
        "//OUTDD DD DSN=APP.OUT,DISP=(NEW,CATLG),RECFM=VB,LRECL=104\n"
    )

    assert (_ran(tmp_path, capsys, jcl), _dataset(tmp_path, "APP.OUT")) == (
        ([Completed(0), Completed(0)], []),
        (
            SequentialLabel(RecordFormat.VB, 104),
            b"".join(
                (len(text) + 4).to_bytes(2, "big") + bytes(2) + text.encode("cp037")
                for text in ("AB", "HELLO, WORLD", "Z" * 100)
            ),
        ),
    )


def test_an_hlasm_step_appends_to_a_dataset_its_dd_codes_disp_mod(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    SystemCatalog(tmp_path / "system").create(
        "APP.OUT", SequentialLabel(RecordFormat.FB, 80)
    ).path.write_bytes("ZEROTH RECORD".ljust(80).encode("cp037"))

    assert _ran(
        tmp_path, capsys, _job("DDWRITE", "DSN=APP.OUT,DISP=MOD", "DDREAD")
    ) == (
        [Completed(0), Completed(0)],
        [text.ljust(80) for text in ("ZEROTH RECORD", *_FIXED)],
    )

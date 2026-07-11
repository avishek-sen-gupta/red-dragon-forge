from pathlib import Path

import pytest

from cobble.corpus_config import CorpusConfig
from cobble.corpus_index import CorpusIndex
from cobble.file_location import FileLocationReason, NoFileLocation
from cobble.interpreter.project.graph_types import NodeKind
from cobble.jackal.dsn import DirectDSN, InStreamDSN
from cobble.jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step
from cobble.jackal.value_parts import Literal


def _config(tmp_path: Path, **overrides) -> CorpusConfig:
    defaults = dict(
        cobol_dir=tmp_path / "cbl",
        cobol_globs=("*.cbl",),
        jcl_dir=tmp_path / "jcl",
        jcl_globs=("*.jcl",),
        proclib_dirs=(),
        csd_files=(),
        copybook_dirs=(tmp_path / "cpy",),
        out_dir=tmp_path / "out",
    )
    defaults.update(overrides)
    return CorpusConfig(**defaults)


def _touch(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_resolves_program_by_filename_stem(tmp_path: Path) -> None:
    _touch(tmp_path / "cbl" / "ACCTFILE.cbl")
    config = _config(tmp_path)
    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.PROGRAM, "ACCTFILE") == tmp_path / "cbl" / "ACCTFILE.cbl"


def test_program_resolution_is_case_insensitive(tmp_path: Path) -> None:
    _touch(tmp_path / "cbl" / "acctfile.cbl")
    config = _config(tmp_path)
    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.PROGRAM, "ACCTFILE") == tmp_path / "cbl" / "acctfile.cbl"


def test_unresolved_program_is_flagged_not_silently_none(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = CorpusIndex(config)
    result = index.resolve_file_path(NodeKind.PROGRAM, "MISSING")
    assert result == NoFileLocation(FileLocationReason.UNRESOLVED)


def test_resolves_copybook_from_copybook_dirs(tmp_path: Path) -> None:
    _touch(tmp_path / "cpy" / "COCOM01Y.cpy")
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.COPYBOOK, "COCOM01Y") == tmp_path / "cpy" / "COCOM01Y.cpy"


def test_dataset_is_always_not_file_based(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.DATASET, "ACCT.MASTER") == NoFileLocation(
        FileLocationReason.NOT_FILE_BASED
    )


def test_cobol_file_is_always_not_file_based(tmp_path: Path) -> None:
    # A COBOL_FILE's id is a DD name shared across whichever programs happen
    # to use it — never a single owning program's file.
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.COBOL_FILE, "ACCTFILE") == NoFileLocation(
        FileLocationReason.NOT_FILE_BASED
    )


def test_transaction_without_csd_has_no_definition_source(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.TRANSACTION, "CC00") == NoFileLocation(
        FileLocationReason.NO_DEFINITION_SOURCE
    )


def test_transaction_resolves_to_its_csd_file(tmp_path: Path) -> None:
    csd_path = _touch(
        tmp_path / "csd" / "CARDDEMO.CSD",
        "DEFINE TRANSACTION(CC00) PROGRAM(COSGN00C) GROUP(CARDDEMO)\n",
    )
    config = _config(tmp_path, csd_files=(csd_path,))
    (tmp_path / "cbl").mkdir()
    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.TRANSACTION, "CC00") == csd_path


def test_cics_file_resolves_to_its_csd_file(tmp_path: Path) -> None:
    csd_path = _touch(
        tmp_path / "csd" / "CARDDEMO.CSD",
        "DEFINE FILE(ACCTFILE) DSNAME(AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS)\n",
    )
    config = _config(tmp_path, csd_files=(csd_path,))
    (tmp_path / "cbl").mkdir()
    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.CICS_FILE, "ACCTFILE") == csd_path


def _simple_dd(ddname: str, name: str) -> DD:
    return DD(
        ddname=ddname,
        dsn=DirectDSN((Literal(name),)),
        disp=Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP),
    )


def _instream_dd(ddname: str) -> DD:
    return DD(
        ddname=ddname,
        dsn=InStreamDSN(),
        disp=Disp(DispStatus.NEW, DispNormal.DELETE, DispNormal.DELETE),
        in_stream=("  DELETE CLUSTER",),
    )


def test_job_and_step_resolve_to_owning_jcl_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jcl_path = _touch(tmp_path / "jcl" / "ACCTFILE.jcl", "//ACCTFILE JOB ...\n")
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()

    job = Job(name="ACCTFILE", steps=(Step(name="STEP05", pgm="IDCAMS", dds=(_simple_dd("SYSIN", "SOME.DSN"),)),))
    monkeypatch.setattr("cobble.corpus_index.parse_jcl", lambda text: job)

    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.JOB, "ACCTFILE") == jcl_path
    assert index.resolve_file_path(NodeKind.STEP, "ACCTFILE.STEP05") == jcl_path


def test_instream_data_resolves_to_owning_jcl_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jcl_path = _touch(tmp_path / "jcl" / "ACCTFILE.jcl", "//ACCTFILE JOB ...\n")
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()

    job = Job(name="ACCTFILE", steps=(Step(name="STEP05", pgm="IDCAMS", dds=(_instream_dd("SYSIN"),)),))
    monkeypatch.setattr("cobble.corpus_index.parse_jcl", lambda text: job)

    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.INSTREAM_DATA, "ACCTFILE.STEP05.SYSIN") == jcl_path


def test_step_from_proc_resolves_to_the_proc_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jcl_path = _touch(tmp_path / "jcl" / "RUNSORT.jcl", "//RUNSORT JOB ...\n")
    proc_path = _touch(tmp_path / "proc" / "SORTPROC.prc", "//SORTPROC PROC\n")
    config = _config(tmp_path, proclib_dirs=(tmp_path / "proc",))
    (tmp_path / "cbl").mkdir()

    outer_job = Job(name="RUNSORT", steps=(Step(name="STEP01", pgm="SORTPROC", dds=()),))
    expanded_job = Job(
        name="RUNSORT", steps=(Step(name="STEP01.SORTSTEP", pgm="SORT", dds=()),)
    )
    monkeypatch.setattr("cobble.corpus_index.parse_jcl", lambda text: outer_job)
    monkeypatch.setattr("cobble.corpus_index.expand_procs", lambda job, proclib_dirs: expanded_job)
    monkeypatch.setattr(
        "cobble.corpus_index.step_proc_provenance",
        lambda job, expanded: {"STEP01.SORTSTEP": "SORTPROC"},
    )

    index = CorpusIndex(config)
    assert index.resolve_file_path(NodeKind.STEP, "RUNSORT.STEP01.SORTSTEP") == proc_path

from pathlib import Path

import pytest
from cobble.corpus_config import CorpusConfig
from cobble.corpus_index_builder import build_corpus_index
from cobble.corpus_table import DEFAULT_COPYBOOK_EXTENSIONS
from cobble.file_location import FileLocationReason, NoFileLocation
from cobble.knowledge_graph.graph_types import NodeKind
from dataclasses import dataclass

from jackal.dsn import DdName, DirectDSN, InStreamDSN
from jackal.expansion import CircularProc, ExpansionFailed, ProcLibrary, ProcNotFound
from jackal.jcl.bridge_parser import JclParseError
from jackal.model import (
    DD,
    Disp,
    DispAbnormal,
    DispNormal,
    DispStatus,
    Job,
    ProcCall,
    ProcDef,
    ProcRef,
    ProgramRef,
    ProgramStep,
    StepName,
)
from jackal.value_parts import Literal


def _config(tmp_path: Path, **overrides) -> CorpusConfig:
    defaults = dict(
        cobol_dir=tmp_path / "cbl",
        cobol_globs=("*.cbl",),
        jcl_dir=tmp_path / "jcl",
        jcl_globs=("*.jcl",),
        proclib_dirs=(),
        csd_files=(),
        copybook_dirs=(tmp_path / "cpy",),
        copybook_extensions=DEFAULT_COPYBOOK_EXTENSIONS,
        asg_dir=tmp_path / "parsed",
    )
    return CorpusConfig(**{**defaults, **overrides})


def _touch(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# Every monkeypatch here targets the module that reads the corpus.
_MODULE = "cobble.corpus_index_builder"


def _patch(monkeypatch: pytest.MonkeyPatch, **targets: object) -> None:
    """Patch reader-module names by attribute name, one call for however many."""
    for name, value in targets.items():
        monkeypatch.setattr(f"{_MODULE}.{name}", value)


def _prepared(tmp_path: Path, **overrides) -> CorpusConfig:
    """A config whose cobol_dir exists — every index build walks it."""
    (tmp_path / "cbl").mkdir(exist_ok=True)
    return _config(tmp_path, **overrides)


def _raise(exc: Exception) -> Job:
    """Fail from inside a lambda, so a stand-in step that raises is one statement."""
    raise exc


def _record(path: Path, text: str, job: Job) -> Job:
    """Write what the reader passed where the test can read it back."""
    path.write_text(text)
    return job


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_resolves_program_by_filename_stem(tmp_path: Path) -> None:
    _touch(tmp_path / "cbl" / "ACCTFILE.cbl")
    config = _config(tmp_path)
    index = build_corpus_index(config)
    resolved = index.resolve_file_path(NodeKind.PROGRAM, "ACCTFILE")
    assert resolved == tmp_path / "cbl" / "ACCTFILE.cbl"


def test_program_resolution_is_case_insensitive(tmp_path: Path) -> None:
    _touch(tmp_path / "cbl" / "acctfile.cbl")
    config = _config(tmp_path)
    index = build_corpus_index(config)
    resolved = index.resolve_file_path(NodeKind.PROGRAM, "ACCTFILE")
    assert resolved == tmp_path / "cbl" / "acctfile.cbl"


def test_unresolved_program_is_flagged_not_silently_none(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = build_corpus_index(config)
    result = index.resolve_file_path(NodeKind.PROGRAM, "MISSING")
    assert result == NoFileLocation(FileLocationReason.UNRESOLVED)


def test_resolves_copybook_from_copybook_dirs(tmp_path: Path) -> None:
    _touch(tmp_path / "cpy" / "COCOM01Y.cpy")
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = build_corpus_index(config)
    resolved = index.resolve_file_path(NodeKind.COPYBOOK, "COCOM01Y")
    assert resolved == tmp_path / "cpy" / "COCOM01Y.cpy"


def test_dataset_is_always_not_file_based(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = build_corpus_index(config)
    assert index.resolve_file_path(NodeKind.DATASET, "ACCT.MASTER") == NoFileLocation(
        FileLocationReason.NOT_FILE_BASED
    )


def test_cobol_file_is_always_not_file_based(tmp_path: Path) -> None:
    # A COBOL_FILE's id is a DD name shared across whichever programs happen
    # to use it — never a single owning program's file.
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = build_corpus_index(config)
    assert index.resolve_file_path(NodeKind.COBOL_FILE, "ACCTFILE") == NoFileLocation(
        FileLocationReason.NOT_FILE_BASED
    )


def test_bms_map_is_not_indexed_rather_than_unresolved(tmp_path: Path) -> None:
    """cobble keeps no BMS index, so no lookup happens for a BMS_MAP at all.
    Calling that UNRESOLVED accuses the corpus of missing files it was never
    asked for — and at corpus scale that is thousands of nodes asserting a
    problem that does not exist."""
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = build_corpus_index(config)
    assert index.resolve_file_path(NodeKind.BMS_MAP, "MAPONE") == NoFileLocation(
        FileLocationReason.NOT_INDEXED
    )


def test_transaction_without_csd_has_no_definition_source(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    index = build_corpus_index(config)
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
    index = build_corpus_index(config)
    assert index.resolve_file_path(NodeKind.TRANSACTION, "CC00") == csd_path


def test_cics_file_resolves_to_its_csd_file(tmp_path: Path) -> None:
    csd_path = _touch(
        tmp_path / "csd" / "CARDDEMO.CSD",
        "DEFINE FILE(ACCTFILE) DSNAME(AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS)\n",
    )
    config = _config(tmp_path, csd_files=(csd_path,))
    (tmp_path / "cbl").mkdir()
    index = build_corpus_index(config)
    assert index.resolve_file_path(NodeKind.CICS_FILE, "ACCTFILE") == csd_path


def _simple_dd(ddname: str, name: str) -> DD:
    return DD(
        ddname=DdName(ddname),
        dsn=DirectDSN((Literal(name),)),
        disp=Disp(DispStatus.SHR, DispNormal.KEEP, DispAbnormal.KEEP),
    )


def _instream_dd(ddname: str) -> DD:
    return DD(
        ddname=DdName(ddname),
        dsn=InStreamDSN(),
        disp=Disp(DispStatus.NEW, DispNormal.DELETE, DispAbnormal.DELETE),
        in_stream=("  DELETE CLUSTER",),
    )


def test_job_and_step_resolve_to_owning_jcl_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jcl_path = _touch(tmp_path / "jcl" / "ACCTFILE.jcl", "//ACCTFILE JOB ...\n")
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()

    job = Job(
        name="ACCTFILE",
        steps=(
            ProgramStep(
                StepName("STEP05"),
                ProgramRef("IDCAMS"),
                (_simple_dd("SYSIN", "SOME.DSN"),),
            ),
        ),
    )
    monkeypatch.setattr("cobble.corpus_index_builder.parse_jcl", lambda text: job)

    index = build_corpus_index(config)
    assert index.resolve_file_path(NodeKind.JOB, "ACCTFILE") == jcl_path
    assert index.resolve_file_path(NodeKind.STEP, "ACCTFILE.STEP05") == jcl_path


def test_a_member_that_does_not_parse_is_reported_not_only_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skipped member has to reach the caller. It used to be a log line only, so
    the run's end-of-run failure report said nothing about 259 members missing
    from the index."""
    _touch(tmp_path / "jcl" / "ACCTFILE.jcl", "//ACCTFILE JOB ...\n")
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()

    def boom(text: str) -> Job:
        raise JclParseError("line 70:9 mismatched input 'EXEC' expecting JOB")

    monkeypatch.setattr("cobble.corpus_index_builder.parse_jcl", boom)

    index = build_corpus_index(config)
    assert index.failures == (
        "index JCL ACCTFILE.jcl: line 70:9 mismatched input 'EXEC' expecting JOB",
    )


def test_an_index_with_nothing_wrong_reports_no_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _touch(tmp_path / "jcl" / "ACCTFILE.jcl", "//ACCTFILE JOB ...\n")
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()
    monkeypatch.setattr(
        "cobble.corpus_index_builder.parse_jcl",
        lambda text: Job(name="ACCTFILE", steps=()),
    )

    index = build_corpus_index(config)
    assert index.failures == ()


def test_a_bug_in_indexing_is_not_filed_as_a_corpus_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``except Exception`` filed cobble's own bugs as corpus shape and carried on.
    Only a parse failure is a corpus problem; anything else must surface."""
    _touch(tmp_path / "jcl" / "ACCTFILE.jcl", "//ACCTFILE JOB ...\n")
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()

    def bug(text: str) -> Job:
        raise AttributeError("'NoneType' object has no attribute 'upper'")

    monkeypatch.setattr("cobble.corpus_index_builder.parse_jcl", bug)

    with pytest.raises(AttributeError) as raised:
        build_corpus_index(config)
    assert str(raised.value) == "'NoneType' object has no attribute 'upper'"


def test_a_csd_that_does_not_parse_is_reported_not_only_logged(
    tmp_path: Path,
) -> None:
    csd_path = _touch(tmp_path / "csd" / "BROKEN.CSD", "this is not a DEFINE\n")
    config = _config(tmp_path, csd_files=(csd_path,))
    (tmp_path / "cbl").mkdir()

    index = build_corpus_index(config)
    assert len(index.failures) == 1
    assert index.failures[0].startswith("index CSD BROKEN.CSD: ")


def test_indexes_a_jcl_member_that_is_not_valid_utf_8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Members are 8-bit text; 58 JCL members in a production corpus carry bytes
    >= 0x80, mostly the 0xA6 broken bar in //* box-drawing comments. A strict
    decode raised inside the per-file try/except, so the member was silently
    dropped from the index and every job, step and dataset in it went
    unresolvable."""
    jcl_path = _write_bytes(
        tmp_path / "jcl" / "ACCTFILE.jcl", b"//*\xa6\xa6\n//ACCTFILE JOB ...\n"
    )
    config = _prepared(tmp_path)

    # Recorded to a file rather than to a captured list: there is exactly one JCL
    # member, so one write, and the spy stays free of accumulator mutation.
    seen_path = tmp_path / "seen.txt"
    job = Job(name="ACCTFILE", steps=())
    _patch(monkeypatch, parse_jcl=lambda text: _record(seen_path, text, job))

    index = build_corpus_index(config)
    assert seen_path.read_text() == "//*¦¦\n//ACCTFILE JOB ...\n"
    assert index.resolve_file_path(NodeKind.JOB, "ACCTFILE") == jcl_path


def test_instream_data_resolves_to_owning_jcl_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jcl_path = _touch(tmp_path / "jcl" / "ACCTFILE.jcl", "//ACCTFILE JOB ...\n")
    config = _config(tmp_path)
    (tmp_path / "cbl").mkdir()

    job = Job(
        name="ACCTFILE",
        steps=(
            ProgramStep(
                StepName("STEP05"), ProgramRef("IDCAMS"), (_instream_dd("SYSIN"),)
            ),
        ),
    )
    monkeypatch.setattr("cobble.corpus_index_builder.parse_jcl", lambda text: job)

    index = build_corpus_index(config)
    resolved = index.resolve_file_path(NodeKind.INSTREAM_DATA, "ACCTFILE.STEP05.SYSIN")
    assert resolved == jcl_path


@dataclass(frozen=True)
class _Library(ProcLibrary):
    procs: tuple[ProcDef, ...] = ()

    def find(self, proc: ProcRef) -> ProcDef | ProcNotFound:
        found = tuple(p for p in self.procs if p.name == proc.name)
        return found[0] if found else ProcNotFound()


class _BrokenLibrary(ProcLibrary):
    def find(self, proc: ProcRef) -> ProcDef | ProcNotFound:
        raise TypeError("'NoneType' object is not iterable")


_SORTPROC = ProcRef("SORTPROC")
_CIRCULAR = _Library(
    (ProcDef("SORTPROC", (), (ProcCall(StepName("AGAIN"), _SORTPROC),)),)
)


def _calls_sortproc(path: Path) -> Job:
    return Job(path.stem, (ProcCall(StepName("STEP01"), _SORTPROC),))


def test_a_member_whose_procs_do_not_expand_is_reported_not_fatal(
    tmp_path: Path,
) -> None:
    """One member whose PROCs do not expand must not abort the index build:
    every member after it still gets indexed."""
    _touch(tmp_path / "jcl" / "RUNSORT.jcl", "//RUNSORT JOB ...\n")
    later = _touch(tmp_path / "jcl" / "LATER.jcl", "//LATER JOB ...\n")
    config = _prepared(tmp_path, proclib_dirs=(tmp_path / "proc",))

    index = build_corpus_index(
        config,
        read_job=lambda path: (
            _calls_sortproc(path) if path.stem == "RUNSORT" else Job(path.stem, ())
        ),
        libraries=lambda dirs: _CIRCULAR,
    )
    circular = ExpansionFailed(CircularProc((_SORTPROC, _SORTPROC)))
    assert index.failures == (f"index JCL RUNSORT.jcl: {circular}",)
    assert index.resolve_file_path(NodeKind.JOB, "LATER") == later


def test_a_member_whose_procs_do_not_expand_keeps_its_unexpanded_steps(
    tmp_path: Path,
) -> None:
    """The outer job parsed; only the inlining failed. Its own steps are exactly
    what the JCL says, so they stay in the index rather than vanishing with the
    PROC's."""
    jcl_path = _touch(tmp_path / "jcl" / "RUNSORT.jcl", "//RUNSORT JOB ...\n")
    config = _prepared(tmp_path, proclib_dirs=(tmp_path / "proc",))

    index = build_corpus_index(
        config, read_job=_calls_sortproc, libraries=lambda dirs: _CIRCULAR
    )
    assert index.resolve_file_path(NodeKind.STEP, "RUNSORT.STEP01") == jcl_path


def test_a_bug_in_proc_expansion_is_not_filed_as_a_corpus_failure(
    tmp_path: Path,
) -> None:
    """Guards the handler's width: expansion failures are corpus shape, a
    TypeError in the code doing the expanding is not."""
    _touch(tmp_path / "jcl" / "RUNSORT.jcl", "//RUNSORT JOB ...\n")
    config = _prepared(tmp_path, proclib_dirs=(tmp_path / "proc",))

    with pytest.raises(TypeError) as raised:
        build_corpus_index(
            config, read_job=_calls_sortproc, libraries=lambda dirs: _BrokenLibrary()
        )
    assert str(raised.value) == "'NoneType' object is not iterable"


def test_step_from_proc_resolves_to_the_proc_file(tmp_path: Path) -> None:
    _touch(tmp_path / "jcl" / "RUNSORT.jcl", "//RUNSORT JOB ...\n")
    proc_path = _touch(tmp_path / "proc" / "SORTPROC.prc", "//SORTPROC PROC\n")
    config = _prepared(tmp_path, proclib_dirs=(tmp_path / "proc",))
    library = _Library(
        (
            ProcDef(
                "SORTPROC",
                (),
                (ProgramStep(StepName("SORTSTEP"), ProgramRef("SORT")),),
            ),
        )
    )

    index = build_corpus_index(
        config, read_job=_calls_sortproc, libraries=lambda dirs: library
    )
    resolved = index.resolve_file_path(NodeKind.STEP, "RUNSORT.STEP01.SORTSTEP")
    assert resolved == proc_path

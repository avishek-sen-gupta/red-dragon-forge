"""Integration tests: &&NAME temporary dataset lifecycle via JobRunner."""

from __future__ import annotations

from jackal.dsn import DirectDSN, TempRef
from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step
from jackal.runner import JobRunner
from tests.covers import NotLanguageFeature, covers


def _pass_dd(alias: str) -> DD:
    """Create a DD that allocates a new temp dataset and passes it to the next step."""
    return DD(
        ddname="WRK",
        dsn=TempRef(alias),
        disp=Disp(DispStatus.NEW, DispNormal.PASS, DispNormal.DELETE),
    )


def _old_pass_dd(alias: str) -> DD:
    """Create a DD that opens an existing temp and passes it onward."""
    return DD(
        ddname="WRK",
        dsn=TempRef(alias),
        disp=Disp(DispStatus.OLD, DispNormal.PASS, DispNormal.DELETE),
    )


def _old_delete_dd(alias: str) -> DD:
    """Create a DD that opens and deletes an existing temp dataset."""
    return DD(
        ddname="WRK",
        dsn=TempRef(alias),
        disp=Disp(DispStatus.OLD, DispNormal.DELETE, DispNormal.DELETE),
    )


def _runner(tmp_path):
    return JobRunner(
        source_dir=tmp_path,
        bridge_jar="unused",
        data_dir=tmp_path,
        copybook_dir=tmp_path,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_two_step_temp_dataset(tmp_path):
    """Step 1 creates &&TEMP (PASS); step 2 opens and deletes it."""
    job = Job(
        name="J",
        steps=(
            Step(name="S1", pgm="IEFBR14", dds=(_pass_dd("&&TEMP"),)),
            Step(name="S2", pgm="IEFBR14", dds=(_old_delete_dd("&&TEMP"),)),
        ),
    )
    result = _runner(tmp_path).run(job, workdir=tmp_path, seeds={})
    assert all(s.ran and s.return_code == 0 for s in result.steps)
    assert not (tmp_path / "TEMP").exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_three_step_pass_chain(tmp_path):
    """Step 1 creates &&TEMP; step 2 reads+passes; step 3 deletes."""
    job = Job(
        name="J",
        steps=(
            Step(name="S1", pgm="IEFBR14", dds=(_pass_dd("&&TEMP"),)),
            Step(name="S2", pgm="IEFBR14", dds=(_old_pass_dd("&&TEMP"),)),
            Step(name="S3", pgm="IEFBR14", dds=(_old_delete_dd("&&TEMP"),)),
        ),
    )
    result = _runner(tmp_path).run(job, workdir=tmp_path, seeds={})
    assert all(s.ran and s.return_code == 0 for s in result.steps)
    assert not (tmp_path / "TEMP").exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_missing_temp_raises(tmp_path):
    """Referencing an unallocated &&GHOST with OLD raises KeyError."""
    import pytest

    job = Job(
        name="J",
        steps=(Step(name="S1", pgm="IEFBR14", dds=(_old_delete_dd("&&GHOST"),)),),
    )
    with pytest.raises(KeyError):
        _runner(tmp_path).run(job, workdir=tmp_path, seeds={})


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_end_cleanup_removes_undeleted_temp(tmp_path):
    """&&TEMP PASSed by step 1 but never explicitly deleted is cleaned at job end."""
    job = Job(
        name="J",
        steps=(Step(name="S1", pgm="IEFBR14", dds=(_pass_dd("&&TEMP"),)),),
    )
    result = _runner(tmp_path).run(job, workdir=tmp_path, seeds={})
    assert result.steps[0].ran
    assert not (tmp_path / "TEMP").exists()

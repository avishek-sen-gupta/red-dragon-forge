"""Integration tests: &&NAME temporary dataset lifecycle via JobRunner."""

from __future__ import annotations

from jackal.model import DD, StepRef, TempRef
from jackal.runner import JobRunner
from tests.covers import NotLanguageFeature, covers
from tests.model_build import dd, disp, job, program


def _pass_dd(name: str) -> DD[StepRef]:
    return dd("WRK", TempRef(name), disp("NEW", "PASS", "DELETE"))


def _old_pass_dd(name: str) -> DD[StepRef]:
    return dd("WRK", TempRef(name), disp("OLD", "PASS", "DELETE"))


def _old_delete_dd(name: str) -> DD[StepRef]:
    return dd("WRK", TempRef(name), disp("OLD", "DELETE", "DELETE"))


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
    j = job(
        "J",
        (
            program("S1", "IEFBR14", (_pass_dd("TEMP"),)),
            program("S2", "IEFBR14", (_old_delete_dd("TEMP"),)),
        ),
    )
    result = _runner(tmp_path).run(j, workdir=tmp_path, seeds={})
    assert all(s.ran and s.return_code == 0 for s in result.steps)
    assert not (tmp_path / "TEMP").exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_three_step_pass_chain(tmp_path):
    """Step 1 creates &&TEMP; step 2 reads+passes; step 3 deletes."""
    j = job(
        "J",
        (
            program("S1", "IEFBR14", (_pass_dd("TEMP"),)),
            program("S2", "IEFBR14", (_old_pass_dd("TEMP"),)),
            program("S3", "IEFBR14", (_old_delete_dd("TEMP"),)),
        ),
    )
    result = _runner(tmp_path).run(j, workdir=tmp_path, seeds={})
    assert all(s.ran and s.return_code == 0 for s in result.steps)
    assert not (tmp_path / "TEMP").exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_missing_temp_raises(tmp_path):
    """Referencing an unallocated &&GHOST with OLD raises KeyError."""
    import pytest

    j = job(
        "J",
        (program("S1", "IEFBR14", (_old_delete_dd("GHOST"),)),),
    )
    with pytest.raises(KeyError):
        _runner(tmp_path).run(j, workdir=tmp_path, seeds={})


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cleanup_runs_after_step_exception(tmp_path):
    """Temp allocated in step 1 is cleaned up even when step 2 raises KeyError."""
    import pytest

    j = job(
        "J",
        (
            program("S1", "IEFBR14", (_pass_dd("KEPT"),)),
            program("S2", "IEFBR14", (_old_delete_dd("GHOST"),)),
        ),
    )
    with pytest.raises(KeyError):
        _runner(tmp_path).run(j, workdir=tmp_path, seeds={})
    # &&KEPT was allocated by step 1 but never deleted — cleanup_temps() must
    # have run (via try/finally in runner) to remove it
    assert not (tmp_path / "KEPT").exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_end_cleanup_removes_undeleted_temp(tmp_path):
    """&&TEMP PASSed by step 1 but never explicitly deleted is cleaned at job end."""
    j = job(
        "J",
        (program("S1", "IEFBR14", (_pass_dd("TEMP"),)),),
    )
    result = _runner(tmp_path).run(j, workdir=tmp_path, seeds={})
    assert result.steps[0].ran
    assert not (tmp_path / "TEMP").exists()

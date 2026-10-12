"""Integration tests: relative GDG generations resolve once per job, roll in at step end and roll off past LIMIT."""

from __future__ import annotations

from pathlib import Path

from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.gdg import Empty, GdgBase, Scratch
from jackal.missing_data import (
    LenientAllocation,
    MissingDataStrategy,
    StrictAllocation,
)
from jackal.missing_program import AbendMissingProgram
from jackal.model import DD, DdName, GenerationDSN, StepRef
from jackal.results import AllocationError, AllocationFailed, Completed
from jackal.runner import JobRunner
from jackal.system_catalog import NotCataloged
from jackal.unresolved import RaiseErrorStrategy
from jackal.value_parts import literal
from tests.covers import NotLanguageFeature, covers
from tests.model_build import dd, disp, job, program
from tests.system_build import gdg, job_catalog, scratch, system


def _gen(ddname: str, base: str, relative: int, *words: str) -> DD[StepRef]:
    return dd(ddname, GenerationDSN(literal(base), relative), disp(*words))


def _runner(tmp_path: Path, missing_data: MissingDataStrategy = StrictAllocation()):
    return JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=missing_data,
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        source_dir=tmp_path,
        bridge_jar="unused",
        system=system(tmp_path),
        copybook_dir=tmp_path,
    )


def _base(name: str, limit: int, generations: tuple[int, ...]) -> GdgBase:
    return GdgBase(name, limit, Empty.NOEMPTY, Scratch.SCRATCH, generations)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_relative_generations_resolve_against_the_gdg_as_the_job_found_it(tmp_path):
    """JCL Ref p. 286, GDGBIAS=JOB: with G0007V00 current when the job starts and
    steps 1 and 2 each creating a generation, step 3's (0) is still G0007V00 and
    its (+1) is the generation step 1 created. Each CATLG generation rolls in at
    the end of its step."""
    gdg(tmp_path, _base("A.HIST", 5, (6, 7)))
    j = job(
        "J",
        (
            program("S1", "IEFBR14", (_gen("NEW1", "A.HIST", 1, "NEW", "CATLG"),)),
            program("S2", "IEFBR14", (_gen("NEW2", "A.HIST", 2, "NEW", "CATLG"),)),
            program(
                "S3",
                "IEFBR14",
                (
                    _gen("CUR", "A.HIST", 0, "SHR"),
                    _gen("PRV", "A.HIST", -1, "SHR"),
                    _gen("FIRST", "A.HIST", 1, "OLD"),
                ),
            ),
        ),
    )
    result = _runner(tmp_path).run(j, scratch=scratch(tmp_path))
    after = job_catalog(tmp_path)
    assert [s.outcome for s in result.steps] == [Completed(0)] * 3
    assert after.gdg("A.HIST") == _base("A.HIST", 5, (6, 7, 8, 9))
    assert tuple(after.resolve(f"A.HIST.G{n:04d}V00").dsn for n in (8, 9)) == (
        "A.HIST.G0008V00",
        "A.HIST.G0009V00",
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_rolling_in_past_the_limit_rolls_off_by_empty_and_scratch(tmp_path):
    """UDS p. 484: past LIMIT the oldest generation rolls off (NOEMPTY), or every
    one does (EMPTY); SCRATCH deletes it, NOSCRATCH leaves it cataloged outside
    the GDG. A NEW,KEEP generation stays cataloged and out of the GDG."""
    gdg(tmp_path, GdgBase("A.OLDEST", 2, Empty.NOEMPTY, Scratch.SCRATCH, (1, 2)))
    gdg(tmp_path, GdgBase("A.ALL", 2, Empty.EMPTY, Scratch.NOSCRATCH, (1, 2)))
    gdg(tmp_path, _base("A.KEPT", 2, (1,)))
    j = job(
        "J",
        (
            program(
                "S1",
                "IEFBR14",
                (
                    _gen("OLDEST", "A.OLDEST", 1, "NEW", "CATLG"),
                    _gen("ALL", "A.ALL", 1, "NEW", "CATLG"),
                    _gen("KEPT", "A.KEPT", 1, "NEW", "KEEP"),
                ),
            ),
        ),
    )
    result = _runner(tmp_path).run(j, scratch=scratch(tmp_path))
    after = job_catalog(tmp_path)
    assert result.steps[0].outcome == Completed(0)
    assert (after.gdg("A.OLDEST"), after.gdg("A.ALL"), after.gdg("A.KEPT")) == (
        GdgBase("A.OLDEST", 2, Empty.NOEMPTY, Scratch.SCRATCH, (2, 3)),
        GdgBase("A.ALL", 2, Empty.EMPTY, Scratch.NOSCRATCH, (3,)),
        _base("A.KEPT", 2, (1,)),
    )
    assert (
        after.resolve("A.OLDEST.G0001V00"),
        after.resolve("A.ALL.G0001V00").dsn,
        after.resolve("A.KEPT.G0002V00").dsn,
    ) == (NotCataloged(), "A.ALL.G0001V00", "A.KEPT.G0002V00")
    assert not (tmp_path / "system" / "datasets" / "A.OLDEST.G0001V00").exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_generation_with_no_base_or_no_dataset_fails_allocation(tmp_path):
    """Record G9: an undefined base fails with GDG_BASE_NOT_FOUND; a (0) of a GDG
    with no generations fails with DATASET_NOT_FOUND. The lenient strategy
    stands in an empty dataset for either."""
    steps = (
        program("S1", "IEFBR14", (_gen("NOBASE", "A.NONE", 1, "NEW", "CATLG"),)),
        program("S2", "IEFBR14", (_gen("NOGEN", "A.EMPTY", 0, "SHR"),)),
    )

    def outcomes(root: Path, missing_data: MissingDataStrategy):
        gdg(root, _base("A.EMPTY", 3, ()))
        runner = _runner(root, missing_data)
        return tuple(
            runner.run(job("J", (step,)), scratch=scratch(root)).steps[0].outcome
            for step in steps
        )

    assert outcomes(tmp_path / "strict", StrictAllocation()) == (
        AllocationFailed(DdName("NOBASE"), AllocationError.GDG_BASE_NOT_FOUND),
        AllocationFailed(DdName("NOGEN"), AllocationError.DATASET_NOT_FOUND),
    )
    assert outcomes(tmp_path / "lenient", LenientAllocation()) == (
        Completed(0),
        Completed(0),
    )

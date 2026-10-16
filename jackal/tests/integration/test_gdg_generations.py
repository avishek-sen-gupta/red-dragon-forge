"""Integration tests: relative GDG generations resolve once per job, roll in at step end and roll off past LIMIT."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from catnip.gdg import Empty, GdgBase, GdgOrder, Scratch
from catnip.system_catalog import NotCataloged
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.missing_data import (
    LenientAllocation,
    MissingDataStrategy,
    StrictAllocation,
)
from jackal.missing_program import AbendMissingProgram
from jackal.model import DD, DdName, GenerationDSN, StepRef
from jackal.results import AllocationError, AllocationFailed, Completed
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from jackal.value_parts import Value, literal
from litter.package import Package
from tests.covers import NotLanguageFeature, covers
from tests.package_build import EMPTY, package
from tests.model_build import dd, disp, job, program
from tests.system_build import gdg, job_catalog, scratch, system, upload


def _gen(ddname: str, base: str, relative: int, *words: str) -> DD[StepRef]:
    return dd(ddname, GenerationDSN(literal(base), relative), disp(*words))


def _runner(
    tmp_path: Path,
    missing_data: MissingDataStrategy = StrictAllocation(),
    packaged: Package = EMPTY,
):
    return JobRunner(
        unresolved=RaiseErrorStrategy(),
        missing_data=missing_data,
        missing_program=AbendMissingProgram(),
        program_step_budget=DEFAULT_PROGRAM_STEP_BUDGET,
        package=packaged,
        system=system(tmp_path),
    )


def _base(name: str, limit: int, generations: tuple[int, ...]) -> GdgBase:
    return GdgBase(
        name, limit, Empty.NOEMPTY, Scratch.SCRATCH, GdgOrder.LIFO, generations
    )


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
    gdg(
        tmp_path,
        GdgBase("A.OLDEST", 2, Empty.NOEMPTY, Scratch.SCRATCH, GdgOrder.LIFO, (1, 2)),
    )
    gdg(
        tmp_path,
        GdgBase("A.ALL", 2, Empty.EMPTY, Scratch.NOSCRATCH, GdgOrder.LIFO, (1, 2)),
    )
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
        GdgBase("A.OLDEST", 2, Empty.NOEMPTY, Scratch.SCRATCH, GdgOrder.LIFO, (2, 3)),
        GdgBase("A.ALL", 2, Empty.EMPTY, Scratch.NOSCRATCH, GdgOrder.LIFO, (3,)),
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
    with no generations fails with DATASET_NOT_FOUND, and so does the base name of
    one (a GDG-all request). The lenient strategy stands in an empty dataset."""
    steps = (
        program("S1", "IEFBR14", (_gen("NOBASE", "A.NONE", 1, "NEW", "CATLG"),)),
        program("S2", "IEFBR14", (_gen("NOGEN", "A.EMPTY", 0, "SHR"),)),
        program("S3", "IEFBR14", (dd("NOALL", "A.EMPTY"),)),
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
        AllocationFailed(DdName("NOALL"), AllocationError.DATASET_NOT_FOUND),
    )
    assert outcomes(tmp_path / "lenient", LenientAllocation()) == (
        Completed(0),
        Completed(0),
        Completed(0),
    )


def _generations(root: Path, name: str, order: GdgOrder) -> None:
    for number in (1, 2, 3):
        upload(
            root, f"{name}.G{number:04d}V00", f"GEN {number}".ljust(80).encode("cp037")
        )
    system(root).catalog_gdg(
        GdgBase(name, 5, Empty.NOEMPTY, Scratch.NOSCRATCH, order, (1, 2, 3))
    )


def _read_all(step: str, base: str, out: str, *words: str, order: Value = ()):
    sysin = replace(dd("SYSIN", base, disp(*words)), gdg_order=order)
    return program(step, "CARDCOPY", (sysin, dd("OUTDD", out, disp("NEW", "CATLG"))))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_gdg_base_name_reads_every_generation_in_the_gdgs_order(tmp_path, bridge_jar):
    """JCL Ref p. 167: omitting the generation number retrieves all generations;
    AMS p. 178: LIFO (the default) returns them newest first, FIFO oldest first;
    GDGORDER on the DD overrides the GDG's order (JCL Ref p. 190). Each generation is allocated and disposed as a member of the concatenation:
    DISP=(OLD,DELETE) deletes every one, and the GDG is left with none."""
    _generations(tmp_path, "A.NEWEST", GdgOrder.LIFO)
    _generations(tmp_path, "A.OLDEST", GdgOrder.FIFO)
    j = job(
        "J",
        (
            _read_all("S1", "A.NEWEST", "J.LIFO", "SHR"),
            _read_all("S2", "A.OLDEST", "J.FIFO", "OLD", "DELETE"),
            _read_all("S3", "A.NEWEST", "J.OVER", "SHR", order=literal("FIFO")),
        ),
    )
    result = _runner(
        tmp_path, packaged=package(tmp_path / "package", bridge_jar, ("CARDCOPY",))
    ).run(j, scratch=scratch(tmp_path))
    after = job_catalog(tmp_path)

    def records(dsn: str) -> list[str]:
        data = system(tmp_path).lookup(dsn).path.read_bytes().decode("cp037")
        return [data[i : i + 80].rstrip() for i in range(0, len(data), 80)]

    assert [s.outcome for s in result.steps] == [Completed(0)] * 3
    assert (records("J.LIFO"), records("J.FIFO"), records("J.OVER")) == (
        ["GEN 3", "GEN 2", "GEN 1"],
        ["GEN 1", "GEN 2", "GEN 3"],
        ["GEN 1", "GEN 2", "GEN 3"],
    )
    assert after.gdg("A.OLDEST") == GdgBase(
        "A.OLDEST", 5, Empty.NOEMPTY, Scratch.NOSCRATCH, GdgOrder.FIFO, ()
    )
    assert (
        tuple(after.resolve(f"A.OLDEST.G{n:04d}V00") for n in (1, 2, 3))
        == (NotCataloged(),) * 3
    )

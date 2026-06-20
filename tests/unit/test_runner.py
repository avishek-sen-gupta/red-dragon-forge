from pathlib import Path

from tests.covers import NotLanguageFeature, covers

from jackal.model import DD, Disp, DispNormal, DispStatus, Job, Step
from jackal.runner import JobRunner


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_runner_runs_all_steps(tmp_path: Path) -> None:
    job = Job(
        name="J",
        steps=(
            Step(
                name="A",
                pgm="IEFBR14",
                dds=(
                    DD(
                        "D",
                        "J.X",
                        Disp(DispStatus.NEW, DispNormal.DELETE, DispNormal.DELETE),
                    ),
                ),
            ),
            Step(name="B", pgm="IEFBR14", dds=()),
        ),
    )
    runner = JobRunner(source_dir=tmp_path, bridge_jar="unused")
    res = runner.run(job, workdir=tmp_path, seeds={})
    assert [s.name for s in res.steps] == ["A", "B"]
    assert all(s.ran and s.return_code == 0 for s in res.steps)

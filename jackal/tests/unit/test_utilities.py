from jackal.allocation import DdEnvironment
from jackal.model import ProgramRef
from jackal.utilities import UTILITIES
from tests.covers import NotLanguageFeature, covers
from tests.model_build import dd, disp, program
from tests.system_build import job_catalog


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_iefbr14_does_nothing_itself_since_the_runner_allocates_and_disposes(
    tmp_path,
):
    cat = job_catalog(tmp_path)
    step = program("DEL", "IEFBR14", (dd("D", "J.TMP", disp("NEW", "DELETE")),))
    assert (
        UTILITIES[ProgramRef("IEFBR14")](step, DdEnvironment(()), cat),
        [f for f in tmp_path.rglob("*") if f.is_file()],
    ) == (0, [])

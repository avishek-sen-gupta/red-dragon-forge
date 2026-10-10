from jackal.allocation import DdEnvironment
from jackal.catalog import DatasetCatalog
from jackal.model import ProgramRef
from jackal.utilities import UTILITIES
from tests.covers import NotLanguageFeature, covers
from tests.model_build import dd, disp, program


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_iefbr14_does_nothing_itself_since_the_runner_allocates_and_disposes(
    tmp_path,
):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    step = program("DEL", "IEFBR14", (dd("D", "J.TMP", disp("NEW", "DELETE")),))
    assert (
        UTILITIES[ProgramRef("IEFBR14")](step, DdEnvironment(()), cat),
        list(tmp_path.iterdir()),
    ) == (0, [])

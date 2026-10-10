import pytest
from jackal.catalog import DatasetCatalog
from jackal.model import DD, DdName, NoDSN, ProgramRef
from jackal.utilities import UTILITIES
from tests.covers import NotLanguageFeature, covers
from tests.model_build import dd, disp, program


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_iefbr14_allocates_then_disposes_every_dataset_but_sysout(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    sysout = DD(DdName("SYSPRINT"), NoDSN(), disp("SHR"), sysout=True)
    step = program(
        "DEL", "IEFBR14", (dd("D", "J.TMP", disp("NEW", "DELETE", "DELETE")), sysout)
    )
    assert UTILITIES[ProgramRef("IEFBR14")](step, cat) == 0
    assert not (tmp_path / "J_TMP").exists()
    with pytest.raises(KeyError):
        cat.resolve("")

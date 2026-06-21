from jackal.catalog import DatasetCatalog
from jackal.model import DD, Disp, DispNormal, DispStatus, Step
from jackal.utilities import UTILITIES
from tests.covers import covers, NotLanguageFeature


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_iefbr14_allocates_then_deletes(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    dd = DD(
        ddname="D",
        dsn="J.TMP",
        disp=Disp(DispStatus.NEW, DispNormal.DELETE, DispNormal.DELETE),
    )
    step = Step(name="DEL", pgm="IEFBR14", dds=(dd,))
    result = UTILITIES["IEFBR14"](step, cat)
    assert result.ran and result.return_code == 0
    assert not (tmp_path / "J_TMP").exists()  # NEW then DELETE -> gone

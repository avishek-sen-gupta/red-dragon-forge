import pytest
from jackal.catalog import DatasetCatalog
from jackal.dsn import DirectDSN
from jackal.model import DD, Disp, DispNormal, DispStatus, Step
from jackal.utilities import UTILITIES
from jackal.value_parts import literal
from tests.covers import covers, NotLanguageFeature


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_iefbr14_allocates_then_deletes(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    dd = DD(
        ddname="D",
        dsn=DirectDSN(literal("J.TMP")),
        disp=Disp(DispStatus.NEW, DispNormal.DELETE, DispNormal.DELETE),
    )
    step = Step(name="DEL", pgm="IEFBR14", dds=(dd,))
    result = UTILITIES["IEFBR14"](step, cat)
    assert result.ran and result.return_code == 0
    assert not (tmp_path / "J_TMP").exists()  # NEW then DELETE -> gone


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_iefbr14_skips_sysout_dd(tmp_path):
    # A SYSOUT DD is not a real dataset; IEFBR14 must not allocate/dispose it.
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    sysout = DD(
        ddname="SYSPRINT",
        dsn=DirectDSN(()),
        disp=Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP),
        sysout=True,
    )
    step = Step(name="S", pgm="IEFBR14", dds=(sysout,))
    result = UTILITIES["IEFBR14"](step, cat)
    assert result.ran and result.return_code == 0
    with pytest.raises(KeyError):
        cat.resolve("")  # the sysout DD must never be catalogued

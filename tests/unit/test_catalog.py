from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog
from jackal.model import DD, Disp, DispNormal, DispStatus, DatasetOrg
from tests.covers import covers, NotLanguageFeature


def _dd(dsn, status, normal=DispNormal.KEEP):
    return DD(ddname="D", dsn=dsn, disp=Disp(status, normal, DispNormal.DELETE))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_new_allocates_empty_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    ds = cat.allocate(_dd("J.WORK", DispStatus.NEW))
    assert ds.path.exists() and ds.path.read_bytes() == b""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_seed_then_shr_resolves_same_file(tmp_path):
    src = tmp_path / "seed.dat"
    src.write_bytes(b"DATA")
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    cat.seed("J.IN", src)
    ds = cat.allocate(_dd("J.IN", DispStatus.SHR))
    assert ds.path == src


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_pass_retains_delete_removes(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    keep = cat.allocate(_dd("J.A", DispStatus.NEW, DispNormal.PASS))
    cat.dispose(_dd("J.A", DispStatus.NEW, DispNormal.PASS))
    assert keep.path.exists()
    drop = cat.allocate(_dd("J.B", DispStatus.NEW, DispNormal.DELETE))
    cat.dispose(_dd("J.B", DispStatus.NEW, DispNormal.DELETE))
    assert not drop.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_shr_on_unknown_dsn_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    with pytest.raises(KeyError):
        cat.allocate(_dd("J.MISSING", DispStatus.SHR))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_shr_resolves_from_data_dir(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "A.B.PS").write_bytes(b"REC1")
    wd = tmp_path / "wd"
    wd.mkdir()
    cat = DatasetCatalog(workdir=wd, data_dir=data)
    dd = DD("D", "A.B.PS", Disp(DispStatus.SHR, DispNormal.KEEP, DispNormal.KEEP))
    assert cat.allocate(dd).path == data / "A.B.PS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_allocate_ksds(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path, data_dir=tmp_path)
    ds = cat.allocate_ksds("A.B.KSDS", key_offset=0, key_length=11, record_size=300)
    assert ds.org is DatasetOrg.KSDS and ds.key_length == 11 and ds.record_size == 300
    assert ds.path.exists()
    assert cat.resolve("A.B.KSDS").org is DatasetOrg.KSDS

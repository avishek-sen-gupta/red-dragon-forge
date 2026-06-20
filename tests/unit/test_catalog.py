from pathlib import Path

import pytest

from jackal.catalog import DatasetCatalog
from jackal.model import DD, Disp, DispNormal, DispStatus
from tests.covers import covers, NotLanguageFeature


def _dd(dsn, status, normal=DispNormal.KEEP):
    return DD(ddname="D", dsn=dsn, disp=Disp(status, normal, DispNormal.DELETE))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_new_allocates_empty_file(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path)
    ds = cat.allocate(_dd("J.WORK", DispStatus.NEW))
    assert ds.path.exists() and ds.path.read_bytes() == b""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_seed_then_shr_resolves_same_file(tmp_path):
    src = tmp_path / "seed.dat"
    src.write_bytes(b"DATA")
    cat = DatasetCatalog(workdir=tmp_path)
    cat.seed("J.IN", src)
    ds = cat.allocate(_dd("J.IN", DispStatus.SHR))
    assert ds.path == src


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_pass_retains_delete_removes(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path)
    keep = cat.allocate(_dd("J.A", DispStatus.NEW, DispNormal.PASS))
    cat.dispose(_dd("J.A", DispStatus.NEW, DispNormal.PASS))
    assert keep.path.exists()
    drop = cat.allocate(_dd("J.B", DispStatus.NEW, DispNormal.DELETE))
    cat.dispose(_dd("J.B", DispStatus.NEW, DispNormal.DELETE))
    assert not drop.path.exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_shr_on_unknown_dsn_raises(tmp_path):
    cat = DatasetCatalog(workdir=tmp_path)
    with pytest.raises(KeyError):
        cat.allocate(_dd("J.MISSING", DispStatus.SHR))

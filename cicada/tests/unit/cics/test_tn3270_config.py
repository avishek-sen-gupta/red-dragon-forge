import pytest

from cics.tn3270.config import ConfigError, load_config
from tests.covers import NotLanguageFeature, covers

_TOML = """
[region]
initial_transid = "CC00"
min_commarea_len = 400
programs = ["COACTVWC"]
[paths]
source_dir = "${APP}/cbl"
copybook_dirs = ["${APP}/cpy"]
bms_dir = "${APP}/bms"
data_dir = "${APP}/data/EBCDIC"
hlasm_export = "/bin/hlasm_export"
[transactions]
CC00 = "COSGN00C"
[datasets.usrsec]
file = "AWS.M2.CARDDEMO.USRSEC.PS"
record_length = 80
key_length = 8
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loads_paths_programs_and_datasets(tmp_path, monkeypatch):
    monkeypatch.setenv("APP", "/carddemo")
    path = tmp_path / "c.toml"
    path.write_text(_TOML)
    config = load_config(path)
    assert str(config.source_dir) == "/carddemo/cbl"
    assert config.programs == frozenset({"COSGN00C", "COACTVWC"})
    assert config.datasets["USRSEC"].key_length == 8


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unset_variable_is_loud(tmp_path, monkeypatch):
    monkeypatch.delenv("APP", raising=False)
    path = tmp_path / "c.toml"
    path.write_text(_TOML)
    with pytest.raises(ConfigError, match="APP"):
        load_config(path)

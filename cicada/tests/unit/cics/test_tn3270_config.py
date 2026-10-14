from pathlib import Path

import pytest

from cics.tn3270.config import (
    ConfigError,
    RegionConfig,
    load_config,
    resolve_program_source,
)
from tests.covers import NotLanguageFeature, covers

_TOML = """
[region]
initial_transid = "CC00"
min_commarea_len = 400
programs = ["COACTVWC"]
[paths]
source_dirs = ["${APP}/cbl"]
copybook_dirs = ["${APP}/cpy"]
bms_dirs = ["${APP}/bms"]
hlasm_export = "/bin/hlasm_export"
csd_files = ["${APP}/csd/CARDDEMO.CSD"]
[transactions]
CC00 = "COSGN00C"
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loads_paths_programs_csd_files_and_system(tmp_path, monkeypatch):
    monkeypatch.setenv("APP", "/carddemo")
    path = tmp_path / "c.toml"
    path.write_text(_TOML)
    config = load_config(path, tmp_path / "system")
    assert tuple(str(d) for d in config.source_dirs) == ("/carddemo/cbl",)
    assert config.programs == frozenset({"COSGN00C", "COACTVWC"})
    assert config.csd_files == (Path("/carddemo/csd/CARDDEMO.CSD"),)
    assert config.system == tmp_path / "system"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unset_variable_is_loud(tmp_path, monkeypatch):
    monkeypatch.delenv("APP", raising=False)
    path = tmp_path / "c.toml"
    path.write_text(_TOML)
    with pytest.raises(ConfigError, match="APP"):
        load_config(path, tmp_path / "system")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_default_copybook_exts_is_empty(tmp_path, monkeypatch):
    """Empty by default so the bridge's own -copybook-ext defaults apply --
    this is what keeps every existing CICS-only config untouched."""
    monkeypatch.setenv("APP", "/carddemo")
    path = tmp_path / "c.toml"
    path.write_text(_TOML)
    assert load_config(path, tmp_path / "system").copybook_exts == ()


def _config(*source_dirs: str) -> RegionConfig:
    return RegionConfig(
        source_dirs=tuple(Path(d) for d in source_dirs),
        copybook_dirs=(),
        bms_dirs=(),
        hlasm_export=None,  # type: ignore[arg-type]
        initial_transid="",
        min_commarea_len=0,
        transactions={},
        programs=frozenset(),
        system=Path("/system"),
        csd_files=(),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_program_source_first_hit_wins(tmp_path):
    """A program present in BOTH source_dirs resolves to the FIRST one --
    the ordering a two-source-tree region (e.g. CICS + Db2 CardDemo) relies
    on to prefer one tree's copy of a shared subprogram."""
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "COACTVWC.cbl").write_text("FIRST")
    (second / "COACTVWC.cbl").write_text("SECOND")
    config = _config(str(first), str(second))
    assert resolve_program_source(config, "COACTVWC").read_text() == "FIRST"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_program_source_falls_through_to_second_dir(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (second / "COTRTUPC.cbl").write_text("DB2 TIER")
    config = _config(str(first), str(second))
    assert resolve_program_source(config, "COTRTUPC").read_text() == "DB2 TIER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_program_source_missing_lists_every_dir_searched(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    config = _config(str(first), str(second))
    with pytest.raises(ConfigError, match="COTRTUPC") as excinfo:
        resolve_program_source(config, "COTRTUPC")
    assert str(first) in str(excinfo.value)
    assert str(second) in str(excinfo.value)

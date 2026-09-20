"""Task 10 (2026-09-19-carddemo-db2-tier): the composed CardDemo Db2 region.

Two things go live for the first time in cicada/config/carddemo-db2-tn3270.toml:
a ``bms_dirs`` with two entries (main tree: 17 maps, Db2 tree: 2 --
COTRTLI/COTRTUP, mapsets CTRTLIA/CTRTUPA) and a ``source_dirs`` spanning both
CardDemo trees. Neither multi-directory path has ever run before this
config, so this test verifies the BMS merge explicitly rather than trusting
build_region's plural plumbing (task 9) to have gotten it right -- a merge
that silently dropped the second directory would surface only much later
(task 11) as a blank TN3270 screen for CTTU/CTLI, far from its real cause.

Needs a live Db2 (db2_dsn fixture) since build_db2_region opens a real
connection to build the SQL spec, and the real bridge_jar/CardDemo checkout
to compile both trees' programs.
"""

from __future__ import annotations

from pathlib import Path

import ibm_db
import pytest

from cics.tn3270.config import load_config
from red_dragon_forge.carddemo_db2_region import build_db2_region

_REPO_ROOT = Path(__file__).parents[2]
_CONFIG = _REPO_ROOT / "cicada" / "config" / "carddemo-db2-tn3270.toml"


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_all_nineteen_bms_maps_reach_one_catalog(
    tmp_path, bridge_jar, db2_dsn, carddemo_home, monkeypatch
):
    """Verified by execution. The main tree's 17 .bms files and the Db2
    tree's 2 are disjoint mapsets, so a correct first-hit-wins merge across
    both bms_dirs must produce exactly 19 catalog entries; a merge that
    dropped the second bms_dirs entry would instead produce 17."""
    monkeypatch.setenv("FORGE_ROOT", str(_REPO_ROOT))
    monkeypatch.setenv("CARDDEMO_HOME", str(carddemo_home))
    config = load_config(_CONFIG)

    # Safe to close: the _reset_builtins_table autouse fixture (conftest.py)
    # restores RedDragon's process-wide Builtins.TABLE after this test, so a
    # stale hook left pointing at this now-closed connection can never reach
    # a later, unrelated test.
    region, conn = build_db2_region(config, bridge_jar, tmp_path, db2_dsn)
    try:
        assert len(region.catalog.maps) == 19
        mapsets = {mapset for (mapset, _label) in region.catalog.maps}
        assert {"COTRTLI", "COTRTUP"} <= mapsets
        labels = {label for (_mapset, label) in region.catalog.maps}
        assert {"CTRTLIA", "CTRTUPA"} <= labels
    finally:
        ibm_db.close(conn)  # type: ignore[reportArgumentType]

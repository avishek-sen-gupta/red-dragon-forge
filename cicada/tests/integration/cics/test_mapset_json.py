"""A mapset's hlasm_export JSON, kept as text, parses to the same catalog as reading its BMS source."""

import os
import shutil
from pathlib import Path

from cics.bms.catalog import catalog_from_json, load_catalog, mapset_json
from tests.covers import NotLanguageFeature, covers

_BMS = Path(__file__).parents[4] / "vendor" / "carddemo" / "app" / "bms"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_catalog_from_json_equals_load_catalog(tmp_path: Path) -> None:
    hlasm = os.environ["HLASM_EXPORT"]
    for name in ("COSGN00", "COMEN01"):
        shutil.copy(_BMS / f"{name}.bms", tmp_path / f"{name}.bms")

    from_json = catalog_from_json(
        [
            mapset_json(tmp_path / f"{name}.bms", hlasm)
            for name in ("COSGN00", "COMEN01")
        ]
    )

    assert (from_json, sorted(from_json.maps)) == (
        load_catalog(tmp_path, hlasm),
        [("COMEN01", "COMEN1A"), ("COSGN00", "COSGN0A")],
    )

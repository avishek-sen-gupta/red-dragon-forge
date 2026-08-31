"""Gated: a hyphenated DFHMDF field name survives the whole bms-tools pipeline.

A BMS field name follows the rules of the language the map is generated for, so
under LANG=COBOL a hyphen is legal. HLASM symbols are not: a hyphenated name
field is not an ordinary symbol, so the assembler classifies it as a macro label
(raw name-field text) instead.

hlasm_export used to export only ordinary-symbol labels, which made a hyphenated
field indistinguishable from a genuinely unnamed constant field -- the JSON simply
had no `label`, with no diagnostic. bms_copybook_gen skips unnamed fields, as it
must, so every symbolic name BMS derives from that field (the L/A/F/O/I suffix
family) vanished from the generated copybook. The only symptom was a COBOL
program failing to compile against a field its own map declares.

This test covers the chain end to end, because that is where the failure was
observed; the exporter's own unit test pins the label capture in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.covers import covers, NotLanguageFeature
from tests.integration.cics.bms_tools_helpers import (
    BMS_TOOLS_AVAILABLE,
    HLASM_EXPORT_BIN,
)

pytestmark = pytest.mark.skipif(
    not BMS_TOOLS_AVAILABLE, reason="needs a built hlasm_export"
)

# Fixed-format HLASM: name in column 1, operation in column 10.
_MAP_SRC = "\n".join(
    [
        "HYMAP    DFHMSD TYPE=MAP,MODE=INOUT,LANG=COBOL,CTRL=FREEKB",
        "HYM1     DFHMDI SIZE=(24,80)",
        "PLAIN    DFHMDF POS=(1,1),LENGTH=4,ATTRB=(ASKIP,NORM)",
        "HY-FLD   DFHMDF POS=(2,1),LENGTH=1,ATTRB=(ASKIP,NORM)",
        "         DFHMDF POS=(3,1),LENGTH=2,ATTRB=(ASKIP,NORM)",
        "         DFHMSD TYPE=FINAL",
        "         END",
        "",
    ]
)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_hyphenated_field_name_reaches_the_symbolic_copybook(tmp_path: Path) -> None:
    from cics.bms.generate import generate_symbolic_copybooks

    bms_dir = tmp_path / "bms"
    bms_dir.mkdir()
    (bms_dir / "HYMAP.bms").write_text(_MAP_SRC)
    out_dir = tmp_path / "sym"

    assert HLASM_EXPORT_BIN is not None
    generate_symbolic_copybooks(
        bms_dir=bms_dir, out_dir=out_dir, hlasm_export_bin=HLASM_EXPORT_BIN
    )

    text = (out_dir / "HYMAP.cpy").read_text().upper()
    assert "PLAINO" in text, "an ordinary-symbol field name still comes through"
    for suffix in ("L", "A", "F", "O", "I"):
        assert (
            f"HY-FLD{suffix}" in text
        ), f"HY-FLD{suffix} missing: the hyphenated field name was dropped"

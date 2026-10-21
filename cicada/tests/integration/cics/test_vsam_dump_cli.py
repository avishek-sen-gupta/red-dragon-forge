"""The VSAM dump command decodes a cataloged dataset through its copybook, and refuses a DSN the catalog lacks."""

from __future__ import annotations

from pathlib import Path

import pytest

from catnip.labels import KsdsLabel
from catnip.system_catalog import SystemCatalog
from cics.vsam.dump import run
from interpreter.encoding.ebcdic_table import EbcdicTable
from tests.covers import NotLanguageFeature, covers
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

_COPYBOOK = """\
       01  ITEM-REC.
           05  ITEM-ID    PIC 9(3).
           05  ITEM-NAME  PIC X(5).
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_the_dump_command_writes_each_record_as_json_and_refuses_an_uncataloged_dsn(
    tmp_path: Path, bridge_jar: str, capsys: pytest.CaptureFixture[str]
) -> None:
    copybook = tmp_path / "ITEMREC.cpy"
    copybook.write_text(_COPYBOOK)
    system = tmp_path / "system"
    SystemCatalog(system).create("T.ITEMS", KsdsLabel(8, 0, 3)).path.write_bytes(
        bytes(EbcdicTable.ascii_to_ebcdic(b"001APPLE002PEAR "))
    )
    common = ["--system", str(system), "--copybook", str(copybook), "--jar", bridge_jar]

    code = run(["--dsn", "T.ITEMS", *common])
    written = capsys.readouterr().out
    with pytest.raises(SystemExit) as refused:
        run(["--dsn", "T.NONE", *common])

    assert code == 0
    assert written == (
        '{"ITEM-ID": 1, "ITEM-NAME": "APPLE"}\n{"ITEM-ID": 2, "ITEM-NAME": "PEAR"}\n'
    )
    assert refused.value.code == 2
    assert capsys.readouterr().err.endswith(
        f"error: T.NONE is not cataloged in {system}\n"
    )

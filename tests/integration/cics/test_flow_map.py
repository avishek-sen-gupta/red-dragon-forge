"""Integration tests for extract_transaction_flow_map().

Synthetic COBOL + synthetic BmsMapSet fixtures. No CardDemo dependency.
Require PROLEAP_BRIDGE_JAR (via bridge_jar fixture from cobol_helpers).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bms_copybook_gen.models import BmsField, BmsMap, BmsMapSet
from cics.flow_map import extract_transaction_flow_map
from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from tests.covers import NotLanguageFeature, covers
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401 — pytest fixture

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"


@pytest.fixture
def cics_parser(bridge_jar):
    """ProLeapCobolParser configured with the CICS copybooks directory."""
    return ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[_CICS_COPYBOOKS]
    )


def _make_mapset(name: str, map_name: str, fields: list[BmsField]) -> BmsMapSet:
    bms_map = BmsMap(label=map_name, fields=fields)
    return BmsMapSet(
        label=name, lang="COBOL", mode="INOUT", tioapfx=False, maps=[bms_map]
    )


_CSD = "DEFINE TRANSACTION(ACCT) GROUP(DEMO) PROGRAM(ACCTPROG)\n"

_ACCTPROG = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 DFHCOMMAREA PIC X(100).
       PROCEDURE DIVISION.
           EXEC CICS RECEIVE MAP('ACCMAP') MAPSET('ACCSET') END-EXEC.
           EXEC CICS SEND MAP('ACCMAP') MAPSET('ACCSET') END-EXEC.
           EXEC CICS RETURN TRANSID('ACCT') END-EXEC.
           STOP RUN.
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_receive_and_return_in_flow(cics_parser):
    mapset = _make_mapset(
        "ACCSET",
        "ACCMAP",
        [
            BmsField(label="ACCTID", length=11, attrb=["UNPROT"]),
            BmsField(label="ACCTNAME", length=50, attrb=["PROT"]),
        ],
    )
    result = extract_transaction_flow_map(
        csd_source=_CSD,
        bms_mapsets={"ACCSET": mapset},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
    )
    assert len(result) == 1
    txn = result[0]
    assert txn["transid"] == "ACCT"
    assert txn["entry_program"] == "ACCTPROG"
    verbs = [e["verb"] for e in txn["flow"]]
    assert "RECEIVE_MAP" in verbs
    assert "SEND_MAP" in verbs
    assert "RETURN_TRANSID" in verbs


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_field_direction_enriched_in_send_map(cics_parser):
    mapset = _make_mapset(
        "ACCSET",
        "ACCMAP",
        [
            BmsField(label="ACCTID", length=11, attrb=["UNPROT"]),
            BmsField(label="ACCTNAME", length=50, attrb=["PROT"]),
        ],
    )
    result = extract_transaction_flow_map(
        csd_source=_CSD,
        bms_mapsets={"ACCSET": mapset},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
    )
    send_entries = [e for e in result[0]["flow"] if e["verb"] == "SEND_MAP"]
    assert len(send_entries) == 1
    fields = {f["name"]: f["direction"] for f in send_entries[0]["fields"]}
    assert fields["ACCTID"] == "input"
    assert fields["ACCTNAME"] == "output"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_xctl_target_populated(cics_parser):
    csd = "DEFINE TRANSACTION(MENU) GROUP(DEMO) PROGRAM(MENUPROG)\n"
    src = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MENUPROG.
       PROCEDURE DIVISION.
           EXEC CICS XCTL PROGRAM('NEXTPROG') END-EXEC.
           STOP RUN.
"""
    result = extract_transaction_flow_map(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"MENUPROG": src},
        parser=cics_parser,
    )
    xctl_entries = [e for e in result[0]["flow"] if e["verb"] == "XCTL"]
    assert len(xctl_entries) == 1
    assert xctl_entries[0]["xctl_target"] == "NEXTPROG"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_return_transid_populated(cics_parser):
    result = extract_transaction_flow_map(
        csd_source=_CSD,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
    )
    ret_entries = [e for e in result[0]["flow"] if e["verb"] == "RETURN_TRANSID"]
    assert len(ret_entries) == 1
    assert ret_entries[0].get("transid") == "ACCT"


_CSD_MULTI = (
    "DEFINE TRANSACTION(ACCT) GROUP(DEMO) PROGRAM(MAINPROG)\n"
    "DEFINE TRANSACTION(MENU) GROUP(DEMO) PROGRAM(MENUPROG)\n"
)

_MAINPROG = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPROG.
       PROCEDURE DIVISION.
           EXEC CICS SEND MAP('MAP1') MAPSET('SET1') END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""

_MENUPROG = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MENUPROG.
       PROCEDURE DIVISION.
           EXEC CICS SEND MAP('MAP2') MAPSET('SET2') END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_multiple_transactions_produce_separate_entries(cics_parser):
    result = extract_transaction_flow_map(
        csd_source=_CSD_MULTI,
        bms_mapsets={},
        cobol_sources={"MAINPROG": _MAINPROG, "MENUPROG": _MENUPROG},
        parser=cics_parser,
    )
    transids = {r["transid"] for r in result}
    assert "ACCT" in transids
    assert "MENU" in transids


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_no_mapset_yields_empty_fields(cics_parser):
    """SEND MAP referencing a mapset not in bms_mapsets → fields: []."""
    result = extract_transaction_flow_map(
        csd_source=_CSD,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
    )
    send_entries = [e for e in result[0]["flow"] if e["verb"] == "SEND_MAP"]
    for entry in send_entries:
        assert entry["fields"] == []

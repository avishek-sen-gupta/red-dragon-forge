"""Integration tests for extract_transaction_flow_graph().

Same synthetic COBOL + synthetic BmsMapSet fixtures as test_flow_map.py — the
two functions share compilation (_compile_all_programs), so this only
re-verifies the graph *shape* is right, not the CICS behaviour
test_flow_map.py already covers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bms_copybook_gen.models import BmsField, BmsMap, BmsMapSet
from cics.flow_map import extract_transaction_flow_graph
from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind
from tests.covers import NotLanguageFeature, covers
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401 — pytest fixture

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"


class _ListSink:
    def __init__(self) -> None:
        self.nodes: list[GraphNode] = []
        self.edges: list[GraphEdge] = []

    def add_node(self, node: GraphNode) -> None:
        self.nodes.append(node)

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)


@pytest.fixture
def cics_parser(bridge_jar):
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
def test_starts_edge_from_transaction_to_program(cics_parser):
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=_CSD,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
        sink=sink,
    )
    nodes, edges = sink.nodes, sink.edges
    starts = [e for e in edges if e.kind == EdgeKind.STARTS]
    assert len(starts) == 1
    assert starts[0].source == "ACCT"
    assert starts[0].target == "ACCTPROG"
    assert any(n.kind == NodeKind.TRANSACTION and n.id == "ACCT" for n in nodes)
    assert any(n.kind == NodeKind.PROGRAM and n.id == "ACCTPROG" for n in nodes)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_return_transid_edge_back_to_transaction(cics_parser):
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=_CSD,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
        sink=sink,
    )
    edges = sink.edges
    ret = [e for e in edges if e.kind == EdgeKind.RETURN_TRANSID]
    assert len(ret) == 1
    assert ret[0].source == "ACCTPROG"
    assert ret[0].target == "ACCT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_and_receive_map_edges_with_bms_map_node(cics_parser):
    mapset = _make_mapset(
        "ACCSET",
        "ACCMAP",
        [
            BmsField(label="ACCTID", length=11, attrb=["UNPROT"]),
            BmsField(label="ACCTNAME", length=50, attrb=["PROT"]),
        ],
    )
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=_CSD,
        bms_mapsets={"ACCSET": mapset},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
        sink=sink,
    )
    nodes, edges = sink.nodes, sink.edges
    sends = [e for e in edges if e.kind == EdgeKind.SENDS_MAP]
    receives = [e for e in edges if e.kind == EdgeKind.RECEIVES_MAP]
    assert len(sends) == 1 and len(receives) == 1
    assert sends[0].source == "ACCTPROG"
    assert sends[0].target == "ACCSET.ACCMAP"
    assert any(n.kind == NodeKind.BMS_MAP and n.id == "ACCSET.ACCMAP" for n in nodes)
    fields = {f["name"]: f["direction"] for f in sends[0].attrs["fields"]}
    assert fields["ACCTID"] == "input"
    assert fields["ACCTNAME"] == "output"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_xctl_edge_between_programs(cics_parser):
    csd = "DEFINE TRANSACTION(MENU) GROUP(DEMO) PROGRAM(MENUPROG)\n"
    src = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MENUPROG.
       PROCEDURE DIVISION.
           EXEC CICS XCTL PROGRAM('NEXTPROG') END-EXEC.
           STOP RUN.
"""
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"MENUPROG": src},
        parser=cics_parser,
        sink=sink,
    )
    nodes, edges = sink.nodes, sink.edges
    xctl = [e for e in edges if e.kind == EdgeKind.XCTL]
    assert len(xctl) == 1
    assert xctl[0].source == "MENUPROG"
    assert xctl[0].target == "NEXTPROG"
    assert any(n.kind == NodeKind.PROGRAM and n.id == "NEXTPROG" for n in nodes)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_edge_to_cics_file(cics_parser):
    csd = "DEFINE TRANSACTION(ACCT) GROUP(DEMO) PROGRAM(ACCTPROG)\n"
    src = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-KEY PIC X(10).
       01 WS-REC PIC X(80).
       PROCEDURE DIVISION.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": src},
        parser=cics_parser,
        sink=sink,
    )
    nodes, edges = sink.nodes, sink.edges
    reads = [e for e in edges if e.kind == EdgeKind.READS and e.source == "ACCTPROG"]
    assert len(reads) == 1
    assert reads[0].target == "ACCTFILE"
    assert reads[0].target_kind == NodeKind.CICS_FILE
    assert any(n.kind == NodeKind.CICS_FILE and n.id == "ACCTFILE" for n in nodes)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_write_edge_to_cics_file(cics_parser):
    csd = "DEFINE TRANSACTION(ACCT) GROUP(DEMO) PROGRAM(ACCTPROG)\n"
    src = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-KEY PIC X(10).
       01 WS-REC PIC X(80).
       PROCEDURE DIVISION.
           EXEC CICS WRITE FILE('CUSTDAT') FROM(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": src},
        parser=cics_parser,
        sink=sink,
    )
    edges = sink.edges
    writes = [e for e in edges if e.kind == EdgeKind.WRITES]
    assert len(writes) == 1
    assert writes[0].source == "ACCTPROG"
    assert writes[0].target == "CUSTDAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_rewrite_edge_is_updates(cics_parser):
    csd = "DEFINE TRANSACTION(ACCT) GROUP(DEMO) PROGRAM(ACCTPROG)\n"
    src = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-REC PIC X(80).
       PROCEDURE DIVISION.
           EXEC CICS REWRITE FILE('CUSTDAT') FROM(WS-REC) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": src},
        parser=cics_parser,
        sink=sink,
    )
    edges = sink.edges
    updates = [e for e in edges if e.kind == EdgeKind.UPDATES]
    assert len(updates) == 1
    assert updates[0].target == "CUSTDAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_edge_is_deletes(cics_parser):
    csd = "DEFINE TRANSACTION(ACCT) GROUP(DEMO) PROGRAM(ACCTPROG)\n"
    src = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-KEY PIC X(10).
       PROCEDURE DIVISION.
           EXEC CICS DELETE FILE('CARDDAT') RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": src},
        parser=cics_parser,
        sink=sink,
    )
    edges = sink.edges
    deletes = [e for e in edges if e.kind == EdgeKind.DELETES]
    assert len(deletes) == 1
    assert deletes[0].target == "CARDDAT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_browse_verbs_are_reads_and_endbr_is_ends_browse(cics_parser):
    csd = "DEFINE TRANSACTION(ACCT) GROUP(DEMO) PROGRAM(ACCTPROG)\n"
    src = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-KEY PIC X(10).
       01 WS-REC PIC X(80).
       PROCEDURE DIVISION.
           EXEC CICS STARTBR FILE('CARDAIX')
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS READNEXT FILE('CARDAIX') INTO(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS READPREV FILE('CARDAIX') INTO(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS ENDBR FILE('CARDAIX') END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": src},
        parser=cics_parser,
        sink=sink,
    )
    edges = sink.edges
    reads = [e for e in edges if e.kind == EdgeKind.READS and e.target == "CARDAIX"]
    ends = [e for e in edges if e.kind == EdgeKind.ENDS_BROWSE]
    assert len(reads) == 3  # STARTBR + READNEXT + READPREV
    assert len(ends) == 1
    assert ends[0].target == "CARDAIX"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_defines_dataset_edge_from_csd_file_dsname(cics_parser):
    csd = (
        "DEFINE TRANSACTION(ACCT) GROUP(DEMO) PROGRAM(ACCTPROG)\n"
        "DEFINE FILE(ACCTFILE) GROUP(DEMO)\n"
        "       DSNAME(AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS)\n"
    )
    src = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-KEY PIC X(10).
       01 WS-REC PIC X(80).
       PROCEDURE DIVISION.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": src},
        parser=cics_parser,
        sink=sink,
    )
    nodes, edges = sink.nodes, sink.edges
    defines_dataset = [e for e in edges if e.kind == EdgeKind.DEFINES_DATASET]
    assert len(defines_dataset) == 1
    assert defines_dataset[0].source == "ACCTFILE"
    assert defines_dataset[0].source_kind == NodeKind.CICS_FILE
    assert defines_dataset[0].target == "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"
    assert defines_dataset[0].target_kind == NodeKind.DATASET
    assert any(
        n.kind == NodeKind.DATASET and n.id == "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"
        for n in nodes
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_no_defines_dataset_edge_when_csd_has_no_file_definitions(cics_parser):
    """The synthetic-CSD tests above (no DEFINE FILE at all) must not error
    or produce a spurious edge — DEFINES_DATASET is additive, opt-in per CSD."""
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=_CSD,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
        sink=sink,
    )
    edges = sink.edges
    assert [e for e in edges if e.kind == EdgeKind.DEFINES_DATASET] == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_node_ids_are_uppercased(cics_parser):
    csd = "DEFINE TRANSACTION(acct) GROUP(DEMO) PROGRAM(ACCTPROG)\n"
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
        sink=sink,
    )
    nodes = sink.nodes
    assert any(n.kind == NodeKind.TRANSACTION and n.id == "ACCT" for n in nodes)

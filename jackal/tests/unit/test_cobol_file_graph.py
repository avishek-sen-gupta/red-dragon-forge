"""Unit tests for extract_cobol_file_graph()."""

import pytest

from tests.covers import NotLanguageFeature, covers
from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.project.graph_types import EdgeKind, NodeKind

from jackal.cobol_file_graph import extract_cobol_file_graph


@pytest.fixture
def parser(bridge_jar: str) -> ProLeapCobolParser:
    return ProLeapCobolParser(RealSubprocessRunner(), bridge_jar, copybook_dirs=[])


_COBOL = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILEDEMO.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO INDD
                  ORGANIZATION IS SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO OUTDD
                  ORGANIZATION IS SEQUENTIAL.
           SELECT MASTER-FILE ASSIGN TO MASTDD
                  ORGANIZATION IS INDEXED
                  ACCESS MODE IS RANDOM
                  RECORD KEY IS MASTER-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC   PIC X(5).
       FD  OUT-FILE.
       01  OUT-REC  PIC X(5).
       FD  MASTER-FILE.
       01  MASTER-REC.
           05 MASTER-KEY PIC X(5).
       WORKING-STORAGE SECTION.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE.
           OPEN OUTPUT OUT-FILE.
           OPEN I-O MASTER-FILE.
           CLOSE IN-FILE.
           CLOSE OUT-FILE.
           CLOSE MASTER-FILE.
           GOBACK.
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_program_node_created(parser: ProLeapCobolParser):
    nodes, _edges = extract_cobol_file_graph(parser.parse(_COBOL))
    assert any(n.kind == NodeKind.PROGRAM and n.id == "FILEDEMO" for n in nodes)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cobol_file_nodes_created_keyed_by_dd_name(parser: ProLeapCobolParser):
    nodes, _edges = extract_cobol_file_graph(parser.parse(_COBOL))
    file_ids = sorted(n.id for n in nodes if n.kind == NodeKind.COBOL_FILE)
    assert file_ids == ["INDD", "MASTDD", "OUTDD"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_open_input_becomes_reads(parser: ProLeapCobolParser):
    _nodes, edges = extract_cobol_file_graph(parser.parse(_COBOL))
    reads = [e for e in edges if e.kind == EdgeKind.READS]
    assert len(reads) == 1
    assert reads[0].source == "FILEDEMO"
    assert reads[0].target == "INDD"
    assert reads[0].target_kind == NodeKind.COBOL_FILE
    assert reads[0].attrs["select_name"] == "IN-FILE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_open_output_becomes_writes(parser: ProLeapCobolParser):
    _nodes, edges = extract_cobol_file_graph(parser.parse(_COBOL))
    writes = [e for e in edges if e.kind == EdgeKind.WRITES]
    assert len(writes) == 1
    assert writes[0].target == "OUTDD"
    assert "mode" not in writes[0].attrs


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_open_io_becomes_updates(parser: ProLeapCobolParser):
    _nodes, edges = extract_cobol_file_graph(parser.parse(_COBOL))
    updates = [e for e in edges if e.kind == EdgeKind.UPDATES]
    assert len(updates) == 1
    assert updates[0].target == "MASTDD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_program_with_no_file_control_yields_only_program_node(
    parser: ProLeapCobolParser,
):
    cobol = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOFILES.
       PROCEDURE DIVISION.
           GOBACK.
"""
    nodes, edges = extract_cobol_file_graph(parser.parse(cobol))
    assert [n.kind for n in nodes] == [NodeKind.PROGRAM]
    assert edges == []

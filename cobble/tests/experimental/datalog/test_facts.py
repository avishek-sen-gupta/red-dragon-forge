"""cobble-experimental-datalog-facts: a run directory written as Souffle facts and their schema."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from cobble.dataflow.fields.access_extent_line import AccessExtentLine
from cobble.dataflow.fields.access_line import AccessLine
from cobble.dataflow.fields.origin import Origin
from cobble.dataflow.fields.origin_kind import OriginKind
from cobble.dataflow.fixpoint.member_counts import MemberCounts
from cobble.dataflow.srccfg.bundle import Bundle, bundle_jsonl
from cobble.dataflow.srccfg.cfg import (
    Atom,
    Cfg,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    external_cfg,
)
from cobble.experimental.datalog.facts_cli import cli
from cobble.experimental.datalog.run_files import lines
from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_file import write_graph
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind as SlotKind

EMPTY_ARTIFACTS = (
    "knowledge-graph.jsonl",
    "extents.jsonl",
    "fixpoint/defs.jsonl",
    "fixpoint/sinks.jsonl",
    "fixpoint/aliases.jsonl",
    "fixpoint/jumps.jsonl",
    "combine/links.jsonl",
    "combine/targets.jsonl",
    "depgraph/edges.jsonl",
    "aggregates/unified.jsonl",
)

SCHEMA = (
    ".decl access(p:symbol, n:symbol, f:symbol, region:symbol, s:number, e:number)",
    ".decl cfg_call(caller:symbol, n:symbol, transfer:symbol, callee:symbol, entry:symbol, resolved:symbol, expr:symbol, certain:symbol)",
    ".decl cfg_call_reason(caller:symbol, n:symbol, why:symbol)",
    ".decl cfg_edge(p:symbol, a:symbol, b:symbol, kind:symbol)",
    ".decl cfg_entry(p:symbol, n:symbol)",
    ".decl cfg_file(p:symbol, n:symbol, f:symbol)",
    ".decl cfg_node(p:symbol, n:symbol, kind:symbol, para:symbol, line:number, transfer:symbol)",
    ".decl cfg_perform(p:symbol, s:symbol, resume:symbol, rend:symbol)",
    ".decl cfg_pred(p:symbol, n:symbol, l:symbol, op:symbol, r:symbol, text:symbol, resolved:symbol)",
    ".decl cfg_read(p:symbol, n:symbol, f:symbol)",
    ".decl cfg_target(p:symbol, n:symbol, t:symbol, resolved:symbol)",
    ".decl cfg_write(p:symbol, n:symbol, f:symbol)",
    ".decl cluster(c:symbol, member:symbol)",
    ".decl dep_edge(src:symbol, dst:symbol, p:symbol, seq:number, verb:symbol)",
    ".decl field_decl(fid:symbol, p:symbol, name:symbol, record:symbol, path:symbol, level:number, pic:symbol, usage:symbol, occurs:number, origin:symbol)",
    ".decl field_extent(fid:symbol, p:symbol, name:symbol, region:symbol, s:number, e:number)",
    ".decl field_redefines(fid:symbol, target:symbol)",
    ".decl field_value(fid:symbol, v:symbol)",
    ".decl fp_counts(p:symbol, settled:symbol, writes:number, covered:number, unhandled:number, unmodelled:number, dynamic:number, files:number)",
    ".decl fp_dead_end(p:symbol, why:symbol)",
    ".decl fp_def(p:symbol, n:symbol, ext:symbol, definer:symbol)",
    ".decl fp_def_reason(p:symbol, n:symbol, ext:symbol, why:symbol)",
    ".decl fp_def_value(p:symbol, n:symbol, ext:symbol, v:symbol)",
    ".decl fp_flow(src:symbol, dst:symbol, n:symbol, okind:symbol, oname:symbol, sext:symbol, dext:symbol)",
    ".decl fp_sink(p:symbol, n:symbol, skind:symbol, sname:symbol, ext:symbol)",
    ".decl fp_sink_definer(p:symbol, n:symbol, skind:symbol, sname:symbol, definer:symbol)",
    ".decl fp_unresolved(p:symbol, why:symbol)",
    ".decl fp_use(p:symbol, n:symbol, ext:symbol)",
    ".decl jump(p:symbol, n:symbol, kind:symbol, returns:symbol)",
    ".decl jump_target_reason(p:symbol, n:symbol, why:symbol)",
    ".decl jump_target_value(p:symbol, n:symbol, v:symbol)",
    ".decl kg_edge(src:symbol, src_kind:symbol, kind:symbol, dst:symbol, dst_kind:symbol)",
    ".decl kg_edge_attr(src:symbol, src_kind:symbol, kind:symbol, dst:symbol, dst_kind:symbol, key:symbol, value:symbol)",
    ".decl kg_node(id:symbol, kind:symbol)",
    ".decl link(caller:symbol, n:symbol, transfer:symbol, callee:symbol, cext:symbol, eext:symbol, returns:symbol, why:symbol)",
    ".decl origin(id:symbol, p:symbol, kind:symbol, name:symbol)",
    ".decl program(p:symbol, where:symbol)",
    ".decl slot(id:symbol, kind:symbol, p:symbol, record:symbol, field:symbol, off:number, size:number)",
    ".decl slot_align(src:symbol, dst:symbol, so:number, to:number, len:number)",
    ".decl slot_edge(src:symbol, dst:symbol, certainty:symbol, cross:symbol, barrier:symbol)",
    ".decl target(caller:symbol, n:symbol, kind:symbol, transfer:symbol, expr:symbol, cand:symbol)",
    ".decl target_reason(caller:symbol, n:symbol, why:symbol)",
    ".decl target_site(caller:symbol, n:symbol, kind:symbol, transfer:symbol, expr:symbol)",
)

FLOW_EDGE = (
    '{"type":"edge","source":"PROGA.FILE:CUSTFILE","source_kind":"FIELD",'
    '"target":"PROGA.WS-A","target_kind":"FIELD","kind":"FLOWS_TO","attrs":'
    '{"node":"MAIN/0","source_extent":"","target_extent":"WS-A@working_storage[0:4]",'
    '"origin":{"kind":"FILE","name":"CUSTFILE"},"landing":[],"rebuilt":false}}\n'
)


def _cfg() -> Cfg:
    return Cfg(
        program="PROGA",
        nodes=(
            Node(id="MAIN#label", kind=NodeKind.LABEL, paragraph="MAIN"),
            Node(
                id="MAIN/0",
                kind=NodeKind.ASSIGN,
                paragraph="MAIN",
                transfer="PERFORM",
                target="SUB",
            ),
            Node(
                id="MAIN/1",
                kind=NodeKind.TEST,
                paragraph="MAIN",
                atom=Atom(text="WS-A = 'X\tY'", left="WS-A", op="==", right="'X\tY'"),
            ),
        ),
        edges=(Edge(source="MAIN#label", target="MAIN/0", kind=EdgeKind.FLOW),),
        entry="MAIN#label",
    )


def _slots() -> FieldGraph:
    origin = GraphNode(
        id="PROGA:FILE:CUSTFILE",
        kind=SlotKind.ORIGIN,
        label="FILE:CUSTFILE",
        program="PROGA",
        origin=Origin(OriginKind.FILE, "CUSTFILE"),
    )
    field = GraphNode(
        id="PROGA:REC.WS-A",
        kind=SlotKind.FIELD,
        label="WS-A",
        program="PROGA",
        record="REC",
        field="WS-A",
        size=4,
    )
    copy = GraphNode(
        id="PROGA:REC.WS-B",
        kind=SlotKind.FIELD,
        label="WS-B",
        program="PROGA",
        record="REC",
        field="WS-B",
        size=4,
        offset=4,
    )
    return FieldGraph(
        nodes=(origin, field, copy),
        edges=(
            GraphEdge(
                source=origin.id,
                target=field.id,
                sites=1,
                clustered=False,
                cross_program=False,
                barrier="",
            ),
            GraphEdge(
                source=field.id,
                target=copy.id,
                sites=1,
                clustered=True,
                cross_program=False,
                barrier="",
                alignments=(ByteAlignment(source=0, target=0, length=4),),
                aligned=True,
            ),
        ),
    )


def _access() -> str:
    return AccessLine(
        kind="access",
        program="PROGA",
        site="PROGA/MAIN/1",
        node="MAIN/1",
        paragraph="MAIN",
        extent=AccessExtentLine(
            field="WS-A", region="working_storage", start=0, end=4, clamped=False
        ),
    ).model_dump_json()


def _written(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def run(tmp_path: Path) -> Path:
    root = tmp_path / "run"
    bundle = Bundle(seed="PROGA", cfgs=(_cfg(), external_cfg("PROGX")))
    _written(root / "srccfg" / "cfg-PROGA.jsonl", bundle_jsonl(bundle))
    _written(root / "accesses" / "PROGA.jsonl", f"{_access()}\n")
    _written(
        root / "fixpoint" / "members" / "PROGA" / "counts.json",
        MemberCounts(member="PROGA", program="PROGA", writes=2).model_dump_json(),
    )
    _written(root / "fixpoint" / "graph.jsonl", FLOW_EDGE)
    write_graph(root / "graph.jsonl", _slots())
    tuple(_written(root / name, "") for name in EMPTY_ARTIFACTS)
    return root


def _facts(out: Path, relation: str) -> list[list[str]]:
    text = (out / f"{relation}.facts").read_text(encoding="utf-8")
    return [line.split("\t") for line in text.splitlines()]


def test_a_run_becomes_one_facts_file_per_relation_from_its_typed_artifacts(
    run: Path, tmp_path: Path
) -> None:
    out = tmp_path / "facts"

    assert cli(("--run", str(run), "--out", str(out))) == 0

    assert _facts(out, "cfg_entry") == [
        ["PROGA", "MAIN#label"],
        ["PROGX", "%EXTERNAL#label"],
    ]
    assert _facts(out, "program") == [["PROGA", "internal"], ["PROGX", "external"]]
    assert _facts(out, "cfg_perform") == [["PROGA", "MAIN/0", "-", "-"]]
    assert _facts(out, "cfg_target") == [["PROGA", "MAIN/0", "SUB", "yes"]]
    assert _facts(out, "cfg_pred") == [
        ["PROGA", "MAIN/1", "WS-A", "==", "'X Y'", "WS-A = 'X Y'", "yes"]
    ]
    assert _facts(out, "access") == [
        ["PROGA", "MAIN/1", "WS-A", "working_storage", "0", "4"]
    ]
    assert _facts(out, "fp_flow") == [
        [
            "PROGA.FILE:CUSTFILE",
            "PROGA.WS-A",
            "MAIN/0",
            "FILE",
            "CUSTFILE",
            "",
            "WS-A@working_storage[0:4]",
        ]
    ]
    assert _facts(out, "fp_counts") == [["PROGA", "yes", "2", "0", "0", "0", "0", "0"]]
    assert _facts(out, "origin") == [
        ["PROGA:FILE:CUSTFILE", "PROGA", "FILE", "CUSTFILE"]
    ]
    assert _facts(out, "slot_edge") == [
        ["PROGA:FILE:CUSTFILE", "PROGA:REC.WS-A", "exact", "no", "none"],
        ["PROGA:REC.WS-A", "PROGA:REC.WS-B", "exact", "no", "none"],
    ]
    assert _facts(out, "slot_align") == [
        ["PROGA:REC.WS-A", "PROGA:REC.WS-B", "0", "0", "4"]
    ]
    assert _facts(out, "cluster") == []


def test_the_schema_declares_every_relation_a_facts_file_was_written_for(
    run: Path, tmp_path: Path
) -> None:
    out = tmp_path / "facts"

    cli(("--run", str(run), "--out", str(out)))
    schema = (out / "schema.dl").read_text(encoding="utf-8").splitlines()

    declared = sorted(line for line in schema if line.startswith(".decl "))
    inputs = sorted(line for line in schema if line.startswith(".input "))
    assert declared == sorted(SCHEMA)
    assert inputs == sorted(f".input {path.stem}" for path in out.glob("*.facts"))
    assert (schema[:2], schema[-1], len(schema)) == (
        ["#ifndef SCHEMA_DL", "#define SCHEMA_DL"],
        "#endif",
        2 * len(SCHEMA) + 3,
    )


def test_a_missing_artifact_fails_naming_it_and_writes_nothing(
    run: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (run / "aggregates" / "unified.jsonl").unlink()
    out = tmp_path / "facts"

    with caplog.at_level(logging.ERROR):
        assert cli(("--run", str(run), "--out", str(out))) == 2

    assert [record.getMessage() for record in caplog.records] == [
        f"datalog: !! missing {run / 'aggregates' / 'unified.jsonl'}"
    ]
    assert not out.exists()


def test_an_artifact_directory_with_no_files_fails_like_a_missing_one(
    run: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tuple(path.unlink() for path in (run / "accesses").glob("*.jsonl"))
    out = tmp_path / "facts"

    with caplog.at_level(logging.ERROR):
        assert cli(("--run", str(run), "--out", str(out))) == 2

    assert [record.getMessage() for record in caplog.records] == [
        f"datalog: !! missing {run / 'accesses' / '*.jsonl'}"
    ]
    assert not out.exists()


def test_a_line_holding_a_unicode_line_separator_reads_whole(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text('{"text": "A\u0085B\u2028C"}\n\n{"text": "D"}\n', encoding="utf-8")
    assert lines(path) == ('{"text": "A\u0085B\u2028C"}', '{"text": "D"}')


KNOWLEDGE_GRAPH = "".join(
    f"{line}\n"
    for line in (
        '{"type":"node","id":"ACCTFILE","kind":"JOB","file_path":"j.jcl","file_path_reason":null,"attrs":{}}',
        '{"type":"node","id":"ACCTFILE","kind":"COBOL_FILE","file_path":null,"file_path_reason":"not_file_based","attrs":{}}',
        '{"type":"edge","source":"ACCTFILE","source_kind":"JOB","target":"ACCTFILE.STEP05","target_kind":"STEP","kind":"JCL_STEP_RUNS","attrs":{}}',
        '{"type":"edge","source":"ACCTFILE.STEP05","source_kind":"STEP","target":"AWS.ACCT","target_kind":"DATASET","kind":"UPDATES","attrs":{"ddname":"ACCTFILE","disp":"OLD"}}',
        '{"type":"edge","source":"PROGA","source_kind":"PROGRAM","target":"ACCTFILE","target_kind":"COBOL_FILE","kind":"UPDATES","attrs":{"select_name":"ACCOUNT-FILE"}}',
        '{"type":"edge","source":"PROGA","source_kind":"PROGRAM","target":"MS.MAPA","target_kind":"BMS_MAP","kind":"RECEIVES_MAP","attrs":{"fields":[{"name":"F1","direction":"input"}]}}',
    )
)


def test_a_knowledge_graph_edge_keeps_its_endpoint_kinds_and_every_attribute(
    run: Path, tmp_path: Path
) -> None:
    """An id can name two nodes (a job and a DD both called ACCTFILE), so an edge
    names each end by id and kind. Its attributes carry the SELECT name a program
    opens a DD by, and the DD and DISP a step binds a dataset with; a nested
    attribute is one row per scalar, keyed by its path."""
    _written(run / "knowledge-graph.jsonl", KNOWLEDGE_GRAPH)
    out = tmp_path / "facts"

    assert cli(("--run", str(run), "--out", str(out))) == 0

    assert _facts(out, "kg_node") == [
        ["ACCTFILE", "COBOL_FILE"],
        ["ACCTFILE", "JOB"],
    ]
    assert _facts(out, "kg_edge") == [
        ["ACCTFILE", "JOB", "JCL_STEP_RUNS", "ACCTFILE.STEP05", "STEP"],
        ["ACCTFILE.STEP05", "STEP", "UPDATES", "AWS.ACCT", "DATASET"],
        ["PROGA", "PROGRAM", "RECEIVES_MAP", "MS.MAPA", "BMS_MAP"],
        ["PROGA", "PROGRAM", "UPDATES", "ACCTFILE", "COBOL_FILE"],
    ]
    assert _facts(out, "kg_edge_attr") == [
        [
            "ACCTFILE.STEP05",
            "STEP",
            "UPDATES",
            "AWS.ACCT",
            "DATASET",
            "ddname",
            "ACCTFILE",
        ],
        ["ACCTFILE.STEP05", "STEP", "UPDATES", "AWS.ACCT", "DATASET", "disp", "OLD"],
        [
            "PROGA",
            "PROGRAM",
            "RECEIVES_MAP",
            "MS.MAPA",
            "BMS_MAP",
            "fields.0.direction",
            "input",
        ],
        [
            "PROGA",
            "PROGRAM",
            "RECEIVES_MAP",
            "MS.MAPA",
            "BMS_MAP",
            "fields.0.name",
            "F1",
        ],
        [
            "PROGA",
            "PROGRAM",
            "UPDATES",
            "ACCTFILE",
            "COBOL_FILE",
            "select_name",
            "ACCOUNT-FILE",
        ],
    ]

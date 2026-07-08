"""Unit tests for extract_jcl_graph()."""

from pathlib import Path

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.jcl_graph import extract_jcl_graph
from interpreter.project.graph_types import EdgeKind, NodeKind


@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """extract_jcl_graph shells to the JCL bridge via parse_jcl; ensure JCL_BRIDGE_JAR is set."""


_JCL = """//PIPE JOB 'demo'
//STEP1 EXEC PGM=UPCASE
//INDD DD DSN=J.IN,DISP=SHR
//WORKDD DD DSN=J.WORK,DISP=(NEW,PASS,DELETE)
//STEP2 EXEC PGM=STARRER
//WORKDD DD DSN=J.WORK,DISP=SHR
//OUTDD DD DSN=J.OUT,DISP=(NEW,CATLG,DELETE)
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_and_step_nodes_created():
    nodes, _edges = extract_jcl_graph(_JCL)
    assert any(n.kind == NodeKind.JOB and n.id == "PIPE" for n in nodes)
    assert any(n.kind == NodeKind.STEP and n.id == "PIPE.STEP1" for n in nodes)
    assert any(n.kind == NodeKind.STEP and n.id == "PIPE.STEP2" for n in nodes)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_step_runs_edges_reflect_step_order():
    _nodes, edges = extract_jcl_graph(_JCL)
    job_to_step = [
        e for e in edges if e.kind == EdgeKind.JCL_STEP_RUNS and e.source == "PIPE"
    ]
    assert [e.target for e in job_to_step] == ["PIPE.STEP1", "PIPE.STEP2"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_runs_program_edge():
    _nodes, edges = extract_jcl_graph(_JCL)
    step_to_prog = {
        e.source: e.target
        for e in edges
        if e.kind == EdgeKind.JCL_STEP_RUNS and e.source.startswith("PIPE.")
    }
    assert step_to_prog["PIPE.STEP1"] == "UPCASE"
    assert step_to_prog["PIPE.STEP2"] == "STARRER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_disp_shr_becomes_reads():
    _nodes, edges = extract_jcl_graph(_JCL)
    reads = [e for e in edges if e.kind == EdgeKind.READS and e.source == "PIPE.STEP1"]
    assert len(reads) == 1
    assert reads[0].target == "J.IN"
    assert reads[0].attrs["disp"] == "SHR"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_disp_new_becomes_writes():
    _nodes, edges = extract_jcl_graph(_JCL)
    writes = [
        e for e in edges if e.kind == EdgeKind.WRITES and e.source == "PIPE.STEP1"
    ]
    assert len(writes) == 1
    assert writes[0].target == "J.WORK"
    assert writes[0].attrs["disp"] == "NEW"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dataset_node_shared_across_steps():
    nodes, edges = extract_jcl_graph(_JCL)
    work_nodes = [n for n in nodes if n.kind == NodeKind.DATASET and n.id == "J.WORK"]
    assert len(work_nodes) == 1  # one node, even though both steps reference it
    step2_reads = [
        e for e in edges if e.kind == EdgeKind.READS and e.source == "PIPE.STEP2"
    ]
    assert step2_reads[0].target == "J.WORK"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_sysout_dd_is_not_a_dataset_node():
    jcl = """//SOUT JOB 'demo'
//STEP1 EXEC PGM=PRINTER
//SYSOUT DD SYSOUT=*
"""
    nodes, edges = extract_jcl_graph(jcl)
    assert not any(n.kind == NodeKind.DATASET for n in nodes)
    assert not any(
        e.kind in (EdgeKind.READS, EdgeKind.WRITES, EdgeKind.UPDATES) for e in edges
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_dataset_is_not_a_dataset_node():
    jcl = """//TMPJ JOB 'demo'
//STEP1 EXEC PGM=SORTER
//WORKDD DD DSN=&&TEMP,DISP=(NEW,PASS,DELETE)
"""
    nodes, edges = extract_jcl_graph(jcl)
    assert not any(n.kind == NodeKind.DATASET for n in nodes)
    assert not any(
        e.kind in (EdgeKind.READS, EdgeKind.WRITES, EdgeKind.UPDATES) for e in edges
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_instream_dd_becomes_instream_data_node_not_dataset():
    jcl = """//DELJ JOB 'demo'
//STEP1 EXEC PGM=IDCAMS
//SYSIN DD *
   DELETE A.B CLUSTER
/*
"""
    nodes, edges = extract_jcl_graph(jcl)
    assert not any(n.kind == NodeKind.DATASET for n in nodes)
    instream_nodes = [n for n in nodes if n.kind == NodeKind.INSTREAM_DATA]
    assert len(instream_nodes) == 1
    assert instream_nodes[0].id == "DELJ.STEP1.SYSIN"

    reads = [e for e in edges if e.kind == EdgeKind.READS and e.source == "DELJ.STEP1"]
    assert len(reads) == 1
    assert reads[0].target == "DELJ.STEP1.SYSIN"
    assert reads[0].target_kind == NodeKind.INSTREAM_DATA


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_instream_dd_reads_edge_carries_raw_text():
    jcl = """//DELJ JOB 'demo'
//STEP1 EXEC PGM=IDCAMS
//SYSIN DD *
   DELETE A.B CLUSTER
   IF MAXCC LE 08 THEN SET MAXCC = 0
/*
"""
    _nodes, edges = extract_jcl_graph(jcl)
    reads = [e for e in edges if e.kind == EdgeKind.READS and e.source == "DELJ.STEP1"]
    assert len(reads) == 1
    assert reads[0].attrs["text"] == (
        "   DELETE A.B CLUSTER\n   IF MAXCC LE 08 THEN SET MAXCC = 0"
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_two_instream_dds_in_different_steps_get_distinct_nodes():
    jcl = """//DELJ JOB 'demo'
//STEP1 EXEC PGM=IDCAMS
//SYSIN DD *
   DELETE A.B CLUSTER
/*
//STEP2 EXEC PGM=IDCAMS
//SYSIN DD *
   DEFINE CLUSTER (NAME(A.B))
/*
"""
    nodes, _edges = extract_jcl_graph(jcl)
    instream_ids = sorted(n.id for n in nodes if n.kind == NodeKind.INSTREAM_DATA)
    assert instream_ids == ["DELJ.STEP1.SYSIN", "DELJ.STEP2.SYSIN"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dummy_dd_is_not_a_dataset_or_instream_node():
    jcl = """//DUMJ JOB 'demo'
//STEP1 EXEC PGM=IEBGENER
//SYSIN DD DUMMY
"""
    nodes, edges = extract_jcl_graph(jcl)
    assert not any(n.kind == NodeKind.DATASET for n in nodes)
    assert not any(n.kind == NodeKind.INSTREAM_DATA for n in nodes)
    assert not any(
        e.kind in (EdgeKind.READS, EdgeKind.WRITES, EdgeKind.UPDATES) for e in edges
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_proc_call_expands_with_qualified_id_and_proc_attr(tmp_path: Path):
    (tmp_path / "REPROC.prc").write_text(
        "//REPROC PROC\n//PRC001 EXEC PGM=IDCAMS\n//SYSIN DD DISP=SHR,DSN=NULLFILE\n// PEND\n"
    )
    jcl = "//TRANREPT JOB 'demo'\n//STEP05R EXEC PROC=REPROC\n"
    nodes, edges = extract_jcl_graph(jcl, proclib_dirs=[tmp_path])

    step_nodes = [n for n in nodes if n.kind == NodeKind.STEP]
    assert any(n.id == "TRANREPT.STEP05R.PRC001" for n in step_nodes)
    assert not any(n.id == "TRANREPT.STEP05R" for n in step_nodes)

    job_to_step = [
        e for e in edges if e.kind == EdgeKind.JCL_STEP_RUNS and e.source == "TRANREPT"
    ]
    assert job_to_step[0].target == "TRANREPT.STEP05R.PRC001"
    assert job_to_step[0].attrs == {"proc": "REPROC"}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extract_jcl_graph_without_proclib_dirs_is_unchanged():
    # Default proclib_dirs=() must produce byte-identical behavior to every
    # existing call site that predates this feature.
    nodes, edges = extract_jcl_graph(_JCL)
    assert [s for s in nodes if s.kind == NodeKind.STEP]
    step_to_prog = {
        e.source: e.target
        for e in edges
        if e.kind == EdgeKind.JCL_STEP_RUNS and e.source.startswith("PIPE.")
    }
    assert step_to_prog["PIPE.STEP1"] == "UPCASE"

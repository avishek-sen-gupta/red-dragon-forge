"""The JCL step-sequencing graph: what a job contributes, and what it skips.

Driven through ``jcl_graph_from_job`` rather than ``extract_jcl_graph`` so the
model is built here instead of parsed -- these are statements about the graph,
not about the bridge, and the bridge costs a JVM per call.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobble.corpus_index import CorpusIndex
from cobble.jcl.jcl_graph import jcl_graph_from_job
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge, NodeKind
from jackal.expansion import ProcLibrary, ProcNotFound
from jackal.model import (
    DD,
    DdName,
    DirectDSN,
    Disp,
    DispAbnormal,
    DispNormal,
    DispStatus,
    InStreamDSN,
    Job,
    ProcCall,
    ProcDef,
    ProcRef,
    ProgramRef,
    ProgramStep,
    StepName,
    TempRef,
)
from jackal.value_parts import Symbol, SymbolName, literal

_SHR = Disp(DispStatus.SHR, DispNormal.KEEP, DispAbnormal.KEEP)
_NEW = Disp(DispStatus.NEW, DispNormal.PASS, DispAbnormal.DELETE)


@dataclass(frozen=True)
class _Library(ProcLibrary):
    procs: tuple[ProcDef, ...] = ()

    def find(self, proc: ProcRef) -> ProcDef | ProcNotFound:
        found = tuple(p for p in self.procs if p.name == proc.name)
        return found[0] if found else ProcNotFound()


def _program(label: str, pgm: str, dds: tuple[DD, ...] = ()) -> ProgramStep:
    return ProgramStep(StepName(label), ProgramRef(pgm), dds)


def _graph(job: Job, library: _Library = _Library()):
    return jcl_graph_from_job(job, CorpusIndex(), library)


def _job(*dds: DD) -> Job:
    return Job("JOBONE", (_program("STEPONE", "PROGONE", dds),))


def _dataset_ids(job: Job) -> tuple[str, ...]:
    nodes, _edges = _graph(job)
    return tuple(node.id for node in nodes if node.kind is NodeKind.DATASET)


def test_a_dsn_is_a_dataset_node_the_step_reads() -> None:
    job = _job(
        DD(ddname=DdName("INPUT"), dsn=DirectDSN(literal("TEST.DATA")), disp=_SHR)
    )
    nodes, edges = _graph(job)

    dataset = next(node for node in nodes if node.kind is NodeKind.DATASET)
    reads = next(edge for edge in edges if edge.kind is EdgeKind.READS)
    assert dataset.id == "TEST.DATA"
    assert (reads.target, reads.attrs["ddname"]) == ("TEST.DATA", "INPUT")


def test_disposition_decides_the_edge_kind() -> None:
    job = _job(
        DD(ddname=DdName("OUTPUT"), dsn=DirectDSN(literal("TEST.DATA")), disp=_NEW)
    )
    _nodes, edges = _graph(job)

    assert [edge.kind for edge in edges if edge.kind is not EdgeKind.JCL_STEP_RUNS] == [
        EdgeKind.WRITES
    ]


def test_a_double_ampersand_temp_is_not_a_dataset() -> None:
    """&&NAME lives and dies inside one job, so it is no cross-job identity."""
    assert (
        _dataset_ids(_job(DD(ddname=DdName("WORK"), dsn=TempRef("WORKIN"), disp=_NEW)))
        == ()
    )


def test_a_single_ampersand_temp_is_not_a_dataset_either() -> None:
    """z/OS reads DSN=&NAME as DSN=&&NAME when NAME is no defined symbol, and
    real JCL writes both spellings for the same dataset in adjacent steps.

    Reading the surviving symbol as a name to resolve cost the whole member:
    dsn_key raised, the raise escaped the pass, and a job lost every step it
    had over one temporary work file.
    """
    job = _job(
        DD(
            ddname=DdName("WORK"),
            dsn=DirectDSN((Symbol(SymbolName("WORKIN")),)),
            disp=_NEW,
        )
    )
    nodes, edges = _graph(job)

    assert _dataset_ids(job) == ()
    assert [node.kind for node in nodes] == [
        NodeKind.JOB,
        NodeKind.STEP,
        NodeKind.PROGRAM,
    ]
    assert [edge.kind for edge in edges] == [
        EdgeKind.JCL_STEP_RUNS,
        EdgeKind.JCL_STEP_RUNS,
    ]


def test_a_symbol_too_long_to_be_a_temp_name_is_still_a_failure() -> None:
    """A temporary dataset name is at most 8 characters. A longer surviving
    symbol is something else -- an unbound PROC parameter, most likely -- and
    guessing it is a temp file would invent a fact. Better to say so.
    """
    job = _job(
        DD(
            ddname=DdName("WORK"),
            dsn=DirectDSN((Symbol(SymbolName("WORKINPUTFILE")),)),
            disp=_NEW,
        )
    )
    try:
        _graph(job)
    except ValueError as exc:
        assert "WORKINPUTFILE" in str(exc)
    else:
        raise AssertionError("expected the unresolved symbol to be reported")


def test_a_partly_literal_dsn_with_a_symbol_is_still_a_failure() -> None:
    """&HLQ..DATA is not a temporary dataset name whatever &HLQ is worth."""
    job = _job(
        DD(
            ddname=DdName("WORK"),
            dsn=DirectDSN((Symbol(SymbolName("HLQ")), *literal(".DATA"))),
            disp=_NEW,
        )
    )
    try:
        _graph(job)
    except ValueError as exc:
        assert "HLQ" in str(exc)
    else:
        raise AssertionError("expected the unresolved symbol to be reported")


def _tso_step(*dds: DD, monitor: str = "IKJEFT01") -> Job:
    return Job("JOBONE", (_program("STEPONE", monitor, dds),))


def _systsin(*lines: str, ddname: str = "SYSTSIN") -> DD:
    return DD(
        ddname=DdName(ddname), dsn=InStreamDSN(), disp=_SHR, in_stream=tuple(lines)
    )


def _tso_edges(job: Job) -> tuple[GraphEdge, ...]:
    _nodes, edges = _graph(job)
    return tuple(edge for edge in edges if edge.kind is EdgeKind.TSO_RUNS_PROGRAM)


def test_a_tso_monitor_step_runs_the_program_its_systsin_names() -> None:
    """The step's EXEC PGM= names the monitor, so this is the only place the
    program doing the work is named at all."""
    job = _tso_step(
        _systsin(
            "  DSN SYSTEM(DSN)",
            "  RUN PROGRAM(PAYROLL) PLAN(PAYPLAN) -",
            "      LIB('BATCH.LOADLIB')",
            "  END",
        )
    )
    nodes, _edges = _graph(job)
    (edge,) = _tso_edges(job)

    assert (edge.source, edge.target) == ("JOBONE.STEPONE", "PAYROLL")
    assert (edge.source_kind, edge.target_kind) == (NodeKind.STEP, NodeKind.PROGRAM)
    assert edge.attrs == {
        "monitor": "IKJEFT01",
        "ddname": "SYSTSIN",
        "plan": "PAYPLAN",
    }
    assert "PAYROLL" in [node.id for node in nodes if node.kind is NodeKind.PROGRAM]


def test_the_monitor_edge_survives_alongside_the_program_edge() -> None:
    """Both facts are true: the step runs IKJEFT01, and IKJEFT01 runs PAYROLL.
    Replacing the first with the second would claim the JCL names a program it
    never names."""
    job = _tso_step(_systsin("  RUN PROGRAM(PAYROLL) PLAN(PAYPLAN)"))
    _nodes, edges = _graph(job)

    assert [
        (edge.kind, edge.target)
        for edge in edges
        if edge.target_kind is NodeKind.PROGRAM
    ] == [
        (EdgeKind.JCL_STEP_RUNS, "IKJEFT01"),
        (EdgeKind.TSO_RUNS_PROGRAM, "PAYROLL"),
    ]


def test_a_plan_less_run_carries_no_plan_attribute() -> None:
    """Absent, not unknown -- so the attribute is omitted rather than empty."""
    (edge,) = _tso_edges(_tso_step(_systsin("  RUN PROGRAM(PAYROLL)")))
    assert edge.attrs == {"monitor": "IKJEFT01", "ddname": "SYSTSIN"}


def test_every_program_one_systsin_runs_gets_its_own_edge() -> None:
    job = _tso_step(
        _systsin(
            "  DSN SYSTEM(DSN)",
            "  RUN PROGRAM(EXTRACT) PLAN(EXTPLAN)",
            "  RUN PROGRAM(REPORT) PLAN(RPTPLAN)",
            "  END",
        )
    )
    assert [edge.target for edge in _tso_edges(job)] == ["EXTRACT", "REPORT"]


def test_a_program_run_twice_is_one_edge() -> None:
    """One relationship between that step and that program. The second
    sighting carries nothing the first does not, so it is not a second edge --
    the same rule _one_per_identity applies to nodes."""
    job = _tso_step(
        _systsin(
            "  RUN PROGRAM(PAYROLL) PLAN(PLANA)",
            "  RUN PROGRAM(PAYROLL) PLAN(PLANB)",
        )
    )
    edges = _tso_edges(job)

    assert [edge.target for edge in edges] == ["PAYROLL"]
    assert edges[0].attrs["plan"] == "PLANA"


def test_each_monitor_entry_point_is_read_the_same_way() -> None:
    for monitor in ("IKJEFT01", "IKJEFT1A", "IKJEFT1B"):
        job = _tso_step(_systsin("  RUN PROGRAM(PAYROLL)"), monitor=monitor)
        (edge,) = _tso_edges(job)
        assert (edge.target, edge.attrs["monitor"]) == ("PAYROLL", monitor)


def test_a_run_in_a_dd_the_monitor_does_not_read_is_not_a_run() -> None:
    """SYSTSIN is the monitor's input. A SYSIN alongside it belongs to the
    program the monitor runs, so a RUN subcommand there is that program's data
    and nothing executes it."""
    job = _tso_step(_systsin("  RUN PROGRAM(PAYROLL)", ddname="SYSIN"))
    assert _tso_edges(job) == ()


def test_a_systsin_under_an_ordinary_program_is_not_read() -> None:
    """Only the monitor reads SYSTSIN as commands. Under any other program the
    in-stream content is data, and stays the opaque text on the READS edge."""
    job = _tso_step(_systsin("  RUN PROGRAM(PAYROLL)"), monitor="IEFBR14")
    assert _tso_edges(job) == ()


def test_the_instream_node_and_its_text_survive_the_reading() -> None:
    """Reading the commands adds an edge; it does not consume the DD. The
    verbatim text stays on the READS edge for anything that wants the rest of
    the stream."""
    job = _tso_step(_systsin("  DSN SYSTEM(DSN)", "  RUN PROGRAM(PAYROLL)"))
    nodes, edges = _graph(job)

    assert [node.id for node in nodes if node.kind is NodeKind.INSTREAM_DATA] == [
        "JOBONE.STEPONE.SYSTSIN"
    ]
    reads = next(edge for edge in edges if edge.kind is EdgeKind.READS)
    assert reads.attrs["text"] == "  DSN SYSTEM(DSN)\n  RUN PROGRAM(PAYROLL)"


def test_a_monitor_step_running_nothing_adds_no_edge() -> None:
    """Most SYSTSIN streams are not DSN at all."""
    job = _tso_step(_systsin("  DELETE 'BATCH.WORK.FILE'"))
    assert _tso_edges(job) == ()


def _proc_edges(job: Job, library: _Library) -> dict[str, str]:
    _nodes, edges = _graph(job, library)
    return {
        edge.target: str(edge.attrs.get("proc", ""))
        for edge in edges
        if edge.kind is EdgeKind.JCL_STEP_RUNS and edge.target_kind is NodeKind.STEP
    }


def test_each_expanded_step_credits_the_proc_its_call_ran() -> None:
    """A step written in the job carries no PROC; an expanded one names the
    PROC its call ran -- even when two calls share a label."""
    library = _Library(
        (
            ProcDef("PROCONE", (), (_program("INNERONE", "PROGONE"),)),
            ProcDef("PROCTWO", (), (_program("INNERTWO", "PROGTWO"),)),
        )
    )
    job = Job(
        "JOBONE",
        (
            ProcCall(StepName("RUN"), ProcRef("PROCONE")),
            _program("STEPTWO", "PROGTWO"),
            ProcCall(StepName("RUN"), ProcRef("PROCTWO")),
        ),
    )
    assert _proc_edges(job, library) == {
        "JOBONE.RUN.INNERONE": "PROCONE",
        "JOBONE.STEPTWO": "",
        "JOBONE.RUN.INNERTWO": "PROCTWO",
    }


def test_a_call_to_a_proc_in_no_library_is_a_step_running_the_proc_name() -> None:
    job = Job("JOBONE", (ProcCall(StepName("STEPONE"), ProcRef("NOSUCH")),))
    _nodes, edges = _graph(job)
    assert [
        (edge.source, edge.target)
        for edge in edges
        if edge.kind is EdgeKind.JCL_STEP_RUNS
    ] == [("JOBONE", "JOBONE.STEPONE"), ("JOBONE.STEPONE", "NOSUCH")]

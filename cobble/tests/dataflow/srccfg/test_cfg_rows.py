"""Each src-cfg row type, written as one JSON line and read back as the value it holds."""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.srccfg.bundle import load_bundle
from cobble.dataflow.srccfg.cfg import (
    Atom,
    Cfg,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    SourceSpan,
)
from cobble.dataflow.srccfg.link import BundleCall
from cobble.dataflow.srccfg.rows.call_row import CfgCallRow
from cobble.dataflow.srccfg.rows.cfg_row import (
    CFG_ROWS,
    call_row,
    edge_row,
    node_row,
    outcome_row,
    program_row,
    refused_row,
    summary_row,
    unresolved_row,
)
from cobble.dataflow.srccfg.rows.edge_row import CfgEdgeRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.program_row import CfgProgramRow
from cobble.dataflow.srccfg.argument_mode import ArgumentMode
from cobble.dataflow.srccfg.rows.reach_outcome import ReachOutcome
from cobble.dataflow.srccfg.using_argument import UsingArgument
from cobol_asg.ref_mod import RefModLiteral, RefModOperand

NODE = Node(
    id="MAIN/3",
    kind=NodeKind.CALL,
    paragraph="MAIN",
    atom=Atom(text="WS-NAME = 'ÄÖÜ £'", left="WS-NAME", op="==", right="'ÄÖÜ £'"),
    writes=("WS-RET",),
    reads=("WS-PGM", "WS-ARG"),
    transfer="CALL",
    target="WS-PGM",
    target_resolved=False,
    target_operand=RefModOperand(
        name="WS-PGM",
        ref_mod_start=RefModLiteral("1"),
        ref_mod_length=RefModLiteral("8"),
    ),
    transfer_operand="WS-PGM",
    using=(UsingArgument("WS-ARG", ArgumentMode.CONTENT),),
    span=SourceSpan(
        line_start=12, col_start=8, line_end=12, col_end=30, source_file="PROGA.cbl"
    ),
    resume="MAIN/4",
    range_end="SUB#end",
)


def test_a_node_row_holds_every_field_of_its_node_and_reads_back_equal() -> None:
    """Every Node field crosses the line: a field the row dropped would be a fact a
    reader of the file silently lacks."""
    line = node_row("PROGA", NODE).model_dump_json()

    read = CFG_ROWS.validate_json(line)

    assert isinstance(read, CfgNodeRow)
    assert (read.program, read.to_node()) == ("PROGA", NODE)


@pytest.mark.parametrize("kind", tuple(EdgeKind))
def test_an_edge_row_reads_back_as_its_edge_for_every_kind(kind: EdgeKind) -> None:
    edge = Edge(source="MAIN/0", target="MAIN/1", kind=kind)

    read = CFG_ROWS.validate_json(edge_row("PROGA", edge).model_dump_json())

    assert isinstance(read, CfgEdgeRow)
    assert (read.program, read.to_edge()) == ("PROGA", edge)


def test_a_program_row_and_a_call_row_read_back_as_what_they_hold() -> None:
    call = BundleCall(
        caller="PROGA",
        node="MAIN/3",
        transfer="CICS_XCTL",
        program="PROGB",
        entry="MAIN#label",
        resolved=False,
        commarea="WS-COMM",
        expression="WS-PGM",
        reasons=("from-callee", "inbound-linkage"),
        certain=False,
    )

    program = CFG_ROWS.validate_json(
        program_row("PROGA", "MAIN#label").model_dump_json()
    )
    called = CFG_ROWS.validate_json(call_row(call).model_dump_json())

    assert isinstance(program, CfgProgramRow)
    assert (program.program, program.entry, program.external) == (
        "PROGA",
        "MAIN#label",
        False,
    )
    assert isinstance(called, CfgCallRow)
    assert called.to_call() == call


def test_a_row_with_an_unknown_type_or_a_stray_field_is_refused() -> None:
    """The union is closed: a misspelt type or a field no row declares is an error,
    never a row quietly read as something else."""
    with pytest.raises(ValueError, match="program"):
        CFG_ROWS.validate_json('{"type": "programme", "program": "PROGA"}')
    with pytest.raises(ValueError, match="extra"):
        CFG_ROWS.validate_json('{"type": "program", "program": "PROGA", "seed": true}')


def test_reach_rows_read_back_and_a_cfg_reader_sees_only_the_graph(
    tmp_path: Path,
) -> None:
    """The reach rows travel in the same file as the reached subgraph: each reads
    back as itself, and load_bundle -- so every renderer -- builds the graph and
    skips them."""
    edge = Edge(source="MAIN/0", target="MAIN#end", kind=EdgeKind.FLOW)
    end = Node(id="MAIN#end", kind=NodeKind.NOP, paragraph="MAIN")
    reach = (
        outcome_row(ReachOutcome.XCTL, "MAIN/0"),
        unresolved_row("MAIN/1"),
        refused_row("MAIN/2"),
        summary_row("MAIN/0", 3),
    )
    rows = (
        program_row("PROGA", ""),
        node_row("PROGA", NODE),
        node_row("PROGA", end),
        edge_row("PROGA", edge),
        *reach,
    )
    path = tmp_path / "reach.jsonl"
    path.write_text("".join(f"{row.model_dump_json()}\n" for row in rows))

    assert (
        tuple(CFG_ROWS.validate_json(row.model_dump_json()) for row in reach) == reach
    )
    assert load_bundle(path).cfgs == (
        Cfg(program="PROGA", nodes=(NODE, end), edges=(edge,), entry=""),
    )

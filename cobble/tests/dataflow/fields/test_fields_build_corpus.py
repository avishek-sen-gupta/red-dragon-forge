"""The corpus pass: one member per ASG file, and every member it could not read.

Named ``test_fields_build_corpus`` because ``tests/dataflow/srccfg`` already has a
``test_build_corpus.py`` and this tree carries no ``__init__.py``, so a duplicate
basename breaks collection outright.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cobble.build_graph import _build_dynamic_targets, _dynamic_call_targets
from cobble.corpus_index import CorpusIndex
from cobble.dataflow.fields.aliases import ALIAS_PHASE_FAILED
from cobble.dataflow.fields.emit_extents import emit
from cobble.dataflow.fields.extents_input import member_rows
from cobble.dataflow.fields.side_tables import target_row
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint import build_corpus
from cobble.dataflow.fixpoint.build_corpus import (
    ALIASES_FILE,
    DEFS_FILE,
    GRAPH_FILE,
    JUMPS_FILE,
    TARGETS_FILE,
    cli,
)
from cobble.dataflow.fixpoint.options import ITERATION_FACTOR, AnalysisOptions
from cobble.dataflow.fixpoint.query import load
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.targets import ResolvedTarget
from cobble.dataflow.jumps.fact import Fact
from cobble.file_location import FileLocationReason, NoFileLocation
from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind
from cobble.knowledge_graph.graph_writer import graph_writer
from cobble.knowledge_graph.row_type import RowType
from cobble.path_utils import ensure_parent


def _program(program_id: str, target: str = "WS-B") -> dict:
    """One member in cache shape. Child offsets are the bridge's, so both are stated:
    a defaulted offset puts every child at 0, which makes two fields one extent."""
    return {
        "program_id": program_id,
        "data_fields": [
            {
                "level": 1,
                "name": "REC",
                "offset": 0,
                "children": [
                    {"level": 5, "name": "WS-A", "pic": "X(4)", "offset": 0},
                    {"level": 5, "name": "WS-B", "pic": "X(4)", "offset": 4},
                ],
            }
        ],
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [
                    {
                        "type": "MOVE",
                        "operands": [{"name": "WS-A"}, {"name": target}],
                    }
                ],
            }
        ],
    }


def _branched(program_id: str) -> dict:
    """WS-A written on four paths, then read once.

    Four writes rather than two so the read has four defining statements: one
    flow, whose defs row has to keep all four, and four is enough that a dedup
    keeping one of them is unmistakable.
    """
    return {
        **_program(program_id),
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [
                    _if(
                        [_if([_move("WS-B", "WS-A")], [_move("'1'", "WS-A")])],
                        [_if([_move("'2'", "WS-A")], [_move("'3'", "WS-A")])],
                    ),
                    _move("WS-A", "WS-B"),
                ],
            }
        ],
    }


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _if(then: list[dict], otherwise: list[dict]) -> dict:
    return {
        "type": "IF",
        "condition": {
            "not": False,
            "relation": {
                "left": {"kind": "ref", "name": "WS-B"},
                "op": "==",
                "right": {"kind": "lit", "value": "'Y'"},
            },
        },
        "children": then,
        "else_children": otherwise,
    }


def _selector(extra: tuple[str, ...]) -> tuple[str, ...]:
    """``--all`` unless the test names its own selection: one is always required."""
    chosen = {"--all", "--member"} & set(extra)
    return () if chosen else ("--all",)


def _rows(path: Path) -> tuple[dict, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return tuple(json.loads(line) for line in lines)


def _tagged(path: Path, row_type: RowType) -> tuple[dict, ...]:
    return tuple(row for row in _rows(path) if row["type"] == row_type.value)


def _edge_text(out_dir: Path) -> str:
    return "".join(
        json.dumps(row) for row in _tagged(out_dir / GRAPH_FILE, RowType.EDGE)
    )


def _member_json(program: dict) -> str:
    return json.dumps({"programs": [program]})


@pytest.fixture
def corpus(tmp_path: Path):
    """An ASG directory, an output directory, a config naming both, and the extents.

    The extents table is an input to this stage, so the fixture runs the stage
    before it -- ``cobble-extents`` over the same cache -- rather than hand-writing
    rows. ``declared`` narrows which members it covers, for the case where a
    member's layout was never published.
    """

    def build(
        members: dict, extra: tuple[str, ...] = (), declared: tuple[str, ...] = ()
    ) -> tuple[list[str], Path]:
        asg_dir = tmp_path / "asg"
        asg_dir.mkdir(exist_ok=True)
        for name, body in members.items():
            (asg_dir / f"{name}.json").write_text(body, encoding="utf-8")
        extents = tmp_path / "extents.jsonl"
        emit(asg_dir, extents, declared, max_workers=1)
        return (
            [
                "--asg-dir",
                str(asg_dir),
                "--out-dir",
                str(tmp_path / "out"),
                "--extents",
                str(extents),
                *_selector(extra),
                *extra,
            ],
            tmp_path / "out",
        )

    return build


def test_a_run_writes_nodes_and_edges_and_exits_zero(corpus):
    argv, out_dir = corpus({"MEMBERA": _member_json(_program("PROGA"))})

    assert cli(argv) == 0

    (edge,) = _tagged(out_dir / GRAPH_FILE, RowType.EDGE)
    assert (edge["source"], edge["target"]) == ("PROGA.WS-A", "PROGA.WS-B")
    assert edge["kind"] == "FLOWS_TO"


def test_one_flow_written_on_four_paths_is_one_edge_and_one_defs_row(corpus):
    """The whole point of the split, end to end: four definers, one flow.

    Pinned to the edge, these were four rows saying the same thing about the same
    bytes, and endpoint-level dedup wrote one of them and dropped three -- which
    one varying between runs. As a relation of its own the flow is stated once and
    every definer survives, keyed by the node that moved the value and the range
    it read."""
    argv, out_dir = corpus({"MEMBERA": _member_json(_branched("PROGA"))})

    assert cli(argv) == 0

    read = [
        row
        for row in _tagged(out_dir / GRAPH_FILE, RowType.EDGE)
        if (row["source"], row["target"]) == ("PROGA.WS-A", "PROGA.WS-B")
        and row["attrs"]["node"] == "MAIN/1"
    ]
    (flow,) = read
    (defs,) = [
        row
        for row in _rows(out_dir / "defs.jsonl")
        if (row["node"], row["extent"]) == ("MAIN/1", flow["attrs"]["source_extent"])
    ]

    assert defs["definers"] == [
        "MAIN/0.else.0.else.0",
        "MAIN/0.else.0.then.0",
        "MAIN/0.then.0.else.0",
        "MAIN/0.then.0.then.0",
    ]


def test_two_runs_of_one_member_write_byte_identical_artefacts(corpus):
    """An artefact that differs between identical runs cannot be diffed.

    Both streams come out of frozensets -- the sources at an extent, the definers
    of one source -- so their order varies with the per-process hash seed, which
    is why this runs the build in subprocesses rather than in-process where the
    seed is fixed. Four definers give twenty-four orders, so distinct seeds
    agreeing by chance is not what a pass here means.

    The alias table is in here too, and needs a linking member to be worth
    comparing: its rows come out of a ``Mapping`` keyed by name
    and are emitted once per caller cell, so a commarea name declared in two
    records makes that more than one row."""
    argv, out_dir = corpus(
        {
            "MEMBERA": _member_json(_branched("PROGA")),
            "XPROGA": _member_json(_twice_declared_area("XPROGB", "XPROGZ")),
            "XPROGB": _member_json(_commarea_member("XPROGB", 12)),
        }
    )
    script = "import sys; from cobble.dataflow.fixpoint.build_corpus import cli; sys.exit(cli(sys.argv[1:]))"

    written = []
    for seed in ("1", "5", "9"):
        run = subprocess.run(
            [sys.executable, "-c", script, *argv],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
        )
        assert run.returncode == 0, run.stderr.decode()
        written.append(
            tuple(
                (out_dir / name).read_bytes()
                for name in (GRAPH_FILE, DEFS_FILE, ALIASES_FILE)
            )
        )

    assert len(set(written)) == 1


def test_every_endpoint_node_states_why_it_has_no_file(corpus):
    """cobble keeps no field-level index, so NOT_INDEXED -- and a resolver row has
    to exist at all, since GraphWriter resolves both endpoints of every edge."""
    argv, out_dir = corpus({"MEMBERA": _member_json(_program("PROGA"))})

    assert cli(argv) == 0

    nodes = _tagged(out_dir / GRAPH_FILE, RowType.NODE)
    assert {node["kind"] for node in nodes} == {"FIELD"}
    assert {node["file_path_reason"] for node in nodes} == {"not_indexed"}


def test_a_malformed_member_is_reported_and_the_run_continues(corpus):
    argv, out_dir = corpus(
        {"MEMBERA": _member_json(_program("PROGA")), "MEMBERB": "{not json"}
    )

    assert cli(argv) == 3

    assert "FLOWS_TO" in _edge_text(out_dir)


def test_a_member_the_extents_table_does_not_hold_is_a_reason_not_a_crash(
    corpus, capsys, caplog
):
    """The layout is an input, so a member without one is a member not analysed.

    Recorded the way the unsizeable skip is recorded -- by name, with a reason, and
    exit 3 -- because the alternative answers "this program has no field flows"
    for a program nobody ever laid out. The reason names the command that fixes it:
    nothing else about the artefact says the table is read rather than written.
    """
    argv, out_dir = corpus(
        {
            "MEMBERA": _member_json(_program("PROGA")),
            "MEMBERB": _member_json(_program("PROGB")),
        },
        declared=("MEMBERA",),
    )

    with caplog.at_level(logging.WARNING):
        assert cli(argv) == 3

    summary = json.loads(capsys.readouterr().out)
    assert (summary["analysed"], summary["skipped"]) == (1, 1)
    assert "PROGB" not in _edge_text(out_dir)
    reason = (
        "no rows in extents.jsonl: run cobble-extents "
        f"--asg-dir {out_dir.parent / "asg"} "
        f"--out {out_dir.parent / "extents.jsonl"} MEMBERB"
    )
    reported = [record.getMessage() for record in caplog.records]
    assert [one for one in reported if one.startswith("fields: !! skipped")] == [
        f"fields: !! skipped MEMBERB: {reason}"
    ]


def test_a_missing_extents_table_exits_two(corpus):
    """Exit 2, the input-not-found code, rather than 29 identical skips."""
    argv, _ = corpus({"MEMBERA": _member_json(_program("PROGA"))})
    absent = [
        "nowhere.jsonl" if argument.endswith("extents.jsonl") else argument
        for argument in argv
    ]

    assert cli(absent) == 2


def test_a_missing_asg_directory_exits_two(tmp_path: Path):
    argv = [
        "--asg-dir",
        str(tmp_path / "nope"),
        "--out-dir",
        str(tmp_path / "out"),
        "--extents",
        str(tmp_path / "e.jsonl"),
        "--all",
    ]

    assert cli(argv) == 2


def test_a_missing_required_argument_is_a_usage_error(tmp_path: Path):
    """--asg-dir and --out-dir replaced the TOML config; a bare invocation still
    fails clearly rather than defaulting into a run that finds no members."""
    argv = [
        "--out-dir",
        str(tmp_path / "out"),
        "--extents",
        str(tmp_path / "e.jsonl"),
        "--all",
    ]

    with pytest.raises(SystemExit) as failure:
        cli(argv)

    assert failure.value.code == 2


def test_two_members_declaring_one_program_id_are_both_reported(corpus):
    """Node ids are scoped by program, so a collision merges two namespaces.

    srccfg answers this by qualifying its output filename, which it can do because
    it writes one file per member. This stage writes one shared graph.jsonl, so
    there is nothing to qualify -- the run reports instead.
    """
    argv, _ = corpus(
        {
            "MEMBERA": _member_json(_program("PROGA")),
            "MEMBERB": _member_json(_program("PROGA")),
        }
    )

    assert cli(argv) == 3


def test_coverage_below_the_floor_exits_one(corpus):
    """A target that resolves to no storage is a write the analysis did not reach."""
    argv, _ = corpus({"MEMBERA": _member_json(_program("PROGA", target="WS-GONE"))})

    assert cli(argv) == 1


def test_a_lowered_floor_accepts_the_same_run(corpus):
    argv, _ = corpus(
        {"MEMBERA": _member_json(_program("PROGA", target="WS-GONE"))},
        extra=("--min-coverage", "0.0"),
    )

    assert cli(argv) == 0


def test_the_run_writes_five_tables_and_no_layout_into_the_graph(corpus):
    """The layout is cobble-extents' table, which this stage reads and does not
    republish; a field node carries its id and nothing a layout would add."""
    argv, out_dir = corpus({"MEMBERA": _member_json(_program("PROGA"))})

    assert cli(argv) == 0

    assert sorted(path.name for path in out_dir.iterdir()) == [
        ALIASES_FILE,
        DEFS_FILE,
        GRAPH_FILE,
        JUMPS_FILE,
        "members",
        TARGETS_FILE,
    ]
    assert [node["attrs"] for node in _tagged(out_dir / GRAPH_FILE, RowType.NODE)] == [
        {},
        {},
    ]


def test_a_named_member_is_the_only_one_analysed(corpus):
    """The intended use: one program, on demand, not the whole cache."""
    argv, out_dir = corpus(
        {
            "MEMBERA": _member_json(_program("PROGA")),
            "MEMBERB": _member_json(_program("PROGB")),
        },
        extra=("--member", "MEMBERA"),
    )

    assert cli(argv) == 0

    edges = _edge_text(out_dir)
    assert "PROGA" in edges
    assert "PROGB" not in edges


def test_several_named_members_are_analysed_together(corpus):
    """A program and its related programs, in one graph -- though no edge crosses
    a program: this stage is intra-program, and a CALL is a synthetic source."""
    argv, _ = corpus(
        {
            "MEMBERA": _member_json(_program("PROGA")),
            "MEMBERB": _member_json(_program("PROGB")),
            "MEMBERC": _member_json(_program("PROGC")),
        },
        extra=("--member", "MEMBERA", "MEMBERC"),
    )

    assert cli(argv) == 0


def test_a_named_member_the_cache_does_not_hold_exits_two(corpus):
    """Before any analysis: coverage over the members that do exist answers a
    question nobody asked."""
    argv, out_dir = corpus(
        {"MEMBERA": _member_json(_program("PROGA"))},
        extra=("--member", "MEMBERA", "MEMBERGONE"),
    )

    assert cli(argv) == 2

    assert not (out_dir / GRAPH_FILE).exists()


def test_the_iteration_factor_reaches_the_fixpoint(corpus, capsys):
    """A member stopped at the cap is published unsettled rather than skipped, and
    re-runnable with more room, so the cap has to be settable from the command
    line."""
    argv, _ = corpus(
        {"MEMBERA": _member_json(_program("PROGA"))}, extra=("--iteration-factor", "0")
    )

    assert cli(argv) == 0

    summary = json.loads(capsys.readouterr().out)
    assert (summary["skipped"], summary["unsettled"]) == (0, 1)


def test_a_sweep_budget_analyses_the_member_and_reports_that_it_settled(corpus, capsys):
    argv, out_dir = corpus(
        {"MEMBERA": _member_json(_program("PROGA"))}, extra=("--sweeps", "2")
    )

    assert cli(argv) == 0

    assert json.loads(capsys.readouterr().out)["unsettled"] == 0
    (edge,) = _tagged(out_dir / GRAPH_FILE, RowType.EDGE)
    assert (edge["source"], edge["target"]) == ("PROGA.WS-A", "PROGA.WS-B")


def test_a_sweep_budget_below_one_is_a_usage_error(corpus):
    """Zero sweeps would select the worklist walk by the value that disables it."""
    argv, _ = corpus(
        {"MEMBERA": _member_json(_program("PROGA"))}, extra=("--sweeps", "0")
    )

    with pytest.raises(SystemExit) as failure:
        cli(argv)

    assert failure.value.code == 2


def test_a_sweep_budget_and_an_iteration_factor_at_once_are_a_usage_error(corpus):
    """The two budgets belong to different walks; taking both would drop one."""
    argv, _ = corpus(
        {"MEMBERA": _member_json(_program("PROGA"))},
        extra=("--sweeps", "2", "--iteration-factor", "100"),
    )

    with pytest.raises(SystemExit) as failure:
        cli(argv)

    assert failure.value.code == 2


def test_no_selection_is_a_usage_error(corpus):
    """A whole-corpus pass is asked for, never defaulted into."""
    argv, _ = corpus({"MEMBERA": _member_json(_program("PROGA"))})
    without_selector = [argument for argument in argv if argument != "--all"]

    with pytest.raises(SystemExit) as failure:
        cli(without_selector)

    assert failure.value.code == 2


def test_both_selections_at_once_are_a_usage_error(corpus):
    argv, _ = corpus(
        {"MEMBERA": _member_json(_program("PROGA"))},
        extra=("--all", "--member", "MEMBERA"),
    )

    with pytest.raises(SystemExit) as failure:
        cli(argv)

    assert failure.value.code == 2


def test_the_run_summary_reaches_stdout_for_a_pipeline(corpus, capsys):
    argv, _ = corpus({"MEMBERA": _member_json(_program("PROGA"))})

    assert cli(argv) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["analysed"] == 1
    assert summary["coverage"] == 1.0


def _link(target: str, area: str) -> dict:
    return {
        "type": "EXEC_CICS",
        "verb": "LINK",
        "options": {
            "PROGRAM": {"text": f"'{target}'", "is_literal": True},
            "COMMAREA": {"text": area, "is_literal": False},
        },
    }


def _caller_of(*statements: dict) -> dict:
    """XPROGA, one 12-byte WS-AREA, and the given statements after a MOVE.

    The MOVE is there so the run clears the coverage floor: the alias table is what
    is under test, and an exit 1 for coverage would hide it. It also puts the first
    given statement at MAIN/1.
    """
    return {
        "program_id": "XPROGA",
        "data_fields": [
            {
                "level": 1,
                "name": "WS-AREA",
                "offset": 0,
                "children": [
                    {"level": 5, "name": "WS-HEAD", "pic": "X(4)", "offset": 0},
                    {"level": 5, "name": "WS-REST", "pic": "X(8)", "offset": 4},
                ],
            }
        ],
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [_move("WS-HEAD", "WS-REST"), *statements],
            }
        ],
    }


def _linking(*targets: str) -> dict:
    """A member with one LINK per target, passing each of them the same WS-AREA."""
    return _caller_of(*(_link(target, "WS-AREA") for target in targets))


def _commarea_member(program_id: str, size: int) -> dict:
    """A callee declaring nothing but the area a LINK passes it."""
    return {
        "program_id": program_id,
        "paragraphs": [],
        "linkage_fields": [{"level": 1, "name": "DFHCOMMAREA", "pic": f"X({size})"}],
    }


def test_the_run_emits_the_alias_table_and_counts_its_dead_ends(corpus, capsys):
    """A fifth table beside the four, with the coverage of it as a stated number.

    The callee is looked up by cache filename, so the members are named for the
    programs they declare rather than MEMBERA/MEMBERB. XPROGZ has no cache file and
    still names itself on its dead-end row: which callee a consumer has to go and
    parse next is exactly what that row is for.
    """
    argv, out_dir = corpus(
        {
            "XPROGA": _member_json(_linking("XPROGB", "XPROGZ")),
            "XPROGB": _member_json(_commarea_member("XPROGB", 12)),
        }
    )

    assert cli(argv) == 0

    rows = _rows(out_dir / ALIASES_FILE)
    assert {row["callee"] for row in rows} == {"XPROGB", "XPROGZ"}
    assert [row["reason"] for row in rows if row["reason"]] == ["callee-not-in-cache"]
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["aliased"] == 1
    assert summary["alias_dead_ends"] == {"callee-not-in-cache": 1}


def test_the_shared_window_is_the_shorter_of_the_two_declared_areas(corpus):
    """A row a cross-program consumer can cross: both sides, rebased, same length."""
    argv, out_dir = corpus(
        {
            "XPROGA": _member_json(_linking("XPROGB", "XPROGZ")),
            "XPROGB": _member_json(_commarea_member("XPROGB", 8)),
        }
    )

    assert cli(argv) == 0

    (shared,) = [row for row in _rows(out_dir / ALIASES_FILE) if not row["reason"]]
    assert shared["caller_extent"] == "WS-AREA@working_storage[0:8]"
    assert shared["callee_extent"] == "DFHCOMMAREA@linkage[0:8]"
    assert (shared["transfer"], shared["returns"]) == ("LINK", True)


def test_unreadable_callees_tally_under_one_dead_end_reason(corpus, capsys):
    """Two callees, two different parse errors, one bucket.

    That reason carries the error's repr, so tallied verbatim it would report a key
    of count one per distinct message -- a breakdown nobody can read a coverage
    figure off. The messages stay on the rows, which is where the parse problem is
    diagnosed.
    """
    argv, out_dir = corpus(
        {
            "XPROGA": _member_json(_linking("XPROGY", "XPROGZ")),
            "XPROGY": "{not json",
            "XPROGZ": '{"program_id": "XPROG',
        }
    )

    assert cli(argv) == 3

    assert len({row["reason"] for row in _rows(out_dir / ALIASES_FILE)}) == 2
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["aliased"] == 0
    assert summary["alias_dead_ends"] == {"unreadable": 2}


def test_a_budget_skipped_member_still_emits_its_alias_rows(corpus, capsys):
    """A member the walk gave up on has its full layout, which is all a row needs.

    The dequeue cap is reached after the index is built, so withholding the rows
    would turn "we stopped early" into "this program calls nothing" -- and the
    members a real corpus gives up on are the ones whose callees matter most.
    """
    argv, out_dir = corpus(
        {
            "XPROGA": _member_json(_linking("XPROGB", "XPROGZ")),
            "XPROGB": _member_json(_commarea_member("XPROGB", 12)),
        },
        extra=("--iteration-factor", "0"),
    )

    assert cli(argv) == 0

    rows = _rows(out_dir / ALIASES_FILE)
    assert [row["callee"] for row in rows if not row["reason"]] == ["XPROGB"]
    assert [row["reason"] for row in rows if row["reason"]] == ["callee-not-in-cache"]
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert (summary["aliased"], summary["alias_dead_ends"]) == (
        1,
        {"callee-not-in-cache": 1},
    )


def test_a_callee_the_parse_cannot_read_costs_one_row_and_not_the_four_tables(
    corpus, capsys
):
    """A defect in a callee's cache file must not delete the caller's records.

    ``null`` is valid JSON and not an object, so laying the callee out raises where
    a truncated file raises somewhere else entirely. Either way the caller's
    nodes, edges, extents and defs are already computed, and the run that says
    nothing flowed in XPROGA is a worse answer than one dead-end row.
    """
    argv, out_dir = corpus(
        {"XPROGA": _member_json(_linking("XPROGB")), "XPROGB": "null"},
        extra=("--member", "XPROGA"),
    )

    assert cli(argv) == 0

    for name in (GRAPH_FILE, DEFS_FILE):
        assert _rows(out_dir / name), name
    (row,) = _rows(out_dir / ALIASES_FILE)
    assert (row["caller"], row["node"], row["transfer"]) == ("XPROGA", "MAIN/1", "LINK")
    assert row["reason"].startswith("unreadable: ")
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert (summary["skipped"], summary["alias_dead_ends"]) == (0, {"unreadable": 1})


def _twice_declared_area(*targets: str) -> dict:
    """WS-AREA declared in two records, so one commarea operand names two cells.

    Two windows on different bytes, so both rows survive the key's dedupe -- which
    is the case ``aliased`` has to count once, because there is one LINK here.
    """
    return {
        "program_id": "XPROGA",
        "data_fields": [
            {
                "level": 1,
                "name": "WS-AREA",
                "offset": 0,
                "children": [
                    {"level": 5, "name": "WS-HEAD", "pic": "X(4)", "offset": 0}
                ],
            },
            {
                "level": 1,
                "name": "WS-BLOCK",
                "offset": 0,
                "children": [
                    {"level": 5, "name": "WS-AREA", "pic": "X(8)", "offset": 0}
                ],
            },
        ],
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [
                    _move("WS-HEAD", "WS-HEAD"),
                    *(_link(target, "WS-AREA") for target in targets),
                ],
            }
        ],
    }


def test_one_site_resolving_to_two_caller_cells_counts_once(corpus, capsys):
    """``aliased`` is a site count, so two rows at one node are one aliased site."""
    argv, out_dir = corpus(
        {
            "XPROGA": _member_json(_twice_declared_area("XPROGB")),
            "XPROGB": _member_json(_commarea_member("XPROGB", 12)),
        }
    )

    assert cli(argv) == 0

    rows = _rows(out_dir / ALIASES_FILE)
    assert {row["node"] for row in rows} == {"MAIN/1"}
    assert {row["caller_extent"] for row in rows} == {
        "WS-AREA@working_storage[0:4]",
        "WS-AREA@working_storage[4:12]",
    }
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["aliased"] == 1


def test_the_report_names_every_dead_end_reason_without_a_dict_repr(corpus, caplog):
    """The run states its alias coverage where it states everything else.

    A ``Mapping`` through ``%s`` is a Python repr in a report meant to be read,
    and its JSON twin is already on stdout.
    """
    argv, _ = corpus(
        {
            "XPROGA": _member_json(_linking("XPROGB", "XPROGZ")),
            "XPROGB": _member_json(_commarea_member("XPROGB", 12)),
        }
    )

    with caplog.at_level(logging.INFO):
        assert cli(argv) == 0

    assert (
        "1 call sites share a commarea window, 1 do not: callee-not-in-cache 1"
        in caplog.text
    )
    assert "{" not in caplog.text


def test_a_run_with_no_call_sites_says_nothing_about_aliases(corpus, caplog):
    """Zeroes read as a failure to alias; a corpus of leaf programs has no
    coverage to state."""
    argv, _ = corpus({"MEMBERA": _member_json(_program("PROGA"))})

    with caplog.at_level(logging.INFO):
        assert cli(argv) == 0

    assert "commarea" not in caplog.text


def test_a_single_member_run_emits_that_members_outbound_aliases(corpus):
    """The callee cache is the whole ASG directory, not the selection: a run about
    one program still says which bytes it hands to the programs it calls."""
    argv, out_dir = corpus(
        {
            "XPROGA": _member_json(_linking("XPROGB", "XPROGZ")),
            "XPROGB": _member_json(_commarea_member("XPROGB", 12)),
        },
        extra=("--member", "XPROGA"),
    )

    assert cli(argv) == 0

    rows = _rows(out_dir / ALIASES_FILE)
    assert {row["caller"] for row in rows} == {"XPROGA"}
    assert [row["callee"] for row in rows if not row["reason"]] == ["XPROGB"]


def _dynamic_link(area: str) -> dict:
    """A LINK whose PROGRAM is a field, so the target is known only at run time."""
    return {
        "type": "EXEC_CICS",
        "verb": "LINK",
        "options": {
            "PROGRAM": {"text": "WS-TARGET", "is_literal": False},
            "COMMAREA": {"text": area, "is_literal": False},
        },
    }


def test_a_blank_callee_means_the_target_could_not_be_resolved(corpus):
    """The blank carries a fact of its own now, so it has to mean only that one.

    A dead end that knows its callee names it, so a reader seeing ``callee: ""``
    can conclude the target is dynamic rather than wondering whether the pass
    simply did not carry it.
    """
    argv, out_dir = corpus(
        {
            "XPROGA": _member_json(
                _caller_of(_dynamic_link("WS-AREA"), _link("XPROGZ", "WS-AREA"))
            )
        },
        extra=("--member", "XPROGA"),
    )

    assert cli(argv) == 0

    named = {row["node"]: row["callee"] for row in _rows(out_dir / ALIASES_FILE)}
    assert named == {"MAIN/1": "", "MAIN/2": "XPROGZ"}


def test_a_commarea_operand_naming_nothing_is_a_named_dead_end(corpus, capsys):
    """``COMMAREA(OF)`` is all qualifier and no name, and says so on its own row.

    An empty name matches no cell, which is what ``caller-field-unknown`` already
    means, so the site is a dead end rather than an exception -- and its siblings
    keep their windows because nothing raised in the first place.
    """
    argv, out_dir = corpus(
        {
            "XPROGA": _member_json(
                _caller_of(_link("XPROGB", "OF"), _link("XPROGB", "WS-AREA"))
            ),
            "XPROGB": _member_json(_commarea_member("XPROGB", 12)),
        }
    )

    assert cli(argv) == 0

    rows = {row["node"]: row for row in _rows(out_dir / ALIASES_FILE)}
    assert rows["MAIN/2"]["caller_extent"] == "WS-AREA@working_storage[0:12]"
    assert (
        rows["MAIN/1"]["caller"],
        rows["MAIN/1"]["callee"],
        rows["MAIN/1"]["reason"],
    ) == ("XPROGA", "XPROGB", "caller-field-unknown")
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert (summary["aliased"], summary["alias_dead_ends"]) == (
        1,
        {"caller-field-unknown": 1},
    )


def _never_aliases(asg, index, asg_dir, targets):
    raise RuntimeError("the pass itself")


def test_the_pass_failing_before_it_enumerates_a_member_is_its_own_reason(
    corpus, monkeypatch
):
    """The one wall, told apart from a callee whose cache file is broken.

    Those are different bugs with different owners: one is the corpus's and one is
    this repo's. It costs the member its alias rows, which is loud, and leaves the
    tables that have nothing to do with aliasing intact, which is the point.
    Reached by making the alias phase raise, since no known route does -- and
    in-process, since a worker process would import the module unpatched.
    """
    argv, _ = corpus(
        {"XPROGA": _member_json(_linking("XPROGB"))}, extra=("--member", "XPROGA")
    )
    monkeypatch.setattr(
        build_corpus,
        "commarea_aliases",
        _never_aliases,
    )
    asg_dir = Path(argv[argv.index("--asg-dir") + 1])
    ((member, block),) = tuple(member_rows(Path(argv[argv.index("--extents") + 1])))

    result, _seconds = build_corpus._analysed(
        build_corpus._MemberTask(
            member=member,
            path=asg_dir / "XPROGA.json",
            block=block,
            options=AnalysisOptions(sweeps=0, factor=ITERATION_FACTOR),
            members=asg_dir / "members",
        )
    )

    assert (result.skipped, bool(result.edges), bool(result.defs)) == ("", True, True)
    (row,) = result.aliases
    assert (row.caller, row.node, row.transfer) == ("XPROGA", "", "")
    assert row.reason.startswith(ALIAS_PHASE_FAILED)
    assert build_corpus._dead_ends(result) == (
        f"{ALIAS_PHASE_FAILED}: RuntimeError('the pass itself')",
    )


def _ambiguous_area(target: str) -> dict:
    """WS-AREA declared twice, once as a group holding no bytes at all.

    One LINK, two resolutions: the 8-byte one shares a window and the empty one
    never can, so this site belongs in both of the run's two buckets.
    """
    return {
        "program_id": "XPROGA",
        "data_fields": [
            {"level": 1, "name": "WS-AREA", "offset": 0},
            {
                "level": 1,
                "name": "WS-BLOCK",
                "offset": 0,
                "children": [
                    {"level": 5, "name": "WS-AREA", "pic": "X(8)", "offset": 0},
                    {"level": 5, "name": "WS-HEAD", "pic": "X(4)", "offset": 8},
                ],
            },
        ],
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [_move("WS-HEAD", "WS-HEAD"), _link(target, "WS-AREA")],
            }
        ],
    }


def test_a_dynamic_site_is_one_row_whether_or_not_it_resolved():
    resolved = ResolvedTarget(
        caller="PROGA",
        node="MAIN/3",
        kind=TargetKind.PROGRAM,
        transfer="CICS_XCTL",
        expression="WS-PGM",
        candidates=("COSGN00C",),
    )
    unresolved = ResolvedTarget(
        caller="PROGA",
        node="MAIN/7",
        kind=TargetKind.PROGRAM,
        transfer="CICS_XCTL",
        expression="CDEMO-TO-PROGRAM",
        reasons=(UnresolvedReason.INBOUND_LINKAGE,),
        dropped=("",),
    )
    file_site = ResolvedTarget(
        caller="PROGA",
        node="MAIN/9",
        kind=TargetKind.FILE,
        transfer="CICS_READ",
        expression="WS-FILE",
        candidates=("USRSEC",),
        operand=Fact(
            extent="WS-FILE@working_storage[0:8]",
            values=("USRSEC  ",),
            writers=("PROGA/MAIN/2",),
        ),
    )

    assert target_row(resolved) == (
        "PROGA\x00MAIN/3",
        json.dumps(
            {
                "caller": "PROGA",
                "node": "MAIN/3",
                "kind": "program",
                "transfer": "CICS_XCTL",
                "expression": "WS-PGM",
                "candidates": ["COSGN00C"],
                "reasons": [],
                "dropped": [],
            }
        ),
    )
    assert json.loads(target_row(unresolved)[1])["reasons"] == ["inbound-linkage"]
    assert json.loads(target_row(file_site)[1]) == {
        "caller": "PROGA",
        "node": "MAIN/9",
        "kind": "file",
        "transfer": "CICS_READ",
        "expression": "WS-FILE",
        "candidates": ["USRSEC"],
        "reasons": [],
        "dropped": [],
        "operand": {
            "extent": "WS-FILE@working_storage[0:8]",
            "values": ["USRSEC  "],
            "writers": ["PROGA/MAIN/2"],
            "reasons": [],
        },
    }


def _two_dynamic_sites() -> dict:
    """XPROGA, one field, two LINK sites naming it: unresolved before the MOVE,
    resolved after."""
    return {
        "program_id": "XPROGA",
        "data_fields": [
            {"level": 1, "name": "WS-TARGET", "pic": "X(8)", "offset": 0},
        ],
        "paragraphs": [
            {
                "name": "MAIN",
                "statements": [
                    _dynamic_link("WS-TARGET"),
                    _move("'XPROGB'", "WS-TARGET"),
                    _dynamic_link("WS-TARGET"),
                ],
            }
        ],
    }


def _dynamic_read(field: str) -> dict:
    """A CICS READ whose DATASET is a field, so the file is known only at run time."""
    return {
        "type": "EXEC_CICS",
        "verb": "READ",
        "options": {"DATASET": {"text": field, "is_literal": False}},
    }


def _call_and_file_sites() -> dict:
    """XPROGA's two LINK sites, and a READ naming its file through the same field
    between the MOVE and the second LINK, which may write the field back."""
    member = _two_dynamic_sites()
    (paragraph,) = member["paragraphs"]
    first, move, second = paragraph["statements"]
    return {
        **member,
        "paragraphs": [
            {
                **paragraph,
                "statements": [first, move, _dynamic_read("WS-TARGET"), second],
            }
        ],
    }


def test_a_dynamic_call_site_is_published_whether_or_not_it_resolves(corpus):
    """The corpus fact a whole-corpus graph build needs: which programs each
    dynamic CALL/XCTL/LINK site can reach, beside the four graph tables."""
    argv, out_dir = corpus({"XPROGA": _member_json(_two_dynamic_sites())})

    assert cli(argv) == 0

    rows = {row["node"]: row for row in _rows(out_dir / TARGETS_FILE)}
    assert (rows["MAIN/0"]["candidates"], rows["MAIN/0"]["reasons"]) == (
        [],
        ["uninitialised"],
    )
    assert (rows["MAIN/2"]["candidates"], rows["MAIN/2"]["reasons"]) == (
        ["XPROGB"],
        [],
    )


def test_the_report_states_how_dynamic_sites_resolved(corpus, caplog):
    argv, _ = corpus({"XPROGA": _member_json(_call_and_file_sites())})

    with caplog.at_level(logging.INFO):
        assert cli(argv) == 0

    assert [
        record.getMessage()
        for record in caplog.records
        if "resolved to one" in record.getMessage()
    ] == [
        "fields: 2 dynamic call sites, 1 resolved to one program, 0 to several, "
        "1 to none (uninitialised 1)",
        "fields: 1 dynamic file sites, 1 resolved to one file, 0 to several, "
        "0 to none",
    ]


def test_the_two_alias_counts_can_both_hold_one_site(corpus, caplog):
    """Neither count is distorted to make them partition the sites, so they exceed
    the site total: one LINK here is both the run's aliased site and its dead end.

    The run line reports both numbers and leaves the caveat to the docs, because it
    is a standing property of the two counts rather than a fact about this run.
    """
    argv, _ = corpus(
        {
            "XPROGA": _member_json(_ambiguous_area("XPROGB")),
            "XPROGB": _member_json(_commarea_member("XPROGB", 12)),
        }
    )

    with caplog.at_level(logging.INFO):
        assert cli(argv) == 0

    assert (
        "1 call sites share a commarea window, 1 do not: empty-window 1" in caplog.text
    )


def test_the_build_reads_the_graph_and_targets_the_fixpoint_wrote(tmp_path, corpus):
    """The two stages end to end, no JVM: the fixpoint's graph file reads back
    through the build's reader, and the build's dynamic-target stage turns the
    targets.jsonl it published into the build's own graph file -- an unresolved
    site into a DYNAMIC_TARGET, a resolved one into an ordinary LINK."""
    argv, out_dir = corpus({"XPROGA": _member_json(_two_dynamic_sites())})
    assert cli(argv) == 0

    _fields, flows = read_graph(out_dir / GRAPH_FILE)
    assert [(flow.source, flow.target, flow.attrs["node"]) for flow in flows] == [
        ("XPROGA.%CALL:WS-TARGET", "XPROGA.WS-TARGET", "MAIN/0"),
        ("XPROGA.LITERAL", "XPROGA.WS-TARGET", "MAIN/1"),
        ("XPROGA.%CALL:WS-TARGET", "XPROGA.WS-TARGET", "MAIN/2"),
    ]

    graph = ensure_parent(tmp_path / "build" / "corpus.jsonl")
    resolver = CorpusIndex()
    with graph_writer(graph, resolver) as writer:
        writer.add_all(
            *_build_dynamic_targets(
                _dynamic_call_targets(str(out_dir / TARGETS_FILE)), resolver
            )
        )

    assert read_graph(graph) == (
        [
            GraphNode(
                id="XPROGA.WS-TARGET",
                kind=NodeKind.DYNAMIC_TARGET,
                location=NoFileLocation(FileLocationReason.NOT_INDEXED),
                attrs={"reason": "uninitialised", "dropped": []},
            ),
            GraphNode(
                id="XPROGB",
                kind=NodeKind.PROGRAM,
                location=NoFileLocation(FileLocationReason.UNRESOLVED),
            ),
            GraphNode(
                id="XPROGA",
                kind=NodeKind.PROGRAM,
                location=NoFileLocation(FileLocationReason.UNRESOLVED),
            ),
        ],
        [
            GraphEdge(
                source="XPROGA",
                source_kind=NodeKind.PROGRAM,
                target="XPROGA.WS-TARGET",
                target_kind=NodeKind.DYNAMIC_TARGET,
                kind=EdgeKind.LINK,
            ),
            GraphEdge(
                source="XPROGA",
                source_kind=NodeKind.PROGRAM,
                target="XPROGB",
                target_kind=NodeKind.PROGRAM,
                kind=EdgeKind.LINK,
            ),
        ],
    )


def _three_members() -> dict:
    return {
        "MEMBERA": _member_json(_program("PROGA")),
        "MEMBERB": _member_json(_branched("PROGB")),
        "MEMBERC": _member_json(_program("PROGC", target="WS-GONE")),
    }


def test_parallel_workers_write_what_one_worker_writes(corpus, tmp_path):
    """Members finish out of order across workers; the tables do not."""
    argv, out_dir = corpus(_three_members(), extra=("--min-coverage", "0.0"))
    parallel = tmp_path / "parallel"
    serial_argv = [*argv, "--max-workers", "1"]
    parallel_argv = [
        str(parallel) if one == str(out_dir) else one
        for one in [*argv, "--max-workers", "3"]
    ]

    assert cli(serial_argv) == 0
    assert cli(parallel_argv) == 0

    assert _published(parallel) == _published(out_dir)


def test_every_member_is_reported_once_as_it_finishes(corpus, caplog):
    argv, _ = corpus(
        _three_members(), extra=("--min-coverage", "0.0", "--max-workers", "3")
    )

    with caplog.at_level(logging.INFO):
        assert cli(argv) == 0

    assert _member_lines(caplog.messages) == ["MEMBERA", "MEMBERB", "MEMBERC"]
    assert sorted(
        message.split("] ", 1)[0]
        for message in caplog.messages
        if message.startswith("fields: [")
    ) == ["fields: [1/3", "fields: [2/3", "fields: [3/3"]


def test_a_worker_count_below_one_is_a_usage_error(corpus):
    argv, _ = corpus(
        {"MEMBERA": _member_json(_program("PROGA"))}, extra=("--max-workers", "0")
    )

    with pytest.raises(SystemExit) as failure:
        cli(argv)

    assert failure.value.code == 2


def test_two_programs_reading_the_same_named_bytes_keep_a_defs_row_each(corpus):
    """Paragraph and field names repeat across programs, so a defs row keyed by
    node and extent alone collided: the first program's row was kept and every
    later one dropped, and the query answered the second program's flow from the
    first program's row, or not at all."""
    argv, out_dir = corpus(
        {
            "MEMBERA": _member_json(_written_then_read("PROGA")),
            "MEMBERB": _member_json(_written_then_read("PROGB")),
        }
    )
    extents = Path(argv[argv.index("--extents") + 1])

    assert cli(argv) == 0

    assert [
        (row["program"], row["node"], row["extent"], row["definers"])
        for row in _rows(out_dir / DEFS_FILE)
    ] == [
        ("PROGA", "MAIN/1", "WS-A@working_storage[0:4]", ["MAIN/0"]),
        ("PROGB", "MAIN/1", "WS-A@working_storage[0:4]", ["MAIN/0"]),
    ]
    store = load(out_dir, extents)
    assert {
        flow.source: store.definers_of(flow)
        for flow in store.flows
        if flow.source.endswith(".WS-A")
    } == {
        "PROGA.WS-A": ("MAIN/0",),
        "PROGB.WS-A": ("MAIN/0",),
    }


def _written_then_read(program_id: str) -> dict:
    """``_program`` with WS-A written first, so its read has a definer of its own."""
    program = _program(program_id)
    main = program["paragraphs"][0]
    return {
        **program,
        "paragraphs": [
            {
                **main,
                "statements": [
                    {"type": "MOVE", "operands": [{"name": "'X'"}, {"name": "WS-A"}]},
                    *main["statements"],
                ],
            }
        ],
    }


def _published(out_dir: Path) -> dict[str, bytes]:
    return {
        name: (out_dir / name).read_bytes()
        for name in (GRAPH_FILE, DEFS_FILE, ALIASES_FILE, TARGETS_FILE, JUMPS_FILE)
    }


def _member_lines(messages: list[str]) -> list[str]:
    """Which members were reported, and how, without the completion counter:
    members finish in whatever order the workers do."""
    return sorted(
        message.split("] ", 1)[1]
        for message in messages
        if message.startswith("fields: [")
    )


def test_an_interrupted_run_resumes_to_what_an_uninterrupted_one_publishes(
    corpus, capsys, caplog
):
    """A finished member is a directory of its own tables and counts; a re-run
    reuses it, analyses only what never finished, and publishes the corpus files
    and summary a single uninterrupted run does."""
    argv, out_dir = corpus(_three_members(), extra=("--min-coverage", "0.0"))
    assert cli(argv) == 0
    whole, summary = _published(out_dir), capsys.readouterr().out
    members = out_dir / "members"
    shutil.rmtree(members / "MEMBERC")
    (members / "MEMBERC.tmp").mkdir()
    (members / "MEMBERC.tmp" / GRAPH_FILE).write_text('{"type": "node", "id"')
    for name in whole:
        (out_dir / name).unlink()

    with caplog.at_level(logging.INFO):
        assert cli(argv) == 0

    assert _published(out_dir) == whole
    assert capsys.readouterr().out == summary
    assert _member_lines(caplog.messages) == [
        "MEMBERA reused",
        "MEMBERB reused",
        "MEMBERC",
    ]
    assert sorted(path.name for path in members.iterdir()) == [
        "MEMBERA",
        "MEMBERB",
        "MEMBERC",
    ]


def test_force_analyses_every_member_again(corpus, caplog):
    argv, out_dir = corpus(_three_members(), extra=("--min-coverage", "0.0"))
    assert cli(argv) == 0
    whole = _published(out_dir)

    with caplog.at_level(logging.INFO):
        assert cli([*argv, "--force"]) == 0

    assert _published(out_dir) == whole
    assert _member_lines(caplog.messages) == ["MEMBERA", "MEMBERB", "MEMBERC"]


def test_a_named_member_run_publishes_it_alone_and_keeps_the_rest(corpus):
    argv, out_dir = corpus(_three_members(), extra=("--min-coverage", "0.0"))
    assert cli(argv) == 0
    named = ["--member" if one == "--all" else one for one in argv]
    named.insert(named.index("--member") + 1, "MEMBERA")

    assert cli(named) == 0

    programs = {
        node["id"].split(".")[0] for node in _tagged(out_dir / GRAPH_FILE, RowType.NODE)
    }
    assert programs == {"PROGA"}
    assert sorted(path.name for path in (out_dir / "members").iterdir()) == [
        "MEMBERA",
        "MEMBERB",
        "MEMBERC",
    ]

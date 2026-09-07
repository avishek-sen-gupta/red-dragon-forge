"""The corpus pass: one member per ASG file, and every member it could not read.

Named ``test_fields_build_corpus`` because ``tests/dataflow/srccfg`` already has a
``test_build_corpus.py`` and this tree carries no ``__init__.py``, so a duplicate
basename breaks collection outright.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cobble.dataflow.fields.build_corpus import (
    ALIASES_FILE,
    DEFS_FILE,
    EDGES_FILE,
    EXTENTS_FILE,
    NODES_FILE,
    cli,
)


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


@pytest.fixture
def corpus(tmp_path: Path):
    """An ASG directory, an output directory, and a config naming both."""

    def build(members: dict, extra: tuple[str, ...] = ()) -> tuple[list[str], Path]:
        asg_dir = tmp_path / "asg"
        asg_dir.mkdir(exist_ok=True)
        for name, body in members.items():
            (asg_dir / f"{name}.json").write_text(body, encoding="utf-8")
        config = tmp_path / "fields.toml"
        config.write_text(
            f'[fields]\nasg_dir = "{asg_dir}"\nout_dir = "{tmp_path / "out"}"\n',
            encoding="utf-8",
        )
        return ["--config", str(config), *_selector(extra), *extra], tmp_path / "out"

    return build


def test_a_run_writes_nodes_and_edges_and_exits_zero(corpus):
    argv, out_dir = corpus({"MEMBERA": json.dumps(_program("PROGA"))})

    assert cli(argv) == 0

    edge = json.loads((out_dir / "edges.jsonl").read_text(encoding="utf-8"))
    assert (edge["source"], edge["target"]) == ("PROGA.WS-A", "PROGA.WS-B")
    assert edge["kind"] == "FLOWS_TO"


def test_one_flow_written_on_four_paths_is_one_edge_and_one_defs_row(corpus):
    """The whole point of the split, end to end: four definers, one flow.

    Pinned to the edge, these were four rows saying the same thing about the same
    bytes, and endpoint-level dedup wrote one of them and dropped three -- which
    one varying between runs. As a relation of its own the flow is stated once and
    every definer survives, keyed by the node that moved the value and the range
    it read."""
    argv, out_dir = corpus({"MEMBERA": json.dumps(_branched("PROGA"))})

    assert cli(argv) == 0

    read = [
        row
        for row in _rows(out_dir / "edges.jsonl")
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
            "MEMBERA": json.dumps(_branched("PROGA")),
            "XPROGA": json.dumps(_twice_declared_area("XPROGB", "XPROGZ")),
            "XPROGB": json.dumps(_commarea_member("XPROGB", 12)),
        }
    )
    script = "import sys; from cobble.dataflow.fields.build_corpus import cli; sys.exit(cli(sys.argv[1:]))"

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
                for name in (EDGES_FILE, EXTENTS_FILE, DEFS_FILE, ALIASES_FILE)
            )
        )

    assert len(set(written)) == 1


def test_every_endpoint_node_states_why_it_has_no_file(corpus):
    """cobble keeps no field-level index, so NOT_INDEXED -- and a resolver row has
    to exist at all, since GraphWriter resolves both endpoints of every edge."""
    argv, out_dir = corpus({"MEMBERA": json.dumps(_program("PROGA"))})

    assert cli(argv) == 0

    rows = (out_dir / "nodes.jsonl").read_text(encoding="utf-8").splitlines()
    nodes = [json.loads(row) for row in rows]
    assert {node["kind"] for node in nodes} == {"FIELD"}
    assert {node["file_path_reason"] for node in nodes} == {"not_indexed"}


def test_a_malformed_member_is_reported_and_the_run_continues(corpus):
    argv, out_dir = corpus(
        {"MEMBERA": json.dumps(_program("PROGA")), "MEMBERB": "{not json"}
    )

    assert cli(argv) == 3

    assert "FLOWS_TO" in (out_dir / "edges.jsonl").read_text(encoding="utf-8")


def test_a_missing_asg_directory_exits_two(tmp_path: Path):
    config = tmp_path / "fields.toml"
    config.write_text(
        f'[fields]\nasg_dir = "{tmp_path / "nope"}"\nout_dir = "{tmp_path / "out"}"\n',
        encoding="utf-8",
    )

    assert cli(["--config", str(config), "--all"]) == 2


def test_a_config_without_the_table_exits_two(tmp_path: Path):
    config = tmp_path / "fields.toml"
    config.write_text('[other]\nasg_dir = "/x"\n', encoding="utf-8")

    assert cli(["--config", str(config), "--all"]) == 2


def test_two_members_declaring_one_program_id_are_both_reported(corpus):
    """Node ids are scoped by program, so a collision merges two namespaces.

    srccfg answers this by qualifying its output filename, which it can do because
    it writes one file per member. This stage writes one shared edges.jsonl, so
    there is nothing to qualify -- the run reports instead.
    """
    argv, _ = corpus(
        {
            "MEMBERA": json.dumps(_program("PROGA")),
            "MEMBERB": json.dumps(_program("PROGA")),
        }
    )

    assert cli(argv) == 3


def test_coverage_below_the_floor_exits_one(corpus):
    """A target that resolves to no storage is a write the analysis did not reach."""
    argv, _ = corpus({"MEMBERA": json.dumps(_program("PROGA", target="WS-GONE"))})

    assert cli(argv) == 1


def test_a_lowered_floor_accepts_the_same_run(corpus):
    argv, _ = corpus(
        {"MEMBERA": json.dumps(_program("PROGA", target="WS-GONE"))},
        extra=("--min-coverage", "0.0"),
    )

    assert cli(argv) == 0


def test_the_declared_extents_go_to_their_own_file_not_into_the_nodes(corpus):
    """Geometry a consumer can intersect, beside the graph rather than in it.

    REC is in the extents file and not in the graph: no value moves through a
    group whose child was the target, so it is a declaration and not a flow
    fact -- and a reader intersecting the group write against it is exactly what
    the file is for."""
    argv, out_dir = corpus({"MEMBERA": json.dumps(_program("PROGA"))})

    assert cli(argv) == 0

    declared = {field["id"]: field for field in _rows(out_dir / EXTENTS_FILE)}
    assert declared["PROGA.WS-B"]["extents"] == ["WS-B@working_storage[4:8]"]
    assert declared["PROGA.REC"]["extents"] == ["REC@working_storage[0:8]"]
    assert (declared["PROGA.WS-B"]["level"], declared["PROGA.WS-B"]["usage"]) == (
        5,
        "DISPLAY",
    )
    assert declared["PROGA.REC"]["level"] == 1
    assert [node["attrs"] for node in _rows(out_dir / NODES_FILE)] == [{}, {}]


def test_a_named_member_is_the_only_one_analysed(corpus):
    """The intended use: one program, on demand, not the whole cache."""
    argv, out_dir = corpus(
        {
            "MEMBERA": json.dumps(_program("PROGA")),
            "MEMBERB": json.dumps(_program("PROGB")),
        },
        extra=("--member", "MEMBERA"),
    )

    assert cli(argv) == 0

    edges = (out_dir / "edges.jsonl").read_text(encoding="utf-8")
    assert "PROGA" in edges
    assert "PROGB" not in edges


def test_several_named_members_are_analysed_together(corpus):
    """A program and its related programs, in one graph -- though no edge crosses
    a program: this stage is intra-program, and a CALL is a synthetic source."""
    argv, _ = corpus(
        {
            "MEMBERA": json.dumps(_program("PROGA")),
            "MEMBERB": json.dumps(_program("PROGB")),
            "MEMBERC": json.dumps(_program("PROGC")),
        },
        extra=("--member", "MEMBERA", "MEMBERC"),
    )

    assert cli(argv) == 0


def test_a_named_member_the_cache_does_not_hold_exits_two(corpus):
    """Before any analysis: coverage over the members that do exist answers a
    question nobody asked."""
    argv, out_dir = corpus(
        {"MEMBERA": json.dumps(_program("PROGA"))},
        extra=("--member", "MEMBERA", "MEMBERGONE"),
    )

    assert cli(argv) == 2

    assert not (out_dir / "edges.jsonl").exists()


def test_the_iteration_factor_reaches_the_fixpoint(corpus):
    """A member given up on at the default factor is re-runnable with more room,
    so the cap has to be settable from the command line."""
    argv, _ = corpus(
        {"MEMBERA": json.dumps(_program("PROGA"))}, extra=("--iteration-factor", "0")
    )

    assert cli(argv) == 3


def test_a_sweep_budget_analyses_the_member_and_reports_that_it_settled(corpus, capsys):
    argv, out_dir = corpus(
        {"MEMBERA": json.dumps(_program("PROGA"))}, extra=("--sweeps", "2")
    )

    assert cli(argv) == 0

    assert json.loads(capsys.readouterr().out)["unsettled"] == 0
    edge = json.loads((out_dir / "edges.jsonl").read_text(encoding="utf-8"))
    assert (edge["source"], edge["target"]) == ("PROGA.WS-A", "PROGA.WS-B")


def test_a_sweep_budget_below_one_is_a_usage_error(corpus):
    """Zero sweeps would select the worklist walk by the value that disables it."""
    argv, _ = corpus(
        {"MEMBERA": json.dumps(_program("PROGA"))}, extra=("--sweeps", "0")
    )

    with pytest.raises(SystemExit) as failure:
        cli(argv)

    assert failure.value.code == 2


def test_a_sweep_budget_and_an_iteration_factor_at_once_are_a_usage_error(corpus):
    """The two budgets belong to different walks; taking both would drop one."""
    argv, _ = corpus(
        {"MEMBERA": json.dumps(_program("PROGA"))},
        extra=("--sweeps", "2", "--iteration-factor", "100"),
    )

    with pytest.raises(SystemExit) as failure:
        cli(argv)

    assert failure.value.code == 2


def test_no_selection_is_a_usage_error(corpus):
    """A whole-corpus pass is asked for, never defaulted into."""
    argv, _ = corpus({"MEMBERA": json.dumps(_program("PROGA"))})
    without_selector = [argument for argument in argv if argument != "--all"]

    with pytest.raises(SystemExit) as failure:
        cli(without_selector)

    assert failure.value.code == 2


def test_both_selections_at_once_are_a_usage_error(corpus):
    argv, _ = corpus(
        {"MEMBERA": json.dumps(_program("PROGA"))},
        extra=("--all", "--member", "MEMBERA"),
    )

    with pytest.raises(SystemExit) as failure:
        cli(argv)

    assert failure.value.code == 2


def test_the_run_summary_reaches_stdout_for_a_pipeline(corpus, capsys):
    argv, _ = corpus({"MEMBERA": json.dumps(_program("PROGA"))})

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


def _linking(*targets: str) -> dict:
    """A member with one LINK per target, passing each of them the same WS-AREA.

    Its own MOVE is there so the run clears the coverage floor: the alias table is
    what is under test, and an exit 1 for coverage would hide it.
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
                "statements": [
                    _move("WS-HEAD", "WS-REST"),
                    *(_link(target, "WS-AREA") for target in targets),
                ],
            }
        ],
    }


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
    programs they declare rather than MEMBERA/MEMBERB.
    """
    argv, out_dir = corpus(
        {
            "XPROGA": json.dumps(_linking("XPROGB", "XPROGZ")),
            "XPROGB": json.dumps(_commarea_member("XPROGB", 12)),
        }
    )

    assert cli(argv) == 0

    rows = _rows(out_dir / ALIASES_FILE)
    assert {row["callee"] for row in rows} == {"XPROGB", ""}
    assert [row["reason"] for row in rows if row["reason"]] == ["callee-not-in-cache"]
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["aliased"] == 1
    assert summary["alias_dead_ends"] == {"callee-not-in-cache": 1}


def test_the_shared_window_is_the_shorter_of_the_two_declared_areas(corpus):
    """A row a cross-program consumer can cross: both sides, rebased, same length."""
    argv, out_dir = corpus(
        {
            "XPROGA": json.dumps(_linking("XPROGB", "XPROGZ")),
            "XPROGB": json.dumps(_commarea_member("XPROGB", 8)),
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
            "XPROGA": json.dumps(_linking("XPROGY", "XPROGZ")),
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
            "XPROGA": json.dumps(_linking("XPROGB", "XPROGZ")),
            "XPROGB": json.dumps(_commarea_member("XPROGB", 12)),
        },
        extra=("--iteration-factor", "0"),
    )

    assert cli(argv) == 3

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
        {"XPROGA": json.dumps(_linking("XPROGB")), "XPROGB": "null"},
        extra=("--member", "XPROGA"),
    )

    assert cli(argv) == 0

    for name in (NODES_FILE, EDGES_FILE, EXTENTS_FILE, DEFS_FILE):
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
            "XPROGA": json.dumps(_twice_declared_area("XPROGB")),
            "XPROGB": json.dumps(_commarea_member("XPROGB", 12)),
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
            "XPROGA": json.dumps(_linking("XPROGB", "XPROGZ")),
            "XPROGB": json.dumps(_commarea_member("XPROGB", 12)),
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
    argv, _ = corpus({"MEMBERA": json.dumps(_program("PROGA"))})

    with caplog.at_level(logging.INFO):
        assert cli(argv) == 0

    assert "commarea" not in caplog.text


def test_a_single_member_run_emits_that_members_outbound_aliases(corpus):
    """The callee cache is the whole ASG directory, not the selection: a run about
    one program still says which bytes it hands to the programs it calls."""
    argv, out_dir = corpus(
        {
            "XPROGA": json.dumps(_linking("XPROGB", "XPROGZ")),
            "XPROGB": json.dumps(_commarea_member("XPROGB", 12)),
        },
        extra=("--member", "XPROGA"),
    )

    assert cli(argv) == 0

    rows = _rows(out_dir / ALIASES_FILE)
    assert {row["caller"] for row in rows} == {"XPROGA"}
    assert [row["callee"] for row in rows if not row["reason"]] == ["XPROGB"]

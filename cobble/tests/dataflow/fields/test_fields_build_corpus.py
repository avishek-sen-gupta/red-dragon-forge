"""The corpus pass: one member per ASG file, and every member it could not read.

Named ``test_fields_build_corpus`` because ``tests/dataflow/srccfg`` already has a
``test_build_corpus.py`` and this tree carries no ``__init__.py``, so a duplicate
basename breaks collection outright.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cobble.dataflow.fields.build_corpus import cli


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

    Four writes rather than two so the read has four defining statements to
    distinguish: one flow per definer, all four sharing endpoints and extents, so
    ``source_node`` is the only thing that tells them apart.
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


def test_four_flows_differing_only_in_their_definer_all_reach_the_artefact(corpus):
    """The whole point of the pass, end to end: which statement defined the value.

    The unit tests cover the two halves separately -- emit puts source_node in
    attrs, GraphWriter keys FLOWS_TO on attrs -- and this is the only assertion
    that the artefact a consumer reads carries all four. Endpoint-level dedup
    wrote one of these rows and dropped three, and which one survived varied
    between runs."""
    argv, out_dir = corpus({"MEMBERA": json.dumps(_branched("PROGA"))})

    assert cli(argv) == 0

    rows = [
        json.loads(row)
        for row in (out_dir / "edges.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    read = [
        row
        for row in rows
        if (row["source"], row["target"]) == ("PROGA.WS-A", "PROGA.WS-B")
        and row["attrs"]["node"] == "MAIN/1"
    ]

    assert sorted(row["attrs"]["source_node"] for row in read) == [
        "MAIN/0.else.0.else.0",
        "MAIN/0.else.0.then.0",
        "MAIN/0.then.0.else.0",
        "MAIN/0.then.0.then.0",
    ]


def test_two_runs_of_one_member_write_byte_identical_edges(corpus):
    """An artefact that differs between identical runs cannot be diffed.

    The order of the four rows above comes out of frozensets -- the sources at an
    extent, the definers of one source -- so it varies with the per-process hash
    seed, which is why this runs the build in subprocesses rather than in-process
    where the seed is fixed. Four definers give twenty-four orders, so distinct
    seeds agreeing by chance is not what a pass here means."""
    argv, out_dir = corpus({"MEMBERA": json.dumps(_branched("PROGA"))})
    script = "import sys; from cobble.dataflow.fields.build_corpus import cli; sys.exit(cli(sys.argv[1:]))"

    written = []
    for seed in ("1", "5", "9"):
        run = subprocess.run(
            [sys.executable, "-c", script, *argv],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
        )
        assert run.returncode == 0, run.stderr.decode()
        written.append((out_dir / "edges.jsonl").read_bytes())

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


def test_expansion_adds_the_aliasing_views_to_each_edge(corpus):
    argv, out_dir = corpus(
        {"MEMBERA": json.dumps(_program("PROGA"))}, extra=("--expand",)
    )

    assert cli(argv) == 0

    edge = json.loads((out_dir / "edges.jsonl").read_text(encoding="utf-8"))
    assert edge["attrs"]["target_fields"] == "WS-B,REC"


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
    argv, _ = corpus({"MEMBERA": json.dumps(_program("PROGA"))}, extra=("--expand",))
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

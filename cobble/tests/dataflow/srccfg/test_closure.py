"""One program and the programs it calls, and nothing else in the cache.

A corpus pass answers "which members are missing from this output". A person reading
one program asks a different question, and building 3,779 CFGs to answer it costs
minutes and buries the nine graphs they wanted. The closure is the seed plus the
programs reachable from it through resolved LINK/XCTL/CALL targets -- transitively,
because a callee's callee is still on the path a field travels.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from cobble.dataflow.srccfg.bundle import bundle_of_rows
from cobble.dataflow.srccfg.cfg import EXTERNAL_ENTRY
from cobble.dataflow.srccfg.closure import build_closure, main
from cobble.dataflow.srccfg.presentation import cross_calls
from cobble.dataflow.srccfg.dynamic_targets import dynamic_targets_of
from cobble.dataflow.srccfg.rows.cfg_row import CFG_ROWS


def _asg(program: str, statements: list[dict]) -> dict:
    return {
        "program_id": program,
        "paragraphs": [{"name": "MAIN", "statements": statements}],
    }


def _move() -> dict:
    return {"type": "MOVE", "operands": [{"name": "'A'"}, {"name": "WS-FLAG-A"}]}


def _link(program: str, literal: bool = True) -> dict:
    return {
        "type": "EXEC_CICS",
        "verb": "LINK",
        "options": {"PROGRAM": {"text": program, "is_literal": literal}},
    }


def _cache(tmp_path: Path, members: dict[str, list[dict]]) -> Path:
    asg_dir = tmp_path / "parsed"
    asg_dir.mkdir(parents=True, exist_ok=True)
    for program, statements in members.items():
        (asg_dir / f"{program}.json").write_text(
            json.dumps({"programs": [_asg(program, statements)]})
        )
    return asg_dir


def _config(tmp_path: Path, asg_dir: Path, source_dir: Path = Path()) -> Path:
    config = tmp_path / "srccfg.toml"
    source_line = f'\nsource_dir = "{source_dir}"' if source_dir != Path() else ""
    config.write_text(f'[srccfg]\nasg_dir = "{asg_dir}"{source_line}\n')
    return config


def _programs(text: str) -> list[str]:
    rows = tuple(CFG_ROWS.validate_json(line) for line in text.splitlines() if line)
    return [cfg.program for cfg in bundle_of_rows(rows).cfgs]


def test_the_cli_writes_the_closure_to_stdout(tmp_path: Path, capsys) -> None:
    """stdout is the machine channel: the CFGs are the answer, so they go there and
    the log carries everything else."""
    asg_dir = _cache(tmp_path, {"PROGA": [_link("'PROGB'")], "PROGB": [_move()]})

    assert main(["--config", str(_config(tmp_path, asg_dir)), "PROGA"]) == 0
    assert _programs(capsys.readouterr().out) == ["PROGA", "PROGB"]


def test_output_sends_the_closure_to_a_file_and_leaves_stdout_empty(
    tmp_path: Path, capsys
) -> None:
    asg_dir = _cache(tmp_path, {"PROGA": [_move()]})
    out = tmp_path / "closure.jsonl"

    main(["--config", str(_config(tmp_path, asg_dir)), "PROGA", "--output", str(out)])

    assert _programs(out.read_text()) == ["PROGA"]
    assert capsys.readouterr().out == ""


def test_the_program_argument_is_required(tmp_path: Path) -> None:
    """Without it there is no seed, and the tool has nothing to build a closure of."""
    asg_dir = _cache(tmp_path, {"PROGA": [_move()]})

    with pytest.raises(SystemExit) as exit_info:
        main(["--config", str(_config(tmp_path, asg_dir))])

    assert exit_info.value.code == 2


def test_a_seed_with_no_asg_in_the_cache_is_an_error_not_an_empty_answer(
    tmp_path: Path, capsys
) -> None:
    """An empty list on stdout would read as "this program calls nothing"."""
    asg_dir = _cache(tmp_path, {"PROGA": [_move()]})

    assert main(["--config", str(_config(tmp_path, asg_dir)), "PROGZ"]) == 1
    assert capsys.readouterr().out == ""


def test_a_program_that_calls_nothing_is_a_closure_of_one(tmp_path: Path) -> None:
    asg_dir = _cache(tmp_path, {"PROGA": [_move()], "PROGB": [_move()]})

    bundle = build_closure(asg_dir, "PROGA", Path())

    assert [cfg.program for cfg in bundle.cfgs] == ["PROGA"]


def test_a_called_program_is_built_after_its_caller(tmp_path: Path) -> None:
    asg_dir = _cache(tmp_path, {"PROGA": [_link("'PROGB'")], "PROGB": [_move()]})

    bundle = build_closure(asg_dir, "PROGA", Path())

    assert [cfg.program for cfg in bundle.cfgs] == ["PROGA", "PROGB"]


def test_a_callee_of_a_callee_is_in_the_closure(tmp_path: Path) -> None:
    """The reason the closure is transitive: a field the seed passes down two calls
    is still written by the program at the bottom."""
    asg_dir = _cache(
        tmp_path,
        {
            "PROGA": [_link("'PROGB'")],
            "PROGB": [_link("'PROGC'")],
            "PROGC": [_move()],
        },
    )

    bundle = build_closure(asg_dir, "PROGA", Path())

    assert [cfg.program for cfg in bundle.cfgs] == ["PROGA", "PROGB", "PROGC"]


def test_a_callee_with_no_asg_in_the_cache_is_an_external_one_node_program(
    tmp_path: Path, caplog
) -> None:
    """A callee the cache does not hold -- another subsystem's module, most often --
    is named on the log and stands in the closure as an external program of one
    node and no structure: its call lands on that node, and the caller carries on
    past the call as it would after any other."""
    asg_dir = _cache(tmp_path, {"PROGA": [_link("'PROGB'")]})

    with caplog.at_level(logging.WARNING):
        bundle = build_closure(asg_dir, "PROGA", Path())

    stub = bundle.cfgs[1]
    (call,) = bundle.calls
    assert (
        [(cfg.program, cfg.external) for cfg in bundle.cfgs],
        stub.nodes,
        stub.edges,
        (call.program, call.entry),
        len(cross_calls(bundle.cfgs, bundle.calls)),
        caplog.messages,
    ) == (
        [("PROGA", False), ("PROGB", True)],
        (EXTERNAL_ENTRY,),
        (),
        ("PROGB", EXTERNAL_ENTRY.id),
        1,
        ["PROGB: called but not in the ASG cache; an external stub stands in"],
    )


def test_two_programs_that_call_each_other_are_each_built_once(tmp_path: Path) -> None:
    """Mutual calls are ordinary on a real corpus, and a walk with no memory of what
    it has built does not terminate on them."""
    asg_dir = _cache(
        tmp_path, {"PROGA": [_link("'PROGB'")], "PROGB": [_link("'PROGA'")]}
    )

    bundle = build_closure(asg_dir, "PROGA", Path())

    assert [cfg.program for cfg in bundle.cfgs] == ["PROGA", "PROGB"]


def test_a_closure_longer_than_the_interpreter_stack_is_built(tmp_path: Path) -> None:
    """Following dynamic calls makes closures long, and a walk that recurses once
    per program dies at a thousand of them."""
    chain = [f"PROG{n:04d}" for n in range(1100)]
    asg_dir = _cache(
        tmp_path,
        {
            **{
                caller: [_link(f"'{callee}'")]
                for caller, callee in zip(chain, chain[1:])
            },
            chain[-1]: [_move()],
        },
    )

    bundle = build_closure(asg_dir, chain[0], Path())

    assert [cfg.program for cfg in bundle.cfgs] == chain


def _target_row(
    caller: str, node: str, field: str, candidates: list[str], reasons: list[str]
) -> dict:
    return {
        "caller": caller,
        "node": node,
        "transfer": "CICS_LINK",
        "expression": field,
        "candidates": candidates,
        "reasons": reasons,
        "dropped": [],
    }


def _targets_file(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "targets.jsonl"
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows))
    return path


def _dynamic_corpus(tmp_path: Path) -> tuple[Path, Path]:
    asg_dir = _cache(
        tmp_path,
        {
            "PROGA": [
                _link("WS-ONE", literal=False),
                _link("WS-TWO", literal=False),
                _link("WS-NONE", literal=False),
                _move(),
            ],
            "PROGB": [_move()],
            "PROGC": [_link("WS-NEXT", literal=False)],
            "PROGD": [_move()],
            "PROGZ": [_move()],
        },
    )
    targets = _targets_file(
        tmp_path,
        [
            _target_row("PROGA", "MAIN/0", "WS-ONE", ["PROGB"], []),
            _target_row(
                "PROGA", "MAIN/1", "WS-TWO", ["PROGB", "PROGC"], ["from-callee"]
            ),
            _target_row("PROGA", "MAIN/2", "WS-NONE", [], ["uninitialised"]),
            _target_row("PROGC", "MAIN/0", "WS-NEXT", ["PROGD"], []),
            {
                **_target_row("PROGA", "MAIN/3", "WS-FILE", ["PROGZ"], []),
                "kind": "file",
                "transfer": "CICS_READ",
            },
        ],
    )
    return asg_dir, targets


def test_a_dynamic_call_pulls_in_every_candidate_and_each_candidates_own(
    tmp_path: Path,
) -> None:
    asg_dir, targets = _dynamic_corpus(tmp_path)

    bundle = build_closure(asg_dir, "PROGA", Path(), dynamic_targets_of(targets))

    assert [cfg.program for cfg in bundle.cfgs] == ["PROGA", "PROGB", "PROGC", "PROGD"]
    assert [
        (c.caller, c.node, c.program, c.entry, c.expression, c.reasons, c.certain)
        for c in bundle.calls
    ] == [
        ("PROGA", "MAIN/0", "PROGB", "MAIN#label", "WS-ONE", (), True),
        ("PROGA", "MAIN/1", "PROGB", "MAIN#label", "WS-TWO", ("from-callee",), False),
        ("PROGA", "MAIN/1", "PROGC", "MAIN#label", "WS-TWO", ("from-callee",), False),
        ("PROGA", "MAIN/2", "WS-NONE", "", "WS-NONE", ("uninitialised",), False),
        ("PROGC", "MAIN/0", "PROGD", "MAIN#label", "WS-NEXT", (), True),
    ]


def test_the_cli_follows_dynamic_calls_only_when_given_the_targets(
    tmp_path: Path, capsys
) -> None:
    asg_dir, targets = _dynamic_corpus(tmp_path)
    config = str(_config(tmp_path, asg_dir))

    assert main(["--config", config, "PROGA"]) == 0
    without = _programs(capsys.readouterr().out)
    assert (
        main(["--config", config, "--dynamic-call-targets", str(targets), "PROGA"]) == 0
    )
    with_targets = _programs(capsys.readouterr().out)

    assert without == ["PROGA"]
    assert with_targets == [
        "PROGA",
        "PROGB",
        "PROGC",
        "PROGD",
    ]


def test_a_named_targets_file_that_does_not_exist_stops_the_build(
    tmp_path: Path, capsys
) -> None:
    asg_dir, _ = _dynamic_corpus(tmp_path)
    missing = tmp_path / "nowhere" / "targets.jsonl"

    with pytest.raises(SystemExit) as stopped:
        main(
            [
                "--config",
                str(_config(tmp_path, asg_dir)),
                "--dynamic-call-targets",
                str(missing),
                "PROGA",
            ]
        )

    assert stopped.value.code == 2
    assert capsys.readouterr().out == ""


def _move_with_span() -> dict:
    return {
        "type": "MOVE",
        "operands": [{"name": "'A'"}, {"name": "WS-FLAG-A"}],
        "line_start": 10,
        "col_start": 12,
        "line_end": 10,
        "col_end": 50,
    }


def test_source_file_is_annotated_when_source_dir_is_given(tmp_path: Path) -> None:
    """build_closure threads source_dir so every CFG node carries its source path."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    asg_dir = _cache(
        tmp_path, {"PROGA": [_move_with_span()], "PROGB": [_move_with_span()]}
    )

    bundle = build_closure(asg_dir, "PROGA", source_dir)

    spanned = [n for n in bundle.cfgs[0].nodes if n.span.source_file]
    assert len(spanned) > 0
    assert spanned[0].span.source_file == "src/PROGA.txt"


def test_source_file_is_empty_when_source_dir_is_empty(tmp_path: Path) -> None:
    asg_dir = _cache(tmp_path, {"PROGA": [_move()]})

    bundle = build_closure(asg_dir, "PROGA", Path())

    assert all(n.span.source_file == "" for n in bundle.cfgs[0].nodes)

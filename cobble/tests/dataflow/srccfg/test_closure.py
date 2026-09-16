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

from cobble.dataflow.srccfg.closure import build_closure, main


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
        (asg_dir / f"{program}.json").write_text(json.dumps(_asg(program, statements)))
    return asg_dir


def _config(tmp_path: Path, asg_dir: Path, source_dir: Path = Path()) -> Path:
    config = tmp_path / "srccfg.toml"
    source_line = f'\nsource_dir = "{source_dir}"' if source_dir != Path() else ""
    config.write_text(f'[srccfg]\nasg_dir = "{asg_dir}"{source_line}\n')
    return config


def test_the_cli_writes_the_closure_to_stdout(tmp_path: Path, capsys) -> None:
    """stdout is the machine channel: the CFGs are the answer, so they go there and
    the log carries everything else."""
    asg_dir = _cache(tmp_path, {"PROGA": [_link("'PROGB'")], "PROGB": [_move()]})

    assert main(["--config", str(_config(tmp_path, asg_dir)), "PROGA"]) == 0
    written = json.loads(capsys.readouterr().out)
    assert [cfg["program"] for cfg in written] == ["PROGA", "PROGB"]


def test_output_sends_the_closure_to_a_file_and_leaves_stdout_empty(
    tmp_path: Path, capsys
) -> None:
    asg_dir = _cache(tmp_path, {"PROGA": [_move()]})
    out = tmp_path / "closure.json"

    main(["--config", str(_config(tmp_path, asg_dir)), "PROGA", "--output", str(out)])

    assert [cfg["program"] for cfg in json.loads(out.read_text())] == ["PROGA"]
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


def test_a_callee_with_no_asg_in_the_cache_does_not_end_the_run(
    tmp_path: Path, caplog
) -> None:
    """The seed is what was asked for. A callee the cache does not hold -- another
    subsystem's module, most often -- is named on the log and the rest is built."""
    asg_dir = _cache(tmp_path, {"PROGA": [_link("'PROGB'")]})

    with caplog.at_level(logging.WARNING):
        bundle = build_closure(asg_dir, "PROGA", Path())

    assert [cfg.program for cfg in bundle.cfgs] == ["PROGA"]
    assert "PROGB" in caplog.text


def test_two_programs_that_call_each_other_are_each_built_once(tmp_path: Path) -> None:
    """Mutual calls are ordinary on a real corpus, and a walk with no memory of what
    it has built does not terminate on them."""
    asg_dir = _cache(
        tmp_path, {"PROGA": [_link("'PROGB'")], "PROGB": [_link("'PROGA'")]}
    )

    bundle = build_closure(asg_dir, "PROGA", Path())

    assert [cfg.program for cfg in bundle.cfgs] == ["PROGA", "PROGB"]


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

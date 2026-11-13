"""What a person sees. Two queries, plain lines, no name in a log record.

The reports are the only part of this whose correctness a reader can check by hand
against a listing, so each line names the node it is claiming something about.
"""

from __future__ import annotations

import json
from pathlib import Path

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.bundle import Bundle, bundle_jsonl
from cobble.dataflow.srccfg.coassign import Tier
from cobble.dataflow.srccfg.query import (
    coassign_report,
    main,
    provenance_report,
)


def _asg(statements: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(
            {
                "program_id": "PROGA",
                "paragraphs": [{"name": "MAIN", "statements": statements}],
            }
        )


def _move(value: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


def _if(condition: dict, then: list[dict], otherwise: list[dict]) -> dict:
    return {
        "type": "IF",
        "condition": condition,
        "children": then,
        "else_children": otherwise,
    }


def _rel(left: str, right: str) -> dict:
    return {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": "==",
            "right": {"kind": "lit", "value": right},
        },
    }


def _guarded_cfg():
    return build_program(
        _asg(
            [
                _move("WS-IN", "WS-MID"),
                _if(_rel("WS-FLAG-A", "'Y'"), [_move("WS-MID", "WS-OUT")], []),
            ]
        )
    )


def _written(tmp_path: Path):
    cfg = _guarded_cfg()
    path = tmp_path / "PROGA.jsonl"
    path.write_text(bundle_jsonl(Bundle(seed=cfg.program, cfgs=(cfg,))))
    return path


def test_every_writing_node_is_named_with_its_verb() -> None:
    lines = provenance_report(_guarded_cfg(), "WS-OUT")

    assert lines[:4] == (
        "WS-OUT in PROGA:",
        "backward -- what its value is derived from:",
        "  WS-OUT <-",
        "  MAIN/1.then.0 MOVE",
    )


def test_a_field_nothing_writes_says_so() -> None:
    """The commonest real answer for a field filled by a caller or a file read, and an
    empty report would read as a failed query."""
    lines = provenance_report(_guarded_cfg(), "WS-NEVER")

    assert any("written nowhere in this member" in line for line in lines)


def test_the_provenance_report_follows_the_chain_back_to_a_source() -> None:
    """WS-OUT comes from WS-MID which comes from WS-IN, and the chain is the answer
    -- one level would stop at the intermediate and say nothing useful."""
    lines = provenance_report(_guarded_cfg(), "WS-OUT")

    assert any("WS-MID" in line for line in lines)
    assert any("WS-IN" in line for line in lines)


def test_the_provenance_report_indents_by_depth() -> None:
    lines = provenance_report(_guarded_cfg(), "WS-OUT")
    depths = [len(line) - len(line.lstrip()) for line in lines if line.strip()]

    assert len(set(depths)) > 1


def test_a_derivation_deeper_than_the_cap_says_it_was_truncated() -> None:
    """Silently stopping is the one failure that turns a useful report into a wrong
    one: the last field shown reads as the source."""
    chain = [_move("WS-F0", "WS-F1"), _move("WS-F1", "WS-F2"), _move("WS-F2", "WS-F3")]
    cfg = build_program(_asg(chain))

    lines = provenance_report(cfg, "WS-F3", max_depth=1)

    assert any("truncated" in line for line in lines)


def test_a_cyclic_derivation_terminates() -> None:
    """COMPUTE WS-A = WS-A + 1 is everywhere, and a naive chase never returns.

    F7: asserting the report is non-empty cannot fail -- the first line is an
    f-string of the arguments, so it is there whether or not the cycle is cut, and a
    chase that did not return would hang or raise rather than return something falsy.
    The evidence that the cycle was CUT is the "(already shown)" line: WS-A is
    reached a second time through its own writer and named without being re-expanded.
    R91: assert the whole report, so a change that drops that line is caught.

    Both directions have to be cut, and the same statement cuts both: MAIN/1 reads
    WS-A and writes WS-A, so a forward chase re-expands it exactly as a backward one
    does. One ``seen`` set, checked before either arrow is followed."""
    cfg = build_program(_asg([_move("'0'", "WS-A"), _move("WS-A", "WS-A")]))

    assert provenance_report(cfg, "WS-A") == (
        "WS-A in PROGA:",
        "backward -- what its value is derived from:",
        "  WS-A <-",
        "  MAIN/0 MOVE",
        "    WS-A <- source (literal-only operands)",
        "  MAIN/1 MOVE",
        "    WS-A (already shown)",
        "forward -- what its value reaches:",
        "  WS-A ->",
        "  MAIN/1 MOVE",
        "    WS-A (already shown)",
    )


def test_the_forward_half_follows_the_value_on_through_its_readers() -> None:
    """The half a backward-only report cannot give: whether the field matters.

    WS-MID is derived from WS-IN and read on into WS-OUT, and a review of a field
    suspected of being wrong needs the second of those to know what the wrongness
    reaches. Assert the whole report so a chain that stops one hop short is caught."""
    assert provenance_report(_guarded_cfg(), "WS-MID") == (
        "WS-MID in PROGA:",
        "backward -- what its value is derived from:",
        "  WS-MID <-",
        "  MAIN/0 MOVE",
        "    WS-IN <- source (written nowhere in this member)",
        "forward -- what its value reaches:",
        "  WS-MID ->",
        "  MAIN/1.then.0 MOVE",
        "    WS-OUT -> sink (read nowhere in this member)",
    )


def test_a_field_that_only_decides_a_branch_is_reported_as_reaching_that_test() -> None:
    """A TEST holds its operands in the atom, not in node.reads.

    So a flag read by nothing but an IF has no reader at all if node.reads is the
    whole search -- and "read nowhere in this member" of a field that decides every
    write in the paragraph is the most misleading answer this report can give. The
    line has to name the test AND say the value stopped there, because a TEST has no
    target field to chase and a chain that just ended would read as truncation."""
    lines = provenance_report(_guarded_cfg(), "WS-FLAG-A")
    forward = lines[lines.index("forward -- what its value reaches:") + 1 :]

    assert forward == (
        "  WS-FLAG-A ->",
        "  MAIN/1#test TEST",
        "    WS-FLAG-A -> decides this branch (no target field)",
    )


def test_a_forward_chase_deeper_than_the_cap_says_it_was_truncated() -> None:
    """The backward cap is load-bearing in both directions, for the same reason: the
    last field shown reads as the end of the flow when the chase was merely cut."""
    chain = [_move("WS-F0", "WS-F1"), _move("WS-F1", "WS-F2"), _move("WS-F2", "WS-F3")]
    lines = provenance_report(build_program(_asg(chain)), "WS-F0", max_depth=1)
    forward = lines[lines.index("forward -- what its value reaches:") + 1 :]

    assert any("truncated at depth 1" in line for line in forward)


def test_the_coassign_report_shows_the_tier_of_each_candidate() -> None:
    """The tier is the whole reason a reader can act on the answer, so it cannot be
    dropped to make the line shorter."""
    cfg = build_program(_asg([_move("WS-IN", "WS-A"), _move("WS-IN", "WS-B")]))

    lines = coassign_report(cfg, "WS-A")

    assert any("SAME_SOURCE" in line and "WS-B" in line for line in lines)


def test_the_coassign_report_honours_min_tier() -> None:
    cfg = build_program(_asg([_move("'1'", "WS-A"), _move("'2'", "WS-B")]))

    assert coassign_report(cfg, "WS-A", min_tier=Tier.SAME_SOURCE) == (
        "WS-A: no co-assignment candidates at tier SAME_SOURCE or stronger",
    )


def _written_pair(tmp_path: Path) -> Path:
    """The shape cobble-srccfg-build writes: a seed and its callees in one file."""
    from dataclasses import replace

    seed = _guarded_cfg()
    path = tmp_path / "closure.jsonl"
    path.write_text(
        bundle_jsonl(
            Bundle(seed=seed.program, cfgs=(seed, replace(seed, program="PROGB")))
        )
    )
    return path


def test_a_file_holding_several_programs_is_queried_across_every_one(
    tmp_path: Path, capsys
) -> None:
    """cobble-srccfg-build writes the seed and its callees as one document, and a
    query CLI that can only read a single-program file cannot be pointed at its own
    build stage's output."""
    exit_code = main(["provenance", "WS-OUT", "--cfg", str(_written_pair(tmp_path))])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "PROGA" in output
    assert "PROGB" in output


def test_a_program_that_does_not_write_the_field_is_still_reported_on(
    tmp_path: Path, capsys
) -> None:
    """A program dropped from the output reads as one that was never searched, which
    is the opposite of what a "written nowhere" answer is for.

    The chain lines say "this member" rather than naming the program, so the heading
    is what carries which one -- assert both together, because either alone would
    pass while the report had stopped saying whose answer this is."""
    from dataclasses import replace

    seed = _guarded_cfg()
    other = replace(seed, program="PROGB", nodes=(), edges=())
    path = tmp_path / "closure.jsonl"
    path.write_text(bundle_jsonl(Bundle(seed=seed.program, cfgs=(seed, other))))

    main(["provenance", "WS-OUT", "--cfg", str(path)])

    output = capsys.readouterr().out
    assert "WS-OUT in PROGB:" in output
    assert "written nowhere in this member" in output


def test_a_single_program_file_prints_exactly_what_the_report_returns(
    tmp_path: Path, capsys
) -> None:
    """The per-member files build_one writes stay readable, unchanged, with no
    heading added around the one report."""
    main(["provenance", "WS-OUT", "--cfg", str(_written(tmp_path))])

    expected = provenance_report(_guarded_cfg(), "WS-OUT")
    assert capsys.readouterr().out == "".join(f"{line}\n" for line in expected)


def test_the_cli_prints_the_provenance_report_to_stdout(tmp_path: Path, capsys) -> None:
    exit_code = main(["provenance", "WS-OUT", "--cfg", str(_written(tmp_path))])

    assert exit_code == 0
    assert "MAIN/1" in capsys.readouterr().out


def test_the_cli_keeps_field_names_out_of_the_log(tmp_path: Path, caplog) -> None:
    """Field names are corpus identifiers. stdout is where the answer goes; a log
    record gets tailed in a shared terminal."""
    import logging

    caplog.set_level(logging.DEBUG)

    main(["provenance", "WS-OUT", "--cfg", str(_written(tmp_path))])

    assert "WS-OUT" not in caplog.text


def test_an_unknown_query_exits_non_zero_without_a_traceback(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(SystemExit) as caught:
        main(["nonsense", "WS-OUT", "--cfg", str(_written(tmp_path))])

    assert caught.value.code == 2


def test_a_missing_cfg_file_exits_non_zero_with_a_message(
    tmp_path: Path, capsys
) -> None:
    """A CFG path is typed by hand, so a wrong one is the commonest failure -- and it
    must not look like "this field has no writers"."""
    exit_code = main(["provenance", "WS-OUT", "--cfg", str(tmp_path / "gone.json")])

    assert exit_code == 2
    assert "gone.json" in capsys.readouterr().err


def test_literal_only_operands_say_so() -> None:
    """F2: When a writer has only literal operands (MOVE SPACES TO X), the derivation
    should explain why it stops, not just end silently.

    R90: the terminus line names the field it terminates, because a report of many
    writers puts several of these lines under one heading and "<- source (...)" with
    no subject leaves the reader counting indentation to work out which."""
    cfg = build_program(_asg([_move("SPACES", "WS-LIT")]))

    assert provenance_report(cfg, "WS-LIT") == (
        "WS-LIT in PROGA:",
        "backward -- what its value is derived from:",
        "  WS-LIT <-",
        "  MAIN/0 MOVE",
        "    WS-LIT <- source (literal-only operands)",
        "forward -- what its value reaches:",
        "  WS-LIT -> sink (read nowhere in this member)",
    )


def test_identity_operand_labeled_as_external() -> None:
    """F5: PROGRAM:PROGB should be labeled as an external identifier, not
    'written nowhere in this member'."""
    # Create a CFG that reads from a PROGRAM: identity
    cfg = build_program(
        _asg(
            [
                {
                    "type": "MOVE",
                    "operands": [{"name": "PROGRAM:PROGB"}, {"name": "WS-OUT"}],
                }
            ]
        )
    )
    lines = provenance_report(cfg, "WS-OUT")

    # Should label it as external identifier, not missing field
    assert any("external identifier" in line and "PROGRAM" in line for line in lines)
    assert not any("written nowhere" in line for line in lines if "PROGRAM" in line)


def test_a_synthetic_handler_field_is_named_as_synthetic_not_as_a_gap() -> None:
    """F5: the ``%`` family had constructors in four modules and no classifier.

    A command that can raise is followed by a test of ``%HANDLER[ANY] RAISED``, and the
    definition of that name is an ASSIGN two nodes away. Reporting it as written
    nowhere in the member is the worst kind of wrong answer: a real gap and an invented
    name print identically, so the reader cannot tell which lines to investigate.

    R91: the whole report, because the bug was a line that should not exist."""
    cfg = build_program(
        _asg(
            [
                {
                    "type": "EXEC_CICS",
                    "verb": "RECEIVE MAP",
                    "options": {"MAP": {"text": "'MAPA'", "is_literal": True}},
                },
                _move("'F'", "WS-RESULT"),
            ]
        )
    )

    assert provenance_report(cfg, "%HANDLER[ANY]") == (
        "%HANDLER[ANY] in PROGA:",
        "backward -- what its value is derived from:",
        "  %HANDLER[ANY] <- synthetic (the handler armed for ANY)",
        "forward -- what its value reaches:",
        "  %HANDLER[ANY] -> synthetic (the handler armed for ANY)",
    )

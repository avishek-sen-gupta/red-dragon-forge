"""What a person sees. Three queries, plain lines, no name in a log record.

The reports are the only part of this whose correctness a reader can check by hand
against a listing, so each line names the node it is claiming something about.
"""

from __future__ import annotations

import json
from pathlib import Path

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.build_corpus import cfg_to_dict
from cobble.dataflow.srccfg.coassign import Tier
from cobble.dataflow.srccfg.query import (
    coassign_report,
    guards_report,
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
    path = tmp_path / "PROGA.json"
    path.write_text(json.dumps(cfg_to_dict(cfg)))
    return path


def test_every_writing_node_is_named_with_the_guard_of_its_write() -> None:
    """A write with no guard shown reads as unconditional, and 65% of them are not."""
    lines = provenance_report(_guarded_cfg(), "WS-OUT")

    assert any("MAIN/1" in line for line in lines)
    assert any("WS-FLAG-A" in line for line in lines)


def test_an_unguarded_write_says_so_rather_than_showing_nothing() -> None:
    """A blank where the guard goes is indistinguishable from a bug in the pass."""
    lines = provenance_report(_guarded_cfg(), "WS-MID")

    assert any("unconditional" in line for line in lines)


def test_a_field_nothing_writes_says_so() -> None:
    """The commonest real answer for a field filled by a caller or a file read, and an
    empty report would read as a failed query."""
    lines = provenance_report(_guarded_cfg(), "WS-NEVER")

    assert any("written nowhere in this member" in line for line in lines)


def test_the_guards_report_prints_one_line_per_path() -> None:
    cfg = build_program(
        _asg(
            [
                _if(_rel("WS-FLAG-A", "'Y'"), [_move("'1'", "WS-X")], []),
                _move("'2'", "WS-AFTER"),
            ]
        )
    )
    writer = next(node.id for node in cfg.nodes if "WS-AFTER" in node.writes)

    lines = guards_report(cfg, writer)

    assert len([line for line in lines if line.startswith("  path")]) == 2


def test_a_negated_guard_reads_as_not() -> None:
    cfg = build_program(
        _asg([_if(_rel("WS-FLAG-A", "'Y'"), [], [_move("'B'", "WS-OUT")])])
    )
    writer = next(node.id for node in cfg.nodes if "WS-OUT" in node.writes)

    assert any("NOT" in line for line in guards_report(cfg, writer))


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
        "  MAIN/0 MOVE when unconditional",
        "    WS-A <- source (literal-only operands)",
        "  MAIN/1 MOVE when unconditional",
        "    WS-A (already shown)",
        "forward -- what its value reaches:",
        "  WS-A ->",
        "  MAIN/1 MOVE when unconditional",
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
        "  MAIN/0 MOVE when unconditional",
        "    WS-IN <- source (written nowhere in this member)",
        "forward -- what its value reaches:",
        "  WS-MID ->",
        "  MAIN/1.then.0 MOVE when WS-FLAG-A == 'Y'",
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
        "  MAIN/1#test TEST when unconditional",
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
    path = tmp_path / "closure.json"
    path.write_text(
        json.dumps([cfg_to_dict(seed), cfg_to_dict(replace(seed, program="PROGB"))])
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
    path = tmp_path / "closure.json"
    path.write_text(json.dumps([cfg_to_dict(seed), cfg_to_dict(other)]))

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


# F1: Guard-operand union (control dependencies) tests
# R91: Assert exact output or check for indented dependency chains, not substring searches


def test_a_field_in_a_guard_appears_in_derivation() -> None:
    """F1: Control dependencies. A field written under IF WS-FLAG = 'Y' should show
    WS-FLAG in its derivation chain with its own indented writer line.

    R91: The distinguishing evidence is WS-FLAG <- appearing as an indented line,
    not just the field name in guard text."""
    cfg = build_program(
        _asg([_if(_rel("WS-FLAG", "'Y'"), [_move("WS-SRC", "WS-DEST")], [])])
    )
    lines = provenance_report(cfg, "WS-DEST")

    # Find the index of WS-FLAG <- which proves it was harvested as a control dependency
    flag_indices = [i for i, line in enumerate(lines) if "WS-FLAG <-" in line]
    assert flag_indices, "WS-FLAG should appear with <- as a control dependency"

    # Also check data dependency appears
    src_indices = [i for i, line in enumerate(lines) if "WS-SRC <-" in line]
    assert src_indices, "WS-SRC should appear with <- as a data dependency"


def test_nested_guards_show_both_control_dependencies() -> None:
    """F1: Nested IFs. A write under two conditions should list both guard fields
    with their own indented dependency lines.

    R91: Both WS-FLAG-A <- and WS-FLAG-B <- must appear as indented lines."""
    cfg = build_program(
        _asg(
            [
                _if(
                    _rel("WS-FLAG-A", "'Y'"),
                    [_if(_rel("WS-FLAG-B", "'X'"), [_move("WS-IN", "WS-OUT")], [])],
                    [],
                )
            ]
        )
    )
    lines = provenance_report(cfg, "WS-OUT")

    # Both flags must appear with <- proving they were harvested
    assert any(
        "WS-FLAG-A <-" in line for line in lines
    ), "WS-FLAG-A should appear as control dependency"
    assert any(
        "WS-FLAG-B <-" in line for line in lines
    ), "WS-FLAG-B should appear as control dependency"


def test_else_arm_guard_shows_false_polarity_field() -> None:
    """F1: FALSE-polarity guard. A write in the ELSE arm depends on the negated
    condition, and WS-CHECK must appear with its own dependency line.

    R91: WS-CHECK <- must appear as an indented line."""
    cfg = build_program(
        _asg([_if(_rel("WS-CHECK", "'N'"), [], [_move("WS-IN", "WS-OUT")])])
    )
    lines = provenance_report(cfg, "WS-OUT")

    # WS-CHECK must appear with <- proving it was harvested even on ELSE arm
    assert any(
        "WS-CHECK <-" in line for line in lines
    ), "WS-CHECK should appear as control dependency on ELSE arm"


def test_multiple_paths_with_different_guards_union() -> None:
    """F1: Union across paths. A field written on two paths with different guards
    should show both guard fields with their own dependency lines.

    R91: Both WS-FLAG-A <- and WS-FLAG-B <- must appear."""
    cfg = build_program(
        _asg(
            [
                _if(_rel("WS-FLAG-A", "'Y'"), [_move("'1'", "WS-OUT")], []),
                _if(_rel("WS-FLAG-B", "'X'"), [_move("'2'", "WS-OUT")], []),
            ]
        )
    )
    lines = provenance_report(cfg, "WS-OUT")

    # Both flags from both paths must appear with <-
    assert any(
        "WS-FLAG-A <-" in line for line in lines
    ), "WS-FLAG-A from first path should appear"
    assert any(
        "WS-FLAG-B <-" in line for line in lines
    ), "WS-FLAG-B from second path should appear"


def test_field_to_field_condition_includes_right_side() -> None:
    """F1: Field-to-field condition. IF WS-FIELD-A = WS-FIELD-B makes both fields
    dependencies, and both must appear with their own dependency lines.

    R91: Both WS-FIELD-A <- and WS-FIELD-B <- must appear, proving both sides
    were harvested from atom.left and atom.right."""
    cfg = build_program(
        _asg(
            [
                {
                    "type": "IF",
                    "condition": {
                        "not": False,
                        "relation": {
                            "left": {"kind": "ref", "name": "WS-FIELD-A"},
                            "op": "==",
                            "right": {"kind": "ref", "name": "WS-FIELD-B"},
                        },
                    },
                    "children": [_move("'X'", "WS-OUT")],
                    "else_children": [],
                }
            ]
        )
    )
    lines = provenance_report(cfg, "WS-OUT")

    # Both sides of the condition must appear with <-
    assert any(
        "WS-FIELD-A <-" in line for line in lines
    ), "WS-FIELD-A (left side) should appear"
    assert any(
        "WS-FIELD-B <-" in line for line in lines
    ), "WS-FIELD-B (right side) should appear"


def test_literals_not_harvested_as_control_dependencies() -> None:
    """F1: Literal filter. A guard like IF WS-FLAG = 'Y' should harvest WS-FLAG
    but not 'Y', and the literal should not appear as a dependency line.

    R91: 'Y' should NOT appear with its own <- line."""
    cfg = build_program(
        _asg([_if(_rel("WS-FLAG", "'Y'"), [_move("WS-SRC", "WS-DEST")], [])])
    )
    lines = provenance_report(cfg, "WS-DEST")

    # Literal 'Y' should NOT appear as a dependency with <-
    assert not any(
        "'Y' <-" in line for line in lines
    ), "Literal 'Y' should not appear as a control dependency"

    # But WS-FLAG should
    assert any(
        "WS-FLAG <-" in line for line in lines
    ), "WS-FLAG should appear as control dependency"


# F2: Literal terminus test


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
        "  MAIN/0 MOVE when unconditional",
        "    WS-LIT <- source (literal-only operands)",
        "forward -- what its value reaches:",
        "  WS-LIT -> sink (read nowhere in this member)",
    )


def test_an_unresolved_guard_is_not_reported_as_literal_operands() -> None:
    """F6: two different terminal states were printed with one wording.

    A condition shape this pass cannot decompose yields UNRESOLVED: the leaf survives
    so no path is lost, but there are no operands to chase. Saying "literal-only
    operands" of it contradicts the node line directly above, which prints UNRESOLVED,
    and tells the reader the write depends on nothing when the truth is that what it
    depends on is unknown -- the honest-reporting invariant, in one line."""
    cfg = build_program(
        _asg(
            [
                {
                    "type": "IF",
                    "condition": {"unrecognised_shape": "x"},
                    "children": [_move("SPACES", "WS-OUT")],
                    "else_children": [],
                }
            ]
        )
    )

    assert provenance_report(cfg, "WS-OUT") == (
        "WS-OUT in PROGA:",
        "backward -- what its value is derived from:",
        "  WS-OUT <-",
        "  MAIN/0.then.0 MOVE when UNRESOLVED",
        "    WS-OUT <- source (unresolved condition, no operands to follow)",
        "forward -- what its value reaches:",
        "  WS-OUT -> sink (read nowhere in this member)",
    )


# F3: Abandoned/truncated/overflowed coverage tests
# R91: Call the real implementation with synthesized Reaching, not inline logic copy


def test_abandoned_node_says_walk_gave_up() -> None:
    """F3: A node in reaching.abandoned should report 'route not found by walk',
    not 'unreachable'. Load-bearing."""
    from cobble.dataflow.srccfg.dataflow import Reaching

    # Create a simple CFG
    cfg = build_program(_asg([_move("WS-A", "WS-B")]))
    node_id = next(n.id for n in cfg.nodes if "WS-B" in n.writes)

    # Manually construct a Reaching with this node in abandoned
    reaching = Reaching(guards={}, abandoned=frozenset([node_id]))

    from cobble.dataflow.srccfg.query import _guard_lines

    lines = _guard_lines(cfg, reaching, node_id).texts

    assert any("route not found by walk" in line for line in lines)
    assert not any("unreachable" in line for line in lines)


def test_overflowed_node_says_cap_hit() -> None:
    """F3: A node in reaching.overflowed should report that the guard cap was hit.

    R91: Call guards_report with a real Reaching that has overflowed set."""
    from unittest.mock import patch

    from cobble.dataflow.srccfg.dataflow import Reaching, reaching_conditions

    # Build a CFG and get actual reaching conditions
    cfg = build_program(_asg([_move("WS-A", "WS-B")]))
    node_id = next(n.id for n in cfg.nodes if "WS-B" in n.writes)

    # Get the real reaching, then construct a modified one with overflowed
    real_reaching = reaching_conditions(cfg)
    test_reaching = Reaching(
        guards=real_reaching.guards,
        truncated=real_reaching.truncated,
        overflowed=frozenset([node_id]),  # Mark this node as overflowed
        abandoned=real_reaching.abandoned,
    )

    # Patch reaching_conditions in the render module
    with patch(
        "cobble.dataflow.srccfg.query.reaching_conditions", return_value=test_reaching
    ):
        lines = guards_report(cfg, node_id)
        assert any(
            "guard cap hit" in line for line in lines
        ), "Should report guard cap was hit"


def test_truncated_node_says_subset() -> None:
    """F3: A node in reaching.truncated should report that upstream paths were
    truncated.

    R91: Call guards_report with a real Reaching that has truncated set."""
    from unittest.mock import patch

    from cobble.dataflow.srccfg.dataflow import Reaching, reaching_conditions

    # Build a CFG and get actual reaching conditions
    cfg = build_program(_asg([_move("WS-A", "WS-B")]))
    node_id = next(n.id for n in cfg.nodes if "WS-B" in n.writes)

    # Get the real reaching, then construct a modified one with truncated
    real_reaching = reaching_conditions(cfg)
    test_reaching = Reaching(
        guards=real_reaching.guards,
        truncated=frozenset([node_id]),  # Mark this node as truncated
        overflowed=real_reaching.overflowed,
        abandoned=real_reaching.abandoned,
    )

    # Patch reaching_conditions in the render module
    with patch(
        "cobble.dataflow.srccfg.query.reaching_conditions", return_value=test_reaching
    ):
        lines = guards_report(cfg, node_id)
        assert any(
            "subset" in line and "upstream" in line for line in lines
        ), "Should report subset due to upstream truncation"


def test_resumed_node_says_its_guard_assumes_the_perform_came_back() -> None:
    """The one caveat that points the other way: every other note warns the list may be
    short, this one warns the guard is there at all only because the walk assumed a
    PERFORM returned. A reader given the guard and not the assumption cannot tell."""
    from unittest.mock import patch

    from cobble.dataflow.srccfg.dataflow import Reaching, reaching_conditions

    cfg = build_program(_asg([_move("WS-A", "WS-B")]))
    node_id = next(n.id for n in cfg.nodes if "WS-B" in n.writes)

    real = reaching_conditions(cfg)
    test_reaching = Reaching(
        guards=real.guards,
        truncated=real.truncated,
        overflowed=real.overflowed,
        abandoned=real.abandoned,
        resumed=frozenset([node_id]),
    )

    with patch(
        "cobble.dataflow.srccfg.query.reaching_conditions", return_value=test_reaching
    ):
        lines = guards_report(cfg, node_id)

    assert any("resumed past a PERFORM" in line for line in lines)


# F5: Identity operand tests


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

    A command that can raise is guarded by ``%HANDLER[ANY] RAISED``, so a write after
    it depends on that name -- and the definition of it is an ASSIGN two nodes away.
    Reporting it as written nowhere in the member is the worst kind of wrong answer:
    a real gap and an invented name print identically, so the reader cannot tell which
    lines to investigate. ``RAISED`` is the state tested for, not a second operand,
    and must not be chased at all.

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

    assert provenance_report(cfg, "WS-RESULT") == (
        "WS-RESULT in PROGA:",
        "backward -- what its value is derived from:",
        "  WS-RESULT <-",
        "  MAIN/1 MOVE when NOT (%HANDLER[ANY] RAISED)",
        "    %HANDLER[ANY] <- synthetic (the handler armed for ANY)",
        "forward -- what its value reaches:",
        "  WS-RESULT -> sink (read nowhere in this member)",
    )


# F2: the guard cap has to survive into every report, not just the guards query


def _overflowed_at(cfg, node_id):
    from cobble.dataflow.srccfg.dataflow import Reaching, reaching_conditions

    real = reaching_conditions(cfg)
    return Reaching(
        guards=real.guards,
        truncated=real.truncated,
        overflowed=frozenset([node_id]),
        abandoned=real.abandoned,
    )


def test_the_provenance_report_says_when_the_guard_cap_cut_the_list() -> None:
    """F2: the cap was reported by the guards query and by nothing else.

    Worse on a chain than on a flat listing: it is transitive, so a capped guard list
    at one writer silently prunes every dependency reached only through the paths that
    were dropped -- and the report still reads as the complete set of conditions under
    which the field is written. A partial answer presented as a whole one, which is
    the failure this subsystem exists to avoid."""
    from unittest.mock import patch

    cfg = _guarded_cfg()
    node_id = next(n.id for n in cfg.nodes if "WS-OUT" in n.writes)

    with patch(
        "cobble.dataflow.srccfg.query.reaching_conditions",
        return_value=_overflowed_at(cfg, node_id),
    ):
        lines = provenance_report(cfg, "WS-OUT")

    assert any("guard cap hit" in line for line in lines)


def test_the_coassign_report_says_when_a_writer_had_no_guards_to_compare() -> None:
    """F3: co_assigned declines a tier-3 comparison when a writer's guards are absent
    or a subset. Silently, unless the report says so -- and a shorter candidate list
    with no explanation is indistinguishable from a member that genuinely has no
    co-assignments."""
    from unittest.mock import patch

    from cobble.dataflow.srccfg.dataflow import Reaching

    cfg = _guarded_cfg()
    node_id = next(n.id for n in cfg.nodes if "WS-OUT" in n.writes)

    with patch(
        "cobble.dataflow.srccfg.query.reaching_conditions",
        return_value=Reaching(guards={}, abandoned=frozenset([node_id])),
    ):
        lines = coassign_report(cfg, "WS-OUT")

    assert any(node_id in line and "no tier-3 comparison" in line for line in lines)

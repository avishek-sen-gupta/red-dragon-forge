"""A node's reaching conditions are the guards along the paths that reach it.

The measured failure this replaces was a guard stack: it negated a two-clause AND as
NOT A AND NOT B, so the ELSE arm of the commonest COBOL shape got a condition no
input satisfies. Here negation is an edge polarity, so the same shape comes out as
two paths -- which is what NOT (A AND B) means.
"""

from __future__ import annotations

from cobble.dataflow.srccfg.build import (
    build_program,
    end_id,
    label_id,
)
from cobble.dataflow.srccfg.cfg import Atom, Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.dataflow import (
    MAX_PATHS,
    entry_of,
    guard_set,
    guard_text,
    guards_of,
    reaching_conditions,
)
from cobble.dataflow.srccfg.synthetic import IMPLICIT_FIRST


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _rel(left: str, right: str) -> dict:
    return {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": "==",
            "right": {"kind": "lit", "value": right},
        },
    }


def _and(left: dict, right: dict) -> dict:
    return {"op": "AND", "left": left, "right": right}


def _if(condition: dict, then: list[dict], otherwise: list[dict] | tuple = ()) -> dict:
    return {
        "type": "IF",
        "condition": condition,
        "children": list(then),
        "else_children": list(otherwise),
    }


def _perform(target: str) -> dict:
    return {"type": "PERFORM", "operands": [target]}


def _goto(target: str) -> dict:
    return {"type": "GOTO", "form": "simple", "target": {"paragraph": target}}


def _program(*paragraphs: dict) -> dict:
    return {"program_id": "PROGA", "paragraphs": list(paragraphs)}


def _writer_of(cfg: Cfg, field: str) -> str:
    return next(node.id for node in cfg.nodes if field in node.writes)


def _kinds(guard) -> list[EdgeKind]:
    return [kind for _, kind in guard]


def test_an_unguarded_assignment_has_one_empty_guard(program_of) -> None:
    """65% of a corpus's assignments carry a guard, which means 35% do not -- and an
    empty tuple of paths would say "unreachable", the opposite claim."""
    cfg = build_program(program_of([_move("'A'", "WS-FLAG-A")]))

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-FLAG-A")) == ((),)


def test_an_assignment_in_a_then_arm_carries_the_true_polarity(program_of) -> None:
    cfg = build_program(
        program_of([_if(_rel("WS-FLAG-A", "'Y'"), [_move("'A'", "WS-RESULT")])])
    )

    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    assert _kinds(guard) == [EdgeKind.TRUE]


def test_the_else_arm_of_a_two_clause_and_is_reached_by_two_paths(program_of) -> None:
    """The whole point. NOT (A AND B) is NOT A OR NOT B, and an OR is two paths --
    so this node has two guards, each ending in a single FALSE, not one guard whose
    two clauses are both negated.
    """
    cfg = build_program(
        program_of(
            [
                _if(
                    _and(_rel("WS-FLAG-A", "'Y'"), _rel("WS-FLAG-B", "'Y'")),
                    [_move("'A'", "WS-TAKEN")],
                    [_move("'B'", "WS-SKIPPED")],
                )
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, _writer_of(cfg, "WS-SKIPPED"))

    assert sorted(len(guard) for guard in guards) == [1, 2]
    assert all(guard[-1][1] == EdgeKind.FALSE for guard in guards)


def test_the_then_arm_of_a_two_clause_and_is_one_path_of_two_tests(program_of) -> None:
    cfg = build_program(
        program_of(
            [
                _if(
                    _and(_rel("WS-FLAG-A", "'Y'"), _rel("WS-FLAG-B", "'Y'")),
                    [_move("'A'", "WS-TAKEN")],
                )
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-TAKEN"))

    assert _kinds(guard) == [EdgeKind.TRUE, EdgeKind.TRUE]


def test_a_statement_after_the_if_is_reached_under_every_arm(program_of) -> None:
    """A node reached under both polarities of one test is unconditional in effect.
    Both paths have to be there for a later pass to see that.
    """
    cfg = build_program(
        program_of(
            [
                _if(_rel("WS-FLAG-A", "'Y'"), [_move("'A'", "WS-X")]),
                _move("'B'", "WS-AFTER"),
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, _writer_of(cfg, "WS-AFTER"))

    assert len(guards) == 2
    assert sorted(_kinds(guard)[0].value for guard in guards) == ["FALSE", "TRUE"]


def test_a_performed_paragraph_carries_the_guard_of_the_call_site(asg_of) -> None:
    """This is why a per-paragraph analysis is not enough: the assignment is
    unconditional where it is written and conditional in every run."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [_if(_rel("WS-FLAG-A", "'Y'"), [_perform("SET-IT")])],
                },
                {"name": "SET-IT", "statements": [_move("'A'", "WS-RESULT")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    assert any(EdgeKind.TRUE in guard_kinds for guard_kinds in map(_kinds, guards))


def test_a_return_edge_is_only_taken_back_to_its_own_call_site(asg_of) -> None:
    """A paragraph PERFORMed twice has two return edges. Following the wrong one
    joins the guard of call site A to everything after call site B, and on a corpus
    where a paragraph is performed from a dozen places that is where the guard sets
    stop meaning anything.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "'Y'"),
                            [_perform("SET-IT"), _move("'1'", "WS-AFTER-A")],
                            [_perform("SET-IT"), _move("'2'", "WS-AFTER-B")],
                        )
                    ],
                },
                {"name": "SET-IT", "statements": [_move("'A'", "WS-RESULT")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert [
        _kinds(guard) for guard in guards_of(reaching, _writer_of(cfg, "WS-AFTER-A"))
    ] == [[EdgeKind.TRUE]]
    assert [
        _kinds(guard) for guard in guards_of(reaching, _writer_of(cfg, "WS-AFTER-B"))
    ] == [[EdgeKind.FALSE]]


def test_the_statement_after_a_perform_is_reached_once_not_twice(asg_of) -> None:
    """A CALL node keeps a FLOW edge to the next statement as well as the PERFORM
    edge, and the paragraph's RETURN edge lands on that same FLOW target. Walking
    both would report the continuation twice under one guard, and a paragraph with
    ten PERFORMs would report 2^10 duplicates -- so control goes through the
    paragraph and comes back, and the FLOW edge is only the fallback.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _perform("SET-IT"),
                        _perform("SET-IT-TOO"),
                        _move("'A'", "WS-AFTER"),
                    ],
                },
                {"name": "SET-IT", "statements": [_move("'B'", "WS-B")]},
                {"name": "SET-IT-TOO", "statements": [_move("'C'", "WS-C")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_performed_paragraph_does_not_fall_through_to_the_next_one(asg_of) -> None:
    """PERFORM MIDDLE returns at the end of MIDDLE. Following the fall-through edge
    out of it as well would run TAIL under the caller's guard, and on a driver
    paragraph that performs forty others those invented paths fill the path cap and
    evict the returns the driver's own later statements are reachable only by --
    measured as 39 nodes with no guards at all on a 922-node synthetic program.

    TAIL is not dead code, though: control reaches MAIN's own end, and the source
    would fall through from there into MIDDLE and on into TAIL. That path is lost to
    the no-repeat rule -- MIDDLE is already on this path -- not to this rule. So the
    zero here is the cost of walking each node once, and it is the loss the module
    docstring names rather than a claim that nothing runs TAIL.
    """
    cfg = build_program(
        asg_of(
            _program(
                {"name": "MAIN", "statements": [_perform("MIDDLE")]},
                {"name": "MIDDLE", "statements": [_move("'A'", "WS-MIDDLE")]},
                {"name": "TAIL", "statements": [_move("'B'", "WS-TAIL")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-MIDDLE")) == ((),)
    assert guards_of(reaching, _writer_of(cfg, "WS-TAIL")) == ()
    assert label_id("TAIL") in reaching.abandoned


def test_a_perform_thru_still_falls_through_inside_the_range(asg_of) -> None:
    """The other side of that rule: a paragraph in the middle of a THRU range
    reaches the next one by falling through, and the return comes from the range's
    last paragraph. Refusing fall-through inside a frame outright would report the
    whole tail of every range unreachable."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        {"type": "PERFORM", "operands": ["FIRST"], "thru": "LAST"},
                        _move("'Z'", "WS-AFTER"),
                    ],
                },
                {"name": "FIRST", "statements": [_move("'A'", "WS-FIRST")]},
                {"name": "LAST", "statements": [_move("'B'", "WS-LAST")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-FIRST")) == ((),)
    assert guards_of(reaching, _writer_of(cfg, "WS-LAST")) == ((),)
    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_call_whose_return_is_spent_still_reaches_the_next_statement(asg_of) -> None:
    """The regression that says why the FLOW rule is conditional and not blanket.

    PB is performed on its own and is also the last paragraph of the second call's
    THRU range, so PB#end carries the return edges of both calls. The first call
    spends PB#end getting back to the second call; the second call then enters PA,
    whose own end has no return edge and whose fall-through to PB is barred because
    PB is already on this path. If the CALL node's FLOW edge were refused merely
    because a PERFORM edge exists, the walk would die at the second call and every
    statement after it would read as unreachable -- silence, which is the worst
    failure this pass can produce. So FLOW is refused only while a return onto it can
    still fire.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _perform("PB"),
                        {"type": "PERFORM", "operands": ["PA"], "thru": "PB"},
                        _move("'Z'", "WS-AFTER"),
                    ],
                },
                {"name": "PA", "statements": [_move("'A'", "WS-A")]},
                {"name": "PB", "statements": [_move("'B'", "WS-B")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_perform_that_can_never_return_still_reaches_the_next_statement(
    asg_of,
) -> None:
    """The same rule from the other end: PA's only statement is a GO TO, so nothing
    in the graph reaches PA#end and the return edge hanging off it can never fire.
    The statement after the call is reached by the FLOW edge or by nothing at all."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        _perform("PX"),
                        _perform("PA"),
                        _move("'Z'", "WS-AFTER"),
                    ],
                },
                {"name": "PA", "statements": [_goto("PX")]},
                {"name": "PX", "statements": [_move("'X'", "WS-X")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_perform_of_an_undeclared_paragraph_still_continues(asg_of) -> None:
    """The target is in a copybook the parse could not resolve, so there is no
    PERFORM edge to follow. Suppressing the FLOW edge there would report the rest of
    the paragraph unreachable -- losing every definition after it."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [_perform("NOWHERE"), _move("'A'", "WS-AFTER")],
                }
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ((),)


def test_a_paragraph_reached_only_by_a_goto_still_gets_guards(asg_of) -> None:
    """11% of paragraphs on a real corpus are never PERFORMed and hold 5% of the
    assignments. A walk that only followed perform edges would report them
    unreachable and lose those definitions."""
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [_if(_rel("WS-FLAG-A", "'Y'"), [_goto("LAND")])],
                },
                {"name": "LAND", "statements": [_move("'A'", "WS-RESULT")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-RESULT"))


def test_a_loop_body_is_walked_once_rather_than_forever(program_of) -> None:
    """No node repeats on a path, so a PERFORM UNTIL terminates. The answer wanted
    is "under what condition does this run at all", not one guard per iteration."""
    cfg = build_program(
        program_of(
            [
                {
                    "type": "PERFORM",
                    "perform_type": "UNTIL",
                    "until": _rel("WS-FLAG-A", "'Y'"),
                    "children": [_move("'A'", "WS-RESULT")],
                }
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    assert [_kinds(guard) for guard in guards] == [[EdgeKind.FALSE]]


def test_an_unreachable_node_has_no_guards_rather_than_an_empty_one(asg_of) -> None:
    """Zero guards and one empty guard are opposite claims. A paragraph nothing
    reaches gets zero, and nothing manufactures a guard to fill the gap."""
    cfg = build_program(
        asg_of(
            _program(
                {"name": "MAIN", "statements": [_goto("THIRD")]},
                {"name": "ORPHAN", "statements": [_move("'A'", "WS-ORPHANED")]},
                {"name": "THIRD", "statements": [_move("'B'", "WS-RESULT")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-ORPHANED")) == ()
    assert guards_of(reaching, _writer_of(cfg, "WS-RESULT")) == ((),)


def test_real_dead_code_is_not_named_abandoned(asg_of) -> None:
    """``abandoned`` is the other half of the same distinction: nothing here leads to
    ORPHAN, so no node next to it carries a guard either, and the zero it reports is a
    statement about the program. Dead code is a finding worth keeping, so it must not
    be swept in with the nodes the walk gave up on."""
    cfg = build_program(
        asg_of(
            _program(
                {"name": "MAIN", "statements": [_goto("THIRD")]},
                {"name": "ORPHAN", "statements": [_move("'A'", "WS-ORPHANED")]},
                {"name": "THIRD", "statements": [_move("'B'", "WS-RESULT")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert reaching.abandoned == frozenset()


def test_a_node_the_walk_gave_up_on_is_named_abandoned_rather_than_dead(asg_of) -> None:
    """The walk's known loss, made visible.

    PB is performed from inside the range of the PERFORM of PA THRU PC, so control
    really does reach PC -- by returning to PA's end, falling through PB a second time
    and on into PC. The no-repeat rule walks PB once, so that route is lost and the
    tail of the range comes out with no guards. Nothing about the cap is involved, so
    ``truncated`` is empty and silence would present the loss as dead code: exactly the
    confident wrong answer this pass exists to avoid. ``abandoned`` names the nodes the
    walk stopped next to instead.
    """
    cfg = build_program(
        asg_of(
            _program(
                {
                    "name": "MAIN",
                    "statements": [
                        {"type": "PERFORM", "operands": ["PA"], "thru": "PC"},
                        _move("'Z'", "WS-AFTER"),
                    ],
                },
                {"name": "PA", "statements": [_perform("PB")]},
                {"name": "PB", "statements": [_move("'B'", "WS-B")]},
                {"name": "PC", "statements": [_move("'C'", "WS-C")]},
            )
        )
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, _writer_of(cfg, "WS-AFTER")) == ()
    assert reaching.truncated == frozenset()
    assert _writer_of(cfg, "WS-AFTER") in reaching.abandoned
    assert label_id("PC") in reaching.abandoned


def test_a_node_that_hit_the_path_cap_is_named_as_truncated(program_of) -> None:
    """A silently capped answer is a wrong answer with no warning: it reads as a
    complete list of the conditions under which a field is written."""
    ifs = [
        _if(_rel(f"WS-FLAG-{n}", "'Y'"), [_move("'A'", f"WS-X{n}")]) for n in range(12)
    ]
    cfg = build_program(program_of([*ifs, _move("'Z'", "WS-LAST")]))

    reaching = reaching_conditions(cfg, max_paths=8)

    assert len(guards_of(reaching, _writer_of(cfg, "WS-LAST"))) <= 8
    assert _writer_of(cfg, "WS-LAST") in reaching.truncated


def test_truncation_carries_forward_to_the_nodes_after_the_capped_one(
    program_of,
) -> None:
    """The walks the cap refused were never expanded, so the nodes after the capped
    one are short of those paths too. Naming only the node that overflowed lets a
    reader treat the next node's guards as the complete answer -- and none of the
    downstream nodes overflows on its own here, because the cap already stopped
    feeding them.

    The tail is four statements long on purpose. Only the first is a single hop from a
    node in ``overflowed``, so a closure that took one step and stopped would still
    flag it; the fourth is reached only by following the chain, which is the transitive
    property the closure exists to have.
    """
    ifs = [
        _if(_rel(f"WS-FLAG-{n}", "'Y'"), [_move("'A'", f"WS-X{n}")]) for n in range(12)
    ]
    tail = [_move("'Z'", "WS-LAST"), *(_move("'Y'", f"WS-HOP{n}") for n in range(1, 4))]
    cfg = build_program(program_of([*ifs, *tail]))

    reaching = reaching_conditions(cfg, max_paths=8)
    hops = [_writer_of(cfg, f"WS-HOP{n}") for n in range(1, 4)]

    assert _writer_of(cfg, "WS-LAST") in reaching.overflowed
    assert [node_id in reaching.overflowed for node_id in hops] == [False] * 3
    assert [len(guards_of(reaching, node_id)) for node_id in hops] == [8] * 3
    assert [node_id in reaching.truncated for node_id in hops] == [True] * 3
    assert end_id("MAIN") in reaching.truncated


def test_a_program_under_the_cap_truncates_nothing(program_of) -> None:
    cfg = build_program(
        program_of(
            [
                _if(_rel("WS-FLAG-A", "'Y'"), [_move("'A'", "WS-X")]),
                _move("'B'", "WS-AFTER"),
            ]
        )
    )

    assert reaching_conditions(cfg).truncated == frozenset()


def test_the_default_cap_is_the_documented_constant() -> None:
    assert MAX_PATHS == 64


def test_guard_set_drops_order_so_two_orders_of_the_same_tests_compare_equal() -> None:
    """Co-assignment asks whether two writes are guarded the same way, and the order
    two independent tests were written in is not part of that question."""
    guard_a = (("MAIN/0#test", EdgeKind.TRUE), ("MAIN/1#test", EdgeKind.FALSE))
    guard_b = (("MAIN/1#test", EdgeKind.FALSE), ("MAIN/0#test", EdgeKind.TRUE))

    assert guard_set(guard_a) == guard_set(guard_b)


def test_guard_text_renders_a_polarity_as_a_readable_predicate(program_of) -> None:
    """The rendering is what a human reads in a derivation, so a FALSE edge has to
    say NOT rather than showing the atom that was tested with no polarity at all."""
    cfg = build_program(
        program_of([_if(_rel("WS-FLAG-A", "'Y'"), [], [_move("'B'", "WS-RESULT")])])
    )
    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    rendered = guard_text(cfg, guard)

    assert len(rendered) == 1
    assert rendered[0].startswith("NOT ")
    assert "WS-FLAG-A" in rendered[0]


def test_an_unresolvable_predicate_survives_in_the_guard_and_renders(
    program_of,
) -> None:
    """Dropping a predicate the pass could not decompose STRENGTHENS the guard: it
    claims the write happens under fewer conditions than it does. So an unreadable
    test keeps its step and its rendered term says it is unreadable."""
    cfg = build_program(
        program_of([_if({"something": "new"}, [_move("'A'", "WS-RESULT")])])
    )
    test_node = next(node for node in cfg.nodes if node.kind == NodeKind.TEST)
    assert test_node.atom.resolved is False

    reaching = reaching_conditions(cfg)
    (guard,) = guards_of(reaching, _writer_of(cfg, "WS-RESULT"))

    assert guard == ((test_node.id, EdgeKind.TRUE),)
    assert guard_text(cfg, guard) == ("UNRESOLVED",)


def test_an_unresolved_atom_that_reads_like_a_predicate_is_still_marked() -> None:
    """The desugaring emits unresolved atoms with text in them -- the arm of an ON
    EXCEPTION, a SEARCH whose outcome is unknown. Rendering those as though they were
    understood is the same dishonesty as dropping them, just quieter, so the mark is
    on ``resolved`` and not on whether the text happens to be empty."""
    node = Node(
        id="MAIN/0#test",
        kind=NodeKind.TEST,
        paragraph="MAIN",
        atom=Atom(text="INVALID KEY ", resolved=False),
    )
    cfg = Cfg(program="PROGA", nodes=(node,), edges=())

    assert guard_text(cfg, ((node.id, EdgeKind.TRUE),)) == ("UNRESOLVED: INVALID KEY",)
    assert guard_text(cfg, ((node.id, EdgeKind.FALSE),)) == (
        "NOT (UNRESOLVED: INVALID KEY)",
    )


def test_a_test_node_records_the_guards_that_reach_it_not_its_own_polarity(
    program_of,
) -> None:
    """A test's own answer is not known until it runs, so its guard is what reached
    it -- otherwise every nested test would double-count itself."""
    cfg = build_program(
        program_of(
            [
                _if(
                    _rel("WS-FLAG-A", "'Y'"),
                    [_if(_rel("WS-FLAG-B", "'Y'"), [_move("'A'", "WS-X")])],
                )
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    inner = next(
        node
        for node in cfg.nodes
        if node.kind == NodeKind.TEST and "WS-FLAG-B" in node.atom.text
    )

    assert [_kinds(guard) for guard in guards_of(reaching, inner.id)] == [
        [EdgeKind.TRUE]
    ]


def test_the_entry_is_the_first_paragraphs_label(asg_of) -> None:
    cfg = build_program(
        asg_of(
            _program(
                {"name": "MAIN", "statements": [_move("'A'", "WS-A")]},
                {"name": "SECOND", "statements": []},
            )
        )
    )

    assert entry_of(cfg) == label_id("MAIN")
    assert guards_of(reaching_conditions(cfg), label_id("MAIN")) == ((),)


def test_the_entry_is_the_implicit_paragraph_when_the_source_has_one(asg_of) -> None:
    """Statements before the first paragraph run first, so the walk has to start
    there -- starting at the first named paragraph would report them unreached."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "statements": [_move("'A'", "WS-A")],
                "paragraphs": [{"name": "MAIN", "statements": []}],
            }
        )
    )

    assert entry_of(cfg) == label_id(IMPLICIT_FIRST)
    assert guards_of(reaching_conditions(cfg), _writer_of(cfg, "WS-A")) == ((),)


def test_an_empty_program_answers_nothing_rather_than_failing(asg_of) -> None:
    cfg = Cfg(program="PROGA", nodes=(), edges=())

    reaching = reaching_conditions(cfg)

    assert entry_of(cfg) == ""
    assert reaching.guards == {}
    assert reaching.truncated == frozenset()


def test_a_paragraph_end_is_reached_under_the_guards_of_its_last_statements(
    program_of,
) -> None:
    """The #end node is the join every caller reads back through, so it has to carry
    the union of the arms rather than the guard of the last arm lowered."""
    cfg = build_program(
        program_of(
            [
                _if(
                    _rel("WS-FLAG-A", "'Y'"),
                    [_move("'A'", "WS-X")],
                    [_move("'B'", "WS-Y")],
                )
            ]
        )
    )

    reaching = reaching_conditions(cfg)
    guards = guards_of(reaching, end_id("MAIN"))

    assert sorted(_kinds(guard)[0].value for guard in guards) == ["FALSE", "TRUE"]


def test_a_return_to_a_non_flow_successor_of_the_call_is_not_taken() -> None:
    """F10: the RETURN rule admits an edge only if its target is a FLOW successor of
    the node on top of the stack, and nothing pinned the FLOW part of that.

    build_program cannot produce a counter-example: RETURN edges are created only at a
    PERFORM node, sourced at the range end and targeting that node's FLOW successors,
    so every RETURN target is already a FLOW successor of its call. The filter is
    therefore unexercised by generated graphs rather than dead -- it is what makes
    _continuations mean "where the call resumes", and _returns_from reads the same
    helper to decide whether a FALLTHRU is a return in disguise. Widen it and that
    refusal fires more often, which is the direction _passable's contract calls the
    worse failure. So it is pinned here with a graph built by hand.

    MAIN/1 is reachable only through the RETURN out of the range end, and it is a
    RETURN successor of the call rather than a FLOW one. It must stay unreached -- and
    visibly so, through `abandoned`, because a walk that declined a route is not a
    program with dead code.
    """
    cfg = Cfg(
        program="PROGA",
        nodes=(
            Node(
                id="MAIN/0",
                kind=NodeKind.CALL,
                paragraph="MAIN",
                transfer="PERFORM",
                target="P-ONE",
            ),
            Node(id="P-ONE#label", kind=NodeKind.LABEL, paragraph="P-ONE"),
            Node(
                id="P-ONE/0", kind=NodeKind.ASSIGN, paragraph="P-ONE", writes=("WS-A",)
            ),
            Node(id="P-ONE#end", kind=NodeKind.NOP, paragraph="P-ONE"),
            Node(id="MAIN/1", kind=NodeKind.ASSIGN, paragraph="MAIN", writes=("WS-B",)),
        ),
        edges=(
            Edge(source="MAIN/0", target="P-ONE#label", kind=EdgeKind.PERFORM),
            Edge(source="MAIN/0", target="MAIN/1", kind=EdgeKind.RETURN),
            Edge(source="P-ONE#label", target="P-ONE/0", kind=EdgeKind.FLOW),
            Edge(source="P-ONE/0", target="P-ONE#end", kind=EdgeKind.FLOW),
            Edge(source="P-ONE#end", target="MAIN/1", kind=EdgeKind.RETURN),
        ),
    )

    reaching = reaching_conditions(cfg)

    assert guards_of(reaching, "MAIN/1") == ()
    assert "MAIN/1" in reaching.abandoned

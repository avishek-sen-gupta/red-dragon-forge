"""Which handler is live at a command that can raise.

Task 10 made arming an assignment precisely so this question needs no new machinery:
the live handlers are the definitions of %HANDLER[...] that reach the dispatch node.
"""

from __future__ import annotations

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.cfg import EdgeKind
from cobble.dataflow.srccfg.dataflow import def_use, live_handlers, with_handler_edges


def _asg(paragraphs: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict({"program_id": "PROGA", "paragraphs": paragraphs})


def _cics(verb: str, options: dict) -> dict:
    return {"type": "EXEC_CICS", "verb": verb, "options": options}


def _arm(condition: str, paragraph: str) -> dict:
    return _cics(
        "HANDLE CONDITION", {condition: {"text": paragraph, "is_literal": False}}
    )


def _receive() -> dict:
    return _cics("RECEIVE MAP", {"MAP": {"text": "'MAPA'", "is_literal": True}})


def _dispatch_of(cfg) -> str:
    return next(node.id for node in cfg.nodes if node.id.endswith("#dispatch"))


def test_a_handler_armed_before_a_command_is_live_at_it() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_arm("MAPFAIL", "H-MAPFAIL"), _receive()],
                },
                {"name": "H-MAPFAIL", "statements": []},
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ("H-MAPFAIL",)


def test_a_handler_armed_after_the_command_is_not_live_at_it() -> None:
    """Arming order is the whole semantics, and a per-paragraph "this paragraph arms
    MAPFAIL" answer gets this backwards."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_receive(), _arm("MAPFAIL", "H-MAPFAIL")],
                },
                {"name": "H-MAPFAIL", "statements": []},
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ()


def test_re_arming_kills_the_earlier_handler_for_the_same_condition() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _arm("MAPFAIL", "H-FIRST"),
                        _arm("MAPFAIL", "H-SECOND"),
                        _receive(),
                    ],
                },
                {"name": "H-FIRST", "statements": []},
                {"name": "H-SECOND", "statements": []},
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ("H-SECOND",)


def test_handlers_for_two_conditions_are_both_live() -> None:
    """%HANDLER[MAPFAIL] and %HANDLER[ERROR] are separate fields, so neither kills
    the other -- and the dispatch can go to either."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _arm("MAPFAIL", "H-MAPFAIL"),
                        _arm("ERROR", "H-ERROR"),
                        _receive(),
                    ],
                },
                {"name": "H-ERROR", "statements": []},
                {"name": "H-MAPFAIL", "statements": []},
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ("H-ERROR", "H-MAPFAIL")


def test_a_handler_armed_on_one_arm_only_is_live_alongside_no_handler() -> None:
    """Sorted and deduplicated, so a dispatch reached under two arms lists each
    target once -- which arm is which is a guard question."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        {
                            "type": "IF",
                            "condition": {
                                "kind": "relation",
                                "left": "WS-FLAG-A",
                                "operator": "=",
                                "right": "'Y'",
                            },
                            "children": [_arm("MAPFAIL", "H-MAPFAIL")],
                            "else_children": [],
                        },
                        _receive(),
                    ],
                },
                {"name": "H-MAPFAIL", "statements": []},
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ("H-MAPFAIL",)


def test_an_ignored_condition_is_not_a_dispatch_target() -> None:
    """IGNORE CONDITION means the command returns and execution continues, so there
    is nowhere to go -- and %IGNORE is not a paragraph name."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _cics("IGNORE CONDITION", {"MAPFAIL": None}),
                        _receive(),
                    ],
                }
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ()


def test_a_condition_reset_to_the_system_default_is_not_a_dispatch_target() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _arm("MAPFAIL", "H-MAPFAIL"),
                        _cics("HANDLE CONDITION", {"MAPFAIL": None}),
                        _receive(),
                    ],
                },
                {"name": "H-MAPFAIL", "statements": []},
            ]
        )
    )

    assert live_handlers(cfg)[_dispatch_of(cfg)] == ()


def test_the_resolved_cfg_grows_a_goto_edge_to_each_live_handler() -> None:
    """The point of resolving: a walk over the returned CFG reaches the handler
    paragraph, so an assignment there gets the guard of the command that raised."""
    cfg = with_handler_edges(
        build_program(
            _asg(
                [
                    {
                        "name": "MAIN",
                        "statements": [_arm("MAPFAIL", "H-MAPFAIL"), _receive()],
                    },
                    {"name": "H-MAPFAIL", "statements": []},
                ]
            )
        )
    )

    edges = cfg.successors(_dispatch_of(cfg))

    assert [(e.target, e.kind) for e in edges] == [("H-MAPFAIL#label", EdgeKind.GOTO)]


def test_a_handler_paragraph_the_program_does_not_declare_gets_no_edge() -> None:
    """I2: A name that is not a paragraph is a dynamic or dead handler. Keeping the
    target on the node with no edge is what stops a later walk landing on a node
    that does not exist."""
    cfg = with_handler_edges(
        build_program(
            _asg(
                [
                    {
                        "name": "MAIN",
                        "statements": [_arm("MAPFAIL", "H-GONE"), _receive()],
                    }
                ]
            )
        )
    )
    dispatch = _dispatch_of(cfg)

    assert cfg.successors(dispatch) == ()
    assert cfg.node(dispatch).target == "H-GONE"


def test_handler_any_is_not_resolved_by_def_use() -> None:
    """M4: def_use reports %HANDLER[ANY] as empty even when live_handlers resolves it.
    This is not a bug: handler reads are resolved by live_handlers, not by def_use."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_arm("MAPFAIL", "H-MAPFAIL"), _receive()],
                },
                {"name": "H-MAPFAIL", "statements": []},
            ]
        )
    )
    dispatch = _dispatch_of(cfg)

    handler_uses = [u for u in def_use(cfg) if u.node == dispatch]
    assert len(handler_uses) == 1
    assert handler_uses[0].field == "%HANDLER[ANY]"
    assert handler_uses[0].definitions == frozenset()
    assert live_handlers(cfg)[dispatch] == ("H-MAPFAIL",)


def test_resolving_a_cfg_with_no_cics_returns_it_unchanged() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        {
                            "type": "MOVE",
                            "operands": [{"name": "'A'"}, {"name": "WS-FLAG-A"}],
                        }
                    ],
                }
            ]
        )
    )

    assert with_handler_edges(cfg) == cfg


def _handler_program() -> dict:
    """MAIN arms MAPFAIL to H-OOPS and issues a command that can raise; H-OOPS writes."""
    return {
        "program_id": "PROGA",
        "paragraphs": [
            {"name": "MAIN", "statements": [_arm("MAPFAIL", "H-OOPS"), _receive()]},
            {
                "name": "H-OOPS",
                "statements": [
                    {"type": "MOVE", "operands": [{"name": "'E'"}, {"name": "WS-ERR"}]}
                ],
            },
        ],
    }


def test_the_built_artefact_has_its_handler_transfers_resolved(tmp_path) -> None:
    """F1: with_handler_edges existed, was tested, and was called by nothing.

    Every consumer reads the artefact, so an unresolved dispatch node made the raise
    path invisible corpus-wide. A dispatch has no outgoing edge of its own, so the only
    way into H-OOPS was the fallthrough out of MAIN -- reached on the FALSE edge of the
    raise test. The handler's own assignment therefore printed as guarded by "NOT
    (%HANDLER[ANY] RAISED)": the negation of the condition that is the one certain
    thing about it. A missing path presented as a complete answer, in the case the
    subsystem models CICS handlers for.

    Both guards are correct once resolved. COBOL falls through from MAIN into H-OOPS,
    so the paragraph is reachable without a raise as well, and the report must show
    both rather than choosing.

    Goes through build_one and load_cfg deliberately: calling with_handler_edges here
    would pass with the production wiring removed, which is precisely the bug."""
    import json

    from cobble.dataflow.srccfg.build_corpus import build_one, load_cfg
    from cobble.dataflow.srccfg.render import writers_report

    (tmp_path / "MEMA.json").write_text(json.dumps(_handler_program()))
    result = build_one(tmp_path / "MEMA.json", tmp_path / "out")

    assert result.message == ""
    assert writers_report(load_cfg(result.cfg_path), "WS-ERR") == (
        "WS-ERR: 1 writer(s) in PROGA",
        "  H-OOPS/0  MOVE  reads 'E'",
        "    when NOT (%HANDLER[ANY] RAISED)",
        "    when %HANDLER[ANY] RAISED",
    )


def test_resolving_an_already_resolved_cfg_adds_nothing(tmp_path) -> None:
    """Now that the corpus build resolves, a consumer of the artefact that resolves
    again -- having no way to tell -- must not get a second GOTO out of every dispatch.
    Duplicate edges double the paths out of the node and spend the guard cap on
    repeats of the same answer."""
    with cached_asg_dialect_parsers_registered():
        asg = CobolASG.from_dict(_handler_program())
    once = with_handler_edges(build_program(asg))

    assert with_handler_edges(once) == once

"""Calls out of a member, and the storage a commarea shares.

A derivation that stops at the member boundary answers nothing for a field filled by
a caller -- and on this corpus most of the interesting ones are. Dynamic program
names are marked rather than dropped: 38 of them, and either silently believing or
silently losing them is worse than an answer that says "unresolved".
"""

from __future__ import annotations

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.link import (
    COMMAREA_RECORD,
    Alias,
    aliases,
    call_graph,
    call_sites,
    callees_of,
    callers_of,
    unresolved_sites,
)


def _asg(program: str, statements: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(
            {
                "program_id": program,
                "paragraphs": [{"name": "MAIN", "statements": statements}],
            }
        )


def _cfg(program: str, statements: list[dict]):
    return build_program(_asg(program, statements))


def _cics(verb: str, options: dict) -> dict:
    return {"type": "EXEC_CICS", "verb": verb, "options": options}


def _link(program: str, literal: bool = True, commarea: str = "") -> dict:
    options = {"PROGRAM": {"text": program, "is_literal": literal}}
    extra = {"COMMAREA": {"text": commarea, "is_literal": False}} if commarea else {}
    return _cics("LINK", {**options, **extra})


def test_a_link_to_a_literal_program_is_a_resolved_call_site() -> None:
    (site,) = call_sites(_cfg("PROGA", [_link("'PROGB'")]))

    assert (site.caller, site.transfer, site.program, site.resolved) == (
        "PROGA",
        "LINK",
        "PROGB",
        True,
    )


def test_the_program_name_loses_its_quotes() -> None:
    """The call graph joins on program id, and 'PROGB' never equals PROGB."""
    (site,) = call_sites(_cfg("PROGA", [_link("'PROGB'")]))

    assert site.program == "PROGB"


def test_an_xctl_is_a_call_site_of_its_own_kind() -> None:
    """XCTL does not return, so a walk must not continue past it the way a LINK does
    -- and a caller asking "what runs after this" needs the two distinguished."""
    (site,) = call_sites(
        _cfg(
            "PROGA",
            [_cics("XCTL", {"PROGRAM": {"text": "'PROGB'", "is_literal": True}})],
        )
    )

    assert site.transfer == "XCTL"


def test_a_static_cobol_call_is_a_call_site() -> None:
    """1,231 of them on the corpus, and they carry USING parameters rather than a
    commarea -- a batch program's whole interface."""
    (site,) = call_sites(
        _cfg(
            "PROGA",
            [{"type": "CALL", "program": "'PROGB'", "using": [{"name": "WS-AREA"}]}],
        )
    )

    assert (site.transfer, site.program, site.resolved) == ("CALL", "PROGB", True)


def test_a_dynamic_program_name_is_unresolved_and_keeps_the_field_name() -> None:
    """Keeping the field is what makes the follow-up possible: the answer to "which
    programs can this reach" is a reaching-definitions query over that field."""
    (site,) = call_sites(_cfg("PROGA", [_link("WS-TARGET", literal=False)]))

    assert (site.program, site.resolved) == ("WS-TARGET", False)


def test_a_call_with_no_program_option_is_not_a_call_site() -> None:
    """A malformed or unparsed command must not become an edge to the empty program,
    which would collapse every one of them onto a single graph node."""
    assert call_sites(_cfg("PROGA", [_cics("LINK", {})])) == ()


def test_a_commarea_is_an_alias_between_the_caller_field_and_dfhcommarea() -> None:
    assert aliases(_cfg("PROGA", [_link("'PROGB'", commarea="WS-AREA")])) == (
        Alias(
            caller="PROGA",
            caller_field="WS-AREA",
            callee="PROGB",
            callee_field=COMMAREA_RECORD,
        ),
    )


def test_a_link_with_no_commarea_produces_no_alias() -> None:
    assert aliases(_cfg("PROGA", [_link("'PROGB'")])) == ()


def test_a_dynamic_target_produces_no_alias_because_the_callee_is_unknown() -> None:
    """An alias to an unresolved program would name the FIELD as the callee, and a
    query joining on program id would then match nothing while looking like data."""
    assert (
        aliases(_cfg("PROGA", [_link("WS-TARGET", literal=False, commarea="WS-AREA")]))
        == ()
    )


def test_a_call_using_aliases_every_parameter_positionally() -> None:
    """USING has no commarea to name, so the alias is positional -- and the position
    is what a later linkage-section match needs."""
    found = aliases(
        _cfg(
            "PROGA",
            [
                {
                    "type": "CALL",
                    "program": "'PROGB'",
                    "using": [{"name": "WS-ONE"}, {"name": "WS-TWO"}],
                }
            ],
        )
    )

    assert [(a.caller_field, a.callee_field) for a in found] == [
        ("WS-ONE", "%USING[0]"),
        ("WS-TWO", "%USING[1]"),
    ]


def test_a_literal_using_parameter_is_not_an_alias() -> None:
    """BY CONTENT of a literal shares no storage back."""
    found = aliases(
        _cfg(
            "PROGA",
            [
                {
                    "type": "CALL",
                    "program": "'PROGB'",
                    "using": [{"name": "'X'", "is_literal": True}],
                }
            ],
        )
    )

    assert found == ()


def test_an_omitted_parameter_takes_its_position_without_an_alias() -> None:
    """OMITTED shifts nothing: the parameter after it is still the third, and
    renumbering would alias the wrong field."""
    found = aliases(
        _cfg(
            "PROGA",
            [
                {
                    "type": "CALL",
                    "program": "'PROGB'",
                    "using": [
                        {"name": "WS-ONE"},
                        {"name": "", "omitted": True},
                        {"name": "WS-THREE"},
                    ],
                }
            ],
        )
    )

    assert [(a.caller_field, a.callee_field) for a in found] == [
        ("WS-ONE", "%USING[0]"),
        ("WS-THREE", "%USING[2]"),
    ]


def test_the_call_graph_joins_two_members() -> None:
    graph = call_graph(
        [_cfg("PROGA", [_link("'PROGB'")]), _cfg("PROGB", [_link("'PROGC'")])]
    )

    assert callees_of(graph, "PROGA") == ("PROGB",)
    assert callers_of(graph, "PROGB") == ("PROGA",)


def test_callers_and_callees_are_sorted_and_deduplicated() -> None:
    """A member that LINKs the same program from eleven places is one edge."""
    graph = call_graph(
        [_cfg("PROGA", [_link("'PROGC'"), _link("'PROGB'"), _link("'PROGB'")])]
    )

    assert callees_of(graph, "PROGA") == ("PROGB", "PROGC")


def test_an_unresolved_site_is_not_a_callee_edge_but_is_reported() -> None:
    """A field name in the callee position would be a node in the call graph that no
    member ever matches -- so it stays out of the edges and into a list a reader can
    work through."""
    graph = call_graph([_cfg("PROGA", [_link("WS-TARGET", literal=False)])])

    assert callees_of(graph, "PROGA") == ()
    assert [s.program for s in unresolved_sites(graph)] == ["WS-TARGET"]


def test_a_program_nobody_calls_has_no_callers() -> None:
    graph = call_graph([_cfg("PROGA", [_link("'PROGB'")])])

    assert callers_of(graph, "PROGA") == ()


def test_a_call_site_names_the_node_so_its_guard_can_be_looked_up() -> None:
    """The call graph on its own says a call is possible; the guard says when. Both
    answers are needed together, and the node id is the join."""
    (site,) = call_sites(_cfg("PROGA", [_link("'PROGB'")]))

    assert site.node.startswith("MAIN/")

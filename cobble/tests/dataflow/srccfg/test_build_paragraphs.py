"""The per-program skeleton: paragraphs in declaration order, fall-through between
them, and GO TO resolved to a label.

A paragraph is lowered once and shared. Every PERFORM of it and every GO TO into it
points at the same nodes, which is what keeps the graph the size of the source
instead of the size of the call tree.
"""

from __future__ import annotations

from cobble.dataflow.srccfg.build import (
    build_program,
    end_id,
    label_id,
    paragraph_order,
)
from cobble.dataflow.srccfg.cfg import EdgeKind, NodeKind
from cobble.dataflow.srccfg.synthetic import IMPLICIT_FIRST


def _move(source: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": source}, {"name": target}]}


def _two_paragraphs() -> dict:
    return {
        "program_id": "PROGA",
        "paragraphs": [
            {"name": "1000-FIRST", "statements": [_move("'F'", "WS-A")]},
            {"name": "2000-SECOND", "statements": [_move("WS-A", "WS-B")]},
        ],
    }


def test_paragraph_order_is_declaration_order(asg_of) -> None:
    """Both fall-through and PERFORM THRU ranges follow it, so it is the one thing
    that must not be sorted or de-duplicated."""
    order = paragraph_order(asg_of(_two_paragraphs()))

    assert [ref.name for ref in order] == ["1000-FIRST", "2000-SECOND"]


def test_paragraphs_inside_sections_keep_their_position_and_section(asg_of) -> None:
    asg = asg_of(
        {
            "program_id": "PROGA",
            "sections": [
                {
                    "name": "MAIN-SECTION",
                    "paragraphs": [{"name": "1000-FIRST", "statements": []}],
                }
            ],
            "paragraphs": [{"name": "2000-SECOND", "statements": []}],
        }
    )

    order = paragraph_order(asg)

    assert [(ref.name, ref.section) for ref in order] == [
        ("1000-FIRST", "MAIN-SECTION"),
        ("2000-SECOND", ""),
    ]


def test_division_level_statements_get_a_synthetic_first_paragraph(asg_of) -> None:
    """A program whose procedure division starts with bare statements has code that
    belongs to no paragraph. It still executes first, so it needs a name -- and the
    name is reserved so it cannot collide with a real paragraph."""
    asg = asg_of(
        {
            "program_id": "PROGA",
            "statements": [_move("'F'", "WS-A")],
            "paragraphs": [{"name": "1000-FIRST", "statements": []}],
        }
    )

    order = paragraph_order(asg)

    assert [ref.name for ref in order] == [IMPLICIT_FIRST, "1000-FIRST"]


def test_a_section_with_bare_statements_gets_one_too(asg_of) -> None:
    asg = asg_of(
        {
            "program_id": "PROGA",
            "sections": [
                {
                    "name": "MAIN-SECTION",
                    "statements": [_move("'F'", "WS-A")],
                    "paragraphs": [{"name": "1000-FIRST", "statements": []}],
                }
            ],
        }
    )

    assert [ref.name for ref in paragraph_order(asg)] == [
        f"MAIN-SECTION{IMPLICIT_FIRST}",
        "1000-FIRST",
    ]


def test_each_paragraph_gets_a_label_node_and_an_end_node(asg_of) -> None:
    cfg = build_program(asg_of(_two_paragraphs()))

    label = cfg.node(label_id("1000-FIRST"))
    assert (label.kind, label.paragraph) == (NodeKind.LABEL, "1000-FIRST")
    assert cfg.node(end_id("1000-FIRST")).kind == NodeKind.NOP


def test_a_paragraph_falls_through_to_the_next_one(asg_of) -> None:
    """Fall-through is why a paragraph's assignments can execute under a guard from
    a paragraph nobody PERFORMs it from."""
    cfg = build_program(asg_of(_two_paragraphs()))

    assert [(e.target, e.kind) for e in cfg.successors(end_id("1000-FIRST"))] == [
        (label_id("2000-SECOND"), EdgeKind.FALLTHRU)
    ]


def test_the_last_paragraph_falls_through_to_nothing(asg_of) -> None:
    cfg = build_program(asg_of(_two_paragraphs()))

    assert cfg.successors(end_id("2000-SECOND")) == ()


def test_a_paragraphs_statements_run_between_its_label_and_its_end(asg_of) -> None:
    cfg = build_program(asg_of(_two_paragraphs()))

    assert [e.target for e in cfg.successors(label_id("1000-FIRST"))] == [
        "1000-FIRST/0"
    ]
    assert [e.target for e in cfg.successors("1000-FIRST/0")] == [end_id("1000-FIRST")]


def test_an_empty_paragraph_wires_its_label_straight_to_its_end(asg_of) -> None:
    """An empty paragraph is a PERFORM target and a fall-through hop, so it cannot
    be dropped -- doing so would silently join the paragraphs either side of it."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [
                    {"name": "1000-FIRST", "statements": []},
                    {"name": "2000-SECOND", "statements": [_move("'F'", "WS-A")]},
                ],
            }
        )
    )

    assert [e.target for e in cfg.successors(label_id("1000-FIRST"))] == [
        end_id("1000-FIRST")
    ]


def test_a_goto_becomes_an_edge_to_the_targets_label(asg_of) -> None:
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [
                    {
                        "name": "1000-FIRST",
                        "statements": [
                            {
                                "type": "GOTO",
                                "form": "simple",
                                "target": {"paragraph": "2000-SECOND"},
                            }
                        ],
                    },
                    {"name": "2000-SECOND", "statements": [_move("'F'", "WS-A")]},
                ],
            }
        )
    )

    assert [(e.target, e.kind) for e in cfg.successors("1000-FIRST/0")] == [
        (label_id("2000-SECOND"), EdgeKind.GOTO)
    ]


def test_a_goto_to_a_paragraph_the_program_does_not_declare_gets_no_edge(
    asg_of,
) -> None:
    """The target is in a copybook the parse could not resolve, or is a section
    name. An edge to a node that does not exist would break every walk, and the
    node itself already records the unresolved target."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [
                    {
                        "name": "1000-FIRST",
                        "statements": [
                            {
                                "type": "GOTO",
                                "form": "simple",
                                "target": {"paragraph": "NOWHERE"},
                            }
                        ],
                    }
                ],
            }
        )
    )

    assert cfg.successors("1000-FIRST/0") == ()
    assert cfg.node("1000-FIRST/0").target == "NOWHERE"


def test_every_edge_lands_on_a_node_that_exists(asg_of) -> None:
    """The invariant the whole package depends on, asserted on a program with a
    paragraph, a section, an empty paragraph, a GO TO, and a PERFORM THRU."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "sections": [
                    {
                        "name": "MAIN-SECTION",
                        "paragraphs": [
                            {
                                "name": "1000-FIRST",
                                "statements": [
                                    {
                                        "type": "PERFORM",
                                        "operands": ["2000-SECOND"],
                                        "thru": "3000-THIRD",
                                    },
                                    {
                                        "type": "GOTO",
                                        "form": "simple",
                                        "target": {"paragraph": "3000-THIRD"},
                                    },
                                ],
                            },
                            {"name": "2000-SECOND", "statements": []},
                        ],
                    }
                ],
                "paragraphs": [
                    {"name": "3000-THIRD", "statements": [_move("'F'", "WS-A")]}
                ],
            }
        )
    )

    dangling = {e.target for e in cfg.edges} - cfg.node_ids
    assert dangling == set()
    assert {e.source for e in cfg.edges} <= cfg.node_ids
    assert len(cfg.node_ids) == len(cfg.nodes)


def test_a_duplicate_paragraph_name_is_renamed_to_keep_node_ids_unique(
    asg_of,
) -> None:
    """A duplicate paragraph name -- legal in COBOL when in different sections --
    is renamed on later occurrences to prevent node id collisions. Measured on a
    private corpus: 12 of 3,779 members contain duplicate paragraph names."""
    asg = asg_of(
        {
            "program_id": "PROGA",
            "sections": [
                {
                    "name": "SECTION-A",
                    "paragraphs": [
                        {"name": "1000-FIRST", "statements": [_move("'A'", "WS-A")]}
                    ],
                },
                {
                    "name": "SECTION-B",
                    "paragraphs": [
                        {"name": "1000-FIRST", "statements": [_move("'B'", "WS-B")]}
                    ],
                },
            ],
            "paragraphs": [{"name": "2000-THIRD", "statements": []}],
        }
    )

    order = paragraph_order(asg)

    assert [ref.name for ref in order] == ["1000-FIRST", "1000-FIRST%2", "2000-THIRD"]
    assert [(ref.name, ref.section) for ref in order] == [
        ("1000-FIRST", "SECTION-A"),
        ("1000-FIRST%2", "SECTION-B"),
        ("2000-THIRD", ""),
    ]


def test_duplicate_paragraph_names_produce_distinct_node_ids(asg_of) -> None:
    """A duplicate paragraph name would share a label and end node, causing the
    graph to claim control forks and merges where none exist -- a false graph."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "sections": [
                    {
                        "name": "SECTION-A",
                        "paragraphs": [
                            {"name": "1000-FIRST", "statements": [_move("'A'", "WS-A")]}
                        ],
                    },
                    {
                        "name": "SECTION-B",
                        "paragraphs": [
                            {"name": "1000-FIRST", "statements": [_move("'B'", "WS-B")]}
                        ],
                    },
                ],
            }
        )
    )

    assert len(cfg.node_ids) == len(cfg.nodes)


def test_a_goto_to_a_duplicate_paragraph_name_resolves_to_the_first_one(
    asg_of,
) -> None:
    """An unqualified GO TO to a duplicate name resolves to the first declaration,
    matching the common reading and keeping existing behaviour."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "sections": [
                    {
                        "name": "SECTION-A",
                        "paragraphs": [
                            {"name": "1000-FIRST", "statements": [_move("'A'", "WS-A")]}
                        ],
                    },
                    {
                        "name": "SECTION-B",
                        "paragraphs": [
                            {
                                "name": "1000-FIRST",
                                "statements": [
                                    {
                                        "type": "GOTO",
                                        "form": "simple",
                                        "target": {"paragraph": "1000-FIRST"},
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        )
    )

    goto_edges = [(e.source, e.target) for e in cfg.edges if e.kind == EdgeKind.GOTO]
    assert goto_edges == [("1000-FIRST%2/0", label_id("1000-FIRST"))]


def test_statements_of_duplicate_paragraphs_land_under_distinct_ids(asg_of) -> None:
    """The renamed paragraph's statements are prefixed by the renamed name, so the
    two bodies are no longer merged."""
    cfg = build_program(
        asg_of(
            {
                "program_id": "PROGA",
                "sections": [
                    {
                        "name": "SECTION-A",
                        "paragraphs": [
                            {"name": "1000-FIRST", "statements": [_move("'A'", "WS-A")]}
                        ],
                    },
                    {
                        "name": "SECTION-B",
                        "paragraphs": [
                            {"name": "1000-FIRST", "statements": [_move("'B'", "WS-B")]}
                        ],
                    },
                ],
            }
        )
    )

    first_body = [e.target for e in cfg.successors(label_id("1000-FIRST"))]
    second_body = [e.target for e in cfg.successors(label_id("1000-FIRST%2"))]
    assert first_body == ["1000-FIRST/0"]
    assert second_body == ["1000-FIRST%2/0"]

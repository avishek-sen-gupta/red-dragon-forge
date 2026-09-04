"""Which fields are written together with this one, in four tiers.

Tiers rather than one answer because the strong relation is rare and the weak one is
everywhere: on a real corpus, "same paragraph" makes a 300-line paragraph's every
field a candidate, which is true and useless. A caller that wants signal stops at
tier 2.
"""

from __future__ import annotations

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.coassign import (
    NO_ROUTE,
    SUBSET,
    Caveat,
    Tier,
    caveats,
    co_assigned,
    guard_signature,
)
from cobble.dataflow.srccfg.dataflow import Reaching, reaching_conditions


def _asg(paragraphs: list[dict]) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict({"program_id": "PROGA", "paragraphs": paragraphs})


def _move(value: str, target: str) -> dict:
    return {"type": "MOVE", "operands": [{"name": value}, {"name": target}]}


def _initialize(*targets: str) -> dict:
    # NOTE: INITIALIZE takes BARE STRING operands, unlike MOVE's dicts. See the
    # operand-shape table in the CORRECTIONS section at the head of this brief.
    return {"type": "INITIALIZE", "operands": list(targets)}


def _perform(target: str) -> dict:
    return {"type": "PERFORM", "operands": [target]}


def _if(condition: dict, then: list[dict], otherwise: list[dict]) -> dict:
    return {
        "type": "IF",
        "condition": condition,
        "children": list(then),
        "else_children": list(otherwise),
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


def _for(cfg, field: str, **kwargs):
    return co_assigned(cfg, field, reaching_conditions(cfg), **kwargs)


def _fields(candidates) -> dict:
    return {candidate.field: candidate.tier for candidate in candidates}


def test_two_fields_written_by_one_statement_are_tier_one() -> None:
    """INITIALIZE and MOVE CORRESPONDING write several fields from one decision, and
    that is the only tier where co-assignment is certain."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_initialize("WS-A", "WS-B")],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_STATEMENT}


def test_two_writes_in_one_paragraph_from_a_shared_source_are_tier_two() -> None:
    """The precise tier: a shared source is evidence of one derivation, not just of
    two statements happening to be near each other."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("WS-IN", "WS-A"), _move("WS-IN", "WS-B")],
                }
            ]
        )
    )

    # WS-IN is only ever READ, so it is not a co-assignment candidate: a MOVE's
    # source lands in `reads` and candidates come from `writes`.
    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_SOURCE}


def test_the_shared_source_is_named_on_the_candidate() -> None:
    """Without it the tier is a claim the reader cannot check against the listing."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("WS-IN", "WS-A"), _move("WS-IN", "WS-B")],
                }
            ]
        )
    )

    candidate = next(c for c in _for(cfg, "WS-A") if c.field == "WS-B")

    assert candidate.shared == ("WS-IN",)


def test_two_fields_under_the_same_guard_in_different_paragraphs_are_tier_three() -> (
    None
):
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "'Y'"),
                            [_perform("P-ONE"), _perform("P-TWO")],
                            [],
                        )
                    ],
                },
                {"name": "P-ONE", "statements": [_move("'1'", "WS-A")]},
                {"name": "P-TWO", "statements": [_move("'2'", "WS-B")]},
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")).get("WS-B") == Tier.SAME_GUARD


def test_two_unrelated_fields_in_one_paragraph_are_tier_four() -> None:
    """The weakest tier is still reported, because on the corpus it is often the only
    evidence there is -- and its weakness has to be visible in the answer rather than
    argued about afterwards."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'1'", "WS-A"), _move("'2'", "WS-B")],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_PARAGRAPH}


def test_a_pair_is_reported_once_at_its_strongest_tier() -> None:
    """Two fields in one paragraph, sharing a source, under one guard, satisfy tiers
    2, 3 and 4 at once. Three rows for one pair would make every count meaningless.
    """
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(
                            _rel("WS-FLAG-A", "'Y'"),
                            [_move("WS-IN", "WS-A"), _move("WS-IN", "WS-B")],
                            [],
                        )
                    ],
                }
            ]
        )
    )

    matches = [c for c in _for(cfg, "WS-A") if c.field == "WS-B"]

    assert [c.tier for c in matches] == [Tier.SAME_SOURCE]


def test_min_tier_two_drops_the_noisy_tiers() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'1'", "WS-A"), _move("'2'", "WS-B")],
                }
            ]
        )
    )

    assert _for(cfg, "WS-A", min_tier=Tier.SAME_SOURCE) == ()


def test_a_field_is_never_a_candidate_for_itself() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'1'", "WS-A"), _move("'2'", "WS-A")],
                }
            ]
        )
    )

    assert _for(cfg, "WS-A") == ()


def test_a_field_written_nowhere_has_no_candidates() -> None:
    cfg = build_program(_asg([{"name": "MAIN", "statements": [_move("'1'", "WS-A")]}]))

    assert _for(cfg, "WS-NEVER") == ()


def test_candidates_are_ordered_by_tier_then_by_name() -> None:
    """Stable output, strongest first: the caller reads the head of the list and
    stops, and two runs diff."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("WS-IN", "WS-A"),
                        _move("WS-IN", "WS-Z"),
                        _move("'2'", "WS-B"),
                    ],
                }
            ]
        )
    )

    # WS-IN is read-only and therefore not a candidate; see the tier-2 test above.
    assert [(c.tier, c.field) for c in _for(cfg, "WS-A")] == [
        (Tier.SAME_SOURCE, "WS-Z"),
        (Tier.SAME_PARAGRAPH, "WS-B"),
    ]


def test_the_pair_of_nodes_is_named_so_the_claim_can_be_checked() -> None:
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("WS-IN", "WS-A"), _move("WS-IN", "WS-B")],
                }
            ]
        )
    )

    candidate = next(c for c in _for(cfg, "WS-A") if c.field == "WS-B")

    assert candidate.nodes == ("MAIN/0", "MAIN/1")


def test_two_writes_of_one_field_in_two_paragraphs_find_candidates_in_both() -> None:
    """A field written in four places has four contexts, and a query that only looked
    at the first would answer for one of them."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'1'", "WS-A"), _move("'2'", "WS-B")],
                },
                {
                    "name": "OTHER",
                    "statements": [_move("'3'", "WS-A"), _move("'4'", "WS-C")],
                },
            ]
        )
    )

    assert set(_fields(_for(cfg, "WS-A"))) == {"WS-B", "WS-C"}


def test_guard_signature_is_order_insensitive_and_covers_every_path() -> None:
    """A node reached under two guards has a signature of two sets, so it matches
    another node only when both are reached the same ways."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _if(_rel("WS-FLAG-A", "'Y'"), [_move("'1'", "WS-A")], []),
                        _move("'2'", "WS-AFTER"),
                    ],
                }
            ]
        )
    )
    reaching = reaching_conditions(cfg)
    writer = next(node.id for node in cfg.nodes if "WS-AFTER" in node.writes)

    assert len(guard_signature(reaching, writer)) == 2


def test_shared_source_filters_out_figurative_constants() -> None:
    """R64: Two writes whose only common read is a figurative constant must come back
    tier 4, not tier 2. Without this filter, every pair of 'MOVE SPACES TO X' /
    'MOVE SPACES TO Y' in one paragraph reports as SAME_SOURCE, making tier 2 worthless.
    """
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("SPACES", "WS-A"), _move("SPACES", "WS-B")],
                }
            ]
        )
    )

    # Should be tier 4 (SAME_PARAGRAPH) because the shared literal is filtered out
    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_PARAGRAPH}


def test_shared_source_filters_out_all_with_literal() -> None:
    """F1: ALL with literal arrives as 'ALL \"-\"' in reads. Without filtering, two
    writes sharing this literal report as tier 2 instead of tier 4."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("ALL '-'", "WS-A"), _move("ALL '-'", "WS-B")],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_PARAGRAPH}


def test_shared_source_filters_out_hex_literals() -> None:
    """F1: Hex literal X'40' appears in reads as \"X'40'\". Without filtering, two
    writes sharing this literal report as tier 2 instead of tier 4."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("X'40'", "WS-A"), _move("X'40'", "WS-B")],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_PARAGRAPH}


def test_shared_source_filters_out_national_literals() -> None:
    """F1: National literal N'...' appears in reads. Without filtering, two writes
    sharing this literal report as tier 2 instead of tier 4."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("N'ABC'", "WS-A"), _move("N'ABC'", "WS-B")],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_PARAGRAPH}


def test_shared_source_filters_out_z_prefixed_literals() -> None:
    """F1: Z-prefixed literal Z'...' appears in reads. Without filtering, two writes
    sharing this literal report as tier 2 instead of tier 4."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("Z'ABC'", "WS-A"), _move("Z'ABC'", "WS-B")],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_PARAGRAPH}


def test_shared_source_filters_out_g_prefixed_literals() -> None:
    """F1: G-prefixed literal G'...' appears in reads. Without filtering, two writes
    sharing this literal report as tier 2 instead of tier 4."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("G'ABC'", "WS-A"), _move("G'ABC'", "WS-B")],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_PARAGRAPH}


def test_shared_source_filters_out_binary_literals() -> None:
    """F1: Binary literal B'...' appears in reads. Without filtering, two writes
    sharing this literal report as tier 2 instead of tier 4."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("B'01010101'", "WS-A"),
                        _move("B'01010101'", "WS-B"),
                    ],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-A")) == {"WS-B": Tier.SAME_PARAGRAPH}


# F3: tier 3 rests on a guard comparison, so it needs guards to compare


def _two_paragraphs() -> object:
    """MAIN performs both paragraphs unconditionally; each writes one field."""
    return build_program(
        _asg(
            [
                {"name": "MAIN", "statements": [_perform("P-ONE"), _perform("P-TWO")]},
                {"name": "P-ONE", "statements": [_move("'1'", "WS-A")]},
                {"name": "P-TWO", "statements": [_move("'2'", "WS-B")]},
            ]
        )
    )


def test_two_unconditional_writes_are_not_a_same_guard_pair() -> None:
    """F3: signature equality was read as evidence, and "no condition" compares equal.

    Both writes are reached unconditionally, so both signatures are {the empty guard}.
    That is not something the two fields share -- it is the absence of a shared thing,
    and it awarded tier 3, the strongest tier here, to every unconditional write paired
    with every other unconditional write in a different paragraph.
    """
    assert _fields(_for(_two_paragraphs(), "WS-A")).get("WS-B") is None


def test_two_writes_the_walk_abandoned_are_not_a_same_guard_pair() -> None:
    """F3: the same read of equality, from the other empty value.

    A node the walk gave up on has no guards at all, and two of them compare equal.
    Reaching's contract is explicit that an empty answer there is a fact about the walk
    and not about the program, so it cannot support the strongest claim this relation
    makes. Declining here is what the caveats channel then has to report.
    """
    cfg = _two_paragraphs()
    writers = tuple(node.id for node in cfg.nodes if node.writes)
    gave_up = Reaching(guards={}, abandoned=frozenset(writers))

    assert co_assigned(cfg, "WS-A", gave_up) == ()


def test_a_writer_the_walk_abandoned_is_reported_as_a_caveat() -> None:
    """F3: declining to compare is invisible otherwise -- the reader sees a shorter
    candidate list and nothing saying a comparison was skipped."""
    cfg = _two_paragraphs()
    gave_up = Reaching(guards={}, abandoned=frozenset({"P-ONE/0"}))

    assert caveats(cfg, "WS-A", gave_up) == (Caveat(node="P-ONE/0", reason=NO_ROUTE),)


def test_a_writer_whose_guards_are_a_subset_is_reported_as_a_caveat() -> None:
    """F3: the cap makes a guard list a subset of the real one (R77), so an equality
    between two of them is not established -- but it is also not known to be false, so
    the pair is still offered, with the reason attached."""
    cfg = _two_paragraphs()
    real = reaching_conditions(cfg)
    capped = Reaching(guards=real.guards, truncated=frozenset({"P-ONE/0"}))

    assert caveats(cfg, "WS-A", capped) == (Caveat(node="P-ONE/0", reason=SUBSET),)


# F4: the same field name must mean the same thing in every query


def test_a_subscripted_write_is_found_by_a_query_on_the_base_name() -> None:
    """F4: writers_of has always matched WS-TAB against a write of WS-TAB(1), and this
    query matched the exact spelling instead. So the two entry points answered "who
    writes this field" differently, with nothing in either report saying which rule was
    applied -- and a table element, which is where COBOL puts most of its state, had no
    co-assignments at all."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [_move("'1'", "WS-TAB(1)"), _move("'2'", "WS-B")],
                }
            ]
        )
    )

    assert _fields(_for(cfg, "WS-TAB")) == {"WS-B": Tier.SAME_PARAGRAPH}


def test_a_field_is_not_its_own_co_assignment_under_a_subscript() -> None:
    """F4: matching by base name has to apply to the exclusion of the queried field
    too, or WS-TAB(1) is reported as a field co-assigned with WS-TAB."""
    cfg = build_program(
        _asg(
            [
                {
                    "name": "MAIN",
                    "statements": [
                        _move("'1'", "WS-TAB(1)"),
                        _move("'2'", "WS-TAB(2)"),
                    ],
                }
            ]
        )
    )

    assert _for(cfg, "WS-TAB") == ()

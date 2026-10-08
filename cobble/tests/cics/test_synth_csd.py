"""What a synthesised CSD may and may not claim.

A corpus can arrive with no CSD at all: the transaction definitions live in a
CICS region nobody exported. Without them the flow stage has no worklist, so
every CICS member and every literal LINK/XCTL edge is missing from the graph.
This module reconstructs the definitions from the members themselves -- from
literal transaction ids in the source, plus the corpus's own naming convention,
which the config supplies. Everything it cannot establish is either marked
synthetic or reported; nothing is guessed into an edge.
"""

from __future__ import annotations

from cics.csd_parse import parse_csd
from cobble.cics.synth_csd import (
    SYNTHETIC_TRANSID_PREFIX,
    Tier,
    TransidRule,
    render_csd,
    report_lines,
    synthesise_csd,
    tier_counts,
)

# The convention this test corpus uses: a member is named PGM<tail>, and it owns
# the transaction T<tail>. Real corpora spell their own rule out in the config.
_RULE = TransidRule(member_pattern=r"^PGM(?P<tail>.{3})$", transid_template="T{tail}")


def _member(*lines: str) -> bytes:
    """Fixed-form source: six columns of sequence area, then the content area."""
    return "\n".join(f"      {line}" for line in lines).encode("latin-1")


def _cics_member(*lines: str) -> bytes:
    return _member("EXEC CICS SEND MAP('SOMEMAP') END-EXEC.", *lines)


def _synthesise(members, *rules: TransidRule):
    return synthesise_csd(members, rules or (_RULE,))


def test_every_member_that_uses_cics_is_defined_exactly_once() -> None:
    """The invariant the whole module exists to hold: a program using CICS is
    referenced by the CSD, without exception.

    The worklist is transid_to_program.values(), so a member with no define is a
    member the flow stage never parses -- its LINK/XCTL edges are silently absent
    from the graph and nothing in the run says so. Which tier a member lands in is
    a question about evidence; whether it lands in one at all is not negotiable.

    The other direction matters too: a define for a member with no EXEC CICS
    drags it out of the batch FILE-CONTROL stage, and a member defined twice is a
    dict key collision in parse_csd that drops one of them.
    """
    members = {
        "PGM101": _cics_member("EXEC CICS RETURN TRANSID('T101') END-EXEC."),
        "PGM102": _cics_member(),
        "OTHER99": _cics_member(),
        "BATCH01": _member("MOVE 1 TO WS-X."),
    }

    result = _synthesise(members)

    uses_cics = {"PGM101", "PGM102", "OTHER99"}
    defined = [d.program for d in result.defines]
    assert sorted(defined) == sorted(uses_cics)
    assert len(defined) == len(set(defined))


def test_a_transaction_a_member_returns_to_is_owned_by_the_named_member() -> None:
    """The strongest evidence available without a CSD: the member names the
    transaction in its own source, and the convention says that member owns it."""
    result = _synthesise(
        {"PGM001": _cics_member("EXEC CICS RETURN TRANSID('T001') END-EXEC.")}
    )

    assert [(d.transid, d.program, d.tier) for d in result.defines] == [
        ("T001", "PGM001", Tier.CORROBORATED)
    ]


def test_a_transaction_only_another_member_starts_is_convention_only() -> None:
    """One member STARTs a transaction it does not own. The convention places the
    owner, but the owner's own source never names the transid -- weaker evidence,
    so it is tiered apart and stays countable in the report."""
    result = _synthesise(
        {
            "PGM002": _cics_member(),
            "PGM003": _cics_member(
                "EXEC CICS START TRANSID('T002') END-EXEC.",
                "EXEC CICS RETURN TRANSID('T003') END-EXEC.",
            ),
        }
    )

    tiers = {d.program: d.tier for d in result.defines}
    assert tiers == {"PGM002": Tier.CONVENTION, "PGM003": Tier.CORROBORATED}


def test_a_cics_member_the_convention_cannot_place_gets_a_synthetic_transid() -> None:
    """The point of the exercise: a member with no recoverable transaction still
    has to reach the flow stage's worklist, because its literal LINK and XCTL
    edges are real. It enters under a transid marked synthetic, per member so
    that two of them cannot collapse onto one CSD key."""
    result = _synthesise({"NOTNAMED": _cics_member()})

    assert result.defines[0].transid == f"{SYNTHETIC_TRANSID_PREFIX}NOTNAMED"
    assert result.defines[0].program == "NOTNAMED"
    assert result.defines[0].tier is Tier.SYNTHETIC


def test_a_member_with_no_exec_cics_is_not_a_transaction_program() -> None:
    """A batch member is the other stage's work. Naming a transaction after it
    would put it in the CICS worklist and take it out of FILE-CONTROL's."""
    result = _synthesise({"PGM004": _member("MOVE 'T004' TO WS-TRAN.")})

    assert result.defines == ()


def test_a_transaction_no_member_claims_is_reported_not_invented() -> None:
    """T999 is real -- something in the corpus starts it -- but no member the
    convention names exists. Inventing a PROGRAM for it would put a node in the
    graph that no source backs.

    PGM005 goes the other way: the convention says it owns T005, but T005 appears
    nowhere in the corpus, so that is a name-shaped guess with no evidence behind
    it. The member still enters the worklist, under a synthetic transid.
    """
    result = _synthesise(
        {"PGM005": _cics_member("EXEC CICS START TRANSID('T999') END-EXEC.")}
    )

    assert [(d.transid, d.tier) for d in result.defines] == [
        (f"{SYNTHETIC_TRANSID_PREFIX}PGM005", Tier.SYNTHETIC)
    ]
    assert result.unclaimed == ("T999",)


def test_two_members_the_convention_maps_to_one_transaction_are_both_reported() -> None:
    """The convention is only useful while it is unambiguous. A collision means
    the rule does not fit this corpus, which the report has to say -- and both
    members fall back. A member that also does RETURN TRANSID still recovers
    under that tier; only the convention is discredited, not the self-declaration."""
    result = _synthesise(
        {
            "PGM006": _cics_member("EXEC CICS RETURN TRANSID('T006') END-EXEC."),
            "PGM006X": _cics_member(),
        },
        TransidRule(
            member_pattern=r"^PGM(?P<tail>.{3}).*$", transid_template="T{tail}"
        ),
    )

    assert result.collisions == (("T006", ("PGM006", "PGM006X")),)
    assert [d.tier for d in result.defines] == [
        Tier.RETURN_TRANSID,
        Tier.SYNTHETIC,
    ]


def test_a_collision_on_a_transaction_the_corpus_never_names_is_not_reported() -> None:
    """A collision is only news when the transaction is real.

    Two members whose names derive the same id are already both synthetic when
    that id appears nowhere in the corpus -- the derivation lost to no evidence,
    not to the ambiguity. Reporting it as a collision reads as "your convention
    does not fit", which is a different and much bigger claim: on the onboarding
    corpus 221 of 223 reported collisions were this, burying the 2 real ones.
    """
    result = _synthesise(
        {
            "PGM010": _cics_member("EXEC CICS START TRANSID('T999') END-EXEC."),
            "PGM010X": _cics_member(),
        },
        TransidRule(
            member_pattern=r"^PGM(?P<tail>.{3}).*$", transid_template="T{tail}"
        ),
    )

    assert result.collisions == ()
    assert [d.tier for d in result.defines] == [Tier.SYNTHETIC, Tier.SYNTHETIC]


def test_the_first_convention_that_fits_the_member_name_wins() -> None:
    """A corpus rarely has one member-naming family. The rules are ordered, and a
    member is placed by the first one that fits it, so a narrow rule can be listed
    ahead of a broad one without the broad one swallowing its members."""
    result = _synthesise(
        {"OLD002": _cics_member("EXEC CICS RETURN TRANSID('T002') END-EXEC.")},
        _RULE,
        TransidRule(member_pattern=r"^OLD(?P<tail>.{3})$", transid_template="T{tail}"),
    )

    assert [(d.transid, d.program) for d in result.defines] == [("T002", "OLD002")]


def test_the_report_counts_every_tier_and_names_what_it_could_not_place() -> None:
    """The counts are the decision: a corpus where most definitions are synthetic
    means the convention in the config is wrong, and one where a transaction goes
    unclaimed means a member is missing from cobol_globs. Neither is visible from
    the CSD itself, so the run has to say it."""
    result = _synthesise(
        {
            "PGM001": _cics_member(
                "EXEC CICS RETURN TRANSID('T001') END-EXEC.",
                "EXEC CICS START TRANSID('T002') END-EXEC.",
                "EXEC CICS START TRANSID('T999') END-EXEC.",
            ),
            "PGM002": _cics_member(),
            "NOTNAMED": _cics_member(),
        }
    )

    assert tier_counts(result) == {
        Tier.CORROBORATED: 1,
        Tier.CONVENTION: 1,
        Tier.RETURN_TRANSID: 0,
        Tier.SYNTHETIC: 1,
    }
    assert "T999" in "\n".join(report_lines(result))


def test_a_commented_out_transaction_is_not_evidence() -> None:
    """Column 7 is the comment indicator in fixed-form COBOL. A commented EXEC
    CICS is not code, and treating it as code invents both the member's CICS-ness
    and its transaction."""
    result = _synthesise(
        {
            "PGM007": (
                "      *EXEC CICS RETURN TRANSID('T007') END-EXEC.\n"
                "      MOVE 1 TO WS-X."
            ).encode("latin-1")
        }
    )

    assert result.defines == ()


def test_text_past_column_72_is_not_evidence() -> None:
    """Columns 73-80 are the identification area -- sequence numbers, member
    stamps, change ids. The compiler does not read them and neither does this."""
    padded = "      MOVE 1 TO WS-X." + " " * 50 + "EXEC CICS"
    result = _synthesise({"PGM008": padded.encode("latin-1")})

    assert result.defines == ()


def test_the_rendered_csd_is_one_the_csd_parser_reads_back() -> None:
    """The output's only consumer is parse_csd, via build_graph. Rendering
    something DFHCSDUP-shaped that the parser then drops would leave the flow
    stage with a worklist that is quietly short."""
    result = _synthesise(
        {
            "PGM009": _cics_member("EXEC CICS RETURN TRANSID('T009') END-EXEC."),
            "NOTNAMED": _cics_member(),
        }
    )

    return_value = render_csd(result)

    assert return_value.endswith("\n")
    assert _parsed(return_value) == {
        "T009": "PGM009",
        f"{SYNTHETIC_TRANSID_PREFIX}NOTNAMED": "NOTNAMED",
    }


def _parsed(csd_source: str) -> dict[str, str]:
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csd", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(csd_source)
        path = Path(handle.name)
    parsed = dict(parse_csd(path))
    path.unlink(missing_ok=True)
    return parsed

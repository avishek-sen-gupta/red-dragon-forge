"""synth_csd.py — reconstruct CICS transaction definitions for a corpus that
arrives without a CSD.

A CSD is an export of a running CICS region, and plenty of corpora are handed
over without one. Its absence is not a small gap: ``build_graph`` skips the whole
CICS flow stage when ``csd_files`` is empty, and even when it runs, the worklist
is ``transid_to_program.values()`` -- so with no CSD, no CICS member is parsed at
all. Every literal ``LINK``/``XCTL`` edge the extractor already knows how to find
stays absent, and the members route into the batch FILE-CONTROL stage instead.

What is recoverable from the members alone:

  * A transaction id that appears as a literal in ``TRANSID(...)`` is real -- some
    program returns to it or starts it.
  * A corpus's member names normally encode which transaction a member serves.
    That convention is a property of the site, so it arrives as a config-supplied
    regex plus a template (``TransidRule``) and never appears in cobble's source.

Which yields three tiers of definition, and the report says how many of each:

  * ``CORROBORATED`` -- the convention names a member for the transaction AND that
    member's own source names the transaction. Two independent signals agreeing.
  * ``CONVENTION`` -- the transaction is named somewhere in the corpus and the
    convention places it on exactly one member, but that member is silent about
    it. Weaker, and countable separately for that reason.
  * ``SYNTHETIC`` -- a CICS member no transaction can be tied to. It still gets a
    definition, under ``UNKNOWN.<member>``, because the point is to get the member
    into the flow stage's worklist; its literal LINK/XCTL edges are real
    regardless of how it is entered. One transid per member, never a shared
    ``UNKNOWN`` key: ``parse_csd`` returns a dict, so a repeated key would collapse
    and silently drop members from the worklist. ``build_graph`` recognises the
    prefix and suppresses the STARTS edge, so no invented TRANSACTION node reaches
    the graph.

Nothing else is asserted. A transaction the corpus names but the convention
cannot place is reported as unclaimed, not given an invented program; two members
whose names claim one real transaction are reported as a collision and both fall
back to synthetic, because a convention that collides does not fit this corpus.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import chain, groupby
from operator import itemgetter

from interpreter.cobol.source_text import decode_source

# The transid a member with no recoverable transaction is defined under. Dots are
# legal in a DFHCSDUP value, so cics.csd_parse reads these back unchanged.
SYNTHETIC_TRANSID_PREFIX = "UNKNOWN."

_GROUP = "SYNTHETIC"

# Fixed-form COBOL: column 7 is the indicator, 8-72 the content area, 73-80 the
# identification area. Zero-based, so the content slice starts at the indicator
# and a comment is recognised by the character there.
_INDICATOR_COLUMN = 6
_CONTENT_END = 72
_COMMENT_INDICATORS = ("*", "/")

_EXEC_CICS = re.compile(r"EXEC\s+CICS\b")
_TRANSID_LITERAL = re.compile(r"TRANSID\s*\(\s*(['\"])(?P<transid>[^'\"]{1,4})\1\s*\)")


class Tier(StrEnum):
    """How much evidence stands behind a definition. Strongest first."""

    CORROBORATED = "corroborated"
    CONVENTION = "convention"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class TransidRule:
    """A corpus's own naming convention, from its config.

    ``member_pattern`` is matched whole against the member name; the named groups
    it captures are substituted into ``transid_template``. A member whose name
    does not match owns no transaction as far as the convention is concerned.

    Config-supplied rather than coded because the convention belongs to the site:
    a wrong one has to be visible and correctable where the corpus is described,
    not buried in cobble.
    """

    member_pattern: str
    transid_template: str


@dataclass(frozen=True)
class Define:
    """One reconstructed ``DEFINE TRANSACTION(...) PROGRAM(...)``."""

    transid: str
    program: str
    tier: Tier


@dataclass(frozen=True)
class SynthesisedCsd:
    defines: tuple[Define, ...] = ()
    unclaimed: tuple[str, ...] = ()
    collisions: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class _CicsMember:
    name: str
    own_transids: frozenset[str]
    derived: str


def _is_comment(line: str) -> bool:
    return (
        len(line) > _INDICATOR_COLUMN and line[_INDICATOR_COLUMN] in _COMMENT_INDICATORS
    )


def code_text(raw: bytes) -> str:
    """The content area of every non-comment line, joined and upper-cased.

    Whole-line scanning finds transactions in change stamps out in columns 73-80
    and in code someone commented out years ago, and counts the member as a CICS
    program on the strength of it.
    """
    lines = decode_source(raw).splitlines()
    return " ".join(
        line[_INDICATOR_COLUMN:_CONTENT_END] for line in lines if not _is_comment(line)
    ).upper()


def _literal_transids(text: str) -> frozenset[str]:
    """Every transaction id the source names as a literal, whichever verb names it."""
    return frozenset(
        match.group("transid") for match in _TRANSID_LITERAL.finditer(text)
    )


def _by_rule(member: str, rule: TransidRule) -> str:
    """The transaction this one convention says the member owns, or "" when the
    member's name does not fit it."""
    matched = re.fullmatch(rule.member_pattern, member)
    return rule.transid_template.format(**matched.groupdict()) if matched else ""


def _derived_transid(member: str, rules: Sequence[TransidRule]) -> str:
    """What the first convention that fits this member's name says it owns.

    Ordered, so a corpus with more than one member-naming family can list its
    narrow rules ahead of its broad ones. "" when no rule fits.
    """
    return next((t for t in (_by_rule(member, r) for r in rules) if t), "")


def _scanned(
    name: str, raw: bytes, rules: Sequence[TransidRule]
) -> tuple[_CicsMember, ...]:
    """The member as a CICS member, or nothing at all when it holds no EXEC CICS.

    A tuple rather than a value so the caller flattens the batch members away: a
    batch member belongs to the FILE-CONTROL stage, and defining a transaction for
    it moves it out of that stage and into a worklist it has no business in.
    """
    text = code_text(raw)
    if not _EXEC_CICS.search(text):
        return ()
    upper = name.upper()
    return (
        _CicsMember(
            name=upper,
            own_transids=_literal_transids(text),
            derived=_derived_transid(upper, rules),
        ),
    )


def _claimants(members: Sequence[_CicsMember]) -> Mapping[str, tuple[str, ...]]:
    """Derived transid -> the members whose names claim it, which a convention
    that fits the corpus makes exactly one each."""
    claimed = sorted(
        (member.derived, member.name) for member in members if member.derived
    )
    return {
        transid: tuple(name for _, name in group)
        for transid, group in groupby(claimed, key=itemgetter(0))
    }


def _may_claim(
    member: _CicsMember,
    claimants: Mapping[str, tuple[str, ...]],
    literals: frozenset[str],
) -> bool:
    """Whether the member may be defined under its convention-derived transaction.

    Two conditions. The transaction has to be one the corpus names somewhere --
    otherwise the definition rests on the member's name alone, which is a guess,
    not evidence. And no other member's name may claim it, because a convention
    that maps two members onto one transaction has stopped being informative.
    """
    return member.derived in literals and claimants.get(member.derived, ()) == (
        member.name,
    )


def _evidence_tier(member: _CicsMember) -> Tier:
    if member.derived in member.own_transids:
        return Tier.CORROBORATED
    return Tier.CONVENTION


def _define(
    member: _CicsMember,
    claimants: Mapping[str, tuple[str, ...]],
    literals: frozenset[str],
) -> Define:
    if _may_claim(member, claimants, literals):
        return Define(member.derived, member.name, _evidence_tier(member))
    return Define(
        f"{SYNTHETIC_TRANSID_PREFIX}{member.name}", member.name, Tier.SYNTHETIC
    )


def _unclaimed(literals: frozenset[str], defines: Sequence[Define]) -> tuple[str, ...]:
    """Transactions the corpus names that no member ends up owning: real
    transactions whose program is not recoverable, reported rather than invented."""
    owned = frozenset(define.transid for define in defines)
    return tuple(sorted(literals - owned))


def _collisions(
    claimants: Mapping[str, tuple[str, ...]],
    literals: frozenset[str],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Transactions the corpus names that more than one member's name claims.

    Restricted to transactions that are real, because that is what makes the
    ambiguity worth a line: those members would otherwise have been defined, and
    the collision is the only reason they were not. Two members deriving an id
    that appears nowhere are already synthetic for want of evidence -- reporting
    that as a collision says the convention does not fit the corpus, which is a
    far bigger claim than the data supports.
    """
    return tuple(
        (transid, names)
        for transid, names in claimants.items()
        if len(names) > 1 and transid in literals
    )


def synthesise_csd(
    members: Mapping[str, bytes], rules: Sequence[TransidRule]
) -> SynthesisedCsd:
    """Reconstruct the transaction definitions the corpus's CICS members imply.

    ``members`` maps member name (the file stem, which is what ``build_graph``
    resolves CICS programs by) to its raw bytes. Pure: the caller reads the files.
    """
    scanned = tuple(
        chain.from_iterable(
            _scanned(name, raw, rules) for name, raw in sorted(members.items())
        )
    )
    literals = frozenset(chain.from_iterable(member.own_transids for member in scanned))
    claimants = _claimants(scanned)
    defines = tuple(_define(member, claimants, literals) for member in scanned)
    return SynthesisedCsd(
        defines=defines,
        unclaimed=_unclaimed(literals, defines),
        collisions=_collisions(claimants, literals),
    )


def tier_counts(csd: SynthesisedCsd) -> Mapping[Tier, int]:
    """How many definitions each tier of evidence produced, every tier present."""
    tiers = tuple(define.tier for define in csd.defines)
    return {tier: tiers.count(tier) for tier in Tier}


_TIER_MEANING = {
    Tier.CORROBORATED: "the convention and the member's own source agree",
    Tier.CONVENTION: "named elsewhere in the corpus, not by the member itself",
    Tier.SYNTHETIC: f"no recoverable transaction: {SYNTHETIC_TRANSID_PREFIX}<member>",
}


def report_lines(csd: SynthesisedCsd) -> tuple[str, ...]:
    """What the run has to say about a CSD it made up.

    The counts are the decision, not trivia: mostly-synthetic means the convention
    in the config does not fit this corpus, and an unclaimed transaction means a
    member the corpus starts is missing from ``cobol_globs``. Neither is visible
    from the CSD file afterwards.
    """
    counts = tier_counts(csd)
    return (
        f"synthetic CSD: {len(csd.defines)} definition(s)",
        *(f"  {counts[tier]:>6}  {tier} ({_TIER_MEANING[tier]})" for tier in Tier),
        f"  {len(csd.unclaimed):>6}  transaction(s) no member claims"
        + _named(csd.unclaimed),
        *(
            f"  collision: {transid} claimed by {', '.join(names)}"
            for transid, names in csd.collisions
        ),
    )


def _named(items: Sequence[str]) -> str:
    return f": {', '.join(items)}" if items else ""


def render_csd(csd: SynthesisedCsd) -> str:
    """The DEFINE lines, in the subset of DFHCSDUP syntax cics.csd_parse reads."""
    return "".join(
        f"DEFINE TRANSACTION({define.transid}) PROGRAM({define.program}) "
        f"GROUP({_GROUP})\n"
        for define in csd.defines
    )

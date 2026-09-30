"""The value domain: what an extent can hold, and why the set may be short."""

from __future__ import annotations

from cobble.dataflow.fields.values import (
    MAX_VALUES,
    EMPTY,
    UnresolvedReason,
    ValueSet,
    because,
    bounded,
    fitted,
    merged,
    of_value,
    refitted,
)


def test_a_set_over_the_budget_keeps_the_lowest_sorted_and_records_the_overflow():
    values = frozenset(f"PGM{n:05d}".encode() for n in range(MAX_VALUES + 8))
    result = bounded(values, frozenset())

    assert result.values == frozenset(sorted(values)[:MAX_VALUES])
    assert result.reasons == frozenset({UnresolvedReason.OVER_BUDGET})
    assert result.complete is False
    assert bounded(frozenset({b"PGMA"}), frozenset()) == of_value(b"PGMA")


def test_merging_unions_both_components_and_re_applies_the_budget():
    left = ValueSet(frozenset({b"PGMA"}), frozenset({UnresolvedReason.FROM_FILE}))
    right = ValueSet(frozenset({b"PGMB"}), frozenset({UnresolvedReason.NO_EXTENT}))
    big = bounded(
        frozenset(f"A{n:07d}".encode() for n in range(MAX_VALUES - 2)), frozenset()
    )
    other = bounded(
        frozenset(f"B{n:07d}".encode() for n in range(MAX_VALUES - 2)), frozenset()
    )

    assert merged(left, right) == ValueSet(
        frozenset({b"PGMA", b"PGMB"}),
        frozenset({UnresolvedReason.FROM_FILE, UnresolvedReason.NO_EXTENT}),
    )
    assert merged(of_value(b"PGMA"), EMPTY) == of_value(b"PGMA")
    assert merged(EMPTY, EMPTY).complete is True
    assert big.complete is True and other.complete is True
    assert len(merged(big, other).values) == MAX_VALUES
    assert merged(big, other).reasons == frozenset({UnresolvedReason.OVER_BUDGET})


def test_a_value_is_truncated_or_space_filled_to_the_field_width():
    assert fitted(b"ABCDEFGH", 4) == b"ABCD"
    assert fitted(b"CO", 8) == b"CO      "
    assert fitted(b"COSGN00C", 8) == b"COSGN00C"
    assert refitted(
        ValueSet(frozenset({b"CO", b"ABCDEFGHIJ"}), frozenset()), 8
    ) == ValueSet(frozenset({b"CO      ", b"ABCDEFGH"}), frozenset())
    assert refitted(because(UnresolvedReason.FROM_FILE), 8) == because(
        UnresolvedReason.FROM_FILE
    )

"""
tests/unit/test_strategy_stores.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for ``squall.strategy_stores.merge_field_meta``'s precedence,
directly against the store functions -- no VM, no strategy construction.

Covers the review finding fixed here: a flat ``SharedSqlStores.field_meta``
shared across an entire spec must not let an EARLIER program's bridge-derived
(inferred) metadata outrank a LATER program's own bridge-derived metadata for
the later program's own field, merely because the earlier program compiled
first. An explicit sidecar declaration still outranks any inference.
"""

from __future__ import annotations

from squall.strategy_stores import SharedSqlStores, absorb_field_meta, merge_field_meta


def test_a_later_programs_own_derived_metadata_wins_over_an_earlier_programs():
    """Reproduces the review's finding 5 scenario directly: program A's
    bridge-derived WS-DESC (len=10) must not survive program B's own,
    unrelated WS-DESC (len=50) merely because A compiled first into the same
    shared store. Neither field is sidecar-declared, so this is a pure
    inference-vs-inference collision -- the exact case the old
    ``{**derived, **store}`` got backwards (it kept A's value, discarding
    B's).

    That old ordering, in full: ``{**derived, **store}`` over
    ``store = {"WS-DESC": {"length": 10}}`` and
    ``derived = {"WS-DESC": {"length": 50}}`` evaluates to
    ``{"WS-DESC": {"length": 10}}`` -- the earlier program's value survives
    B's own, unrelated inference for the same bare COBOL name. This test
    (not a standalone one -- see history for
    ``test_old_ordering_would_fail_the_cross_program_case``, removed for
    proving nothing about ``merge_field_meta`` itself) is what actually
    falls over under that ordering: the assertion below would read 10, not
    50.
    """
    stores = SharedSqlStores()

    merge_field_meta(stores.field_meta, {"WS-DESC": {"length": 10}})
    assert stores.field_meta["WS-DESC"] == {"length": 10}

    merge_field_meta(
        stores.field_meta,
        {"WS-DESC": {"length": 50}},
        stores.sidecar_field_names,
    )

    assert stores.field_meta["WS-DESC"] == {"length": 50}


def test_a_sidecar_declaration_still_wins_over_any_programs_inference():
    """The explicit/inferred asymmetry the old code was trying to preserve
    must survive the fix: once a name is sidecar-declared (by any program),
    no later inference -- from that program or another -- displaces it."""
    stores = SharedSqlStores()
    absorb_field_meta(
        stores.field_meta,
        {"DCL-TR-DESCRIPTION": {"category": "ALPHANUMERIC", "length": 999}},
        stores.sidecar_field_names,
    )

    merge_field_meta(
        stores.field_meta,
        {"DCL-TR-DESCRIPTION": {"category": "VARCHAR", "length": 50}},
        stores.sidecar_field_names,
    )

    assert stores.field_meta["DCL-TR-DESCRIPTION"] == {
        "category": "ALPHANUMERIC",
        "length": 999,
    }

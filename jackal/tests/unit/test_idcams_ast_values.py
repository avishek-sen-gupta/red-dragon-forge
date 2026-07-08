"""Tests for IDCAMS AST value types."""

from __future__ import annotations

import pytest

from jackal.idcams.ast_values import Name, Retention, SpaceAllocation
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_plain_name_is_not_generic():
    n = Name(text="A.B.C")
    assert n.generic is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_valid_generic_name_single_trailing_wildcard():
    n = Name.parse("A.*")
    assert n.text == "A.*"
    assert n.generic is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_valid_generic_name_wildcard_mid_qualifier_list():
    n = Name.parse("A.*.C")
    assert n.generic is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_generic_name_rejects_leading_wildcard():
    with pytest.raises(ValueError):
        Name.parse("*.B.C")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_generic_name_rejects_multiple_wildcards():
    with pytest.raises(ValueError):
        Name.parse("A.*.*")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_generic_name_rejects_partial_qualifier_wildcard():
    with pytest.raises(ValueError):
        Name.parse("A.B*")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_space_allocation_holds_unit_primary_secondary():
    s = SpaceAllocation(unit="CYLINDERS", primary=10, secondary=5)
    assert s.unit == "CYLINDERS"
    assert s.secondary == 5


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_retention_to_date_and_for_days_are_independent_fields():
    r1 = Retention(to_date="99365")
    r2 = Retention(for_days=9999)
    assert r1.for_days is None
    assert r2.to_date is None

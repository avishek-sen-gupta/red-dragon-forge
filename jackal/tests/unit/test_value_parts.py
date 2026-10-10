"""Unit tests for the Literal/Symbol value-part type."""

from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.value_parts import Literal, Symbol, SymbolName, literal, resolve


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_literal_helper_builds_single_literal_part():
    assert literal("A.B") == (Literal("A.B"),)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_literal_helper_empty_string_is_empty_value():
    assert literal("") == (Literal(""),)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_concatenates_literal_parts():
    value = (Literal("A."), Literal("B"))
    assert resolve(value) == "A.B"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_empty_tuple_is_empty_string():
    assert resolve(()) == ""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_raises_on_unresolved_symbol():
    value = (Symbol(SymbolName("CNTLLIB")),)
    with pytest.raises(ValueError, match="CNTLLIB"):
        resolve(value)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_resolve_raises_on_symbol_mixed_with_literal():
    value = (Symbol(SymbolName("CNTLLIB")), Literal("(REPROCT)"))
    with pytest.raises(ValueError, match="CNTLLIB"):
        resolve(value)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_literal_and_symbol_are_frozen_and_hashable():
    assert hash(Literal("A")) == hash(Literal("A"))
    assert hash(Symbol(SymbolName("A"))) == hash(Symbol(SymbolName("A")))
    assert Literal("A") != Symbol(SymbolName("A"))

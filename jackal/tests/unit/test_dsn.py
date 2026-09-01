"""Unit tests for the DSN type hierarchy."""

from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.value_parts import Literal, Symbol, literal


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_direct_dsn_name():
    from jackal.dsn import DirectDSN

    assert DirectDSN(literal("MY.DS")).name == literal("MY.DS")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_ref_alias():
    from jackal.dsn import TempRef

    assert TempRef("&&WORKIN").alias == "&&WORKIN"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_direct_dsn_equality():
    from jackal.dsn import DirectDSN

    assert DirectDSN(literal("A")) == DirectDSN(literal("A"))
    assert DirectDSN(literal("A")) != DirectDSN(literal("B"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_ref_equality():
    from jackal.dsn import TempRef

    assert TempRef("&&A") == TempRef("&&A")
    assert TempRef("&&A") != TempRef("&&B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_extracts_direct_name():
    from jackal.dsn import DirectDSN, dsn_key

    assert dsn_key(DirectDSN(literal("MY.DS"))) == "MY.DS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_raises_for_unresolved_symbol():
    from jackal.dsn import DirectDSN, dsn_key

    with pytest.raises(ValueError, match="CNTLLIB"):
        dsn_key(DirectDSN((Symbol("CNTLLIB"),)))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_raises_for_temp_ref():
    from jackal.dsn import TempRef, dsn_key

    with pytest.raises(TypeError, match="TempRef"):
        dsn_key(TempRef("&&WORKIN"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_fields():
    from jackal.dsn import BackwardRef

    br = BackwardRef(step="STEP1", ddname="WRK")
    assert br.step == "STEP1"
    assert br.ddname == "WRK"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_backward_ref_equality():
    from jackal.dsn import BackwardRef

    assert BackwardRef("STEP1", "WRK") == BackwardRef("STEP1", "WRK")
    assert BackwardRef("STEP1", "WRK") != BackwardRef("STEP2", "WRK")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_raises_for_backward_ref():
    from jackal.dsn import BackwardRef, dsn_key

    with pytest.raises(TypeError, match="BackwardRef"):
        dsn_key(BackwardRef("STEP1", "WRK"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_lone_unresolved_symbol_dsn_reads_as_a_temp():
    from jackal.dsn import DirectDSN, TempRef, temp_if_unresolved

    assert temp_if_unresolved(DirectDSN((Symbol("WORK"),))) == TempRef("&WORK")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_symbol_glued_to_literal_text_is_not_a_temp():
    """&HLQ..DATA is a parameter the caller forgot to pass, not a work file:
    reading it as one would invent a dataset."""
    from jackal.dsn import DirectDSN, temp_if_unresolved

    glued = DirectDSN((Symbol("HLQ"), Literal("..DATA")))
    assert temp_if_unresolved(glued) == glued


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_symbol_too_long_to_name_a_temp_is_left_alone():
    """A temp dataset name is a DSN qualifier, so at most 8 characters.

    Unreachable from real JCL source: the bridge lexer caps a symbol name at 8
    characters and spills the rest into a Literal (&WORKAREAX lexes as
    Symbol('WORKAREA') + Literal('X')), which the glued-text rule already
    excludes. The guard states the z/OS rule for a DSN built in code.
    """
    from jackal.dsn import DirectDSN, temp_if_unresolved

    too_long = DirectDSN((Symbol("WORKAREA1"),))
    assert temp_if_unresolved(too_long) == too_long


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_if_unresolved_leaves_a_resolvable_dsn_alone():
    from jackal.dsn import DirectDSN, temp_if_unresolved

    plain = DirectDSN(literal("MY.DS"))
    assert temp_if_unresolved(plain) == plain

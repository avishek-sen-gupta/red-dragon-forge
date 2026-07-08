"""Unit tests for the DSN type hierarchy."""

from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.value_parts import literal, Symbol


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

"""Unit tests for the DSN type hierarchy."""

from __future__ import annotations

import pytest

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_direct_dsn_name():
    from jackal.dsn import DirectDSN

    assert DirectDSN("MY.DS").name == "MY.DS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_ref_alias():
    from jackal.dsn import TempRef

    assert TempRef("&&WORKIN").alias == "&&WORKIN"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_direct_dsn_equality():
    from jackal.dsn import DirectDSN

    assert DirectDSN("A") == DirectDSN("A")
    assert DirectDSN("A") != DirectDSN("B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_ref_equality():
    from jackal.dsn import TempRef

    assert TempRef("&&A") == TempRef("&&A")
    assert TempRef("&&A") != TempRef("&&B")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_extracts_direct_name():
    from jackal.dsn import DirectDSN, dsn_key

    assert dsn_key(DirectDSN("MY.DS")) == "MY.DS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dsn_key_raises_for_temp_ref():
    from jackal.dsn import TempRef, dsn_key

    with pytest.raises(TypeError, match="TempRef"):
        dsn_key(TempRef("&&WORKIN"))

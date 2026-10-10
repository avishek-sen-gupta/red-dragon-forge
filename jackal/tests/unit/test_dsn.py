"""Unit tests for the DSN variants."""

from __future__ import annotations

import pytest
from jackal.model import (
    UnresolvedDd,
    BackwardRef,
    DdName,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
)
from jackal.value_parts import Literal, Symbol, SymbolName, literal
from tests.covers import NotLanguageFeature, covers
from tests.model_build import ref


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_only_a_resolved_direct_dsn_has_a_dataset_name():
    assert DirectDSN((Literal("MY."), Literal("DS"))).dataset_name() == "MY.DS"
    with pytest.raises(ValueError, match="CNTLLIB"):
        DirectDSN((Symbol(SymbolName("CNTLLIB")),)).dataset_name()
    for dsn, says in (
        (TempRef("WORKIN"), "&&WORKIN"),
        (BackwardRef(ref("STEP1"), UnresolvedDd(DdName("WRK"))), "WRK"),
        (InStreamDSN(), "in-stream"),
        (DummyDSN(), "DUMMY"),
        (NoDSN(), "no DSN"),
    ):
        with pytest.raises(TypeError, match=says):
            dsn.dataset_name()
    assert DirectDSN(literal("A")) != DirectDSN(literal("B"))

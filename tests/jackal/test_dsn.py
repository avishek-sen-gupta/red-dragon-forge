import pytest

from cobble.jackal.dsn import (
    BackwardRef,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
    dsn_key,
)
from cobble.jackal.value_parts import Symbol, literal


def test_dsn_key_resolves_direct_dsn() -> None:
    assert dsn_key(DirectDSN(name=literal("ACCTDATA.PS"))) == "ACCTDATA.PS"


def test_dsn_key_raises_for_unresolved_symbol_in_direct_dsn() -> None:
    with pytest.raises(ValueError, match="SYM"):
        dsn_key(DirectDSN(name=(Symbol(name="SYM"),)))


def test_dsn_key_raises_for_temp_ref() -> None:
    with pytest.raises(TypeError, match="WORKIN"):
        dsn_key(TempRef(alias="&&WORKIN"))


def test_dsn_key_raises_for_backward_ref() -> None:
    with pytest.raises(TypeError, match=r"\*\.STEP1\.WRK"):
        dsn_key(BackwardRef(step="STEP1", ddname="WRK"))


def test_dsn_key_raises_for_instream_dsn() -> None:
    with pytest.raises(TypeError):
        dsn_key(InStreamDSN())


def test_dsn_key_raises_for_dummy_dsn() -> None:
    with pytest.raises(TypeError):
        dsn_key(DummyDSN())


def test_dsn_key_raises_for_no_dsn() -> None:
    with pytest.raises(TypeError):
        dsn_key(NoDSN())

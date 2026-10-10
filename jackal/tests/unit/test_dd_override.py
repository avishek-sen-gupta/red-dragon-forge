"""An override DD merges onto a PROC's DD one parameter at a time."""

from jackal.model import (
    DD,
    ConcatMember,
    DdName,
    DirectDSN,
    DummyDSN,
    NoDSN,
    NotCoded,
    NullifiedDSN,
    StepRef,
)
from jackal.value_parts import literal
from tests.covers import NotLanguageFeature, covers
from tests.model_build import disp

NAME = DdName("IN")


def _dd(
    dsn: object, d: object, sysout: bool = False, members: tuple[object, ...] = ()
) -> DD[StepRef]:
    return DD(NAME, dsn, d, (), sysout, members)


def _named(text: str) -> DirectDSN:
    return DirectDSN(literal(text))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_each_parameter_is_kept_replaced_or_nullified() -> None:
    shr, old = disp("SHR"), disp("OLD")
    proc = _dd(
        _named("T.A"),
        shr,
        members=(ConcatMember(_named("T.B"), shr), ConcatMember(_named("T.C"), shr)),
    )
    sysout_proc = _dd(NoDSN(), NotCoded(), sysout=True)
    assert (
        proc.overridden_by(_dd(NoDSN(), old)),
        proc.overridden_by(_dd(NullifiedDSN(), disp())),
        proc.overridden_by(_dd(DummyDSN(), NotCoded())),
        proc.overridden_by(_dd(NoDSN(), NotCoded(), sysout=True)),
        sysout_proc.overridden_by(_dd(_named("T.LOG"), shr)),
        _dd(DummyDSN(), NotCoded()).overridden_by(_dd(NoDSN(), NotCoded(), True)),
        proc.overridden_by(
            _dd(
                NoDSN(),
                NotCoded(),
                members=(
                    ConcatMember(NoDSN(), NotCoded()),
                    ConcatMember(_named("T.Z"), NotCoded()),
                ),
            )
        ),
    ) == (
        _dd(_named("T.A"), old, members=proc.concatenated),
        _dd(NoDSN(), disp(), members=proc.concatenated),
        _dd(DummyDSN(), NotCoded(), members=proc.concatenated),
        _dd(_named("T.A"), NotCoded(), True, proc.concatenated),
        _dd(_named("T.LOG"), shr),
        _dd(NoDSN(), NotCoded(), True),
        _dd(
            _named("T.A"),
            shr,
            members=(
                ConcatMember(_named("T.B"), shr),
                ConcatMember(_named("T.Z"), shr),
            ),
        ),
    )

"""Acceptance: every DCB form parses into its model and attributes, and the job around it is intact."""

from dataclasses import replace

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dcb_forms_parse(parse_fixture):
    from jackal.model import (
        BackwardRef,
        Dcb,
        DdName,
        DirectDSN,
        Job,
        NoDSN,
        OwnScope,
        StepName,
        StepRef,
        UnresolvedDd,
    )
    from jackal.value_parts import literal
    from tests.acceptance import build as b

    new_catlg = b.disp("NEW", "CATLG")
    model = DirectDSN(literal("T.MODEL"))
    fb80 = (literal("FB"), literal("80"))
    a_in_s1 = BackwardRef(
        StepRef(OwnScope(), StepName("S1")), UnresolvedDd(DdName("A"))
    )
    assert parse_fixture("dcb/dcb.jcl") == Job(
        "ACCEPT",
        (
            b.pgm(
                "S1",
                "PGMA",
                (
                    replace(b.dataset("A", "T.A", new_catlg), dcb=Dcb(model)),
                    replace(b.dataset("B", "T.B", new_catlg), dcb=Dcb(model, *fb80)),
                    replace(b.dataset("C", "T.C", new_catlg), dcb=Dcb(a_in_s1)),
                    replace(b.dataset("D", "T.D", new_catlg), dcb=Dcb(NoDSN(), *fb80)),
                ),
            ),
            b.pgm("S2", "PGMB", (b.dataset("E", "T.A"),)),
        ),
    )

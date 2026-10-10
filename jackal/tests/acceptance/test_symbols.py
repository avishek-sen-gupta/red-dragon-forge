"""Acceptance: PROC symbolic parameters, resolved in the caller's scope."""

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_symbols_expand(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import ProcCall
    from jackal.value_parts import literal
    from tests.acceptance import build as b

    hlq, suffix = b.symbol("HLQ"), b.symbol("SUFFIX")
    s1 = ProcCall(b.name("S1"), b.proc("SYMP"))
    s2 = ProcCall(
        b.name("S2"), b.proc("SYMP"), symbol_overrides=((hlq.name, literal("PROD")),)
    )
    s3 = ProcCall(b.name("S3"), b.proc("WRAP"))
    w1 = ProcCall(
        b.name("W1"), b.proc("SYMP"), symbol_overrides=((suffix.name, (hlq,)),)
    )
    out = b.temp("OUT", "OUTNAME", b.disp("NEW", "PASS", "DELETE"))
    assert expand_fixture("symbols/symbols.jcl") == ExpandedJob(
        "ACCEPT",
        (
            b.qualified(
                (s1,), b.pgm("P1", "PGMA", (b.dataset("IN", "T.IN"), out), parm="DFLT")
            ),
            b.qualified(
                (s2,),
                b.pgm("P1", "PGMA", (b.dataset("IN", "PROD.IN"), out), parm="DFLT"),
            ),
            b.qualified(
                (s3, w1),
                b.pgm("P1", "PGMA", (b.dataset("IN", "T.IN"), out), parm="OUT"),
            ),
        ),
    )

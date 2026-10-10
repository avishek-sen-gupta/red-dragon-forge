"""Acceptance: PROC symbolic parameters."""

from tests.acceptance.markers import EXPANDED
from tests.covers import NotLanguageFeature, covers


@EXPANDED
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_symbols_expand(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import ProcCall
    from jackal.value_parts import literal
    from tests.acceptance import build as b

    s1 = ProcCall(b.name("S1"), "SYMP")
    s2 = ProcCall(
        b.name("S2"),
        "SYMP",
        symbol_overrides=(
            (b.symbol("HLQ").name, literal("PROD")),
            (b.symbol("SUFFIX").name, (b.symbol("HLQ"),)),
        ),
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
                b.pgm("P1", "PGMA", (b.dataset("IN", "PROD.IN"), out), parm="PROD"),
            ),
        ),
    )

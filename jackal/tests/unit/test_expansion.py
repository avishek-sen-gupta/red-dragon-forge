"""expand_procs on jobs built in code, with an in-memory PROC library."""

from dataclasses import dataclass

from tests.covers import NotLanguageFeature, covers
from tests.model_build import dd, job, program
from jackal.dsn import DirectDSN, TempRef
from jackal.expansion import ExpandedJob, ProcLibrary, ProcNotFound, expand_procs
from jackal.model import ProcCall, ProcDef, ProcRef, QualifiedStep, StepName
from jackal.value_parts import Literal, Symbol, SymbolName, literal


@dataclass(frozen=True)
class _Library(ProcLibrary):
    procs: tuple[ProcDef, ...]

    def find(self, proc: ProcRef) -> ProcDef | ProcNotFound:
        found = tuple(p for p in self.procs if p.name == proc.name)
        return found[0] if found else ProcNotFound()


def _symbol(name: str) -> Symbol:
    return Symbol(SymbolName(name))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_only_a_lone_unbound_symbol_short_enough_for_a_qualifier_is_a_temp():
    lone = DirectDSN((_symbol("WORK"),))
    glued = DirectDSN((_symbol("HLQ"), Literal(".DATA")))
    too_long = DirectDSN((_symbol("WORKAREA1"),))
    step = program("S1", "PGMA", (dd("A", lone), dd("B", glued), dd("C", too_long)))
    expanded = expand_procs(job("J", (step,)), _Library(()))
    assert isinstance(expanded, ExpandedJob)
    assert [d.dsn for d in expanded.steps[0].step.dds] == [
        TempRef("WORK"),
        glued,
        too_long,
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_symbols_resolve_against_the_call_then_the_defaults_and_unbound_ones_stay():
    proc = ProcDef(
        "P",
        ((SymbolName("HLQ"), literal("TEST")), (SymbolName("SUF"), literal("X"))),
        (
            program(
                "P1",
                "PGMA",
                (
                    dd("IN", DirectDSN((_symbol("HLQ"), Literal(".DATA.")))),
                    dd(
                        "OUT",
                        DirectDSN((_symbol("SUF"), Literal("."), _symbol("NOPE"))),
                    ),
                ),
            ),
        ),
    )
    call = ProcCall(
        StepName("S1"), ProcRef("P"), ((SymbolName("HLQ"), literal("PROD")),)
    )
    expanded = expand_procs(job("J", (call,)), _Library((proc,)))
    assert expanded == ExpandedJob(
        "J",
        (
            QualifiedStep(
                (call,),
                program(
                    "P1",
                    "PGMA",
                    (
                        dd("IN", DirectDSN(literal("PROD.DATA."))),
                        dd("OUT", DirectDSN((Literal("X."), _symbol("NOPE")))),
                    ),
                ),
            ),
        ),
    )

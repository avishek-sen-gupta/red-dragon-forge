"""Acceptance: IF/THEN/ELSE/ENDIF as structure, then as guards."""

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_structure_parses(parse_fixture):
    from jackal.model import CondOp, IfBlock, Job, RcTest
    from tests.acceptance import build as b

    assert parse_fixture("if/if.jcl") == Job(
        "ACCEPT",
        (
            b.pgm("S1", "PGMA"),
            IfBlock(
                b.name("C1"),
                RcTest(b.ref("S1"), CondOp.EQ, 0),
                (
                    b.pgm("S2", "PGMB"),
                    IfBlock(
                        b.name("C2"),
                        RcTest(b.ref("S2"), CondOp.GT, 4),
                        (b.pgm("S3", "PGMC"),),
                    ),
                ),
                (b.pgm("S4", "PGMD"),),
            ),
            b.pgm("S5", "PGME"),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_terms_parse(parse_fixture):
    from jackal.model import (
        AbendCodeTest,
        AbendTest,
        AllOf,
        AllPriorSteps,
        AnyOf,
        CondOp,
        IfBlock,
        Job,
        Negated,
        RcTest,
        RunTest,
        SystemAbend,
        UserAbend,
    )
    from tests.acceptance import build as b

    s1 = b.ref("S1")

    def block(label: str, guard: object, step: object) -> IfBlock:
        return IfBlock(b.name(label), guard, (step,))

    assert parse_fixture("if/terms.jcl") == Job(
        "ACCEPT",
        (
            b.pgm("S1", "PGMA"),
            block("T1", RcTest(AllPriorSteps(), CondOp.LE, 4), b.pgm("S2", "PGMB")),
            block("T2", AbendTest(AllPriorSteps()), b.pgm("S3", "PGMC")),
            block("T3", AbendTest(s1), b.pgm("S4", "PGMD")),
            block("T4", Negated(AbendTest(AllPriorSteps())), b.pgm("S5", "PGME")),
            block(
                "T5",
                AbendCodeTest(AllPriorSteps(), UserAbend(100)),
                b.pgm("S6", "PGMF"),
            ),
            block("T6", AbendCodeTest(s1, SystemAbend(0x0C7)), b.pgm("S7", "PGMG")),
            block(
                "T7",
                AllOf(
                    (
                        RunTest(s1),
                        AnyOf((RcTest(s1, CondOp.LT, 8), Negated(AbendTest(s1)))),
                    )
                ),
                b.pgm("S8", "PGMH"),
            ),
            block(
                "T8",
                AllOf(
                    (
                        RunTest(s1),
                        AnyOf((RcTest(s1, CondOp.GE, 2), Negated(RunTest(s1)))),
                    )
                ),
                b.pgm("S9", "PGMI"),
            ),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_guards_expand(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import AllOf, CondOp, Negated, ProgramStep, RcTest
    from tests.acceptance import build as b

    s1 = b.qualified((), b.pgm("S1", "PGMA"))
    on_s1 = RcTest(s1.reference(), CondOp.EQ, 0)

    def guarded(label: str, program: str, guard: object) -> object:
        plain = b.pgm(label, program)
        return b.qualified(
            (),
            ProgramStep(
                plain.label, plain.pgm, plain.dds, plain.cond, plain.parm, guard
            ),
        )

    s2 = guarded("S2", "PGMB", on_s1)
    assert expand_fixture("if/if.jcl") == ExpandedJob(
        "ACCEPT",
        (
            s1,
            s2,
            guarded("S3", "PGMC", AllOf((on_s1, RcTest(s2.reference(), CondOp.GT, 4)))),
            guarded("S4", "PGMD", Negated(on_s1)),
            b.qualified((), b.pgm("S5", "PGME")),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_if_inside_proc_expands(expand_fixture):
    from jackal.expansion import ExpandedJob
    from jackal.model import CondOp, ProcCall, ProgramStep, RcTest
    from tests.acceptance import build as b

    call = b.called(ProcCall(b.name("S1"), b.proc("IFP")), "if/IFP.prc")
    p1 = b.qualified((call,), b.pgm("P1", "PGMA"))
    plain = b.pgm("P2", "PGMB")
    assert expand_fixture("if/in_proc.jcl") == ExpandedJob(
        "ACCEPT",
        (
            p1,
            b.qualified(
                (call,),
                ProgramStep(
                    plain.label,
                    plain.pgm,
                    plain.dds,
                    plain.cond,
                    plain.parm,
                    RcTest(p1.reference(), CondOp.EQ, 0),
                ),
            ),
        ),
    )

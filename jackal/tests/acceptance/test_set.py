"""Acceptance: SET statements define symbols for the statements after them."""

from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_statements_parse_in_order_wherever_they_sit(parse_fixture):
    from dataclasses import replace

    from jackal.model import (
        DD,
        CondOp,
        DirectDSN,
        IfBlock,
        Job,
        ProcCall,
        RcTest,
        SetStatement,
    )
    from jackal.value_parts import Literal, literal
    from tests.acceptance import build as b

    hlq, lib, sfx = b.symbol("HLQ"), b.symbol("LIB"), b.symbol("SFX")
    x = b.symbol("X")
    assert parse_fixture("set/set.jcl") == Job(
        "ACCEPT",
        (
            SetStatement(
                (
                    (hlq.name, literal("T1")),
                    (x.name, literal("A")),
                    (x.name, literal("B")),
                )
            ),
            replace(
                b.pgm(
                    "S1",
                    "PGMA",
                    (DD(b.dd_name("IN"), DirectDSN((hlq, Literal(".IN"))), b.SHR),),
                ),
                parm=(x,),
            ),
            SetStatement(((hlq.name, literal("T2")), (sfx.name, ()))),
            SetStatement(((lib.name, (hlq, Literal(".LIB"))),)),
            replace(
                b.pgm("S2", "PGMB", (DD(b.dd_name("IN"), DirectDSN((lib,)), b.SHR),)),
                parm=(Literal("A"), sfx),
            ),
            ProcCall(
                b.name("S3"),
                b.proc("SETP"),
                symbol_overrides=((b.symbol("MODE").name, literal("EXEC")),),
            ),
            IfBlock(
                b.name("C1"),
                RcTest(b.ref("S1"), CondOp.EQ, 0),
                (b.pgm("S4", "PGMC"),),
                (SetStatement(((hlq.name, literal("T4")),)),),
            ),
            b.pgm(
                "S5",
                "PGMD",
                (DD(b.dd_name("IN"), DirectDSN((hlq, Literal(".IN"))), b.SHR),),
            ),
        ),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_symbols_apply_after_the_set_beneath_exec_and_proc_values(
    expand_fixture,
):
    from dataclasses import replace

    from jackal.expansion import ExpandedJob
    from jackal.model import CondOp, ProcCall, RcTest
    from jackal.value_parts import literal
    from tests.acceptance import build as b

    s1 = b.qualified((), b.pgm("S1", "PGMA", (b.dataset("IN", "T1.IN"),), parm="B"))
    call = ProcCall(
        b.name("S3"),
        b.proc("SETP"),
        symbol_overrides=((b.symbol("MODE").name, literal("EXEC")),),
    )
    guard = RcTest(s1.reference(), CondOp.EQ, 0)
    assert expand_fixture("set/set.jcl") == ExpandedJob(
        "ACCEPT",
        (
            s1,
            b.qualified(
                (), b.pgm("S2", "PGMB", (b.dataset("IN", "T2.LIB"),), parm="A")
            ),
            b.qualified(
                (b.called(call, "set/SETP.prc"),),
                b.pgm("P1", "PGMP", (b.dataset("IN", "T2.PDFLT"),), parm="EXEC"),
            ),
            b.qualified((), replace(b.pgm("S4", "PGMC"), guard=guard)),
            b.qualified((), b.pgm("S5", "PGMD", (b.dataset("IN", "T4.IN"),))),
        ),
    )

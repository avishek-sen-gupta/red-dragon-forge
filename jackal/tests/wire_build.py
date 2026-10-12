"""Bridge output for tests, built from the wire models rather than written by hand."""

from collections.abc import Sequence

from jackal.jcl import wire

NO_COND = wire.Cond(tests=(), mode="NORMAL")
NO_DCB = wire.DcbWire(
    coded=False,
    source=wire.NoneDsn(),
    recfm=(),
    lrecl=(),
    like=wire.NoneDsn(),
    refdd=wire.NoneDsn(),
)


def lit(text: str) -> wire.LiteralPart:
    return wire.LiteralPart(text=text)


def sym(name: str) -> wire.SymbolPart:
    return wire.SymbolPart(name=name)


def name_dsn(text: str) -> wire.NameDsn:
    return wire.NameDsn(value=(lit(text),))


def dd(
    ddname: str,
    dsn: wire.Dsn = wire.NoneDsn(),
    disp: tuple[str, ...] = (),
    in_stream: tuple[str, ...] = (),
    sysout: bool = False,
) -> wire.Dd:
    return wire.Dd(
        ddname=ddname,
        dsn=dsn,
        disp=disp,
        nullified=(),
        in_stream=in_stream,
        sysout=sysout,
        concatenated=(),
        dcb=NO_DCB,
        gdg_order=(),
    )


def cond_test(code: int, op: wire.Op, step: str = "") -> wire.CondTest:
    target: wire.Target = wire.StepTarget(step=step) if step else wire.AllPrior()
    return wire.CondTest(code=code, op=op, target=target)


def program(
    label: str,
    pgm: str,
    dds: Sequence[wire.Dd] = (),
    cond: wire.Cond = NO_COND,
    parm: Sequence[wire.Part] = (),
) -> wire.Program:
    return wire.Program(
        label=label, pgm=pgm, parm=tuple(parm), cond=cond, dds=tuple(dds)
    )


def proc_call(
    label: str, proc: str, symbols: Sequence[wire.SymbolValue] = ()
) -> wire.ProcCall:
    return wire.ProcCall(
        label=label,
        proc=proc,
        symbol_overrides=tuple(symbols),
        parm_overrides=(),
        cond_overrides=(),
        dd_overrides=(),
    )


def job_json(
    name: str,
    statements: Sequence[wire.Statement],
    end_job_tests: Sequence[wire.RcComparison] = (),
) -> str:
    return wire.Document(
        wire.JobDoc(
            name=name,
            end_job_tests=tuple(end_job_tests),
            statements=tuple(statements),
        )
    ).model_dump_json()


def proc_json(
    name: str,
    defaults: Sequence[wire.SymbolValue],
    statements: Sequence[wire.Statement],
) -> str:
    return wire.Document(
        wire.ProcDoc(name=name, defaults=tuple(defaults), statements=tuple(statements))
    ).model_dump_json()

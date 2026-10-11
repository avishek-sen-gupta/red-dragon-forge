"""What jackal reads from each CardDemo job, as plain facts that survive a model change."""

import argparse
import logging
from pathlib import Path
from typing import Literal as TypeLiteral

from jackal.expansion import DirectoryProcLibrary, ExpansionFailed, expand_or_fail
from jackal.jcl.bridge_parser import JclParseError
from jackal.jcl.parser import parse_jcl
from jackal.model import (
    DD,
    DSN,
    AllPriorSteps,
    BackwardRef,
    BypassTest,
    DirectDSN,
    GenerationDSN,
    Disp,
    DispAbnormal,
    DispNormal,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    NotOverridden,
    Omitted,
    ProgramStep,
    QualifiedStep,
    StepCondition,
    TempRef,
    UnexpandedCall,
)
from jackal.value_parts import Literal, Symbol, Value
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

SNAPSHOT = Path(__file__).parent / "carddemo_snapshot.json"
PROC_DIRS = ("app/proc", "samples/proc")

EXPECTED_CHANGES: dict[str, str] = {}


class DdFacts(BaseModel):
    model_config = ConfigDict(frozen=True)
    ddname: str
    dsn: str
    disp: tuple[str, str, str]


class StepFacts(BaseModel):
    model_config = ConfigDict(frozen=True)
    step: str
    pgm: str
    parm: str
    cond: tuple[tuple[int, str, str], ...]
    dds: tuple[DdFacts, ...]


class ReadJob(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: TypeLiteral["read"] = "read"
    file: str
    job: str
    steps: tuple[StepFacts, ...]


class UnreadJob(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: TypeLiteral["unread"] = "unread"
    file: str
    error: str


class CardDemoSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    jobs: tuple[ReadJob | UnreadJob, ...]


def _part_text(part: Literal | Symbol) -> str:
    match part:
        case Literal(text=text):
            return text
        case Symbol(name=symbol):
            return f"&{symbol.text}"


def _text(value: Value) -> str:
    return "".join(_part_text(part) for part in value)


def _dsn_text(dsn: DSN, sysout: bool) -> str:
    match dsn:
        case DirectDSN(name=n):
            return _text(n)
        case GenerationDSN(base=b, relative=r):
            return f"{_text(b)}({'+' if r > 0 else ''}{r})"
        case TempRef(name=name):
            return f"&&{name}"
        case BackwardRef(step=s, dd=d):
            return f"*.{s.rendered()}.{d.rendered()}"
        case InStreamDSN():
            return "*"
        case DummyDSN():
            return "DUMMY"
        case NoDSN():
            return "SYSOUT" if sysout else ""


def _coded(slot: DispNormal | DispAbnormal | Omitted) -> str:
    match slot:
        case Omitted():
            return ""
        case _:
            return slot.value


def _disp_facts(disp: Disp) -> tuple[str, str, str]:
    return (disp.status.value, _coded(disp.normal), _coded(disp.abnormal))


def _dd_facts(dd: DD, ddname: str = "") -> DdFacts:
    return DdFacts(
        ddname=ddname or dd.ddname.text,
        dsn=_dsn_text(dd.dsn, dd.sysout),
        disp=_disp_facts(dd.disposition()),
    )


def _cond_facts(test: BypassTest) -> tuple[int, str, str]:
    target = "" if isinstance(test.target, AllPriorSteps) else test.target.rendered()
    return (test.comparison.code, test.comparison.op.value, target)


def _condition(condition: StepCondition | NotOverridden) -> tuple:
    match condition:
        case NotOverridden():
            return ()
        case _:
            return tuple(_cond_facts(t) for t in condition.bypass_tests)


def _parm(parm: Value | NotOverridden) -> str:
    match parm:
        case NotOverridden():
            return ""
        case _:
            return _text(parm)


def _program_facts(name: str, step: ProgramStep) -> StepFacts:
    return StepFacts(
        step=name,
        pgm=step.pgm.name,
        parm=_text(step.parm),
        cond=_condition(step.cond),
        dds=tuple(_dd_facts(dd) for dd in step.dds),
    )


def _unexpanded_facts(name: str, entry: UnexpandedCall) -> StepFacts:
    call = entry.call()
    qualified = tuple(
        _dd_facts(dd, f"{procstep.text}.{dd.ddname.text}")
        for procstep, overrides in call.per_step
        for dd in overrides.dds
    )
    return StepFacts(
        step=name,
        pgm=call.proc.name,
        parm=_parm(call.parm_for_first_step),
        cond=_condition(call.cond_for_every_step),
        dds=(*(_dd_facts(dd) for dd in call.dds_for_first_step), *qualified),
    )


def _step_facts(entry: QualifiedStep | UnexpandedCall) -> StepFacts:
    match entry:
        case UnexpandedCall():
            return _unexpanded_facts(entry.rendered(), entry)
        case QualifiedStep():
            return _program_facts(entry.rendered(), entry.step)


def facts_for_job(carddemo_root: Path, path: Path) -> ReadJob | UnreadJob:
    rel = str(path.relative_to(carddemo_root))
    library = DirectoryProcLibrary(tuple(carddemo_root / d for d in PROC_DIRS))
    try:
        job = expand_or_fail(parse_jcl(path.read_text(errors="replace")), library)
    except (JclParseError, ExpansionFailed) as error:
        return UnreadJob(file=rel, error=type(error).__name__)
    return ReadJob(
        file=rel, job=job.name, steps=tuple(_step_facts(s) for s in job.steps)
    )


def facts_for_corpus(carddemo_root: Path) -> CardDemoSnapshot:
    paths = sorted(p for p in carddemo_root.rglob("*") if p.suffix.lower() == ".jcl")
    logger.info("reading %d CardDemo JCL members", len(paths))
    return CardDemoSnapshot(jobs=tuple(facts_for_job(carddemo_root, p) for p in paths))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write the CardDemo facts snapshot from today's code."
    )
    parser.add_argument("carddemo_root", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    SNAPSHOT.write_text(facts_for_corpus(args.carddemo_root).model_dump_json(indent=1))
    logger.info("wrote %s", SNAPSHOT)


if __name__ == "__main__":
    main()

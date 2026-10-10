"""What jackal reads from each CardDemo job, as plain facts that survive a model change."""

import argparse
import logging
from pathlib import Path
from typing import Literal as TypeLiteral

from pydantic import BaseModel, ConfigDict

from jackal.dsn import (
    DSN,
    BackwardRef,
    DirectDSN,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    TempRef,
)
from jackal.jcl.bridge_parser import JclParseError
from jackal.jcl.parser import parse_jcl
from jackal.jcl.proc_expand import ProcExpansionError, expand_procs
from jackal.model import DD, Step
from jackal.value_parts import Literal, Symbol, Value

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
            return f"&{symbol}"


def _text(value: Value) -> str:
    return "".join(_part_text(part) for part in value)


def _dsn_text(dsn: DSN, sysout: bool) -> str:
    match dsn:
        case DirectDSN(name=n):
            return _text(n)
        case TempRef(alias=a):
            return a
        case BackwardRef(step=s, ddname=d):
            return f"*.{s}.{d}"
        case InStreamDSN():
            return "*"
        case DummyDSN():
            return "DUMMY"
        case NoDSN():
            return "SYSOUT" if sysout else ""


def _dd_facts(dd: DD) -> DdFacts:
    return DdFacts(
        ddname=dd.ddname,
        dsn=_dsn_text(dd.dsn, dd.sysout),
        disp=(dd.disp.status.value, dd.disp.normal.value, dd.disp.abnormal.value),
    )


def _step_facts(step: Step) -> StepFacts:
    return StepFacts(
        step=step.name,
        pgm=step.pgm,
        parm=_text(step.parm),
        cond=tuple((c.code, c.op.value, c.step) for c in step.conds),
        dds=tuple(_dd_facts(dd) for dd in step.dds),
    )


def facts_for_job(carddemo_root: Path, path: Path) -> ReadJob | UnreadJob:
    rel = str(path.relative_to(carddemo_root))
    try:
        job = expand_procs(
            parse_jcl(path.read_text(errors="replace")),
            tuple(carddemo_root / d for d in PROC_DIRS),
        )
    except (JclParseError, ProcExpansionError) as error:
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

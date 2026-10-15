"""Capture JCL (jackal) evidence for the capabilities presentation.

Drives jackal's JobRunner directly (not the `jackal run` CLI) because the CLI runs each
job in a throwaway temp dir, so a multi-job chain cannot share a catalog and produced
datasets are deleted before they can be excerpted.

Modes:
  chain  OUT WORK          ACCTFILE.jcl then READACCT.jcl in one catalog
  demo   OUT WORK          TRANREPT PROC expansion + a COND/referback demo job
  survey OUT WORK TIMEOUT  every CardDemo job, each in its own subprocess
  one    JOB WORK MODE RESULT_JSON   (internal: one survey job)
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import traceback
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial, reduce
from itertools import accumulate
from pathlib import Path
from types import CodeType, FrameType

from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.catalog import DatasetCatalog
from jackal.dsn import dsn_key
from jackal.jcl.parser import parse_jcl
from jackal.jcl.proc_expand import expand_procs
from jackal.model import Job, Step
from jackal.results import JobResult, StepResult
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from jackal.utilities import UTILITIES
from litter.open import open_package

HOME = Path(os.environ["CARDDEMO_HOME"])
JCL_DIR = HOME / "jcl"
CBL_DIR = HOME / "cbl"
SOURCE_DATA_DIR = HOME / "data" / "EBCDIC"
PROC_DIR = HOME / "proc"
PACKAGE = Path(os.environ["CARDDEMO_PACKAGE"])

LOADER_JOBS = (
    "ACCTFILE",
    "CARDFILE",
    "CUSTFILE",
    "XREFFILE",
    "TRANFILE",
    "TRANTYPE",
    "TRANCATG",
    "DISCGRP",
    "TCATBALF",
)
SURVEY_MODES = ("standalone", "after_loaders")

# Job failures are evidence, recorded into the artifacts; the log is for whoever
# attaches a handler, and stays silent otherwise so stdout/stderr are unchanged.
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def _emit(text: str) -> None:
    sys.stdout.write(f"{text}\n")


@dataclass(frozen=True)
class Session:
    runner: JobRunner
    catalog: DatasetCatalog
    sink: io.StringIO


@dataclass(frozen=True)
class Timed:
    result: JobResult
    seconds: float


def _staged_data(work: Path) -> Path:
    """A private copy of CardDemo's data: jobs DELETE and rewrite datasets they resolve
    there (DUSRSECJ deletes USRSEC.PS), which must never reach vendor/carddemo."""
    staged = work / "carddemo-data"
    if not staged.exists():
        shutil.copytree(SOURCE_DATA_DIR, staged)
    return staged


def _session(work: Path, workdir: Path, proclib: bool) -> Session:
    data_dir = _staged_data(work)
    runner = JobRunner(
        unresolved=RaiseErrorStrategy(),
        package=open_package(PACKAGE),
        data_dir=data_dir,
        proclib_dirs=[PROC_DIR] if proclib else (),
    )
    catalog = DatasetCatalog(workdir=workdir, data_dir=data_dir)
    return Session(runner, catalog, io.StringIO())


def _timed_run(session: Session, jcl_text: str) -> Timed:
    started_at = time.perf_counter()
    with contextlib.redirect_stdout(session.sink):
        result = session.runner.run_job(parse_jcl(jcl_text), session.catalog)
    return Timed(result, time.perf_counter() - started_at)


def _step_table(result: JobResult) -> str:
    rows = [
        f"  {s.name:<18} {s.return_code:>4}  {s.disposition.value}"
        for s in result.steps
    ]
    return "\n".join([f"  {'STEP':<18} {'RC':>4}  DISPOSITION", *rows])


def _jcl_path(job: str) -> Path:
    found = [p for p in (JCL_DIR / f"{job}.jcl", JCL_DIR / f"{job}.JCL") if p.exists()]
    if not found:
        raise FileNotFoundError(job)
    return found[0]


@dataclass(frozen=True)
class Attribution:
    """Which steps a failed run_job had started and finished, read off the traceback."""

    started: tuple[Step, ...]
    finished: tuple[StepResult, ...]

    def failed_step(self, fallback: str) -> tuple[str, str]:
        return next(((s.name, s.pgm) for s in self.started[-1:]), (fallback, ""))


_RUN_JOB = JobRunner.run_job.__code__
_RUN_STEP = JobRunner._run_step.__code__


def _frames(exc: BaseException, code: CodeType) -> tuple[FrameType, ...]:
    return tuple(
        frame
        for frame, _lineno in traceback.walk_tb(exc.__traceback__)
        if frame.f_code is code
    )


def _attribution(exc: BaseException) -> Attribution:
    """run_job appends each _run_step result to both `executed` and `results`, and one
    `results` entry per step of the expanded `job`, so a step started iff its result
    is in `executed` -- plus the step whose _run_step frame the exception unwound."""
    scopes = tuple(frame.f_locals for frame in _frames(exc, _RUN_JOB)[-1:])
    executed = tuple(r for scope in scopes for r in scope.get("executed", ()))
    ran = tuple(
        step
        for scope in scopes
        for step, result in zip(
            scope["job"].steps, scope.get("results", ()), strict=False
        )
        if any(result is done for done in executed)
    )
    in_flight = tuple(frame.f_locals["step"] for frame in _frames(exc, _RUN_STEP)[-1:])
    return Attribution(started=ran + in_flight, finished=executed)


def _zoned(raw: bytes, scale: int) -> str:
    value = int("".join(str(b & 0x0F) for b in raw))
    negative = (raw[-1] & 0xF0) == 0xD0
    return f"{'-' if negative else ''}{value / 10**scale:,.2f}"


def _comp3(raw: bytes, scale: int) -> str:
    nibbles = "".join(f"{b:02X}" for b in raw)
    digits, sign = nibbles[:-1], nibbles[-1]
    value = int(digits)
    return f"{'-' if sign == 'D' else ''}{value / 10**scale:,.2f}"


def _text(raw: bytes) -> str:
    return EbcdicTable.ebcdic_to_ascii(raw).decode("ascii", "replace")


_money = partial(_zoned, scale=2)

# OUT-ACCT-REC in CBACT01C.cbl (LRECL=107 in READACCT.jcl)
_PSCOMP_LAYOUT: tuple[tuple[str, int, Callable[[bytes], str]], ...] = (
    ("ACCT-ID", 11, _text),
    ("STATUS", 1, _text),
    ("CURR-BAL", 12, _money),
    ("CREDIT-LIMIT", 12, _money),
    ("CASH-LIMIT", 12, _money),
    ("OPEN-DATE", 10, _text),
    ("EXPIRY-DATE", 10, _text),
    ("REISSUE-DATE", 10, _text),
    ("CYC-CREDIT", 12, _money),
    ("CYC-DEBIT(COMP-3)", 7, partial(_comp3, scale=2)),
    ("GROUP-ID", 10, _text),
)
_PSCOMP_WIDTHS = tuple(width for _label, width, _decode in _PSCOMP_LAYOUT)
_PSCOMP_OFFSETS = tuple(accumulate(_PSCOMP_WIDTHS, initial=0))
_PSCOMP_LRECL = sum(_PSCOMP_WIDTHS)


def _decode_pscomp_record(rec: bytes) -> list[str]:
    return [
        decode(rec[offset : offset + width])
        for offset, (_label, width, decode) in zip(
            _PSCOMP_OFFSETS, _PSCOMP_LAYOUT, strict=False
        )
    ]


def _aligned(cells: Sequence[str], widths: Sequence[int]) -> str:
    return "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=False))


def _decode_pscomp(data: bytes, n: int) -> str:
    rows = [
        _decode_pscomp_record(data[i : i + _PSCOMP_LRECL])
        for i in range(0, min(len(data), n * _PSCOMP_LRECL), _PSCOMP_LRECL)
    ]
    headers = [label for label, _width, _decode in _PSCOMP_LAYOUT]
    widths = [max(len(h), *(len(r[c]) for r in rows)) for c, h in enumerate(headers)]
    table = [headers, ["-" * w for w in widths], *rows]
    return "\n".join(_aligned(cells, widths) for cells in table)


def _require_rc0(out: Path, log: tuple[str, ...], job: str, result: JobResult) -> None:
    if not all(s.ran and s.return_code == 0 for s in result.steps):
        (out / "acctfile-readacct.log.txt").write_text("\n".join(log))
        raise SystemExit(f"{job} did not complete with RC 0")


def _chain_job(
    out: Path, session: Session, log: tuple[str, ...], job: str
) -> tuple[str, ...]:
    path = _jcl_path(job)
    timed = _timed_run(session, path.read_text())
    lines = (
        *log,
        f"JOB {job}  (app/jcl/{path.name})  "
        f"wall {timed.seconds:.2f}s  MAXRC {max(s.return_code for s in timed.result.steps)}",
        _step_table(timed.result),
        "",
    )
    _require_rc0(out, lines, job, timed.result)
    return lines


def _chain_dataset_lines(catalog: DatasetCatalog) -> tuple[tuple[str, ...], bytes]:
    ksds = catalog.resolve("AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS")
    pscomp = catalog.resolve("AWS.M2.CARDDEMO.ACCTDATA.PSCOMP").path.read_bytes()
    lines = (
        "Datasets after the chain:",
        f"  AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS  {ksds.path.stat().st_size} bytes "
        f"(RECORDSIZE {ksds.record_size}, KEYS({ksds.key_length} {ksds.key_offset}))"
        f" = {ksds.path.stat().st_size // ksds.record_size} records",
        f"  AWS.M2.CARDDEMO.ACCTDATA.PSCOMP     {len(pscomp)} bytes "
        f"(LRECL {_PSCOMP_LRECL}) = {len(pscomp) // _PSCOMP_LRECL} records",
    )
    return lines, pscomp


def _write_sysout_excerpt(out: Path, sysout: io.StringIO) -> None:
    display = sysout.getvalue().replace("'ACCT-ID ", "\n'ACCT-ID ")
    (out / "readacct-sysout-excerpt.txt").write_text(
        "CBACT01C DISPLAY output (SYSOUT), first 60 lines; COBOL DISPLAY statements "
        "run on the RedDragon VM\n\n" + "\n".join(display.splitlines()[:60]) + "\n"
    )


def _write_pscomp_excerpt(out: Path, pscomp: bytes) -> None:
    (out / "readacct-pscomp-excerpt.txt").write_text(
        "AWS.M2.CARDDEMO.ACCTDATA.PSCOMP written by CBACT01C (READACCT STEP05), "
        "first 10 of "
        f"{len(pscomp) // _PSCOMP_LRECL} records, EBCDIC decoded per OUT-ACCT-REC "
        "(zoned decimal + COMP-3)\n"
        "Source notes (app/cbl/CBACT01C.cbl 1300-POPUL-ACCT-RECORD): CYC-DEBIT is "
        "MOVE 2525.00 when the input is zero; REISSUE-DATE is the output of CALL "
        "'COBDATFT' (HLASM, app/asm/COBDATFT.asm), which is not executed here, so it is "
        "blank; GROUP-ID is blank in the input account data.\n\n"
        + _decode_pscomp(pscomp, 10)
        + "\n"
    )


def chain(out: Path, work: Path) -> None:
    session = _session(work, workdir=work, proclib=False)
    log = reduce(
        partial(_chain_job, out, session),
        ("ACCTFILE", "READACCT"),
        ("JCL chain: ACCTFILE.jcl -> READACCT.jcl (one job-scoped DatasetCatalog)", ""),
    )
    dataset_lines, pscomp = _chain_dataset_lines(session.catalog)
    report = "\n".join((*log, *dataset_lines))
    (out / "acctfile-readacct.log.txt").write_text(report + "\n")
    _write_sysout_excerpt(out, session.sink)
    _write_pscomp_excerpt(out, pscomp)
    _emit(report)


COND_DEMO_JCL = """\
//CONDDEMO JOB 'COND and referback demo'
//* Presentation demo job (not part of CardDemo): real CardDemo datasets and
//* program CBACT01C, wired to exercise RC-gated COND= and a DSN referback.
//DELMISS  EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
   DELETE AWS.M2.CARDDEMO.NOSUCH.VSAM.KSDS CLUSTER
/*
//SKIPPED  EXEC PGM=IEFBR14,COND=(0,NE)
//DEFINE   EXEC PGM=IDCAMS,COND=(8,LT)
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
   DEFINE CLUSTER (NAME(AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS) -
          KEYS(11 0) RECORDSIZE(300 300) INDEXED)
/*
//LOAD     EXEC PGM=IDCAMS,COND=(8,LT)
//SYSPRINT DD SYSOUT=*
//ACCTDATA DD DISP=SHR,DSN=AWS.M2.CARDDEMO.ACCTDATA.PS
//ACCTVSAM DD DISP=SHR,DSN=AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS
//SYSIN    DD *
   REPRO INFILE(ACCTDATA) OUTFILE(ACCTVSAM)
/*
//READ     EXEC PGM=CBACT01C,COND=((8,LT,DELMISS),(0,NE,LOAD))
//ACCTFILE DD DISP=SHR,DSN=*.LOAD.ACCTVSAM
//OUTFILE  DD DSN=&&PSCOMP,DISP=(NEW,PASS,DELETE)
//ARRYFILE DD DSN=&&ARRY,DISP=(NEW,PASS,DELETE)
//VBRCFILE DD DSN=&&VBRC,DISP=(NEW,PASS,DELETE)
//SYSOUT   DD SYSOUT=*
"""

COND_DEMO_EXPECTED = {
    "DELMISS": (8, True),
    "SKIPPED": (0, False),
    "DEFINE": (0, True),
    "LOAD": (0, True),
    "READ": (0, True),
}


def _render_dsn(dd) -> str:
    if dd.in_stream:
        return "(in-stream)"
    try:
        return dsn_key(dd.dsn)
    except (TypeError, ValueError):
        return type(dd.dsn).__name__


def _expanded_step_line(step: Step) -> str:
    dds = ", ".join(
        f"{d.ddname}={_render_dsn(d)}"
        for d in step.dds
        if d.ddname in ("FILEIN", "FILEOUT", "SYSIN")
    )
    return f"  {step.name:<18} PGM={step.pgm:<9} {dds}"


def _expansion_lines(job: Job) -> list[str]:
    return [
        "PROC expansion: real CardDemo TRANREPT.jcl against app/proc (REPROC.prc)",
        "",
        "Before expand_procs:",
        *[f"  {s.name:<18} PGM={s.pgm}" for s in job.steps],
        "",
        "After expand_procs (proclib = app/proc):",
        *[_expanded_step_line(s) for s in expand_procs(job, [PROC_DIR]).steps],
        "",
        "Executing TRANREPT through JobRunner(proclib_dirs=[app/proc]):",
    ]


def _tranrept_outcome(work: Path, job: Job) -> str:
    session = _session(work, workdir=work / "tranrept", proclib=True)
    (work / "tranrept").mkdir(parents=True, exist_ok=True)
    try:
        with contextlib.redirect_stdout(session.sink):
            result = session.runner.run_job(job, session.catalog)
    except Exception as exc:
        logger.exception("TRANREPT stopped")
        name, pgm = _attribution(exc).failed_step("<none>")
        return f"  stopped in step {name} (PGM={pgm}): {type(exc).__name__}: {exc}"
    return _step_table(result)


def _cond_report(timed: Timed) -> str:
    return (
        "COND= / RC gating / referback demo (conddemo.jcl; presentation-authored job "
        "over real CardDemo datasets and CBACT01C)\n\n"
        f"wall {timed.seconds:.2f}s\n{_step_table(timed.result)}\n\n"
        "Expected by IBM COND semantics (bypass when `code op RC` is true):\n"
        "  DELMISS  DELETE of an absent cluster, no IF MAXCC reset -> RC 8\n"
        "  SKIPPED  COND=(0,NE): 0 NE 8 true -> bypassed\n"
        "  DEFINE   COND=(8,LT): 8 LT 8 false -> runs\n"
        "  LOAD     COND=(8,LT) -> runs\n"
        "  READ     COND=((8,LT,DELMISS),(0,NE,LOAD)) -> runs; ACCTFILE=*.LOAD.ACCTVSAM\n"
    )


def _require_cond_expectation(result: JobResult) -> None:
    actual = {s.name: (s.return_code, s.ran) for s in result.steps}
    if actual != COND_DEMO_EXPECTED:
        raise SystemExit(f"COND demo diverged from expectation: {actual}")


def _cond_demo(out: Path, work: Path) -> None:
    (work / "cond").mkdir(parents=True, exist_ok=True)
    (out / "conddemo.jcl").write_text(COND_DEMO_JCL)
    session = _session(work, workdir=work / "cond", proclib=False)
    timed = _timed_run(session, COND_DEMO_JCL)
    text = _cond_report(timed)
    (out / "conddemo.log.txt").write_text(text)
    _emit(text)
    _require_cond_expectation(timed.result)


def demo(out: Path, work: Path) -> None:
    job = parse_jcl(_jcl_path("TRANREPT").read_text())
    report = "\n".join([*_expansion_lines(job), _tranrept_outcome(work, job)])
    (out / "tranrept-proc-expansion.txt").write_text(report + "\n")
    _emit(report)
    _cond_demo(out, work)


@dataclass(frozen=True)
class Failure:
    exc: BaseException
    pgm: str
    started: tuple[Step, ...]


def _idcams_sysin_not_instream(failure: Failure) -> bool:
    sysins = [
        dd for step in failure.started[-1:] for dd in step.dds if dd.ddname == "SYSIN"
    ]
    return failure.pgm == "IDCAMS" and any(not dd.in_stream for dd in sysins[:1])


def _cobol_source_missing(failure: Failure) -> bool:
    return isinstance(failure.exc, FileNotFoundError) and str(
        failure.exc.filename
    ).endswith(".cbl")


def _missing_source_category(failure: Failure) -> str:
    unsupported = (
        failure.pgm not in UTILITIES and not (CBL_DIR / f"{failure.pgm}.cbl").exists()
    )
    return f"unsupported_program:{failure.pgm}" if unsupported else "runtime_error"


def _idcams_grammar_rejected(failure: Failure) -> bool:
    return type(failure.exc).__module__.startswith(
        "lark"
    ) or "Unhandled IDCAMS command" in str(failure.exc)


def _input_dataset_missing(failure: Failure) -> bool:
    return isinstance(failure.exc, KeyError)


def _sysin_exhausted(failure: Failure) -> bool:
    return isinstance(failure.exc, StopIteration)


def _named(category: str) -> Callable[[Failure], str]:
    return lambda _failure: category


_CATEGORY_RULES: tuple[
    tuple[Callable[[Failure], bool], Callable[[Failure], str]], ...
] = (
    (_idcams_sysin_not_instream, _named("idcams_sysin_not_instream")),
    (_cobol_source_missing, _missing_source_category),
    (_input_dataset_missing, _named("missing_input_dataset")),
    (_sysin_exhausted, _named("idcams_sysin_not_instream")),
    (_idcams_grammar_rejected, _named("idcams_unsupported")),
)


def _classify(failure: Failure) -> str:
    return next(
        (
            category(failure)
            for applies, category in _CATEGORY_RULES
            if applies(failure)
        ),
        "runtime_error:" + type(failure.exc).__name__,
    )


def _loads_cleanly(session: Session, loader: str) -> bool:
    try:
        with contextlib.redirect_stdout(session.sink):
            result = session.runner.run_job(
                parse_jcl(_jcl_path(loader).read_text()), session.catalog
            )
    except Exception:
        logger.exception("loader %s failed", loader)
        return False
    return all(s.return_code == 0 for s in result.steps if s.ran)


def _preloaded(mode: str, job: str, session: Session) -> dict[str, list[str]]:
    if mode != "after_loaders":
        return {}
    return {
        "preloaded": [
            loader
            for loader in LOADER_JOBS
            if loader != job and _loads_cleanly(session, loader)
        ]
    }


def _failure_record(exc: BaseException) -> dict:
    attribution = _attribution(exc)
    name, pgm = attribution.failed_step("<pre-step>")
    return {
        "outcome": "failed",
        "max_rc": max((s.return_code for s in attribution.finished), default=None),
        "category": _classify(Failure(exc, pgm, attribution.started)),
        "failed_step": name,
        "failed_pgm": pgm,
        "steps_completed": [[s.name, s.return_code] for s in attribution.finished],
        "error": f"{type(exc).__name__}: {exc}"[:300],
        "error_site": traceback.extract_tb(exc.__traceback__)[-1].filename.split(
            "red-dragon-forge/"
        )[-1],
    }


def _success_record(result: JobResult) -> dict:
    max_rc = max((s.return_code for s in result.steps), default=0)
    return {
        "outcome": "ran",
        "max_rc": max_rc,
        "category": "ok" if max_rc == 0 else "nonzero_rc",
        "steps": [[s.name, s.return_code, s.disposition.value] for s in result.steps],
    }


def _execution_record(session: Session, job_model: Job) -> dict:
    try:
        with contextlib.redirect_stdout(session.sink):
            result = session.runner.run_job(job_model, session.catalog)
    except Exception as exc:
        logger.exception("survey job failed")
        return _failure_record(exc)
    return _success_record(result)


def _job_record(job: str, session: Session, started_at: float) -> dict:
    try:
        job_model = parse_jcl(_jcl_path(job).read_text())
    except Exception as exc:
        logger.exception("JCL parse failed for %s", job)
        return {
            "outcome": "failed",
            "category": "jcl_parse_error",
            "error": str(exc)[:300],
        }
    return _execution_record(session, job_model) | {
        "seconds": round(time.perf_counter() - started_at, 2)
    }


def one(job: str, work: Path, mode: str, result_json: Path) -> None:
    started_at = time.perf_counter()
    session = _session(work, workdir=work, proclib=True)
    header = {"job": job, "mode": mode} | _preloaded(mode, job, session)
    record = header | _job_record(job, session, started_at)
    result_json.write_text(json.dumps(record))


def _reported_record(
    proc: subprocess.CompletedProcess[str], result_path: Path, job: str, mode: str
) -> dict:
    if result_path.exists():
        return json.loads(result_path.read_text())
    return {
        "job": job,
        "mode": mode,
        "outcome": "failed",
        "category": "harness_crash",
        "error": proc.stderr[-300:],
    }


def _survey_job(work: Path, timeout: int, mode: str, job: str) -> dict:
    job_work = work / mode / job
    job_work.mkdir(parents=True, exist_ok=True)
    result_path = job_work / "result.json"
    started_at = time.perf_counter()
    try:
        proc = subprocess.run(
            [
                sys.executable,
                __file__,
                "one",
                job,
                str(job_work),
                mode,
                str(result_path),
            ],
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return {
            "job": job,
            "mode": mode,
            "outcome": "failed",
            "category": "timeout",
            "seconds": round(time.perf_counter() - started_at, 2),
        }
    return _reported_record(proc, result_path, job, mode)


def _announced(record: Mapping) -> Mapping:
    _emit(
        f"{record['mode']:<14} {record['job']:<10} "
        f"{record['outcome']:<7} {record['category']}"
    )
    sys.stdout.flush()
    return record


def _mode_summary(records: Sequence[Mapping], mode: str) -> dict:
    rs = [r for r in records if r["mode"] == mode]
    categories = Counter(r["category"] for r in rs)
    return {
        "jobs": len(rs),
        "ran_rc0": sum(r["category"] == "ok" for r in rs),
        "ran_nonzero_rc": sum(r["category"] == "nonzero_rc" for r in rs),
        "failed": sum(r["outcome"] == "failed" for r in rs),
        "by_category": dict(sorted(categories.items())),
    }


def survey(out: Path, work: Path, timeout: int) -> None:
    jobs = sorted(p.stem for p in JCL_DIR.iterdir() if p.suffix.lower() == ".jcl")
    records = [
        _announced(_survey_job(work, timeout, mode, job))
        for mode in SURVEY_MODES
        for job in jobs
    ]
    summary = {mode: _mode_summary(records, mode) for mode in SURVEY_MODES}
    doc = {
        "generated_by": "docs/presentation/capture/jcl.sh",
        "timeout_seconds_per_job": timeout,
        "jcl_dir": "vendor/carddemo/app/jcl",
        "modes": {
            "standalone": "fresh catalog; only app/data/EBCDIC flat files resolvable",
            "after_loaders": "fresh catalog pre-populated by running the loader jobs "
            + ", ".join(LOADER_JOBS)
            + " best-effort first",
        },
        "summary": summary,
        "jobs": records,
    }
    (out / "job-survey.json").write_text(json.dumps(doc, indent=2) + "\n")
    _emit(json.dumps(summary, indent=2))


COMMANDS: dict[str, Callable[[Sequence[str]], None]] = {
    "chain": lambda args: chain(Path(args[0]), Path(args[1])),
    "demo": lambda args: demo(Path(args[0]), Path(args[1])),
    "survey": lambda args: survey(Path(args[0]), Path(args[1]), int(args[2])),
    "one": lambda args: one(args[0], Path(args[1]), args[2], Path(args[3])),
}


def main(argv: Sequence[str]) -> None:
    cmd, *args = argv
    if cmd not in COMMANDS:
        raise SystemExit(f"unknown mode {cmd}")
    COMMANDS[cmd](args)


if __name__ == "__main__":
    main(sys.argv[1:])

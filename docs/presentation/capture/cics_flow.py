"""Capture a real CardDemo CICS screen flow through cicada's CicsRegion.

    uv run --no-sync python docs/presentation/capture/cics_flow.py

Compiles the unmodified CardDemo programs, catalogs clusters loaded from
CardDemo's shipped EBCDIC data files, drives the region one turn at a time with scripted terminal
input, and writes every SEND MAP payload unchanged to
docs/presentation/artifacts/cics/NN-<map>.json plus a per-turn turns.jsonl.
Exits non-zero if the flow stops before the script is exhausted.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from catnip.alternate_index import AlternateIndex
from catnip.catalog_path import CatalogPath
from catnip.dataset import Dataset
from catnip.labels import KsdsLabel
from catnip.system_catalog import SystemCatalog
from cics.bms.generate import generate_symbolic_copybooks
from cics.bootstrap import compile_cics_program
from cics.coprocessor import build_cics_spec
from cics.dispatcher import CicsRegion, InputEvent
from cics.interval import StartQueue
from cics.runtime import install_cics_runtime
from cics.types import DispatchKind, DispatchResult
from cics.vsam.engine import VsamEngine
from cics.vsam.file_table import cics_files
from cics.vsam.format import read_flat_file
from cics.vsam.key_match import KeyMatch
from cics.vsam.read_outcome import ReadOutcome
from interpreter.project.coprocessor_compile import CoprocessorSpec
from interpreter.project.types import LinkedProgram

if TYPE_CHECKING:
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.copybook_search import CopybookSearch

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "vendor" / "carddemo" / "app"
EBCDIC = APP / "data" / "EBCDIC"
OUT = REPO / "docs" / "presentation" / "artifacts" / "cics"
HLASM_EXPORT = (
    REPO
    / "vendor"
    / "red-dragon"
    / "hlasm-bridge"
    / "che4z"
    / "build"
    / "bin"
    / "hlasm_export"
)
BRIDGE_JAR = os.environ.get(
    "PROLEAP_BRIDGE_JAR",
    str(
        REPO
        / "vendor"
        / "red-dragon"
        / "proleap-bridge"
        / "target"
        / "proleap-bridge-0.1.0-shaded.jar"
    ),
)

DFHENTER = "\x7d"
DFHPF3 = "\xf3"
ENTRY_TRANSID = "CC00"


@dataclass(frozen=True)
class Cluster:
    """A CICS FILE's CardDemo EBCDIC source and its record geometry, keyed at offset 0."""

    source: str
    record_length: int
    key_length: int


@dataclass(frozen=True)
class AlternateKey:
    """A CICS FILE read through a path over another file's cluster, by the key at this position."""

    base: str
    key_offset: int
    key_length: int


# Geometry follows the copybooks CSUSR01Y, CVACT01Y, CVCUS01Y, CVACT03Y, CVACT02Y.
CLUSTERS = {
    "USRSEC": Cluster("AWS.M2.CARDDEMO.USRSEC.PS", 80, 8),
    "ACCTDAT": Cluster("AWS.M2.CARDDEMO.ACCTDATA.PS", 300, 11),
    "CUSTDAT": Cluster("AWS.M2.CARDDEMO.CUSTDATA.PS", 500, 9),
    "CCXREF": Cluster("AWS.M2.CARDDEMO.CARDXREF.PS", 50, 16),
    "CARDDAT": Cluster("AWS.M2.CARDDEMO.CARDDATA.PS", 150, 16),
}
PATHS = {
    "CXACAIX": AlternateKey("CCXREF", 25, 11),
    "CARDAIX": AlternateKey("CARDDAT", 16, 11),
}

PROGRAMS = {
    "CC00": "COSGN00C",
    "CM00": "COMEN01C",
    "CAVW": "COACTVWC",
    "CCLI": "COCRDLIC",
}

# CSUSR01Y: an 8-byte user id, two 20-byte names, then the 8-byte sign-on field.
SIGNON_USER = "USER0001"
USRSEC_ID = slice(0, 8)
USRSEC_SIGNON = slice(8 + 20 + 20, 8 + 20 + 20 + 8)

SIGNON_BMS = APP / "bms" / "COSGN00.bms"
BMS_FIELD = re.compile(r"^(\w+)\s+DFHMDF\s+ATTRB=\(([^)]*)\)", re.MULTILINE)


@dataclass(frozen=True)
class Step:
    """One terminal interaction; ``events`` is empty when the turn takes no input."""

    label: str
    events: tuple[InputEvent, ...] = ()


XCTL_STEP = Step("(XCTL, no input)")


def signon_fields() -> tuple[str, ...]:
    """The sign-on map's unprotected input fields, in screen order."""
    return tuple(
        label
        for label, attributes in BMS_FIELD.findall(SIGNON_BMS.read_text())
        if "UNPROT" in attributes.split(",")
    )


def signon_value(user: str) -> str:
    """The user's sign-on field as shipped in CardDemo's USRSEC data."""
    usrsec = CLUSTERS["USRSEC"]
    rows = (
        record.decode("cp037")
        for record in read_flat_file(EBCDIC / usrsec.source, usrsec.record_length)
    )
    return next(row[USRSEC_SIGNON] for row in rows if row[USRSEC_ID] == user)


def script() -> tuple[Step, ...]:
    """Consumed on the entry turn and after each RETURN TRANSID."""
    user_field, signon_field = signon_fields()
    return (
        Step("sign-on screen requested (CC00, no COMMAREA, no map input)"),
        Step(
            "ENTER user id + password",
            (
                InputEvent(
                    DFHENTER,
                    {user_field: SIGNON_USER, signon_field: signon_value(SIGNON_USER)},
                ),
            ),
        ),
        Step(
            "ENTER menu option 01 (Account View)",
            (InputEvent(DFHENTER, {"OPTION": "01"}),),
        ),
        Step(
            "ENTER account id 00000000001",
            (InputEvent(DFHENTER, {"ACCTSID": "00000000001"}),),
        ),
        Step("PF3 back to menu", (InputEvent(DFHPF3, {}),)),
        Step(
            "ENTER menu option 03 (Credit Card List)",
            (InputEvent(DFHENTER, {"OPTION": "03"}),),
        ),
    )


def rid_entry(op: str, file_name: str, resp: int, rid: bytes) -> dict[str, str | int]:
    return {
        "op": op,
        "file": file_name.strip(),
        "resp": resp,
        "rid": rid.decode("cp037", errors="replace").rstrip(),
    }


def browse_entry(op: str, file_name: str, resp: int) -> dict[str, str | int]:
    return {"op": op, "file": file_name.strip(), "resp": resp}


class RecordingVsamEngine(VsamEngine):
    """Journals every file-control call the CICS builtins make onto a queue."""

    def __init__(self, files: Mapping[str, Dataset], journal: queue.Queue) -> None:
        super().__init__(files)
        self._journal = journal

    def read(
        self, file_name: str, rid: bytes, by: KeyMatch = KeyMatch.EQUAL
    ) -> ReadOutcome:
        outcome = super().read(file_name, rid, by)
        self._journal.put(rid_entry("READ", file_name, outcome.resp, rid))
        return outcome

    def write(self, file_name: str, rid: bytes, rid_len: int, record: bytes) -> int:
        resp = super().write(file_name, rid, rid_len, record)
        self._journal.put(rid_entry("WRITE", file_name, resp, rid))
        return resp

    def startbr(
        self,
        file_name: str,
        rid: bytes,
        cursor: tuple[str, str, str],
        start: KeyMatch = KeyMatch.GTEQ,
    ) -> int:
        resp = super().startbr(file_name, rid, cursor, start)
        self._journal.put(rid_entry("STARTBR", file_name, resp, rid))
        return resp

    def readnext(self, file_name: str, cursor: tuple[str, str, str]) -> ReadOutcome:
        outcome = super().readnext(file_name, cursor)
        self._journal.put(browse_entry("READNEXT", file_name, outcome.resp))
        return outcome

    def readprev(self, file_name: str, cursor: tuple[str, str, str]) -> ReadOutcome:
        outcome = super().readprev(file_name, cursor)
        self._journal.put(browse_entry("READPREV", file_name, outcome.resp))
        return outcome

    def endbr(self, file_name: str, cursor: tuple[str, str, str]) -> int:
        resp = super().endbr(file_name, cursor)
        self._journal.put(browse_entry("ENDBR", file_name, resp))
        return resp


def cluster_dsn(system: SystemCatalog, name: str, cluster: Cluster) -> str:
    dsn = f"CAPTURE.{name}"
    records = read_flat_file(EBCDIC / cluster.source, cluster.record_length)
    ordered = sorted(records, key=lambda record: record[: cluster.key_length])
    label = KsdsLabel(cluster.record_length, 0, cluster.key_length)
    system.create(dsn, label).path.write_bytes(b"".join(ordered))
    return dsn


def path_dsn(system: SystemCatalog, base: str, key: AlternateKey) -> str:
    system.define_aix(
        AlternateIndex(f"{base}.AIX", base, key.key_offset, key.key_length, False)
    )
    system.define_path(CatalogPath(f"{base}.PATH", f"{base}.AIX"))
    return f"{base}.PATH"


def seeded_engine(root: Path, journal: queue.Queue) -> RecordingVsamEngine:
    system = SystemCatalog(root)
    clusters = {
        name: cluster_dsn(system, name, cluster) for name, cluster in CLUSTERS.items()
    }
    paths = {
        name: path_dsn(system, clusters[key.base], key) for name, key in PATHS.items()
    }
    return RecordingVsamEngine(cics_files(system, {**clusters, **paths}), journal)


def drain(channel: queue.Queue) -> list:
    """Everything queued so far; the region runs on this thread, so qsize is exact."""
    return [channel.get_nowait() for _ in range(channel.qsize())]


def emit(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


@dataclass(frozen=True)
class Compiled:
    program: LinkedProgram
    seconds: float


@dataclass(frozen=True)
class Capture:
    region: CicsRegion
    journal: queue.Queue
    screens: queue.Queue
    inputs: queue.Queue


@dataclass(frozen=True)
class Progress:
    """The flow after some turns; ``last`` is empty until the first dispatch."""

    steps: tuple[Step, ...]
    turns: tuple[dict, ...]
    screens: int
    program: str
    last: tuple[DispatchResult, ...]
    stopped: str


@dataclass(frozen=True)
class Outcome:
    """One dispatch: its result, or no result and the exception that stopped it."""

    results: tuple[DispatchResult, ...]
    stopped: str


def compile_program(
    program: str, parser: ProLeapCobolParser, spec: CoprocessorSpec
) -> Compiled:
    began = time.perf_counter()
    linked = compile_cics_program(
        (APP / "cbl" / f"{program}.cbl").read_bytes(),
        parser,
        spec,
        source_search_dirs=[APP / "cbl"],
    )
    compiled = Compiled(linked, round(time.perf_counter() - began, 2))
    emit(f"compiled {program} in {compiled.seconds}s")
    return compiled


def cobol_parser(sym_dir: Path) -> ProLeapCobolParser:
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    return ProLeapCobolParser(
        RealSubprocessRunner(),
        BRIDGE_JAR,
        copybooks=CopybookSearch(dirs=(sym_dir,
            APP / "cpy",
            APP / "cpy-bms",
            REPO / "cicada" / "cics" / "copybooks")),
    )


def clear_stale_artifacts() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    [
        stale.unlink(missing_ok=True)
        for stale in [*OUT.glob("[0-9][0-9]-*.json"), OUT / "turns.jsonl"]
    ]


def main() -> int:
    clear_stale_artifacts()
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        generate_symbolic_copybooks(
            bms_dir=APP / "bms", out_dir=tmp / "sym", hlasm_export_bin=str(HLASM_EXPORT)
        )
        journal: queue.Queue = queue.Queue()
        return run_region(
            cobol_parser(tmp / "sym"), seeded_engine(tmp / "system", journal), journal
        )


def run_region(
    parser: ProLeapCobolParser, engine: RecordingVsamEngine, journal: queue.Queue
) -> int:
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        start_queue=start_queue,
        result_holder=result_holder,
        vsam_engine=engine,
        screen_queue=screen_q,
        input_queue=input_q,
    )
    spec = build_cics_spec()
    compiled = {prog: compile_program(prog, parser, spec) for prog in PROGRAMS.values()}
    region = CicsRegion(
        {prog: c.program for prog, c in compiled.items()},
        dict(PROGRAMS),
        screen_q,
        input_q,
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        max_steps=2_000_000,
        min_commarea_len=400,
        builtins=runtime.builtins,
    )
    return drive(
        Capture(region, journal, screen_q, input_q),
        {prog: c.seconds for prog, c in compiled.items()},
    )


def drive(capture: Capture, compile_s: Mapping[str, float]) -> int:
    final = run_turns(
        capture,
        Progress(
            steps=script(),
            turns=(),
            screens=0,
            program=PROGRAMS[ENTRY_TRANSID],
            last=(),
            stopped="",
        ),
    )
    records = ({"compile_seconds": dict(compile_s)}, *final.turns)
    (OUT / "turns.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )
    return exit_status(final)


def exit_status(final: Progress) -> int:
    match (final.stopped, final.steps):
        case ("", ()):
            return 0
        case _:
            sys.stderr.write(f"STOPPED: {final.stopped or 'script not exhausted'}\n")
            return 1


def needs_input(last: tuple[DispatchResult, ...]) -> bool:
    return all(result.kind == DispatchKind.RETURN_TRANSID for result in last)


def run_turns(capture: Capture, progress: Progress) -> Progress:
    match (needs_input(progress.last), progress.steps):
        case (True, ()):
            return progress
        case (True, (step, *remaining)):
            return continue_turns(
                capture, take_turn(capture, progress, step, tuple(remaining))
            )
        case _:
            return continue_turns(
                capture, take_turn(capture, progress, XCTL_STEP, progress.steps)
            )


def continue_turns(capture: Capture, progress: Progress) -> Progress:
    match progress.stopped:
        case "":
            return run_turns(capture, progress)
        case _:
            return progress


def take_turn(
    capture: Capture, progress: Progress, step: Step, remaining: tuple[Step, ...]
) -> Progress:
    turn_no = len(progress.turns) + 1
    transid = turn_transid(capture.region, progress.last)
    drain(capture.journal)
    began = time.perf_counter()
    outcome = dispatch(capture.region, progress, step, turn_no)
    elapsed = round(time.perf_counter() - began, 3)
    maps = write_maps(drain(capture.screens), progress.screens)
    turn = {
        "turn": turn_no,
        "transid": transid,
        "program": progress.program,
        "action": step.label,
        "input": input_json(step.events),
        "maps_sent": list(maps),
        "vsam": drain(capture.journal),
        "result": result_json(outcome.results),
        "seconds": elapsed,
        "input_left_unconsumed": bool(step.events) and bool(drain(capture.inputs)),
    }
    emit(json.dumps(turn))
    return Progress(
        steps=remaining,
        turns=(*progress.turns, turn),
        screens=progress.screens + len(maps),
        program=next_program(progress.program, outcome.results),
        last=outcome.results,
        stopped=stop_reason(capture.region, outcome),
    )


def turn_transid(region: CicsRegion, last: tuple[DispatchResult, ...]) -> str:
    match last:
        case ():
            return ENTRY_TRANSID
        case _:
            return region.transid


def dispatch(
    region: CicsRegion, progress: Progress, step: Step, turn_no: int
) -> Outcome:
    try:
        return Outcome((call_region(region, progress.last, step.events),), "")
    except Exception as exc:
        logger.exception("turn %d (%s) raised", turn_no, progress.program)
        return Outcome(
            (),
            f"turn {turn_no} ({progress.program}) raised {type(exc).__name__}: {exc}",
        )


def call_region(
    region: CicsRegion,
    last: tuple[DispatchResult, ...],
    events: tuple[InputEvent, ...],
) -> DispatchResult:
    event = next(iter(events), None)
    match last:
        case ():
            return region.start(ENTRY_TRANSID, commarea=b"", input_event=event)
        case _:
            return region.step(input_event=event)


def write_maps(
    payloads: Sequence[Mapping[str, str]], screens_before: int
) -> tuple[str, ...]:
    return tuple(
        write_map(payload, screen_no)
        for screen_no, payload in enumerate(payloads, start=screens_before + 1)
    )


def write_map(payload: Mapping[str, str], screen_no: int) -> str:
    path = OUT / f"{screen_no:02d}-{payload.get('map') or 'TEXT'}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path.name


def input_json(events: tuple[InputEvent, ...]):
    match events:
        case (event,):
            return {"eibaid": event.eibaid.encode("latin-1").hex(), **event.fields}
        case _:
            return None


def result_json(results: tuple[DispatchResult, ...]):
    match results:
        case (result,):
            return {
                "kind": result.kind.name,
                "transid": stripped_or_null(result.transid),
                "program": stripped_or_null(result.program),
                "abcode": result.abcode,
            }
        case _:
            return None


def stripped_or_null(text):
    match (text or "").strip():
        case "":
            return None
        case stripped:
            return stripped


def next_program(program: str, results: tuple[DispatchResult, ...]) -> str:
    match results:
        case (DispatchResult(kind=DispatchKind.XCTL, program=target),):
            return target.strip()
        case (DispatchResult(kind=DispatchKind.RETURN_TRANSID, transid=transid),):
            return PROGRAMS.get((transid or "").strip(), "?")
        case _:
            return program


def stop_reason(region: CicsRegion, outcome: Outcome) -> str:
    match outcome.results:
        case (result,) if region.done:
            return f"region terminated with {result.kind.name}"
        case _:
            return outcome.stopped


if __name__ == "__main__":
    raise SystemExit(main())

"""Capture SQL-section evidence: Bank-of-Z INQCUST (CICS LINK + EXEC SQL) against
live Db2, the CICS+SQL composition programs, and squall's standalone cursor.sqb.

Run from the repo root:
    make db2-up
    . ./bridge-env.sh
    SQUALL_DIR=squall . squall/db2/dsn-env.sh
    uv run --no-sync python docs/presentation/capture/db2_inqcust_capture.py

Reuses the integration tests' own setup helpers; wraps Db2Backend in a recorder
(delegation only, no product code touched) to log every statement that reached Db2.
Exits non-zero on any failure.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import io
import os
import queue
import re
import sqlite3
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import reduce
from itertools import chain
from pathlib import Path
from types import ModuleType

import ibm_db
from cics.coprocessor import build_cics_spec
from cics.dispatcher import run_cics
from cics.types import CicsContext, DispatchKind
from interpreter.project.coprocessor_compile import compile_program
from interpreter.project.types import LinkedProgram
from squall.backend import SqlBackend, SqlResult
from squall.backends.db2 import Db2Backend
from squall.backends.sqlite import SqliteBackend
from squall.connector import NamedDbConnector
from squall.coprocessor import build_sql_spec

from red_dragon_forge.run import run_program

REPO = Path(__file__).resolve().parents[3]
# An unrelated installed `tests` package shadows the repo's; the root must win.
sys.path = [str(REPO), *sys.path]
comp = importlib.import_module("tests.integration.test_cics_sql_composition")
inq = importlib.import_module("tests.integration.test_inqcust_e2e")
make_parser = importlib.import_module(
    "tests.integration.forge_cobol_helpers"
).make_parser

OUT = REPO / "docs" / "presentation" / "artifacts" / "sql"
INQCUST_CBL = inq._BANK_OF_Z_COBOL / "INQCUST.cbl"
CUSTDB2_CPY = inq._BANK_OF_Z_COPY / "CUSTDB2.cpy"
SQUALL_IT = REPO / "squall" / "tests" / "integration"
CURSOR_SQB = REPO / "squall" / "testbed" / "db2-samples" / "cobol_mf" / "cursor.sqb"
STAFF_ROWS = (
    (10, "SANDERS", 20, "Mgr"),
    (30, "MARENGHI", 38, "Mgr"),
    (40, "NGAN", 15, "Clerk"),
)

Field = Mapping[str, int]
Layout = Mapping[str, Field]


@dataclass(frozen=True)
class StatementLog:
    """The script's one mutable cell. The runtime drives SqlBackend calls and hands
    no return value back to the caller, so what reached the backend must be sunk
    somewhere the caller can drain after the run."""

    entries: queue.SimpleQueue[str] = field(default_factory=queue.SimpleQueue)

    def record(self, entry: str) -> None:
        self.entries.put(entry)

    def drain(self) -> tuple[str, ...]:
        return tuple(self.entries.get_nowait() for _ in range(self.entries.qsize()))


@dataclass(frozen=True)
class RecordingBackend:
    """Delegates to a real SqlBackend and reports each call reaching it."""

    inner: SqlBackend
    record: Callable[[str], None]

    @property
    def _cursors(self):
        return self.inner._cursors

    def execute(self, sql: str, params: Sequence) -> SqlResult:
        result = self.inner.execute(sql, params)
        self.record(
            f"EXECUTE  sql={_one_line(sql)}\n         params={params!r}\n"
            f"         -> sqlcode={result.sqlcode} rowcount={result.rowcount} "
            f"rows={_rows(result.rows)}"
        )
        return result

    def open_cursor(self, name: str, sql: str, params: Sequence) -> None:
        self.inner.open_cursor(name, sql, params)
        self.record(f"OPEN     cursor={name} sql={_one_line(sql)} params={params!r}")

    def fetch(self, name: str) -> SqlResult:
        result = self.inner.fetch(name)
        self.record(
            f"FETCH    cursor={name} -> sqlcode={result.sqlcode} "
            f"rows={_rows(result.rows)}"
        )
        return result

    def close(self, name: str) -> None:
        self.inner.close(name)
        self.record(f"CLOSE    cursor={name}")

    def commit(self) -> None:
        self.inner.commit()
        self.record("COMMIT")

    def rollback(self) -> None:
        self.inner.rollback()
        self.record("ROLLBACK")


def _one_line(sql: str) -> str:
    return " ".join(sql.split())


def _rows(rows: Sequence[Sequence]) -> str:
    return repr(
        [tuple(v.rstrip() if isinstance(v, str) else v for v in r) for r in rows]
    )


def _indented(entries: Sequence[str]) -> list[str]:
    return [f"  {entry}" for entry in entries]


@dataclass(frozen=True)
class _BlockScan:
    """Fold state over numbered source lines; ``start`` 0 means outside a block."""

    spans: tuple[tuple[int, int], ...] = ()
    start: int = 0


def _opens_exec_sql(line: str) -> bool:
    return bool(re.search(r"\bEXEC\s+SQL\b", line[6:72], re.I)) and line[6:7] != "*"


def _closes_exec_sql(line: str) -> bool:
    return bool(re.search(r"\bEND-EXEC\b", line[6:72], re.I))


def _scan_line(scan: _BlockScan, numbered: tuple[int, str]) -> _BlockScan:
    number, line = numbered
    start = scan.start or (number if _opens_exec_sql(line) else 0)
    if start and _closes_exec_sql(line):
        return _BlockScan((*scan.spans, (start, number)), 0)
    return _BlockScan(scan.spans, start)


def _exec_sql_blocks(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    spans = reduce(_scan_line, enumerate(lines, 1), _BlockScan()).spans
    return [(start, "\n".join(lines[start - 1 : end])) for start, end in spans]


def _excerpt(path: Path) -> str:
    rel = path.relative_to(REPO)
    return "\n\n".join(
        f"--- {rel}:{line} ---\n{text}" for line, text in _exec_sql_blocks(path)
    )


def _is_group(candidate: Field, fields: Sequence[tuple[str, Field]]) -> bool:
    return any(
        other is not candidate
        and candidate["offset"]
        <= other["offset"]
        < candidate["offset"] + candidate["length"]
        and other["length"] < candidate["length"]
        for _, other in fields
    )


def _leaf_fields(layout: Layout, prefix: str, base: Field) -> list[tuple[str, Field]]:
    lo, hi = base["offset"], base["offset"] + base["length"]
    fields = [
        (n, f)
        for n, f in layout.items()
        if n.startswith(prefix) and lo <= f["offset"] < hi
    ]
    by_offset = sorted(
        (f["offset"], position, n, f)
        for position, (n, f) in enumerate(fields)
        if not _is_group(f, fields)
    )
    return [(n, f) for _offset, _position, n, f in by_offset]


def _field_bytes(buf: bytes, target: Field, base: Field) -> bytes:
    off = target["offset"] - base["offset"]
    return buf[off : off + target["length"]]


def _field_row(buf: bytes, name: str, target: Field, base: Field) -> str:
    off = target["offset"] - base["offset"]
    raw = _field_bytes(buf, target, base)
    text = raw.decode("cp037") if any(raw) else f"<{len(raw)} x NUL bytes>"
    return f"  {name:<26} +{off:<4} len {target['length']:<3} = {text.rstrip()!r}"


def _decode_commarea(buf: bytes, layout: Layout, base: Field) -> list[str]:
    return [
        _field_row(buf, name, target, base)
        for name, target in _leaf_fields(layout, "INQCUST-", base)
    ]


def _drop_table(conn, table: str) -> None:
    with contextlib.suppress(Exception):
        ibm_db.exec_immediate(conn, f"DROP TABLE {table}")


def _drop_table_and_commit(conn, table: str) -> None:
    with contextlib.suppress(Exception):
        ibm_db.exec_immediate(conn, f"DROP TABLE {table}")
        ibm_db.commit(conn)


@dataclass(frozen=True)
class InqcustCase:
    label: str
    custno: str
    expected: str


@dataclass(frozen=True)
class CompiledInqcust:
    """WRAPPER linked with INQCUST in its program cache, plus the shared CICS cells."""

    linked: LinkedProgram
    layout: Layout
    context_holder: list
    result_holder: list

    @property
    def ws_ca(self) -> Field:
        return self.layout["WS-CA"]


def _compile_inqcust(bridge_jar: str, recorder: RecordingBackend) -> CompiledInqcust:
    context_holder, result_holder = [None], [None]
    inq_cics = build_cics_spec(
        context_holder=context_holder, result_holder=result_holder, program_cache={}
    )
    inq_sql = build_sql_spec(
        connections={"SAMPLE": recorder},
        copybook_dirs=[inq._BANK_OF_Z_COPY],
        initial_connector=NamedDbConnector("SAMPLE"),
    )
    parser = make_parser(bridge_jar, copybook_dirs=[inq._BANK_OF_Z_COPY])
    _f, inq_linked = compile_program(
        INQCUST_CBL.read_bytes(), parser, [inq_cics, inq_sql]
    )
    wrap_spec = build_cics_spec(
        context_holder=context_holder,
        result_holder=result_holder,
        program_cache={"INQCUST": inq_linked},
    )
    wrap_frontend, wrap_linked = compile_program(
        inq._WRAPPER_PROGRAM.encode("utf-8"),
        make_parser(bridge_jar, copybook_dirs=[inq._BANK_OF_Z_COPY]),
        [wrap_spec],
    )
    return CompiledInqcust(
        wrap_linked, wrap_frontend.data_layout, context_holder, result_holder
    )


def _run_inqcust_case(
    program: CompiledInqcust, log: StatementLog, case: InqcustCase
) -> list[str]:
    commarea = inq._seed_commarea(inq._SORT_CODE, case.custno, program.ws_ca["length"])
    t1 = time.perf_counter()
    result = run_cics(
        program.linked,
        CicsContext(transid="WRAP", commarea=commarea, eibaid="\x7d"),
        queue.Queue(),
        queue.Queue(),
        context_holder=program.context_holder,
        result_holder=program.result_holder,
        max_steps=50_000,
    )
    run_s = time.perf_counter() - t1
    success = program.layout["INQCUST-INQ-SUCCESS"]
    got = _field_bytes(result.commarea, success, program.ws_ca).decode("cp037")
    if result.kind != DispatchKind.RETURN_TRANSID or got != case.expected:
        raise SystemExit(
            f"INQCUST {case.label}: kind={result.kind} INQ-SUCCESS={got!r}, "
            f"expected {case.expected!r}"
        )
    return [
        "",
        f"=== Case: {case.label} ===",
        f"COMMAREA in  ({program.ws_ca['length']} bytes, cp037): "
        f"INQCUST-SCODE={inq._SORT_CODE!r} INQCUST-CUSTNO={case.custno!r}; rest NUL",
        f"Dispatch:    {result.kind.name}   elapsed {run_s:.2f}s",
        "SQL reaching Db2 (recorded at the SqlBackend boundary):",
        *_indented(log.drain()),
        "COMMAREA out (INQCUSTZ leaf fields, decoded cp037):",
        *_decode_commarea(result.commarea, program.layout, program.ws_ca),
        f"Check:       INQCUST-INQ-SUCCESS = {got!r} (expected {case.expected!r}) OK",
    ]


def _inqcust_header(server) -> list[str]:
    return [
        "INQCUST end-to-end capture (CICS LINK -> unmodified Bank-of-Z INQCUST "
        "-> EXEC SQL -> live Db2)",
        "Captured by: docs/presentation/capture/db2_inqcust_capture.py "
        "(mirrors tests/integration/test_inqcust_e2e.py)",
        "Backend:     squall.backends.db2.Db2Backend over ibm_db; "
        f"server {server.DBMS_NAME} {server.DBMS_VER}, database MOJO",
        f"Program:     {INQCUST_CBL.relative_to(REPO)} "
        "(compiled with CICS + SQL CoprocessorSpecs)",
        "Driver:      synthetic WRAPPER (CICS only) does "
        "EXEC CICS LINK PROGRAM('INQCUST') COMMAREA(WS-CA),",
        "             then RETURN TRANSID('WRAP') COMMAREA(WS-CA) "
        "so the mutated COMMAREA is observable.",
        "DB2 thread:  NamedDbConnector('SAMPLE') models the CICS Db2 attachment; "
        "INQCUST issues no CONNECT.",
        "",
    ]


def _inqcust_run_lines(bridge_jar: str, conn) -> list[str]:
    inq._seed_customer(conn)
    seeded = (
        f"Seeded CUSTOMER row (test fixture): sortcode={inq._SORT_CODE} "
        f"number={inq._FOUND_CUSTNO} TITLE=MR FIRST=TESTFIRST LAST=TESTLAST "
        "DOB=19800101 CITY=CITY CREDIT_SCORE=750"
    )
    log = StatementLog()
    t0 = time.perf_counter()
    program = _compile_inqcust(
        bridge_jar, RecordingBackend(Db2Backend(conn), log.record)
    )
    compile_s = time.perf_counter() - t0
    cases = (
        InqcustCase("FOUND", inq._FOUND_CUSTNO, "Y"),
        InqcustCase("NOT FOUND", inq._NOT_FOUND_CUSTNO, "N"),
    )
    return [
        seeded,
        f"Compile (ProLeap parse + lower, INQCUST + WRAPPER): {compile_s:.2f}s",
        *chain.from_iterable(_run_inqcust_case(program, log, c) for c in cases),
    ]


def capture_inqcust(bridge_jar: str, dsn: str) -> None:
    conn = ibm_db.connect(dsn, "", "")
    header = _inqcust_header(ibm_db.server_info(conn))
    try:
        body = _inqcust_run_lines(bridge_jar, conn)
    finally:
        inq._drop_customer(conn)
        ibm_db.close(conn)
    (OUT / "inqcust-run.txt").write_text(
        "\n".join([*header, *body]) + "\n", encoding="utf-8"
    )
    (OUT / "inqcust-source-excerpt.txt").write_text(
        "EXEC SQL blocks in the unmodified IBM Bank-of-Z sources "
        "(vendor/bank-of-z, not edited).\n"
        "INCLUDE CUSTDB2 / INCLUDE SQLCA are rewritten to COPY by squall's prepass.\n\n"
        + _excerpt(INQCUST_CBL)
        + "\n\n"
        + _excerpt(CUSTDB2_CPY)
        + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class CompositionCase:
    title: str
    source: str
    transid: str
    table_ddl: str
    seed_rows: tuple[str, ...]

    @property
    def table(self) -> str:
        return self.table_ddl.split()[2]

    @property
    def setup_statements(self) -> tuple[str, ...]:
        return (self.table_ddl, *self.seed_rows)


COMPOSITION_CASES = (
    CompositionCase(
        "COMBINED: EXEC SQL CONNECT + SELECT INTO, then EXEC CICS ASSIGN APPLID + RETURN",
        comp._COMBINED_PROGRAM,
        "COMB",
        "CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)",
        ("INSERT INTO ACCOUNT VALUES (42, 777)",),
    ),
    CompositionCase(
        "CURSORPGM: DECLARE/OPEN/FETCH cursor, then EXEC CICS RETURN "
        "(task-end hook must close it)",
        comp._CURSOR_PROGRAM,
        "CURS",
        "CREATE TABLE STAFF (NAME VARCHAR(9), DEPT INTEGER, JOB VARCHAR(5))",
        ("INSERT INTO STAFF VALUES ('SANDERS', 20, 'Mgr')",),
    ),
)


@contextlib.contextmanager
def _sqlite_backend(case: CompositionCase) -> Iterator[SqliteBackend]:
    raw = sqlite3.connect(":memory:")
    for statement in case.setup_statements:
        raw.execute(statement)
    raw.commit()
    try:
        yield SqliteBackend(raw)
    finally:
        raw.close()


@contextlib.contextmanager
def _db2_backend(dsn: str, case: CompositionCase) -> Iterator[Db2Backend]:
    db2 = ibm_db.connect(dsn, "", "")
    _drop_table(db2, case.table)
    for statement in case.setup_statements:
        ibm_db.exec_immediate(db2, statement)
    ibm_db.commit(db2)
    try:
        yield Db2Backend(db2)
    finally:
        _drop_table_and_commit(db2, case.table)
        ibm_db.close(db2)


def _run_composed(source: str, backend: SqlBackend, transid: str):
    context_holder, result_holder = [None], [None]
    cics_spec = build_cics_spec(
        program_cache={},
        context_holder=context_holder,
        result_holder=result_holder,
        applid="FORGEAPP",
    )
    sql_spec = build_sql_spec(connections={"SAMPLE": backend})
    _f, linked = compile_program(
        source.encode("utf-8"),
        make_parser(os.environ["PROLEAP_BRIDGE_JAR"]),
        [cics_spec, sql_spec],
    )
    t0 = time.perf_counter()
    result = run_program(
        linked,
        [cics_spec, sql_spec],
        CicsContext(transid=transid, commarea=b"", eibaid="\x7d"),
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=10_000,
    )
    return result, time.perf_counter() - t0


def _backend_section(
    case: CompositionCase,
    backend_label: str,
    backend_scope: contextlib.AbstractContextManager[SqlBackend],
) -> list[str]:
    log = StatementLog()
    with backend_scope as inner:
        result, run_s = _run_composed(
            case.source, RecordingBackend(inner, log.record), case.transid
        )
        open_after = dict(inner._cursors)
    if result.kind != DispatchKind.RETURN or open_after:
        raise SystemExit(
            f"composition {case.transid}/{backend_label} failed: "
            f"{result.kind} {open_after}"
        )
    return [
        f"--- backend: {backend_label} ---",
        f"Dispatch: {result.kind.name}   elapsed {run_s:.2f}s",
        *_indented(log.drain()),
        f"Open cursors left in backend after RETURN: {sorted(open_after)}",
    ]


def _composition_case_lines(case: CompositionCase, dsn: str) -> list[str]:
    return [
        "",
        f"=== {case.title} ===",
        case.source.rstrip(),
        *_backend_section(case, "SQLite (as in the test)", _sqlite_backend(case)),
        *_backend_section(
            case, "Db2 MOJO (capture substitution)", _db2_backend(dsn, case)
        ),
    ]


def capture_composition(dsn: str) -> None:
    lines = [
        "CICS + SQL in ONE compiled program "
        "(tests/integration/test_cics_sql_composition.py)",
        "The pytest versions run against in-memory SQLite. This capture runs the SAME two COBOL",
        "programs (verbatim from the test module) against BOTH SQLite (as the test does) "
        "and live Db2",
        "(Db2Backend, database MOJO) -- only the backend object differs.",
        *chain.from_iterable(
            _composition_case_lines(case, dsn) for case in COMPOSITION_CASES
        ),
    ]
    (OUT / "composition-run.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_squall_helpers() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "squall_cobol_helpers", SQUALL_IT / "squall_cobol_helpers.py"
    )
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    return helpers


def _seed_staff(conn) -> None:
    _drop_table(conn, "STAFF")
    ibm_db.exec_immediate(
        conn,
        "CREATE TABLE STAFF (ID SMALLINT, NAME VARCHAR(9), DEPT SMALLINT, JOB CHAR(5))",
    )
    for sid, name, dept, job in STAFF_ROWS:
        ibm_db.exec_immediate(
            conn, f"INSERT INTO STAFF VALUES ({sid}, '{name}', {dept}, '{job}')"
        )
    ibm_db.commit(conn)


def _run_cursor_sqb(
    helpers: ModuleType, bridge_jar: str, recorder: RecordingBackend
) -> tuple[str, float]:
    stdout = io.StringIO()
    t0 = time.perf_counter()
    with contextlib.redirect_stdout(stdout):
        helpers.run_cobol(
            CURSOR_SQB.read_text(encoding="utf-8"),
            bridge_jar,
            connections={"SAMPLE": recorder},
            copybook_dirs=[SQUALL_IT / "db2_includes"],
            max_steps=8000,
        )
    elapsed = time.perf_counter() - t0
    return stdout.getvalue(), elapsed


def _cursor_sqb_text(out: str, elapsed: float, entries: Sequence[str]) -> str:
    return "\n".join(
        [
            "squall standalone (no CICS): unmodified IBM db2-samples cursor.sqb "
            "against live Db2 MOJO",
            f"Program: {CURSOR_SQB.relative_to(REPO)}  "
            "(mirrors squall/tests/integration/test_db2_cursor_e2e.py)",
            f"Seeded STAFF: {list(STAFF_ROWS)}",
            f"Compile + run elapsed: {elapsed:.2f}s",
            "",
            "SQL reaching Db2 (recorded at the SqlBackend boundary):",
            *_indented(entries),
            "",
            "Program DISPLAY output (captured stdout):",
            out.rstrip(),
            "",
            "EXEC SQL blocks in the program:",
            _excerpt(CURSOR_SQB),
        ]
    )


def _seeded_cursor_sqb_run(
    helpers: ModuleType, bridge_jar: str, conn, log: StatementLog
) -> tuple[str, float]:
    _seed_staff(conn)
    recorder = RecordingBackend(Db2Backend(conn), log.record)
    return _run_cursor_sqb(helpers, bridge_jar, recorder)


@contextlib.contextmanager
def _staff_connection(dsn: str) -> Iterator:
    conn = ibm_db.connect(dsn, "", "")
    try:
        yield conn
    finally:
        _drop_table_and_commit(conn, "STAFF")
        ibm_db.close(conn)


def _check_cursor_sqb_output(out: str) -> None:
    if "SANDERS" not in out or "MARENGHI" not in out or "NGAN" in out:
        raise SystemExit(f"cursor.sqb output unexpected:\n{out}")


def capture_cursor_sqb(bridge_jar: str, dsn: str) -> None:
    helpers = _load_squall_helpers()
    log = StatementLog()
    with _staff_connection(dsn) as conn:
        out, elapsed = _seeded_cursor_sqb_run(helpers, bridge_jar, conn, log)
    _check_cursor_sqb_output(out)
    (OUT / "cursor-sqb-run.txt").write_text(
        _cursor_sqb_text(out, elapsed, log.drain()) + "\n", encoding="utf-8"
    )


def main() -> None:
    bridge_jar = os.environ["PROLEAP_BRIDGE_JAR"]
    dsn = os.environ["SQUALL_DB2_DSN"]
    OUT.mkdir(parents=True, exist_ok=True)
    capture_inqcust(bridge_jar, dsn)
    capture_composition(dsn)
    capture_cursor_sqb(bridge_jar, dsn)
    sys.stdout.write(f"wrote {sorted(p.name for p in OUT.iterdir())}\n")


if __name__ == "__main__":
    main()

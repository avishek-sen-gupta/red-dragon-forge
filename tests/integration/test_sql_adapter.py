from __future__ import annotations

import sqlite3

from interpreter.project.entry_point import EntryPoint
from interpreter.run import run_linked
from interpreter.address import Address
from interpreter.var_name import VarName
from interpreter.vm.vm import VMState, StackFrame
from interpreter.func_name import FuncName
from interpreter import constants as rd_constants

from squall.backends.sqlite import SqliteBackend
from squall.binding import _decode_field

from squall.coprocessor import build_sql_spec
from interpreter.project.coprocessor_compile import compile_program
from tests.integration.forge_cobol_helpers import make_parser

_SQL_ONLY_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLONLY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID  PIC 9(4) VALUE 11.
       01 WS-BAL PIC 9(9).
       01 SQLCODE PIC S9(9).
       PROCEDURE DIVISION.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           EXEC SQL
               SELECT ACCT_BAL
               INTO :WS-BAL
               FROM ACCOUNT
               WHERE ACCT_ID = :WS-ID
           END-EXEC.
           STOP RUN.
"""


def _read_ws_field(vm: VMState, field_name: str):
    ws_var = VarName("__ws_region")
    region = None
    for frame in reversed(vm.call_stack):
        local_vars = getattr(frame, "local_vars", {})
        if ws_var in local_vars:
            addr = Address(str(local_vars[ws_var].value))
            region = vm.region_get(addr)
            break
    assert region is not None, "__ws_region not found in call stack"
    layout = vm.data_layout
    f = layout[field_name]
    off, length = f["offset"], f["length"]
    raw = bytes(region[off : off + length])
    return _decode_field(raw, f)


def test_sql_only_spec_selects_into(bridge_jar):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)")
    conn.execute("INSERT INTO ACCOUNT VALUES (11, 500)")
    conn.commit()
    backend = SqliteBackend(conn)

    spec = build_sql_spec(connections={"SAMPLE": backend})
    parser = make_parser(bridge_jar)

    _frontend, linked = compile_program(
        _SQL_ONLY_PROGRAM.encode("utf-8"), parser, [spec]
    )

    entry_point = EntryPoint.top_level()
    if linked.func_symbol_table:
        proc_label = next(
            (
                label
                for label in linked.func_symbol_table
                if not str(label).startswith("func_init_params_")
            ),
            None,
        )
        if proc_label is not None:
            entry_point = EntryPoint.function(
                lambda ref, _l=proc_label: ref.label == _l
            )

    initial_vm = VMState()
    initial_vm.data_layout = linked.data_layout
    initial_vm.call_stack.append(
        StackFrame(function_name=FuncName(rd_constants.MAIN_FRAME_NAME))
    )

    vm = run_linked(
        linked, entry_point=entry_point, max_steps=2000, initial_vm=initial_vm
    )

    assert _read_ws_field(vm, "WS-BAL") == 500
    assert _read_ws_field(vm, "SQLCODE") == 0

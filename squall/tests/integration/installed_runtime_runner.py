"""Read a linked SQL program, install the SQL runtime over seeded SQLite, run it, print WS-BAL and SQLCODE."""

import importlib.util
import sqlite3
import sys
from pathlib import Path

from interpreter.project.ir_codec import IrCodec
from interpreter.project.linked_codec import LinkedCodec
from squall.backends.sqlite import SqliteBackend
from squall.runtime import install_sql_runtime

_HELPERS = Path(__file__).with_name("squall_cobol_helpers.py")
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)

conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)")
conn.execute("INSERT INTO ACCOUNT VALUES (11, 500)")
conn.commit()
install_sql_runtime({"SAMPLE": SqliteBackend(conn)})
linked = LinkedCodec(IrCodec()).read(Path(sys.argv[1]))
vm = _helpers.run_linked_program(linked, max_steps=2000)
print(_helpers.read_ws_field(vm, "WS-BAL"), _helpers.read_ws_field(vm, "SQLCODE"))

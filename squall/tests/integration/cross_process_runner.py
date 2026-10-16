"""Run a pickled SQL program in this process, with only a fresh SQL runtime installed."""

import importlib.util
import pickle
import sqlite3
import sys
from pathlib import Path

from squall.backends.sqlite import SqliteBackend
from squall.runtime import install_sql_runtime

_HELPERS = Path(__file__).parent / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)

conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE EMP (EMP_ID INTEGER NOT NULL, EMP_NAME VARCHAR(9))")
runtime = install_sql_runtime({"SAMPLE": SqliteBackend(conn)})
linked = pickle.loads(Path(sys.argv[1]).read_bytes())
vm = _helpers.run_linked_program(linked, _helpers.sql_builtins(runtime), max_steps=4000)
print(
    _helpers.read_ws_field(vm, "EMP-NAME-LEN"),
    _helpers.read_ws_field(vm, "EMP-NAME-TEXT").rstrip(),
)

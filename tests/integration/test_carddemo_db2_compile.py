"""The compile gate for the CardDemo Db2 tier (task 4 of the
2026-09-19-carddemo-db2-tier plan).

Proves both `COTRTUPC` and `COTRTLIC` compile with the CICS and SQL
coprocessor specs composed (compilation never touches a database, so this
gate does not require Db2).

Verified recipe — later tasks (9-11) should copy this rather than
rediscover it:

- **Copybook dirs**, in this order: the Db2 tree's own `cpy`, `cpy-bms`,
  `dcl` (holds the hand-written `DCLTRTYP.dcl` / `DCLTRCAT.dcl` DCLGEN
  copybooks), then the top-level `carddemo_home`'s
  `cpy`, `cpy-bms` (BMS-generated map copybooks + `COCOM01Y.cpy`, which
  declares `CARDDEMO-COMMAREA`), plus squall's and cicada's own bundled
  `copybooks` directories (`SQLCA.cpy`, `DFHEIBLK.cpy`).
- **`copybook_exts`**: `["", "cpy", "CPY", "cob", "cbl", "copy", "COPY",
  "dcl"]` — passed to `ProLeapCobolParser` directly (`-copybook-ext`
  *replaces* the bridge's default list rather than extending it, so every
  extension the corpus uses, including the DCLGEN `.dcl` one, must be
  restated).
- **`tolerant=True`** on `install_sql_runtime` when the program runs — host
  variables missing from the data layout are skipped rather than raised.
- `stage_sanitised_copybooks` is deliberately NOT used: proving the raw
  `.dcl` files parse now that Task 1/2 stop corrupting fixed-format columns
  is the point of this test.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.layout_data import field_positions
from interpreter.instructions import Const
from interpreter.project.coprocessor_compile import compile_program
from interpreter.run import declarations_of
from squall.coprocessor import build_sql_spec

from tests.integration.forge_cobol_helpers import (
    cics_copybooks_dir,
    squall_copybooks_dir,
)

COPYBOOK_EXTS = ["", "cpy", "CPY", "cob", "cbl", "copy", "COPY", "dcl"]


def _carddemo_home() -> Path:
    """Root of the CardDemo checkout ('.../carddemo/app'). CARDDEMO_HOME
    overrides; otherwise the vendored submodule is used. Fails (never
    skips) when the corpus is missing -- a skip here would silently pass
    this gate, exactly the failure mode that let the column bug through
    four times on this branch already."""
    env = os.environ.get("CARDDEMO_HOME")
    home = (
        Path(env)
        if env
        else Path(__file__).resolve().parents[2] / "vendor" / "carddemo" / "app"
    )
    if not home.is_dir():
        pytest.fail(
            f"CardDemo checkout not found at {home}; set CARDDEMO_HOME", pytrace=False
        )
    return home


def _db2_tree() -> Path:
    db2 = _carddemo_home() / "app-transaction-type-db2"
    if not db2.is_dir():
        pytest.fail(f"Db2 tier not found under {db2}", pytrace=False)
    return db2


def _copybook_dirs() -> list[Path]:
    home = _carddemo_home()
    db2 = _db2_tree()
    return [
        db2 / "cpy",
        db2 / "cpy-bms",
        db2 / "dcl",
        home / "cpy",
        home / "cpy-bms",
        squall_copybooks_dir(),
        cics_copybooks_dir(),
    ]


def _make_parser(bridge_jar: str) -> ProLeapCobolParser:
    return ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybooks=CopybookSearch(
            dirs=tuple(_copybook_dirs()), exts=tuple(COPYBOOK_EXTS)
        ),
    )


def _compile(bridge_jar: str, program_name: str):
    source = (_db2_tree() / "cbl" / f"{program_name}.cbl").read_bytes()
    parser = _make_parser(bridge_jar)

    runtime = install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        result_holder=[None],
    )
    cics_spec = build_cics_spec()
    sql_spec = build_sql_spec()

    return compile_program(source, parser, [cics_spec, sql_spec], tolerant=True)


def test_cotrtupc_compiles_with_cics_and_sql_composed(bridge_jar):
    """The gate. Absence of any of these four fields is the exact signature
    of the column-corruption bug (Task 2's fix target): a rewrite that slid
    the identification area into Area B, which made ProLeap's error
    recovery silently swallow a whole 01-level record declaration."""
    linked = _compile(bridge_jar, "COTRTUPC")

    required = frozenset(
        (
            "CARDDEMO-COMMAREA",
            "SQLCA",
            "DCLTRANSACTION-TYPE",
            "DCLTRANSACTION-TYPE-CATEGORY",
        )
    )
    present = frozenset(
        name
        for name in required
        if name in field_positions(declarations_of(linked, "COTRTUPC"))
    )
    assert present == required, (
        f"{sorted(required - present)} missing from COTRTUPC's compiled "
        "field layout -- this is the signature of the column-corruption bug returning"
    )


def test_cotrtlic_compiles_with_cics_and_sql_composed(bridge_jar):
    """COTRTLIC INCLUDEs SQLCA and DCLTRTYP (not DCLTRCAT) directly, plus
    references CARDDEMO-COMMAREA -- assert those field names explicitly
    rather than only checking that a LinkedProgram came back, for the same
    reason as COTRTUPC above."""
    linked = _compile(bridge_jar, "COTRTLIC")

    required = frozenset(("CARDDEMO-COMMAREA", "SQLCA", "DCLTRANSACTION-TYPE"))
    present = frozenset(
        name
        for name in required
        if name in field_positions(declarations_of(linked, "COTRTLIC"))
    )
    assert present == required, (
        f"{sorted(required - present)} missing from COTRTLIC's compiled "
        "field layout -- this is the signature of the column-corruption bug returning"
    )


def test_cotrtlic_working_storage_cursors_reach_their_opens(bridge_jar):
    """The regression gate for forge-qhi (task 7): COTRTLIC declares BOTH
    C-TR-TYPE-FORWARD and C-TR-TYPE-BACKWARD in WORKING-STORAGE, nested
    inside WS-MISC-STORAGE, not as PROCEDURE DIVISION statements. Neither
    ever lowers, so the only way either reaches its OPEN call is
    through the real ProLeap bridge's "data_division_exec_sql" ASG key
    (proleap-bridge, red-dragon commit d9e5afd4) and
    squall.data_division_exec_sql.derive_cursors.

    Every other test of this recovery path feeds a hand-written
    data_division_exec_sql dict -- this is the one committed test that
    exercises the real bridge→squall seam end to end, so a bridge or ASG
    contract regression on either side cannot pass silently."""
    linked = _compile(bridge_jar, "COTRTLIC")
    texts = {
        i.value
        for i in linked.merged_ir
        if isinstance(i, Const) and isinstance(i.value, str)
    }
    declared = {
        name
        for name in ("C-TR-TYPE-FORWARD", "C-TR-TYPE-BACKWARD")
        if any(f"DECLARE {name} CURSOR" in text for text in texts)
    }
    assert declared == {"C-TR-TYPE-FORWARD", "C-TR-TYPE-BACKWARD"}

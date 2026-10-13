"""Shared helpers for squall COBOL integration tests.

Centralises the ProLeap bridge JAR discovery and the compile+run pipeline
so that individual tests only specify COBOL source, strategy, and assertions.

Pattern (mirrors cicada's tests/integration/cobol_helpers.py):
  1. ``bridge_jar`` fixture — reads PROLEAP_BRIDGE_JAR env, fails loudly if absent.
  2. ``compile_cobol`` — builds a real CobolFrontend with extension_strategies,
     lowers source to IR, and assembles a LinkedProgram.
  3. ``run_linked`` (re-exported from interpreter.run) — executes the LinkedProgram
     on the real VMState and returns it.
  4. ``read_field`` — decodes a named field from the post-run VMState's WS region.
"""

from __future__ import annotations

import importlib.resources
import os
from pathlib import Path

import pytest

from interpreter.cobol.cobol_frontend import CobolFrontend
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.project.types import LinkedProgram
from interpreter.project.entry_point import EntryPoint
from interpreter.run import run_linked
from interpreter.address import Address
from interpreter.vm.vm import VMState


def _squall_copybooks_dir() -> Path:
    """Return the filesystem path to the squall.copybooks package directory."""
    ref = importlib.resources.files("squall.copybooks")
    # files() returns a Traversable; resolve to a real Path via __fspath__ or str.
    return Path(str(ref))


@pytest.fixture
def bridge_jar() -> str:
    """Return the ProLeap bridge JAR path from the required PROLEAP_BRIDGE_JAR env.

    No default, no skip: missing env is a hard failure so tests cannot silently
    succeed without the JAR present.
    """
    return os.environ["PROLEAP_BRIDGE_JAR"]


def make_cobol_parser(
    bridge_jar_path: str,
    copybook_dirs: list[Path] | None = None,
) -> ProLeapCobolParser:
    """Build a ProLeapCobolParser for the given JAR path.

    Always includes the squall.copybooks directory so that COPY statements
    produced by apply_sql_prepass (from EXEC SQL INCLUDE) can be resolved.
    Additional directories may be passed via *copybook_dirs*.
    """
    dirs: list[Path] = [_squall_copybooks_dir()]
    if copybook_dirs:
        dirs.extend(copybook_dirs)
    return ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar_path, copybook_dirs=dirs
    )


def compile_cobol(
    source: str,
    bridge_jar_path: str,
    connections,
    copybook_dirs: list[Path] | None = None,
) -> tuple[CobolFrontend, LinkedProgram]:
    """Compile a COBOL source string to a LinkedProgram.

    *connections* is the connection registry (name -> backend) the program's
    EXEC SQL CONNECT selects from at run time; a run starts disconnected.

    Builds one CoprocessorSpec (squall.coprocessor.build_sql_spec) and delegates to RedDragon's shared compile_program
    (interpreter.project.coprocessor_compile) -- the same composition
    mechanism Cicada and red-dragon-forge use.

    Returns (frontend, linked) so that callers can access frontend.data_layout
    for assertions and pass the LinkedProgram to run_linked.
    """
    from squall.coprocessor import build_sql_spec
    from interpreter.project.coprocessor_compile import compile_program

    dirs = copybook_dirs or []
    parser = make_cobol_parser(bridge_jar_path, copybook_dirs=dirs)
    spec = build_sql_spec(connections)
    return compile_program(source.encode("utf-8"), parser, [spec])


def run_cobol(
    source: str,
    bridge_jar_path: str,
    connections,
    max_steps: int = 1000,
    copybook_dirs: list[Path] | None = None,
):
    """Compile and run a COBOL program against the *connections* registry; return
    the final VMState.

    Builds the SQL strategy from *connections* (name → backend) and wraps it in
    the frontend's extension_strategies array. The run
    starts disconnected; the program's EXEC SQL CONNECT selects its database.

    Mirrors the two-phase execution model in interpreter.run.run() for COBOL:
    Phase 1 runs the init block (top-level), phase 2 dispatches into the
    program's procedure division function (func_<pid>_0).  This is required
    so that __ws_region is visible in the frame when the builtins execute.
    """
    frontend, linked = compile_cobol(
        source, bridge_jar_path, connections, copybook_dirs=copybook_dirs
    )

    # For COBOL, use function-entry mode so run_linked runs the WS init block
    # (phase 1) then dispatches into func_<pid>_0 (phase 2).
    # Without this, only the init block runs and __ws_region is never in scope.
    entry_point = EntryPoint.function(lambda ref: ref.label == linked.entry_func_label)

    # Pre-populate data_layout on initial_vm so builtins that run DURING
    # execution (e.g. __exec_sql writing to WS fields) can find the layout.
    # Without this, vm.data_layout is empty until run_linked() sets it AFTER
    # execution ends — too late for any builtin that reads/writes WS fields.
    # We also push the main frame; execute_cfg only pushes it when vm is None.
    from interpreter.func_name import FuncName
    from interpreter.vm.vm import StackFrame
    from interpreter import constants as _constants

    initial_vm = VMState()
    initial_vm.data_layout = linked.data_layout
    initial_vm.call_stack.append(
        StackFrame(function_name=FuncName(_constants.MAIN_FRAME_NAME))
    )

    vm = run_linked(
        linked,
        entry_point=entry_point,
        max_steps=max_steps,
        initial_vm=initial_vm,
    )
    return vm


def read_ws_field(vm, field_name: str):
    """Decode a named WS field from the post-run VMState.

    Locates the __ws_region address in the top-most call frame, then reads
    and decodes the field using vm.data_layout (populated by run_linked).

    Decoding delegates to squall.binding._decode_field, which handles:
      ZONED_DECIMAL  → int
      ALPHANUMERIC   → str
      COMP3          → Decimal
      BINARY         → int

    Returns None if the field or WS region is not found.
    """
    from interpreter.var_name import VarName
    from squall.binding import _decode_field

    ws_var = VarName("__ws_region")
    region = None
    for frame in reversed(vm.call_stack):
        local_vars = getattr(frame, "local_vars", {})
        if ws_var in local_vars:
            tv = local_vars[ws_var]
            addr = Address(str(tv.value))
            region = vm.region_get(addr)
            break

    if region is None:
        return None

    layout = vm.data_layout
    f = layout.get(field_name)
    if f is None:
        return None

    off, length = f["offset"], f["length"]
    raw = bytes(region[off : off + length])
    return _decode_field(raw, f)

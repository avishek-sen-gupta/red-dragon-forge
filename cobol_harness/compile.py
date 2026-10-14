"""Primitives for compiling a real COBOL/CICS program (and whatever it
EXEC CICS LINKs to) through RedDragon/cicada, ready to drop into a
CicsRegion's program_cache.

Agnostic to any one program: callers supply the source bytes, the copybook
search dirs, and (optionally) a directory of hand-written LINK-target stubs.
Any LINK target without a stub file gets a generic no-op fallback, so a new
program's harness only needs to write stubs for subprograms whose caller
actually branches on what they write back to the COMMAREA.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from cics.bootstrap import compile_cics_program
from interpreter.frontend import make_cobol_parser


def make_parser(copybook_dirs: Sequence[Path], copybook_exts: Sequence[str] = ("cpy", "txt")) -> Any:
    """Build a ProLeapCobolParser with copybook resolution wired up.

    NOTE this is the one place COPY-statement resolution is actually
    configured: ``compile_cobol``/``compile_cics_program``'s own
    ``copybook_dirs=`` kwarg only affects the *lowering* step, not the
    ProLeap *parse* step that resolves ``COPY`` -- the parser object itself
    must be built with ``copybook_dirs`` for COPY to resolve at all.
    """
    return make_cobol_parser(copybook_dirs=list(copybook_dirs), copybook_exts=list(copybook_exts))


def make_noop_stub_source(program_name: str) -> bytes:
    """A trivial ``EXEC CICS RETURN`` stub for an EXEC CICS LINK target.

    Safe when the caller only checks default-initialized COMMAREA fields
    after the LINK (e.g. checks ``X = 'N'`` on a field it zeroed/blanked via
    its own INITIALIZE before the LINK). NOT safe when the caller branches
    on a value the real subprogram would have *written back* -- for those,
    write a real stub with a LINKAGE SECTION DFHCOMMAREA matching the
    caller's layout and MOVE the needed value into it.
    """
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {program_name}.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       PROCEDURE DIVISION.
           EXEC CICS RETURN END-EXEC.
""".encode()


def compile_link_targets(
    parser: Any,
    spec: Any,
    program_cache: dict[str, Any],
    names: Sequence[str],
    *,
    stub_dir: Path | None = None,
    tolerant: bool = True,
) -> None:
    """Compile a stub for every name in ``names`` into ``program_cache``.

    For each name, uses ``stub_dir/<name>.cbl`` if it exists, else falls
    back to ``make_noop_stub_source``. Skips names already in
    ``program_cache`` (so the real program itself, or a previously-compiled
    stub, is never clobbered).
    """
    for name in names:
        if name in program_cache:
            continue
        stub_path = (stub_dir / f"{name}.cbl") if stub_dir else None
        source = stub_path.read_bytes() if stub_path and stub_path.exists() else make_noop_stub_source(name)
        program_cache[name] = compile_cics_program(source, parser, spec, tolerant=tolerant)


def compile_main_program(
    parser: Any,
    spec: Any,
    program_cache: dict[str, Any],
    source: bytes,
    name: str,
    *,
    tolerant: bool = True,
) -> Any:
    """Compile the program under test itself into ``program_cache[name]``.

    Returns the ``LinkedProgram``, whose declarations carry the field layout
    ``commarea.build_commarea`` and ``state.read_vm_field`` need.
    """
    linked = compile_cics_program(source, parser, spec, tolerant=tolerant)
    program_cache[name] = linked
    return linked

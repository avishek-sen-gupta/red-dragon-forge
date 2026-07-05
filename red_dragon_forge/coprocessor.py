"""CoprocessorSpec — the generic seam for composing RedDragon COBOL coprocessor
lowering strategies (CICS, EXEC SQL, and others later).

This module and compile.py must never import cics.* or squall.* — only the
adapters/ package is allowed to know which coprocessors exist by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from interpreter.frontend_extension import (
    DialectParser,
    NullDialectParser,
    RedDragonExtensionLoweringStrategy,
)


def _identity(source: str) -> str:
    return source


def _no_extra_program_source_dirs() -> Sequence[Path]:
    return ()


@dataclass(frozen=True)
class CoprocessorSpec:
    """One coprocessor's contribution to a composed COBOL program.

    ``make_strategy`` is a zero-arg closure built by a per-coprocessor adapter
    (e.g. ``adapters.cics.build_cics_spec``), already bound to whatever runtime
    state that coprocessor needs. ``source_prepass`` runs at the source-text
    layer, before ProLeap parses the program.

    A coprocessor whose strategy construction depends on state its own prepass
    computes (e.g. Squall's dclgen field metadata) closes over a private
    mutable one-element list shared between ``source_prepass`` and
    ``make_strategy`` — the same holder-cell idiom Cicada's own
    CicsLoweringStrategy already uses for ``context_holder``/``result_holder``.
    ``compile_program`` guarantees every spec's ``source_prepass`` runs before
    ANY spec's ``make_strategy`` is called, so that holder is always populated
    in time.

    ``owns_execution`` marks the (at most one) coprocessor that imposes
    execution semantics on the compiled program (CICS's dispatcher/SUSPEND) —
    see ``run_program`` in ``run.py``.

    ``dialect_parser`` threads RedDragon's ``compile_cobol(dialect_parsers=[...])``
    array through without this module knowing what any dialect parser does —
    every adapter sets one (a real one, or the NullDialectParser default);
    compile_program collects them all unconditionally.

    ``extra_program_source_dirs`` threads RedDragon's
    ``compile_cobol(program_source_dirs=[...])`` search path through the same
    way — a coprocessor whose CALLed subprograms are never on disk under the
    caller's own directory (e.g. Cicada's IBM Language Environment stubs such
    as CEEDAYS, which live in cics.le_stubs.LE_STUBS_DIR) sets this to
    contribute that directory, without this module knowing what's in it or
    what any of it is for. compile_program appends every spec's contribution,
    in order, after the caller's own program_source_dirs.
    """

    name: str
    make_strategy: Callable[[], RedDragonExtensionLoweringStrategy]
    source_prepass: Callable[[str], str] = _identity
    owns_execution: bool = False
    dialect_parser: DialectParser = NullDialectParser()
    extra_program_source_dirs: Callable[[], Sequence[Path]] = (
        _no_extra_program_source_dirs
    )

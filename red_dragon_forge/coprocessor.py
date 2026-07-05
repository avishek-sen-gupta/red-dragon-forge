"""CoprocessorSpec — the generic seam for composing RedDragon COBOL coprocessor
lowering strategies (CICS, EXEC SQL, and others later).

This module and compile.py must never import cics.* or squall.* — only the
adapters/ package is allowed to know which coprocessors exist by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from interpreter.cobol.dialect_parser import DialectParser, NullDialectParser
from interpreter.cobol.red_dragon_extension_strategy import (
    RedDragonExtensionLoweringStrategy,
)


def _identity(source: str) -> str:
    return source


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
    """

    name: str
    make_strategy: Callable[[], RedDragonExtensionLoweringStrategy]
    source_prepass: Callable[[str], str] = _identity
    owns_execution: bool = False
    dialect_parser: DialectParser = NullDialectParser()

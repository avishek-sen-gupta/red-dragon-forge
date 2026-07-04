"""compile_program() — generic compile-time composition of CoprocessorSpecs.

This module must never import cics.* or squall.* — only the adapters/ package
is allowed to know which coprocessors exist by name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from interpreter.project.cobol_compile import compile_cobol
from interpreter.project.types import LinkedProgram

from red_dragon_forge.coprocessor import CoprocessorSpec


def compile_program(
    source: bytes,
    parser: Any,
    specs: Sequence[CoprocessorSpec],
    *,
    program_source_dir: Path | None = None,
    extra_subprogram_sources: dict[str, bytes] | None = None,
) -> tuple[Any, LinkedProgram]:
    """Compile ``source`` with every spec's prepass and strategy composed.

    Every spec's ``source_prepass`` runs, in order, before ANY spec's
    ``make_strategy`` is called — a spec whose strategy construction depends on
    state its own prepass populates (e.g. Squall's dclgen field metadata)
    relies on this ordering (see CoprocessorSpec's docstring).
    """
    text = source.decode("utf-8")
    for spec in specs:
        text = spec.source_prepass(text)

    strategies = [spec.make_strategy() for spec in specs]
    dialect_parsers = [spec.dialect_parser for spec in specs]

    return compile_cobol(
        text.encode("utf-8"),
        parser=parser,
        extension_strategies=strategies,
        dialect_parsers=dialect_parsers,
        program_source_dir=program_source_dir if program_source_dir is not None else Path("."),
        extra_subprogram_sources=extra_subprogram_sources
        if extra_subprogram_sources is not None
        else {},
    )

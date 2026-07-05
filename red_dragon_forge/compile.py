"""compile_program() — generic compile-time composition of CoprocessorSpecs.

This module must never import cics.* or squall.* — only the adapters/ package
is allowed to know which coprocessors exist by name.
"""

from __future__ import annotations

import functools
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
    program_source_dirs: Sequence[Path] = (),
) -> tuple[Any, LinkedProgram]:
    """Compile ``source`` with every spec's prepass and strategy composed.

    Every spec's ``source_prepass`` runs, in order, before ANY spec's
    ``make_strategy`` is called — a spec whose strategy construction depends on
    state its own prepass populates (e.g. Squall's dclgen field metadata)
    relies on this ordering (see CoprocessorSpec's docstring).
    """
    text = functools.reduce(
        lambda t, spec: spec.source_prepass(t), specs, source.decode("utf-8")
    )

    strategies = [spec.make_strategy() for spec in specs]
    dialect_parsers = [spec.dialect_parser for spec in specs]
    all_program_source_dirs: tuple[Path, ...] = functools.reduce(
        lambda dirs, spec: (*dirs, *spec.extra_program_source_dirs()),
        specs,
        tuple(program_source_dirs),
    )

    return compile_cobol(
        text.encode("utf-8"),
        parser=parser,
        extension_strategies=strategies,
        dialect_parsers=dialect_parsers,
        program_source_dirs=all_program_source_dirs,
    )

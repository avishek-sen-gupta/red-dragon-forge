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

    At most one spec may supply a ``cics_text_parser`` — RedDragon's
    ``compile_cobol`` accepts only one.
    """
    text = source.decode("utf-8")
    for spec in specs:
        text = spec.source_prepass(text)

    strategies = [spec.make_strategy() for spec in specs]

    cics_text_parsers = [s.cics_text_parser for s in specs if s.cics_text_parser is not None]
    assert len(cics_text_parsers) <= 1, (
        f"at most one CoprocessorSpec may supply a cics_text_parser, got "
        f"{len(cics_text_parsers)}"
    )

    return compile_cobol(
        text.encode("utf-8"),
        parser=parser,
        extension_strategies=strategies,
        cics_text_parser=cics_text_parsers[0] if cics_text_parsers else None,
        program_source_dir=program_source_dir,
        extra_subprogram_sources=extra_subprogram_sources,
    )

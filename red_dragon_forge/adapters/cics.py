"""Adapter wrapping Cicada's CicsLoweringStrategy as a CoprocessorSpec.

This is the ONLY module in red_dragon_forge (besides run.py) allowed to import
cics.*.
"""

from __future__ import annotations

from typing import Any

from cics.le_stubs import LE_STUBS_DIR
from cics.preprocessor import apply_cics_prepass
from cics.statements import CicsDialectParser
from cics.strategy import CicsLoweringStrategy

from red_dragon_forge.coprocessor import CoprocessorSpec


def build_cics_spec(
    context_holder: list,
    result_holder: list | None = None,
    program_cache: dict | None = None,
    vsam_engine: Any = None,
    screen_queue: Any = None,
    input_queue: Any = None,
    **kwargs: Any,
) -> CoprocessorSpec:
    """Build the EXEC CICS CoprocessorSpec.

    ``context_holder``/``result_holder``/``program_cache`` are the same
    mutable cells CicsLoweringStrategy already uses internally (Cicada's own
    convention) — pass the SAME dicts/lists across multiple compile_program()
    calls for programs that LINK to each other within one region.
    """

    def _make_strategy() -> CicsLoweringStrategy:
        return CicsLoweringStrategy(
            context_holder=context_holder,
            result_holder=result_holder,
            program_cache=program_cache,
            vsam_engine=vsam_engine,
            screen_queue=screen_queue,
            input_queue=input_queue,
            **kwargs,
        )

    return CoprocessorSpec(
        name="cics",
        make_strategy=_make_strategy,
        source_prepass=apply_cics_prepass,
        owns_execution=True,
        dialect_parser=CicsDialectParser(),
        extra_program_source_dirs=lambda: (LE_STUBS_DIR,),
    )

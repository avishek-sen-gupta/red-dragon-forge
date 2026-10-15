"""The CICS coprocessor's compile surface: a CoprocessorSpec whose strategy only lowers EXEC CICS."""

from __future__ import annotations

from cics.le_stubs import LE_STUBS_DIR
from cics.preprocessor import apply_cics_prepass
from cics.statements import CicsDialectParser
from cics.strategy import CicsLoweringStrategy
from interpreter.project.coprocessor_compile import CoprocessorSpec

_OWN_UNSUPPORTED: set[str] = set()


def build_cics_spec(
    *,
    conversational: bool = False,
    unsupported_verbs: set[str] = _OWN_UNSUPPORTED,
) -> CoprocessorSpec:
    collected = set() if unsupported_verbs is _OWN_UNSUPPORTED else unsupported_verbs
    dialect_parser = CicsDialectParser()

    def _make_strategy() -> CicsLoweringStrategy:
        return CicsLoweringStrategy(
            conversational=conversational,
            handler_source=dialect_parser.statements,
            unsupported_verbs=collected,
        )

    return CoprocessorSpec(
        name="cics",
        make_strategy=_make_strategy,
        source_prepass=apply_cics_prepass,
        owns_execution=True,
        dialect_parser=dialect_parser,
        source_search_dirs=lambda: (LE_STUBS_DIR,),
    )

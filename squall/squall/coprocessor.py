"""Wraps Squall's SqlLoweringStrategy as a CoprocessorSpec -- the seam
interpreter.project.coprocessor_compile.compile_program composes."""

from __future__ import annotations

from interpreter.project.coprocessor_compile import CoprocessorSpec
from squall.db2_stubs import read_db2_stub_sources
from squall.preprocess import apply_sql_prepass
from squall.statements import SqlDialectParser
from squall.strategy import SqlLoweringStrategy


def build_sql_spec() -> CoprocessorSpec:
    """Build the EXEC SQL CoprocessorSpec.

    ``source_prepass`` rewrites EXEC SQL INCLUDE -> COPY.

    ``linked_subprogram_sources`` links squall's Db2 stubs (``DSNTIAC``) into
    every run unit this spec compiles. Linking them outright rather than
    contributing a ``source_search_dirs`` entry is forced, not a preference:
    the search path is walked from CALL edges a text scan found, and CardDemo
    reaches DSNTIAC by data-name, which no scan can discover (red-dragon-t3kl).
    See ``squall.db2_stubs`` for what each stub does and does not model.
    """

    return CoprocessorSpec(
        name="sql",
        make_strategy=SqlLoweringStrategy,
        source_prepass=apply_sql_prepass,
        owns_execution=False,
        dialect_parser=SqlDialectParser(),
        linked_subprogram_sources=read_db2_stub_sources,
    )

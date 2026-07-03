"""Adapter wrapping Squall's SqlLoweringStrategy as a CoprocessorSpec.

This is the ONLY module in red_dragon_forge allowed to import squall.*.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from squall.backend import SqlBackend
from squall.parser.sql_model import FieldMeta
from squall.preprocess import apply_sql_prepass
from squall.strategy import SqlLoweringStrategy

from red_dragon_forge.coprocessor import CoprocessorSpec


def build_sql_spec(
    connections: Mapping[str, SqlBackend],
    copybook_dirs: Sequence[Path] = (),
) -> CoprocessorSpec:
    """Build the EXEC SQL CoprocessorSpec.

    ``source_prepass`` expands EXEC SQL INCLUDE -> COPY and gathers the dclgen
    field metadata into a private holder as a side effect; ``make_strategy``
    reads that holder when called. ``compile_program`` always runs every
    spec's prepass before any spec's make_strategy, so the holder is populated
    in time (see CoprocessorSpec's docstring for why this ordering is required
    for SQL specifically, unlike CICS).
    """
    field_meta_holder: list[Mapping[str, FieldMeta]] = [{}]

    def _prepass(source: str) -> str:
        result = apply_sql_prepass(source, copybook_dirs)
        field_meta_holder[0] = result.field_meta
        return result.source

    def _make_strategy() -> SqlLoweringStrategy:
        return SqlLoweringStrategy(connections, field_meta_holder[0])

    return CoprocessorSpec(
        name="sql",
        make_strategy=_make_strategy,
        source_prepass=_prepass,
        owns_execution=False,
    )

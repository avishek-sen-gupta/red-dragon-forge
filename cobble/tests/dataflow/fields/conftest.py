"""Fixtures for the field-level dataflow tests.

Programs are built as ASG dicts in the exact shape the parse cache holds, so a
test's input is the same thing the corpus pass reads. No corpus member is named
anywhere in this directory; the acceptance test reads a gitignored config.

``field`` is a fixture rather than an importable helper because ``cobble/tests``
carries no ``__init__.py`` -- a relative ``from .conftest import field`` would not
resolve, and a duplicate basename anywhere in the tree breaks collection.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.extent import CellIndex, cell_index
from cobble.dataflow.fields.program_layout import ProgramLayout, program_layout
from cobble.dataflow.layout import program_records
from cobol_asg.asg_types import CobolASG

CORPUS_CONFIG = Path(__file__).resolve().parents[3] / "config" / "fields-tests.toml"
PUBLIC_CONFIG = (
    Path(__file__).resolve().parents[3] / "config" / "carddemo-fields-tests.toml"
)


@pytest.fixture
def corpus_config() -> Mapping[str, object]:
    """A local config naming real members, else the tracked public-corpus one.

    The local name stays gitignored because it is where a corpus under analysis
    gets pointed at; the public one is tracked so the acceptance tests are a gate
    rather than a permanent skip.
    """
    chosen = CORPUS_CONFIG if CORPUS_CONFIG.is_file() else PUBLIC_CONFIG
    if not chosen.is_file():
        pytest.skip(f"no {CORPUS_CONFIG.name} and no {PUBLIC_CONFIG.name}")
    return tomllib.loads(chosen.read_text(encoding="utf-8"))


@pytest.fixture
def program_of():
    """A one-paragraph program PROGA whose paragraph is MAIN."""

    def build(statements: Sequence[Mapping], **extra) -> CobolASG:
        body = {
            "program_id": "PROGA",
            "paragraphs": [{"name": "MAIN", "statements": list(statements)}],
            **extra,
        }
        with cached_asg_dialect_parsers_registered():
            return CobolASG.from_dict(json.loads(json.dumps(body)))

    return build


@pytest.fixture
def index_of():
    """A CellIndex over a program's records."""

    def build(asg: CobolASG) -> CellIndex:
        return cell_index(program_records(asg))

    return build


@pytest.fixture
def layout_of():
    """A program's records and the index over them, the pair emit now takes."""

    def build(asg: CobolASG) -> ProgramLayout:
        return program_layout(asg)

    return build


@pytest.fixture
def field():
    """One DATA DIVISION entry, in cache shape.

    ``offset`` is the bridge's, not something layout derives, so a record with
    more than one child states each child's offset the way the parse cache does
    (see tests/dataflow/test_field_layout.py, which builds fields the same way).
    """

    def build(level: int, name: str, pic: str = "", **extra) -> dict:
        entry: dict = {"level": level, "name": name}
        if pic:
            entry["pic"] = pic
        return {**entry, **extra}

    return build

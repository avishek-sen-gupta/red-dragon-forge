"""Fixtures shared by the srccfg tests.

``asg_of`` is the one that matters: a program's procedure division as a dict, in
the exact shape the parse cache holds, turned into the same CobolASG object the
real pass consumes. Registering the dialect parsers is not optional -- without it
any member containing EXEC CICS raises "Unknown COBOL statement type".

No corpus member is named in any test. ``corpus_asg_paths`` reads a gitignored
config so a developer can run the slow acceptance test against a real cache
without that cache's identifiers entering the repository; with no config, the
tests that use it skip.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from cobol_asg.asg_types import CobolASG

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered

CORPUS_CONFIG = Path(__file__).resolve().parents[3] / "config" / "srccfg-tests.toml"


@pytest.fixture
def asg_of():
    """Build a CobolASG from a procedure-division dict."""

    def build(body: Mapping) -> CobolASG:
        with cached_asg_dialect_parsers_registered():
            return CobolASG.from_dict(json.loads(json.dumps(dict(body))))

    return build


@pytest.fixture
def program_of(asg_of):
    """A one-paragraph program named PROGA whose paragraph is MAIN."""

    def build(statements: Sequence[Mapping], **extra) -> CobolASG:
        return asg_of(
            {
                "program_id": "PROGA",
                "paragraphs": [{"name": "MAIN", "statements": list(statements)}],
                **extra,
            }
        )

    return build


@pytest.fixture
def corpus_asg_paths() -> tuple[Path, ...]:
    """Parsed-ASG files from a real cache, or a skip.

    The config is gitignored (`config/*.toml`), so the member names it points at
    stay out of the repository. Shape:

        cache_dir = "/abs/path/to/out-<corpus>-parsed"
        members = ["SOMEMEMBER", "OTHERMEMBER"]
    """
    if not CORPUS_CONFIG.is_file():
        pytest.skip(f"no {CORPUS_CONFIG.name}; acceptance test needs a parsed cache")
    raw = tomllib.loads(CORPUS_CONFIG.read_text())
    cache = Path(raw["cache_dir"])
    return tuple(cache / f"{member}.json" for member in raw["members"])

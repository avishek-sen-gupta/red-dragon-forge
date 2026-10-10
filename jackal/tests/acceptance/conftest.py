"""Fixtures that turn an acceptance fixture path into a parsed or expanded job."""

from collections.abc import Callable
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def parse_fixture(jcl_bridge_jar: str) -> Callable[[str], object]:
    def _parse(rel: str) -> object:
        from jackal.jcl.parser import parse_jcl

        return parse_jcl((FIXTURES / rel).read_text())

    return _parse


@pytest.fixture
def expand_fixture(
    parse_fixture: Callable[[str], object],
) -> Callable[[str], object]:
    def _expand(rel: str) -> object:
        from jackal.expansion import DirectoryProcLibrary, expand_procs

        path = FIXTURES / rel
        return expand_procs(parse_fixture(rel), DirectoryProcLibrary((path.parent,)))

    return _expand

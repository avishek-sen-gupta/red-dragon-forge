"""Fixtures for litter's tests: the ProLeap parser, which fails loudly without its bridge JAR."""

import os

import pytest
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner


@pytest.fixture
def parser() -> ProLeapCobolParser:
    return ProLeapCobolParser(
        runner=RealSubprocessRunner(),
        bridge_jar=os.environ["PROLEAP_BRIDGE_JAR"],
        copybook_dirs=[],
    )

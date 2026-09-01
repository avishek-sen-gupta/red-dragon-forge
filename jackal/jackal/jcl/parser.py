"""JCL parser: text -> Job, via the jcl-bridge JAR (ANTLR mapa grammar)."""

from __future__ import annotations

import os

from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.model import Job, ProcDef


def bridge_parser() -> JclBridgeParser:
    """The production bridge, for a caller driving many members through one store
    rather than a single text through ``parse_jcl``."""
    jar = os.environ["JCL_BRIDGE_JAR"]  # fail loud if unset
    return JclBridgeParser(JclSubprocessRunner(), jar)


def parse_jcl(text: str) -> Job:
    return bridge_parser().parse(text)


def parse_proc(text: str) -> ProcDef:
    """Parse a bare PROC document (.prc file: //NAME PROC ... // PEND, no
    JOB card) via the same jcl-bridge grammar's procJCL alternative."""
    jar = os.environ["JCL_BRIDGE_JAR"]  # fail loud if unset
    return JclBridgeParser(JclSubprocessRunner(), jar).parse_proc(text)

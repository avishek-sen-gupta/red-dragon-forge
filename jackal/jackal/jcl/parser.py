"""JCL parser: text -> Job, via the jcl-bridge JAR (ANTLR mapa grammar)."""

from __future__ import annotations

import os

from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.model import Job, ProcDef


def parse_jcl(text: str) -> Job:
    jar = os.environ["JCL_BRIDGE_JAR"]  # fail loud if unset
    return JclBridgeParser(JclSubprocessRunner(), jar).parse(text)


def parse_proc(text: str) -> ProcDef:
    """Parse a bare PROC document (.prc file: //NAME PROC ... // PEND, no
    JOB card) via the same jcl-bridge grammar's procJCL alternative."""
    jar = os.environ["JCL_BRIDGE_JAR"]  # fail loud if unset
    return JclBridgeParser(JclSubprocessRunner(), jar).parse_proc(text)

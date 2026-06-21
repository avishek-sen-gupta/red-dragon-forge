"""JCL parser: text -> Job, via the jcl-bridge JAR (ANTLR mapa grammar)."""

from __future__ import annotations

import os

from jackal.jcl.bridge_parser import JclBridgeParser, JclSubprocessRunner
from jackal.model import Job


def parse_jcl(text: str) -> Job:
    jar = os.environ["JCL_BRIDGE_JAR"]  # fail loud if unset
    return JclBridgeParser(JclSubprocessRunner(), jar).parse(text)

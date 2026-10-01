"""One program's CFG, the one way every consumer builds it."""

from __future__ import annotations

from cobble.dataflow.srccfg.build import build_program
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.dataflow import with_handler_edges
from cobol_asg.asg_types import CobolASG


def program_cfg(asg: CobolASG, source_file: str = "") -> Cfg:
    """The lowered program with its CICS raises joined to the handlers armed there.

    Without the handler edges a paragraph reached only through HANDLE CONDITION is
    unreachable, and every analysis over the CFG silently skips it.
    """
    return with_handler_edges(build_program(asg, source_file=source_file))

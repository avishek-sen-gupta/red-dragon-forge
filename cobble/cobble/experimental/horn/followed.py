"""The CFG edges no run takes: the FLOW edge past a PERFORM that cannot come back, and a PGMIDERR dispatch from a command that cannot raise it."""

from cobble.dataflow.srccfg.cfg import Edge, EdgeKind
from cobble.dataflow.srccfg.desugar import DISPATCH_TRANSFER_CICS, PERFORM_TRANSFER
from cobble.experimental.horn.context import members, perform_edge, performed
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.xctl import never_pgmiderr, pgmiderr_handlers
from cobol_asg.cobol_statements import (
    AlterStatement,
    ExitProgramStatement,
    GobackStatement,
    StopRunStatement,
)

TERMINATORS = (StopRunStatement, GobackStatement, ExitProgramStatement)


def unfollowed(program: Program) -> frozenset[Edge]:
    return frozenset(
        edge
        for edge in program.cfg.edges
        if _never_back(program, edge) or _never_raised(program, edge)
    )


def _never_back(program: Program, edge: Edge) -> bool:
    """The FLOW edge the CFG keeps past a PERFORM whose range end nothing reaches,
    when every way out of the range ends the task and no ALTER can redirect a GO
    TO: the PERFORM cannot come back, so the edge is not a path."""
    cfg = program.cfg
    if (
        edge.kind is not EdgeKind.FLOW
        or cfg.node(edge.source).transfer != PERFORM_TRANSFER
    ):
        return False
    calls = perform_edge(cfg, edge.source)
    return (
        bool(calls)
        and not _altered(program)
        and all(
            ends_task(program, node)
            for call in calls
            for node in members(cfg, performed(cfg, call))
            if not cfg.successors(node)
        )
    )


def _altered(program: Program) -> bool:
    return any(
        isinstance(statement, AlterStatement)
        for statement in program.statements.values()
    )


def ends_task(program: Program, node: str) -> bool:
    """STOP RUN, GOBACK, EXIT PROGRAM, or a CICS condition no handler takes."""
    if program.cfg.node(node).transfer == DISPATCH_TRANSFER_CICS:
        return True
    return isinstance(program.statements.get(node), TERMINATORS)


def _never_raised(program: Program, edge: Edge) -> bool:
    """The dispatch into a handler armed for PGMIDERR alone, from the one command
    before it, when that command cannot raise PGMIDERR."""
    cfg = program.cfg
    if not (
        edge.kind is EdgeKind.GOTO
        and cfg.node(edge.source).transfer == DISPATCH_TRANSFER_CICS
        and cfg.node(edge.target).paragraph in pgmiderr_handlers(program)
    ):
        return False
    commands = raising(program, edge)
    return len(commands) == 1 and never_pgmiderr(program, commands[0])


def raising(program: Program, edge: Edge) -> tuple[str, ...]:
    cfg = program.cfg
    return tuple(
        command.source
        for raised in cfg.predecessors(edge.source)
        for command in cfg.predecessors(raised.source)
    )

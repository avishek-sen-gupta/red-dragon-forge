"""What one reachability state leads to: the edges taken out of it, and what it records.

The rules are the spec's semantics table, one function each, chosen by the first
test in ``_RULES`` the state meets.
"""

from collections.abc import Callable, Mapping
from types import MappingProxyType

from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node
from cobble.dataflow.srccfg.desugar import DISPATCH_TRANSFER_CICS, PERFORM_TRANSFER
from cobble.dataflow.srccfg.reach.reach_error import ReachError
from cobble.dataflow.srccfg.reach.reach_frame import ReachFrame
from cobble.dataflow.srccfg.reach.reach_state import ReachState
from cobble.dataflow.srccfg.reach.reach_step import ReachStep
from cobble.dataflow.srccfg.reach.reach_visit import ReachVisit
from cobble.dataflow.srccfg.rows.cfg_row import outcome_row, refused_row, unresolved_row
from cobble.dataflow.srccfg.rows.reach_outcome import ReachOutcome

_ENDING: Mapping[str, ReachOutcome] = MappingProxyType(
    {
        "STOPRUN": ReachOutcome.STOP_RUN,
        "GOBACK": ReachOutcome.GOBACK,
        "EXITPROGRAM": ReachOutcome.EXIT_PROGRAM,
        "CICS_ABEND": ReachOutcome.ABEND,
    }
)
_LEAVING: Mapping[str, ReachOutcome] = MappingProxyType(
    {"CICS_XCTL": ReachOutcome.XCTL, "CICS_RETURN": ReachOutcome.CICS_RETURN}
)

Test = Callable[[Cfg, Node, ReachState], bool]
Rule = Callable[[Cfg, Node, ReachState], ReachVisit]


def start(cfg: Cfg, seed: str) -> ReachVisit:
    """The seed's own expansion: enter its range with one frame, its resume point."""
    node = _performing(cfg, _present(cfg, seed))
    return _performed(cfg, node, ReachState(node=seed, stack=()))


def _present(cfg: Cfg, seed: str) -> Node:
    if seed not in cfg.node_ids:
        raise ReachError(f"{cfg.program} has no node {seed}")
    return cfg.node(seed)


def _performing(cfg: Cfg, node: Node) -> Node:
    if node.transfer != PERFORM_TRANSFER:
        raise ReachError(
            f"{node.id} is not a PERFORM "
            f"(kind {node.kind.value}, transfer {node.transfer or 'none'})"
        )
    if not _performs(cfg, node.id):
        raise ReachError(
            f"{node.id} performs {node.target}, which {cfg.program} does not declare"
        )
    return node


def expand(cfg: Cfg, state: ReachState) -> ReachVisit:
    node = cfg.node(state.node)
    rule = next(rule for test, rule in _RULES if test(cfg, node, state))
    return rule(cfg, node, state)


def _returns(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    return ReachVisit(steps=(), events=(outcome_row(ReachOutcome.RETURNS, node.id),))


def _ends(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    return ReachVisit(steps=(), events=(outcome_row(_ENDING[node.transfer], node.id),))


def _leaves(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    return ReachVisit(
        steps=_onward(cfg, node, state).steps,
        events=(outcome_row(_LEAVING[node.transfer], node.id),),
    )


def _onward(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    return ReachVisit(
        steps=tuple(
            ReachStep(edge=edge, state=ReachState(node=edge.target, stack=state.stack))
            for edge in cfg.successors(node.id)
        ),
        events=(),
    )


def _performed(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    performs = _performs(cfg, node.id)
    if not performs:
        return ReachVisit(
            steps=_onward(cfg, node, state).steps, events=(unresolved_row(node.id),)
        )
    frame = ReachFrame(resume=_resume(cfg, node), end=node.range_end)
    if frame in state.stack:
        return _stepped_over(node, frame.resume, state)
    return ReachVisit(
        steps=tuple(
            ReachStep(
                edge=edge,
                state=ReachState(node=edge.target, stack=(*state.stack, frame)),
            )
            for edge in performs
        ),
        events=(),
    )


def _stepped_over(node: Node, resume: str, state: ReachState) -> ReachVisit:
    """A recursive PERFORM is undefined in COBOL: the walk does not push it, and goes
    on at its resume point along an edge the CFG does not hold, named by the
    ``refused`` row."""
    return ReachVisit(
        steps=(
            ReachStep(
                edge=Edge(source=node.id, target=resume, kind=EdgeKind.FLOW),
                state=ReachState(node=resume, stack=state.stack),
            ),
        ),
        events=(refused_row(node.id),),
    )


def _performs(cfg: Cfg, node_id: str) -> tuple[Edge, ...]:
    return tuple(
        edge for edge in cfg.successors(node_id) if edge.kind is EdgeKind.PERFORM
    )


def _resume(cfg: Cfg, node: Node) -> str:
    """Where the PERFORM continues once its range returns: ``Node.resume``, or for a
    range that never returns, the FLOW edge the build kept past it."""
    if node.resume:
        return node.resume
    return next(
        (edge.target for edge in cfg.successors(node.id) if edge.kind is EdgeKind.FLOW),
        "",
    )


def _range_end(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    """Return from the innermost open PERFORM whose range ends here, dropping any
    opened inside it that a GO TO left behind; with none, fall through, as COBOL
    does at an end no open PERFORM closes.

    A frame is matched by the end it returns from, never by where it resumes: the
    two arms of an IF can PERFORM different ranges that resume at one statement."""
    closing = tuple(at for at, frame in enumerate(state.stack) if frame.end == node.id)
    if not closing:
        return _fallen_through(cfg, node, state)
    frame = state.stack[closing[-1]]
    return ReachVisit(
        steps=(
            ReachStep(
                edge=Edge(source=node.id, target=frame.resume, kind=EdgeKind.RETURN),
                state=ReachState(node=frame.resume, stack=state.stack[: closing[-1]]),
            ),
        ),
        events=(),
    )


def _fallen_through(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    onward = tuple(
        ReachStep(edge=edge, state=ReachState(node=edge.target, stack=state.stack))
        for edge in cfg.successors(node.id)
        if edge.kind is not EdgeKind.RETURN
    )
    if not onward:
        return _stuck(cfg, node, state)
    return ReachVisit(steps=onward, events=())


def _stuck(cfg: Cfg, node: Node, state: ReachState) -> ReachVisit:
    kind = (
        ReachOutcome.UNHANDLED_CONDITION
        if node.transfer == DISPATCH_TRANSFER_CICS
        else ReachOutcome.DEAD_END
    )
    return ReachVisit(steps=(), events=(outcome_row(kind, node.id),))


_RULES: tuple[tuple[Test, Rule], ...] = (
    (lambda cfg, node, state: not state.stack, _returns),
    (lambda cfg, node, state: node.transfer in _ENDING, _ends),
    (lambda cfg, node, state: node.transfer in _LEAVING, _leaves),
    (lambda cfg, node, state: node.transfer == PERFORM_TRANSFER, _performed),
    (
        lambda cfg, node, state: any(
            edge.kind is EdgeKind.RETURN for edge in cfg.successors(node.id)
        ),
        _range_end,
    ),
    (lambda cfg, node, state: not cfg.successors(node.id), _stuck),
    (lambda cfg, node, state: True, _onward),
)

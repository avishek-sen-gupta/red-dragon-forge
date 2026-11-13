"""The ways a node is reached, each checked by Z3, with what Z3 proves about every other test on its route."""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.condition import Entered, Took
from cobble.experimental.horn.leading_to import leading_to
from cobble.experimental.horn.lower import HornSystem, lower
from cobble.experimental.horn.outcome import Outcome
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import Program
from cobble.experimental.horn.reaches import Asked, reaches
from cobble.experimental.horn.route import route_tests
from cobble.experimental.horn.verdict import Verdict
from cobble.experimental.horn.ways import Way, ways_to

logger = logging.getLogger(__name__)


class RouteVerdict(Enum):
    EITHER_WAY = "either way"
    IF_IT_RUNS = "if it runs"
    NEVER_RUNS = "never runs on this way"
    GAVE_UP = "solver gave up"


@dataclass(frozen=True)
class RouteTest:
    """``outcome`` is the one the test takes if it runs, for ``IF_IT_RUNS``, and
    ``UNRUN`` otherwise."""

    test: str
    verdict: RouteVerdict
    outcome: Outcome


@dataclass(frozen=True)
class CheckedWay:
    way: Way
    answer: Answer
    route: tuple[RouteTest, ...]


@dataclass(frozen=True)
class Report:
    """``dropped`` counts the ways Z3 proved no run takes; ``cut`` says the ways
    were capped."""

    program: str
    node: str
    ways: tuple[CheckedWay, ...]
    dropped: int
    cut: bool


DECIDED: Mapping[tuple[Answer, Answer], tuple[RouteVerdict, Outcome]] = {
    (Answer.SAT, Answer.SAT): (RouteVerdict.EITHER_WAY, Outcome.UNRUN),
    (Answer.SAT, Answer.UNSAT): (RouteVerdict.IF_IT_RUNS, Outcome.TRUE),
    (Answer.UNSAT, Answer.SAT): (RouteVerdict.IF_IT_RUNS, Outcome.FALSE),
    (Answer.UNSAT, Answer.UNSAT): (RouteVerdict.NEVER_RUNS, Outcome.UNRUN),
}
GAVE_UP = (RouteVerdict.GAVE_UP, Outcome.UNRUN)

Ask = Callable[[HornSystem, Point, Sequence[Asked], Callable[[], float]], Verdict]


def classified(test: str, true: Answer, false: Answer) -> RouteTest:
    """Both outcomes possible, one only, or neither; or the solver gave up on
    either."""
    verdict, outcome = DECIDED.get((true, false), GAVE_UP)
    return RouteTest(test, verdict, outcome)


def _unchecked(test: str) -> RouteTest:
    """A route test under a way the solver gave up on: each of its checks asks
    more than the way, so it is left as given up rather than run to the limit."""
    return RouteTest(test, *GAVE_UP)


@dataclass(frozen=True)
class Checker:
    program: Program
    node: str
    clock: Callable[[], float]
    ask: Ask

    def checked(self, index: int, way: Way) -> CheckedWay:
        route = route_tests(self.program, way, self.node)
        last = {d.test: d.outcome for d in way.decisions}
        system = lower(
            self.program,
            kept=leading_to(self.program.cfg, self.node),
            outcomes=(*last, *route),
            entries=tuple(dict.fromkeys(context for context, _ in way.calls)),
        )
        conditions = (
            *(Took(test, outcome) for test, outcome in last.items()),
            *(Entered(context, call) for context, call in way.calls),
        )
        answer = self._ask(system, conditions, f"way {index}")
        if answer is Answer.UNSAT:
            return CheckedWay(way, answer, ())
        if answer is Answer.UNKNOWN:
            return CheckedWay(way, answer, tuple(_unchecked(test) for test in route))
        return CheckedWay(
            way,
            answer,
            tuple(self._route(system, conditions, index, test) for test in route),
        )

    def _route(
        self,
        system: HornSystem,
        conditions: tuple[Asked, ...],
        index: int,
        test: str,
    ) -> RouteTest:
        true, false = tuple(
            self._ask(
                system, (*conditions, Took(test, o)), f"way {index}, {test} {o.name}"
            )
            for o in (Outcome.TRUE, Outcome.FALSE)
        )
        return classified(test, true, false)

    def _ask(
        self, system: HornSystem, conditions: tuple[Asked, ...], what: str
    ) -> Answer:
        point = Point(self.program.cfg.program, self.node)
        verdict = self.ask(system, point, conditions, self.clock)
        logger.info("%s: %s in %.1fs", what, verdict.answer.name, verdict.seconds)
        return verdict.answer


def reaching_conditions(
    program: Program, node: str, clock: Callable[[], float], ask: Ask = reaches
) -> Report:
    cfg = program.cfg
    if node not in cfg.node_ids:
        raise ValueError(f"{node} is not a node of {cfg.program}")
    found = ways_to(program, node)
    checker = Checker(program, node, clock, ask)
    checked = tuple(checker.checked(n, way) for n, way in enumerate(found.ways))
    kept = tuple(way for way in checked if way.answer is not Answer.UNSAT)
    return Report(cfg.program, node, kept, len(checked) - len(kept), found.cut)

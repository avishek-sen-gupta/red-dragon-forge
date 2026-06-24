"""Pure evaluation of JCL COND= step-bypass conditions (IBM semantics)."""

from __future__ import annotations

import operator
from collections.abc import Callable

from jackal.model import Cond, CondOp
from jackal.results import StepResult

_OPS: dict[CondOp, Callable[[int, int], bool]] = {
    CondOp.GT: operator.gt,
    CondOp.GE: operator.ge,
    CondOp.EQ: operator.eq,
    CondOp.NE: operator.ne,
    CondOp.LT: operator.lt,
    CondOp.LE: operator.le,
}


def _condition_true(cond: Cond, prior_executed: tuple[StepResult, ...]) -> bool:
    # Reversed operands: bypass if `code <op> rc` for any relevant prior RC.
    if cond.step:
        rcs = [r.return_code for r in prior_executed if r.name == cond.step]
    else:
        rcs = [r.return_code for r in prior_executed]
    test = _OPS[cond.op]
    return any(test(cond.code, rc) for rc in rcs)


def should_bypass(
    conds: tuple[Cond, ...], prior_executed: tuple[StepResult, ...]
) -> bool:
    """True if this step should be bypassed — i.e. ANY condition is true."""
    return any(_condition_true(c, prior_executed) for c in conds)

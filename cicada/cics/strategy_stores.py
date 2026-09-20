"""The CICS lowering strategy's writes into state it does not own.

Each store changes an object in place because its owner reads that same object
afterwards: the VM looks builtins up in the process-global ``Builtins.TABLE``,
the dialect parser's statement list is shared with every module compile_cobol
lowers, and the unsupported-verb set is the harness's cell.
"""

from __future__ import annotations

import logging
from collections.abc import MutableSequence
from typing import TypeVar

from interpreter.func_name import FuncName

T = TypeVar("T")

# The overwrite warnings are the strategy's own diagnostics; keep them on its logger.
logger = logging.getLogger("cics.strategy")

_OVERWRITING = "Builtins.TABLE already contains %s — overwriting."


def register(name: str, builtin: object, consequence: str = "") -> None:
    # Deferred import to avoid violating project-no-vm-internals import contract.
    from interpreter.vm.builtins import Builtins

    func_name = FuncName(name)
    if func_name in Builtins.TABLE:
        logger.warning(_OVERWRITING + consequence, func_name)
    Builtins.TABLE[func_name] = builtin


def register_default(name: str, builtin: object) -> None:
    """Register ``builtin`` only if nothing is registered under ``name`` yet — for
    a generic extension point another coprocessor may independently claim by
    registering its own real implementation over this default (see
    __cics_task_end_hook). Order-independent: if the other coprocessor
    constructs first, its registration is already present and this call leaves
    it alone; if it constructs later, its own (overwriting) registration
    replaces this default.
    """
    from interpreter.vm.builtins import Builtins

    Builtins.TABLE.setdefault(FuncName(name), builtin)


def swap(name: str, builtin: object) -> object | None:
    """Replace whatever is registered under ``name`` with ``builtin`` and
    return the previous value (``None`` if nothing was registered) — the
    save half of a save/restore around a Builtins.TABLE entry, the same
    pattern ``make_link_builtin`` already applies to ``result_holder`` (see
    cics.builtins.flow), used there to suppress a LINKed program's
    __cics_task_end_hook for the duration of the LINK. Silent: unlike
    ``register``, a save/restore swap is not a registration change worth a
    warning.
    """
    from interpreter.vm.builtins import Builtins

    func_name = FuncName(name)
    previous = Builtins.TABLE.get(func_name)
    Builtins.TABLE[func_name] = builtin
    return previous


def restore(name: str, previous: object | None) -> None:
    """The restore half of ``swap``: put back whatever was registered under
    ``name`` before the swap, or remove the entry if nothing was."""
    from interpreter.vm.builtins import Builtins

    func_name = FuncName(name)
    if previous is None:
        Builtins.TABLE.pop(func_name, None)
    else:
        Builtins.TABLE[func_name] = previous


def drain(items: MutableSequence[T]) -> tuple[T, ...]:
    drained = tuple(items)
    items.clear()
    return drained


def note_unsupported(verbs: set[str], verb: str) -> None:
    verbs.add(verb)

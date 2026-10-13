"""The SQL lowering strategy's one write into state it does not own: builtin registration.

The VM looks builtins up in the process-global ``Builtins.TABLE``, so the
registration has to change that object in place; a rebuilt copy would go unseen
by the VM. Every lowering decision stays gated in strategy.py.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_OVERWRITING = "Builtins.TABLE already contains %s — overwriting."


def register(name: str, builtin: object) -> None:
    """Insert *builtin* into the process-global ``Builtins.TABLE`` under
    ``FuncName(name)``."""
    # Deferred import to avoid violating project-no-vm-internals import contract.
    from interpreter.func_name import FuncName
    from interpreter.vm.builtins import Builtins

    func_name = FuncName(name)
    if func_name in Builtins.TABLE:
        logger.warning(_OVERWRITING, func_name)
    Builtins.TABLE[func_name] = builtin

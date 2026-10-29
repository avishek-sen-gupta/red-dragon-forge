"""The HLASM floating-point builtin tables (binary, hexadecimal, decimal, PFPO) as one table."""

from __future__ import annotations

from collections.abc import Mapping

from interpreter.func_name import FuncName
from interpreter.hlasm.bfp_builtins import bfp_builtins
from interpreter.hlasm.dfp_builtins import dfp_builtins
from interpreter.hlasm.hfp_builtins import hfp_builtins
from interpreter.hlasm.pfpo_builtins import pfpo_builtins
from interpreter.vm.builtin import Builtin
from interpreter.vm.builtins import compose_builtins


def floating_point_builtins() -> Mapping[FuncName, Builtin]:
    return compose_builtins(
        bfp_builtins(), hfp_builtins(), dfp_builtins(), pfpo_builtins()
    )

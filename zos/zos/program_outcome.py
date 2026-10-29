"""What a finished run of a program says: the abends it ended in and, for a program that did not abend, its return code."""

from __future__ import annotations

from infrastructure.zos.abend.system_abend import SystemAbend
from infrastructure.zos.abend.user_abend import UserAbend
from interpreter.cobol.cee3abd_abend import user_abend
from interpreter.cobol.return_code_readback import read_return_code
from interpreter.constants import Language
from interpreter.hlasm.hlasm_outcome import hlasm_abend, hlasm_return_code
from interpreter.project.program_language import program_language
from interpreter.project.types import LinkedProgram
from interpreter.vm.vm_types import VMState


def program_abends(vm: VMState) -> tuple[SystemAbend | UserAbend, ...]:
    return (*user_abend(vm), *hlasm_abend(vm))


def program_return_code(linked: LinkedProgram, entry: str, vm: VMState) -> int:
    match program_language(linked, entry):
        case Language.HLASM:
            return hlasm_return_code(vm)
        case _:
            return read_return_code(vm)

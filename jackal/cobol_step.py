"""Run an EXEC PGM COBOL step against the red-dragon VM."""

from __future__ import annotations

from pathlib import Path

from interpreter.address import Address
from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.real_file_provider import RealFileIOProvider
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.return_code_readback import read_return_code
from interpreter.constants import Language
from interpreter.func_name import FuncName
from interpreter.project.cobol_compile import compile_cobol
from interpreter.project.entry_point import EntryPoint
from interpreter.run import run, run_linked
from interpreter.types.type_expr import UNKNOWN
from interpreter.types.typed_value import TypedValue
from interpreter.var_name import VarName
from interpreter.vm.vm_types import StackFrame, VMState

from jackal.catalog import DatasetCatalog
from jackal.model import Step
from jackal.parm import build_parm_region
from jackal.results import StepDisposition, StepResult

# DDs whose absence is expected in the emulated environment and should be skipped
# silently rather than raising an error.
#   STEPLIB / JOBLIB — load-library DDs: real mainframe load libraries are never
#   present in the local file tree; the emulator finds programs via source_dir instead.
OPTIONAL_DDS: frozenset[str] = frozenset({"STEPLIB", "JOBLIB"})


def _file_control(source: str, bridge_jar: str, copybook_dirs: list[Path]) -> list:
    parser = ProLeapCobolParser(
        runner=RealSubprocessRunner(),
        bridge_jar=bridge_jar,
        copybook_dirs=copybook_dirs,
    )
    return parser.parse(source.encode("utf-8")).file_control


def _overrides(step: Step, catalog: DatasetCatalog) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for dd in step.dds:
        if dd.sysout:
            continue
        if dd.ddname in OPTIONAL_DDS:
            continue
        overrides[dd.ddname] = catalog.allocate(dd).path
    return overrides


def run_cobol_step(
    step: Step,
    source: str,
    catalog: DatasetCatalog,
    bridge_jar: str,
    copybook_dirs: list[Path],
) -> StepResult:
    if not bridge_jar:
        raise ValueError(
            f"PROLEAP_BRIDGE_JAR not set; required to run COBOL step {step.name!r}"
        )
    overrides = _overrides(step, catalog)
    provider = RealFileIOProvider(
        base_dir=catalog.workdir,
        file_control=_file_control(source, bridge_jar, copybook_dirs),
        path_overrides=overrides,
    )
    if step.parm:
        _, linked = compile_cobol(source.encode("utf-8"), copybook_dirs=copybook_dirs)
        parm_addr = Address("rgn_parm")
        parm_vm = VMState()
        parm_vm.region_set(parm_addr, bytearray(build_parm_region(step.parm)))
        parm_vm.call_stack.append(
            StackFrame(
                function_name=FuncName("__jcl_entry__"),
                local_vars={
                    VarName("__params_region"): TypedValue(
                        value=parm_addr, type=UNKNOWN
                    )
                },
            )
        )
        # For COBOL, mirror run()'s entry-point switch: when func_symbol_table is
        # populated, use function-entry mode so run_linked runs the init block
        # (phase 1, including RETURN-CODE region setup) then dispatches into the
        # PROCEDURE DIVISION function (phase 2).
        proc_label = next(
            (
                label
                for label in linked.func_symbol_table
                if not str(label).startswith("func_init_params_")
            ),
            None,
        )
        if proc_label is not None:
            _label = proc_label
            entry_point = EntryPoint.function(lambda ref: ref.label == _label)
        else:
            entry_point = EntryPoint.top_level()
        vm = run_linked(
            linked,
            entry_point,
            io_provider=provider,
            initial_vm=parm_vm,
            max_steps=500_000,
        )
    else:
        vm = run(
            source,
            language=Language.COBOL,
            io_provider=provider,
            max_steps=500_000,
            copybook_dirs=copybook_dirs,
        )
    for dd in step.dds:
        catalog.dispose(dd)
    return StepResult(
        name=step.name,
        return_code=read_return_code(vm),
        ran=True,
        disposition=StepDisposition.EXECUTED,
    )

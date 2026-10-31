"""[plain]: one program entered directly on the package image, its files bound to catalogued datasets."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Mapping
from functools import partial
from pathlib import Path

from catnip.dataset import Dataset, Relabeller
from catnip.labels import Label
from catnip.system_catalog import NotCataloged, SystemCatalog
from interpreter.cobol.symbolic_return_code_error import SymbolicReturnCodeError
from interpreter.func_name import FuncName
from interpreter.hlasm_run_inputs.dd_builtins import dd_builtins
from interpreter.hlasm_run_inputs.declare_file_builtins import declare_file_builtins
from interpreter.project.program_entry import ProgramEntry
from interpreter.run import (
    BudgetExhausted,
    Completed,
    RunOutcome,
    Suspended,
    initial_vm_state,
    run_linked_resumable,
)
from interpreter.vm.builtin import Builtin
from interpreter.vm.builtins import compose_builtins
from interpreter.vm.vm_types import VMState
from litter.package import Package
from zos.cobol.io.dataset_files import DatasetFileIOProvider
from zos.cobol.io.dd_definitions import dd_definitions
from zos.cobol.io.dd_files import DdFileIOProvider
from zos.cobol.io.file_bindings import FileBindings
from zos.cobol.io.file_definitions import program_files_of
from zos.cobol.io.program_files import ProgramFilesIOProvider
from zos.cobol.io.system_input import SystemInput
from zos.program_outcome import program_abends, program_return_code

from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.plain_run import PlainRun


class CatalogRelabeller(Relabeller):
    """Records a dataset's label in the system catalog when its first OPEN gives it one."""

    def __init__(self, catalog: SystemCatalog) -> None:
        self._catalog = catalog

    def relabel(self, dataset: Dataset, label: Label) -> None:
        self._catalog.relabel(dataset.dsn, label)


def _resolved(catalog: SystemCatalog, assign: str, dsn: str) -> Dataset:
    match catalog.lookup(dsn):
        case Dataset() as dataset:
            return dataset
        case NotCataloged():
            raise ConfigError(f"[plain.files] {assign}: {dsn} is not cataloged")


def _bindings(catalog: SystemCatalog, plain: PlainRun) -> FileBindings:
    datasets = {
        assign: _resolved(catalog, assign, dsn) for assign, dsn in plain.files.items()
    }
    return FileBindings(
        paths={assign: dataset.path for assign, dataset in datasets.items()},
        appended=frozenset(),
        datasets=datasets,
    )


def _completed(package: Package, plain: PlainRun, vm: VMState) -> int:
    abends = program_abends(vm)
    if abends:
        sys.stdout.write(f"{abends[0].rendered()}\n")
        return 1
    sys.stdout.write(f"RC {_return_code(package, plain, vm)}\n")
    return 0


def _return_code(package: Package, plain: PlainRun, vm: VMState) -> int:
    try:
        return program_return_code(package.image, plain.program, vm)
    except SymbolicReturnCodeError:
        sys.stderr.write(
            f"forge-run: warning: {plain.program}'s RETURN-CODE is unknown;"
            " reported as 0\n"
        )
        return 0


def _reported(package: Package, plain: PlainRun, outcome: RunOutcome) -> int:
    match outcome:
        case Suspended():
            sys.stderr.write(
                f"forge-run: {plain.program} reached a SUSPEND, which only a CICS"
                " task can\n"
            )
            return 1
        case _:
            return _ended(package, plain, outcome)


def _ended(
    package: Package, plain: PlainRun, outcome: Completed | BudgetExhausted
) -> int:
    match outcome:
        case Completed(vm=vm):
            return _completed(package, plain, vm)
        case BudgetExhausted():
            sys.stdout.write(f"budget exhausted after {plain.max_steps} steps\n")
            return 1


def run_plain(
    package: Package,
    catalog: SystemCatalog,
    plain: PlainRun,
    builtins: Mapping[FuncName, Builtin],
    system_input: SystemInput,
    permit_unresolved_call_targets: bool,
) -> int:
    bindings = _bindings(catalog, plain)
    relabeller = CatalogRelabeller(catalog)
    with tempfile.TemporaryDirectory(prefix="forge-run-") as scratch:
        provider = ProgramFilesIOProvider(
            tuple(package.image.programs),
            partial(
                DatasetFileIOProvider,
                Path(scratch),
                bindings=bindings,
                relabeller=relabeller,
            ),
            program_files_of(package.image),
            DdFileIOProvider(Path(scratch), bindings, relabeller),
            system_input,
        )
        outcome = run_linked_resumable(
            package.image,
            ProgramEntry(plain.program),
            max_steps=plain.max_steps,
            builtins=compose_builtins(
                builtins,
                dd_builtins(dd_definitions(bindings.datasets)),
                declare_file_builtins(),
            ),
            initial_vm=initial_vm_state(io_provider=provider),
            permit_unresolved_call_targets=permit_unresolved_call_targets,
        )
    return _reported(package, plain, outcome)

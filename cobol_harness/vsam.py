"""Test-data setup: byte-exact VSAM records, cluster registration/seeding in a system catalog,
and ASCII/EBCDIC conversion.  Agnostic to any one program or copybook.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from catnip.dataset import Dataset
from catnip.labels import KsdsLabel
from catnip.system_catalog import SystemCatalog
from cics.vsam.engine import VsamEngine
from cics.vsam.file_table import cics_files

from .state import program_regions
from interpreter.vm.builtins import core_builtins


def to_ebcdic(s: str) -> bytes:
    """ASCII string -> EBCDIC bytes (cp037).

    RedDragon's COBOL VM stores character data EBCDIC-internally (matching
    real mainframe byte semantics). Any field you build in Python as a
    plain ASCII string -- a commarea, a VSAM key, a seed record field --
    must go through this before it's compared against the real program's
    own EBCDIC fields, or key/value matches silently fail.
    """
    return s.encode("cp037")


def from_ebcdic(b: bytes) -> str:
    """Inverse of ``to_ebcdic``, for reading seeded/returned bytes back
    as readable text in assertions/prints."""
    return b.decode("cp037")


def build_record(
    parser: Any,
    copybook_dirs: Sequence[Path],
    copy_member: str,
    record_name: str,
    overrides: dict[str, str],
    expected_length: int | None = None,
) -> bytes:
    """Compile a throwaway ``COPY <member>. INITIALIZE <record>. MOVE
    ... .`` COBOL program, run it, and read back ``record_name``'s raw
    bytes.

    This gets PICTURE-correct zero/space-fill for every field you don't
    override for free (COBOL's own INITIALIZE semantics), instead of
    hand-computing byte offsets per field and risking a numeric field full
    of raw spaces blowing up a later COMPUTE. Overrides are written as
    plain alphanumeric ``MOVE '<value>' TO <field>.`` statements, so this
    only handles PIC X-style overrides -- numeric overrides needing
    COMPUTE-style literal forms aren't covered (write a bespoke tiny
    program for those, same pattern).
    """
    moves = "\n".join(f"           MOVE '{v}' TO {k}." for k, v in overrides.items())
    src = f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RECINIT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY {copy_member}.
       PROCEDURE DIVISION.
           INITIALIZE {record_name}.
{moves}
           GOBACK.
"""
    from interpreter.project.cobol_compile import compile_cobol
    from interpreter.project.entry_point import EntryPoint
    from interpreter.cobol.layout_data import field_positions
    from interpreter.run import initial_vm_state, run_linked

    linked = compile_cobol(
        src.encode(), parser=parser, copybook_dirs=list(copybook_dirs), tolerant=True
    )
    entry_point = EntryPoint.function(lambda ref: ref.label == linked.entry_func_label)
    vm = run_linked(
        linked,
        entry_point,
        max_steps=500_000,
        initial_vm=initial_vm_state(),
        builtins=core_builtins(),
    )
    layout = field_positions(vm.declarations)
    fld = layout.get(record_name)
    if fld is None:
        raise KeyError(f"{record_name!r} not in layout: {sorted(layout)[:40]}")
    off, sz = fld.offset, fld.length
    for rgn in program_regions(vm):
        if rgn is not None and len(rgn) >= off + sz:
            data = bytes(rgn[off : off + sz])
            if expected_length is not None and len(data) != expected_length:
                raise AssertionError(
                    f"{record_name} length {len(data)} != expected {expected_length}"
                )
            return data
    raise RuntimeError(f"region not found for {record_name!r}")


@dataclass
class VsamFixture:
    """One region's VSAM file control: KSDS clusters in a system catalog, one per CICS file.

    ``register`` must be called for a dataset even if you want it left
    EMPTY (e.g. because the real program's own EIBRESP handling treats
    NOTFND as the clean/expected branch) -- an *unregistered* dataset
    behaves differently from a *registered-but-empty* one (DISABLED vs.
    NOTFND), and COBOL programs commonly branch on which one they get.
    """

    system: SystemCatalog
    files: dict[str, Dataset] = field(default_factory=dict)
    engine: VsamEngine = field(init=False)

    def __post_init__(self) -> None:
        self.engine = VsamEngine(self.files)

    @classmethod
    def create(cls, vsam_dir: Path) -> "VsamFixture":
        return cls(SystemCatalog(Path(vsam_dir)))

    def register(
        self,
        dataset: str,
        *,
        record_length: int,
        key_offset: int = 0,
        key_length: int = 8,
    ) -> None:
        dsn = f"TEST.{dataset}"
        self.system.create(dsn, KsdsLabel(record_length, key_offset, key_length))
        self.files.update(cics_files(self.system, {dataset: dsn}))

    def seed(self, dataset: str, records: list[bytes]) -> None:
        """Write ``records``, key-sorted, as ``dataset``'s cluster.
        ``dataset`` must already be ``register``ed."""
        if dataset not in self.files:
            raise KeyError(f"{dataset!r} not registered -- call register() first")
        cluster = self.files[dataset]
        label = cluster.label
        assert isinstance(label, KsdsLabel)
        start, end = label.key_offset, label.key_offset + label.key_length
        cluster.path.write_bytes(b"".join(sorted(records, key=lambda r: r[start:end])))

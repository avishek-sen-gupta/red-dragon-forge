"""IDCAMS command executor.

Functional dispatch over command objects produced by the IDCAMS parser.
Returns the final MAXCC (maximum condition code) after processing all commands.
"""

from __future__ import annotations

from collections.abc import Sequence

from interpreter.cobol.file_drivers import IndexedDriver, SequentialDriver
from interpreter.cobol.file_enums import OpenMode

from jackal.catalog import DatasetCatalog
from jackal.idcams.commands import Command, DefineCluster, Delete, IfMaxcc, Repro
from jackal.model import DD

_OPS = {
    "LE": lambda maxcc, value: maxcc <= value,
    "LT": lambda maxcc, value: maxcc < value,
    "GE": lambda maxcc, value: maxcc >= value,
    "GT": lambda maxcc, value: maxcc > value,
    "EQ": lambda maxcc, value: maxcc == value,
    "NE": lambda maxcc, value: maxcc != value,
}


def _handle_delete(cmd: Delete, catalog: DatasetCatalog) -> int:
    deleted = catalog.delete_dsn(cmd.dsn)
    return 0 if deleted else 8


def _handle_define_cluster(cmd: DefineCluster, catalog: DatasetCatalog) -> int:
    catalog.allocate_ksds(
        dsn=cmd.name,
        key_offset=cmd.key_offset,
        key_length=cmd.key_length,
        record_size=cmd.record_size,
    )
    return 0


def _handle_repro(
    cmd: Repro,
    dds_by_ddname: dict[str, DD],
    catalog: DatasetCatalog,
) -> int:
    infile_dd = dds_by_ddname[cmd.infile_dd]
    outfile_dd = dds_by_ddname[cmd.outfile_dd]

    in_ds = catalog.allocate(infile_dd)
    out_ds = catalog.resolve(outfile_dd.dsn)

    record_size = out_ds.record_size

    in_drv = SequentialDriver()
    in_drv.open(in_ds.path, OpenMode.INPUT, record_size, 0, 0)

    out_drv = IndexedDriver()
    out_drv.open(
        out_ds.path,
        OpenMode.OUTPUT,
        record_size,
        out_ds.key_offset,
        out_ds.key_length,
    )

    while True:
        result = in_drv.read_seq()
        if result.status == "10":
            break
        assert result.data is not None
        out_drv.write(result.data.encode("latin-1"))

    in_drv.close()
    out_drv.close()
    return 0


def _handle_if_maxcc(cmd: IfMaxcc, maxcc: int) -> int:
    predicate = _OPS[cmd.op]
    return cmd.set_value if predicate(maxcc, cmd.value) else maxcc


def run_idcams(
    commands: Sequence[Command],
    step_dds: tuple[DD, ...] | Sequence[DD],
    catalog: DatasetCatalog,
) -> int:
    """Execute a sequence of IDCAMS commands and return the final MAXCC."""
    dds_by_ddname: dict[str, DD] = {dd.ddname: dd for dd in step_dds}
    maxcc = 0

    for cmd in commands:
        if isinstance(cmd, Delete):
            maxcc = max(maxcc, _handle_delete(cmd, catalog))
        elif isinstance(cmd, DefineCluster):
            maxcc = max(maxcc, _handle_define_cluster(cmd, catalog))
        elif isinstance(cmd, Repro):
            maxcc = max(maxcc, _handle_repro(cmd, dds_by_ddname, catalog))
        elif isinstance(cmd, IfMaxcc):
            maxcc = _handle_if_maxcc(cmd, maxcc)

    return maxcc

"""IDCAMS command executor.

Functional dispatch over command objects produced by the IDCAMS parser.
Returns the final MAXCC (maximum condition code) after processing all commands.
"""

from __future__ import annotations

from collections.abc import Sequence

from interpreter.cobol.access_result import AccessCondition
from cobol_asg.file_enums import OpenMode

from jackal.catalog import DatasetCatalog, DatasetSpec
from jackal.dsn import dsn_key
from jackal.idcams.commands import (
    Command,
    DefineCluster,
    Delete,
    IfMaxcc,
    Repro,
    SetMaxcc,
)
from jackal.model import DD, DatasetOrg

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
    try:
        catalog.allocate_new(
            DatasetSpec(
                dsn=cmd.name,
                org=DatasetOrg.KSDS,
                key_offset=cmd.key_offset,
                key_length=cmd.key_length,
                record_size=cmd.record_size,
            )
        )
    except ValueError:
        return 12
    return 0


def _handle_repro(
    cmd: Repro,
    dds_by_ddname: dict[str, DD],
    catalog: DatasetCatalog,
) -> int:
    infile_dd = dds_by_ddname[cmd.infile_dd]
    outfile_dd = dds_by_ddname[cmd.outfile_dd]

    in_ds = catalog.allocate(infile_dd)
    out_ds = catalog.resolve(dsn_key(outfile_dd.dsn))

    # jackal-ifq workaround: PS input has record_size=0 (no DCB info at allocation time);
    # pass the output KSDS record_size as override. Remove when jackal-ifq is fixed.
    in_drv = catalog.open_dataset(
        in_ds.dsn, OpenMode.INPUT, record_size=out_ds.record_size
    )
    out_drv = catalog.open_dataset(out_ds.dsn, OpenMode.OUTPUT)

    while True:
        result = in_drv.read_seq()
        if result.condition is AccessCondition.END_OF_FILE:
            break
        if result.data is None:
            raise ValueError("driver returned non-EOF with no data")
        out_drv.write(result.data)

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
    """Execute a sequence of IDCAMS commands and return the final MAXCC.

    LASTCC (the rc of the immediately-preceding functional command) and
    MAXCC (the running maximum, overridable by SET) are tracked as two
    distinct counters, per the manual: only Delete/DefineCluster/Repro
    update LASTCC; IF and SET never do (SET MAXCC does not affect LASTCC).
    """
    dds_by_ddname: dict[str, DD] = {dd.ddname: dd for dd in step_dds}
    lastcc = 0
    maxcc = 0

    for cmd in commands:
        if isinstance(cmd, Delete):
            lastcc = _handle_delete(cmd, catalog)
            maxcc = max(maxcc, lastcc)
        elif isinstance(cmd, DefineCluster):
            lastcc = _handle_define_cluster(cmd, catalog)
            maxcc = max(maxcc, lastcc)
        elif isinstance(cmd, Repro):
            lastcc = _handle_repro(cmd, dds_by_ddname, catalog)
            maxcc = max(maxcc, lastcc)
        elif isinstance(cmd, IfMaxcc):
            current = lastcc if cmd.test_field == "LASTCC" else maxcc
            maxcc = _handle_if_maxcc(cmd, current)
        elif isinstance(cmd, SetMaxcc):
            maxcc = cmd.value
        else:
            raise TypeError(f"Unhandled IDCAMS command: {type(cmd).__name__}")

    return maxcc

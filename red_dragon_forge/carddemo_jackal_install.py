"""Install CardDemo's datasets into a jackal system catalog, labelled as its README declares them."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from jackal.dataset import Dataset
from jackal.labels import RecordFormat, SequentialLabel
from jackal.system_catalog import SystemCatalog

logger = logging.getLogger(__name__)

VENDORED_DATA = (
    Path(__file__).parents[1] / "vendor" / "carddemo" / "app" / "data" / "EBCDIC"
)


@dataclass(frozen=True)
class CardDemoDataset:
    dsn: str
    copybook: str
    label: SequentialLabel


@dataclass(frozen=True)
class Undeclared:
    dsn: str
    reason: str


def _fb(dsn: str, copybook: str, lrecl: int) -> CardDemoDataset:
    return CardDemoDataset(dsn, copybook, SequentialLabel(RecordFormat.FB, lrecl))


CARDDEMO_DATASETS: tuple[CardDemoDataset, ...] = (
    _fb("AWS.M2.CARDDEMO.USRSEC.PS", "CSUSR01Y", 80),
    _fb("AWS.M2.CARDDEMO.ACCTDATA.PS", "CVACT01Y", 300),
    _fb("AWS.M2.CARDDEMO.CARDDATA.PS", "CVACT02Y", 150),
    _fb("AWS.M2.CARDDEMO.CUSTDATA.PS", "CVCUS01Y", 500),
    _fb("AWS.M2.CARDDEMO.CARDXREF.PS", "CVACT03Y", 50),
    _fb("AWS.M2.CARDDEMO.DALYTRAN.PS.INIT", "CVTRA06Y", 350),
    _fb("AWS.M2.CARDDEMO.DALYTRAN.PS", "CVTRA06Y", 350),
    _fb("AWS.M2.CARDDEMO.DISCGRP.PS", "CVTRA02Y", 50),
    _fb("AWS.M2.CARDDEMO.TRANCATG.PS", "CVTRA04Y", 60),
    _fb("AWS.M2.CARDDEMO.TRANTYPE.PS", "CVTRA03Y", 60),
    _fb("AWS.M2.CARDDEMO.TCATBALF.PS", "CVTRA01Y", 50),
)

UNDECLARED: tuple[Undeclared, ...] = (
    Undeclared(
        "AWS.M2.CARDDEMO.ACCDATA.PS",
        "not in the README's table; a byte-identical copy of ACCTDATA.PS that no job reads",
    ),
    Undeclared(
        "AWS.M2.CARDDEMO.EXPORT.DATA.PS",
        "not in the README's table and no job reads it; CBEXPORT/CBIMPORT use the "
        "AWS.M2.CARDDEMO.EXPORT.DATA KSDS, which CBEXPORT defines",
    ),
)


def install(system: SystemCatalog, data_dir: Path) -> tuple[Dataset, ...]:
    return tuple(_installed(system, data_dir, dataset) for dataset in CARDDEMO_DATASETS)


def _installed(
    system: SystemCatalog, data_dir: Path, dataset: CardDemoDataset
) -> Dataset:
    logger.info("installing %s (%s)", dataset.dsn, dataset.copybook)
    return system.add(dataset.dsn, data_dir / dataset.dsn, dataset.label)


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Install CardDemo's datasets into a jackal system directory."
    )
    parser.add_argument("system", type=Path)
    parser.add_argument("--data-dir", type=Path, default=VENDORED_DATA)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    installed = install(SystemCatalog(args.system), args.data_dir)
    logger.info("installed %d datasets into %s", len(installed), args.system)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""A package's manifest: its programs, coprocessors, CSD tables and mapsets; the only thing serialised to manifest.json."""

from litter.cics_file import CicsFile
from litter.transaction import Transaction
from pydantic import BaseModel, ConfigDict


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    programs: tuple[str, ...]
    coprocessors: tuple[str, ...]
    transactions: tuple[Transaction, ...]
    files: tuple[CicsFile, ...]
    mapsets: tuple[str, ...]

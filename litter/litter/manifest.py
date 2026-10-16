"""A package's manifest: the programs linked into its image, coprocessors, CSD tables and mapsets; the only thing serialised to manifest.json."""

from litter.cics_file import CicsFile
from litter.member_name import MemberName
from litter.transaction import Transaction
from pydantic import BaseModel, ConfigDict


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    programs: tuple[MemberName, ...]
    coprocessors: tuple[str, ...]
    transactions: tuple[Transaction, ...]
    files: tuple[CicsFile, ...]
    mapsets: tuple[MemberName, ...]

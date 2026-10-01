"""BmsFile -- a corpus config file, as far as the BMS stage reads it."""

from cobble.bms_table import BmsTable
from pydantic import BaseModel, ConfigDict


class BmsFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    bms: BmsTable

"""BmsTable -- a config file's [bms] table, validated as it was written."""

from pydantic import BaseModel, ConfigDict

DEFAULT_BMS_GLOBS: tuple[str, ...] = ("*.bms",)


class BmsTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    bms_dir: str
    bms_globs: tuple[str, ...] = DEFAULT_BMS_GLOBS
    macros_dir: str
    sym_dir: str

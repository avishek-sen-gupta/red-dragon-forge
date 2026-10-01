"""CorpusTable -- a config file's [corpus] table, validated as it was written."""

from cobble.cics.synth_csd import TransidRule
from pydantic import BaseModel, ConfigDict

DEFAULT_COPYBOOK_EXTENSIONS: tuple[str, ...] = (
    "",
    "cpy",
    "CPY",
    "cob",
    "cbl",
    "copy",
    "COPY",
)


class CorpusTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    cobol_dir: str
    cobol_globs: tuple[str, ...]
    jcl_dir: str
    jcl_globs: tuple[str, ...]
    proclib_dirs: tuple[str, ...] = ()
    csd_files: tuple[str, ...] = ()
    copybook_dirs: tuple[str, ...]
    copybook_extensions: tuple[str, ...] = DEFAULT_COPYBOOK_EXTENSIONS
    asg_dir: str
    transid_rules: tuple[TransidRule, ...] = ()

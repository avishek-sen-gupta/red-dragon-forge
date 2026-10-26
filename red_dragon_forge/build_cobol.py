"""build.toml's [cobol]: where the COBOL sources and copybooks are, the extensions a source may have, and the COBOL programs lowered."""

from pathlib import Path

from litter.member_name import MemberName
from pydantic import BaseModel, ConfigDict


class BuildCobol(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_dirs: tuple[Path, ...] = ()
    source_exts: tuple[str, ...] = ()
    copybook_dirs: tuple[Path, ...] = ()
    copybook_exts: tuple[str, ...] = ()
    programs: tuple[MemberName, ...] = ()

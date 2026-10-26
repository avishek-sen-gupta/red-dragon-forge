"""build.toml's [hlasm]: where the assembler sources and macro libraries are, the extensions a source may have, and the HLASM programs lowered."""

from pathlib import Path

from litter.member_name import MemberName
from pydantic import BaseModel, ConfigDict


class BuildHlasm(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_dirs: tuple[Path, ...] = ()
    source_exts: tuple[str, ...] = ()
    maclib_dirs: tuple[Path, ...] = ()
    programs: tuple[MemberName, ...] = ()

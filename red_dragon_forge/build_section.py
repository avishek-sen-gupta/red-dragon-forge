"""build.toml's [build]: the package's name, the programs lowered, those linked into its image, and its coprocessors."""

from pathlib import Path

from litter.member_name import MemberName
from litter.package_name import PackageName
from pydantic import BaseModel, ConfigDict

from red_dragon_forge.coprocessor_name import CoprocessorName


class BuildSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: PackageName
    programs: tuple[MemberName, ...]
    link: tuple[MemberName, ...]
    coprocessors: tuple[CoprocessorName, ...] = ()
    tolerant: bool = False
    out_dir: Path

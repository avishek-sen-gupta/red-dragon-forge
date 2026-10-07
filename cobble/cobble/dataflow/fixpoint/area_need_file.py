"""The corpus-wide area need as stored on disk, so a pre-pass is paid once per corpus."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AreaNeedFile(BaseModel):
    """Per parameter position, the area-relative bounds needed on entry and read back."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry: tuple[tuple[int, tuple[int, ...]], ...] = ()
    back: tuple[tuple[int, tuple[int, ...]], ...] = ()

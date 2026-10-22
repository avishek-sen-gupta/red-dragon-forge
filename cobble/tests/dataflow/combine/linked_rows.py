"""The combine tables read back as typed rows."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class TargetRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    caller: str
    node: str
    kind: str = "program"
    transfer: str
    expression: str
    candidates: tuple[str, ...]
    reasons: tuple[str, ...]
    dropped: tuple[str, ...]
    outside: tuple[str, ...] = ()


class LinkRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    caller: str
    node: str
    transfer: str
    callee: str
    caller_extent: str
    callee_extent: str
    returns: bool
    reason: str
    discovered: bool


def target_rows(path: Path) -> list[TargetRow]:
    return [
        TargetRow.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def link_rows(path: Path) -> list[LinkRow]:
    return [
        LinkRow.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]

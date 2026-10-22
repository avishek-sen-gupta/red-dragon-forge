"""The jumps.jsonl wire form: one Jump per line, validated back into a Jump on read."""

import json

from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.jump_kind import JumpKind
from pydantic import BaseModel, ConfigDict


class _FactRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    extent: str = ""
    values: tuple[str, ...] = ()
    writers: tuple[str, ...] = ()
    reasons: tuple[UnresolvedReason, ...] = ()


class _AreaRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    param: int
    extent: str
    fields: tuple[_FactRow, ...] = ()


class _JumpRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    program: str
    node: str
    line: int
    kind: JumpKind
    returns: bool
    target: _FactRow = _FactRow()
    transid: _FactRow = _FactRow()
    areas: tuple[_AreaRow, ...] = ()


def fact_dict(fact: Fact) -> dict[str, str | list[str]]:
    return {
        "extent": fact.extent,
        "values": list(fact.values),
        "writers": list(fact.writers),
        "reasons": [reason.value for reason in fact.reasons],
    }


def _area_dict(
    area: JumpArea,
) -> dict[str, int | str | list[dict[str, str | list[str]]]]:
    return {
        "param": area.param,
        "extent": area.extent,
        "fields": [fact_dict(field) for field in area.fields],
    }


def jump_row(jump: Jump) -> str:
    return json.dumps(
        {
            "program": jump.program,
            "node": jump.node,
            "line": jump.line,
            "kind": jump.kind.value,
            "returns": jump.returns,
            "target": fact_dict(jump.target),
            "transid": fact_dict(jump.transid),
            "areas": [_area_dict(area) for area in jump.areas],
        }
    )


def _fact(row: _FactRow) -> Fact:
    return Fact(row.extent, row.values, row.writers, row.reasons)


def jump_from_row(text: str) -> Jump:
    row = _JumpRow.model_validate_json(text)
    return Jump(
        program=row.program,
        node=row.node,
        line=row.line,
        kind=row.kind,
        returns=row.returns,
        target=_fact(row.target),
        transid=_fact(row.transid),
        areas=tuple(
            JumpArea(area.param, area.extent, tuple(map(_fact, area.fields)))
            for area in row.areas
        ),
    )


def jump_identity(jump: Jump) -> str:
    return f"{jump.program}\0{jump.node}\0{jump.kind.value}"

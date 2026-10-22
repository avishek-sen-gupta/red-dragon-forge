"""A src-cfg row holding one CFG node."""

from typing import Annotated, Literal

from cobble.dataflow.srccfg.cfg import (
    NO_TARGET_OPERAND,
    Atom,
    Node,
    NodeKind,
    SourceSpan,
)
from cobble.dataflow.srccfg.rows.cfg_row_type import CfgRowType
from cobble.dataflow.srccfg.using_argument import UsingArgument
from cobol_asg.ref_mod import RefModOperand
from pydantic import BaseModel, ConfigDict, PlainSerializer, PlainValidator


def _operand_of(raw: RefModOperand | dict) -> RefModOperand:
    """A row built from a Node holds the operand itself; a row read from a line holds
    the object RefModOperand.to_dict wrote, which its own from_dict reads."""
    if isinstance(raw, RefModOperand):
        return raw
    return RefModOperand.from_dict(raw)


def _operand_dict(operand: RefModOperand) -> dict:
    return operand.to_dict()


Operand = Annotated[
    RefModOperand, PlainValidator(_operand_of), PlainSerializer(_operand_dict)
]


class CfgNodeRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[CfgRowType.NODE]
    program: str
    id: str
    kind: NodeKind
    paragraph: str
    atom: Atom
    writes: tuple[str, ...]
    reads: tuple[str, ...]
    transfer: str
    target: str
    target_resolved: bool
    target_operand: Operand
    transfer_operand: str
    file: str = ""
    file_operand: Operand = NO_TARGET_OPERAND
    using: tuple[UsingArgument, ...]
    span: SourceSpan
    resume: str
    range_end: str

    def to_node(self) -> Node:
        return Node(
            id=self.id,
            kind=self.kind,
            paragraph=self.paragraph,
            atom=self.atom,
            writes=self.writes,
            reads=self.reads,
            transfer=self.transfer,
            target=self.target,
            target_resolved=self.target_resolved,
            target_operand=self.target_operand,
            transfer_operand=self.transfer_operand,
            file=self.file,
            file_operand=self.file_operand,
            using=self.using,
            span=self.span,
            resume=self.resume,
            range_end=self.range_end,
        )

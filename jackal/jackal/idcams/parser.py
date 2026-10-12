"""IDCAMS control-language parser: text -> tuple[Command, ...]."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import TypeAlias, TypeVar

from jackal.gdg import Empty, Scratch
from jackal.idcams.commands import (
    Cancel,
    Cc,
    CcOp,
    Command,
    Condition,
    DefineCluster,
    DefineGdg,
    Delete,
    If,
    Repro,
    SetCc,
    Verify,
    VerifyDataset,
    VerifyFile,
)
from lark import Lark, Token, Transformer

_GRAMMAR = (files("jackal.idcams") / "grammar.lark").read_text()
_OPS = {
    "=": CcOp.EQ,
    "EQ": CcOp.EQ,
    "¬=": CcOp.NE,
    "NE": CcOp.NE,
    ">": CcOp.GT,
    "GT": CcOp.GT,
    "<": CcOp.LT,
    "LT": CcOp.LT,
    ">=": CcOp.GE,
    "GE": CcOp.GE,
    "<=": CcOp.LE,
    "LE": CcOp.LE,
}
_PARSER = Lark(_GRAMMAR, start="start", parser="earley")


@dataclass(frozen=True)
class _Name:
    text: str


@dataclass(frozen=True)
class _Keys:
    length: int
    offset: int


@dataclass(frozen=True)
class _RecordSize:
    average: int


@dataclass(frozen=True)
class _Limit:
    count: int


@dataclass(frozen=True)
class _Extended:
    pass


@dataclass(frozen=True)
class _Purge:
    pass


@dataclass(frozen=True)
class _Then:
    commands: tuple[Command, ...]


@dataclass(frozen=True)
class _Else:
    commands: tuple[Command, ...]


@dataclass(frozen=True)
class _Block:
    commands: tuple[Command, ...]


def _commands(item: Command | _Block) -> tuple[Command, ...]:
    match item:
        case _Block():
            return item.commands
        case _:
            return (item,)


def _branch(c: Sequence[Command | _Block]) -> tuple[Command, ...]:
    return tuple(command for item in c for command in _commands(item))


def _if(c: Sequence[_IfPart]) -> If:
    condition = Condition(_part(c, Cc), _part(c, CcOp), _part(c, int))
    otherwise = _part(c, _Else, (_Else(()),))
    return If(condition, _part(c, _Then).commands, otherwise.commands)


_IfPart: TypeAlias = Cc | CcOp | int | _Then | _Else
Part = TypeVar("Part", Cc, CcOp, int, _Then, _Else)


def _part(
    parts: Sequence[_IfPart], kind: type[Part], default: tuple[Part, ...] = ()
) -> Part:
    return next(p for p in (*parts, *default) if isinstance(p, kind))


_Param: TypeAlias = _Name | _Keys | _RecordSize | _Limit | _Extended | Empty | Scratch
P = TypeVar("P", _Name, _Keys, _RecordSize, _Limit, _Extended, Empty, Scratch)


def _found(params: Sequence[_Param], kind: type[P], default: P) -> P:
    return next((p for p in params if isinstance(p, kind)), default)


def _required(params: Sequence[_Param], kind: type[P]) -> P:
    return next(p for p in params if isinstance(p, kind))


class _Build(Transformer[Token, tuple[Command, ...]]):
    def NAME(self, t: Token) -> str:
        return str(t)

    def DSNAME(self, t: Token) -> str:
        return str(t)

    def INT(self, t: Token) -> int:
        return int(t)

    def OP(self, t: Token) -> CcOp:
        return _OPS[str(t)]

    def IF_FIELD(self, t: Token) -> Cc:
        return Cc(str(t))

    def start(self, c: Sequence[Command]) -> tuple[Command, ...]:
        return tuple(c)

    def command(self, c: Sequence[Command]) -> Command:
        return c[0]

    def purge_trailer(self, c: Sequence[str]) -> _Purge:
        return _Purge()

    def delete_cmd(self, c: Sequence[str | _Purge]) -> Delete:
        return Delete(dsn=str(c[0]), purge=any(isinstance(x, _Purge) for x in c))

    def name_param(self, c: Sequence[str]) -> _Name:
        return _Name(c[0])

    def keys_param(self, c: Sequence[int]) -> _Keys:
        return _Keys(c[0], c[1])

    def recordsize_param(self, c: Sequence[int]) -> _RecordSize:
        return _RecordSize(c[0])

    def limit_param(self, c: Sequence[int]) -> _Limit:
        return _Limit(c[0])

    def empty_param(self, c: Sequence[str]) -> Empty:
        return Empty.EMPTY

    def noempty_param(self, c: Sequence[str]) -> Empty:
        return Empty.NOEMPTY

    def scratch_param(self, c: Sequence[str]) -> Scratch:
        return Scratch.SCRATCH

    def noscratch_param(self, c: Sequence[str]) -> Scratch:
        return Scratch.NOSCRATCH

    def extended_param(self, c: Sequence[str]) -> _Extended:
        return _Extended()

    def define_cmd(self, c: Sequence[_Param]) -> DefineCluster:
        keys = _required(c, _Keys)
        return DefineCluster(
            name=_required(c, _Name).text,
            key_length=keys.length,
            key_offset=keys.offset,
            record_size=_required(c, _RecordSize).average,
        )

    def define_gdg(self, c: Sequence[_Param]) -> DefineGdg:
        return DefineGdg(
            name=_required(c, _Name).text,
            limit=_required(c, _Limit).count,
            empty=_found(c, Empty, Empty.NOEMPTY),
            scratch=_found(c, Scratch, Scratch.NOSCRATCH),
            extended=any(isinstance(p, _Extended) for p in c),
        )

    def repro_cmd(self, c: Sequence[str]) -> Repro:
        return Repro(infile_dd=c[0], outfile_dd=c[1])

    def if_matched(self, c: Sequence[_IfPart]) -> If:
        return _if(c)

    def if_open(self, c: Sequence[_IfPart]) -> If:
        return _if(c)

    def then_closed(self, c: Sequence[Command | _Block]) -> _Then:
        return _Then(_branch(c))

    def then_any(self, c: Sequence[Command | _Block]) -> _Then:
        return _Then(_branch(c))

    def else_closed(self, c: Sequence[Command | _Block]) -> _Else:
        return _Else(_branch(c))

    def else_open(self, c: Sequence[Command | _Block]) -> _Else:
        return _Else(_branch(c))

    def do_block(self, c: Sequence[Command]) -> _Block:
        return _Block(tuple(c))

    def set_cmd(self, c: Sequence[_IfPart]) -> SetCc:
        return SetCc(_part(c, Cc), _part(c, int))

    def cancel_cmd(self, c: Sequence[str]) -> Cancel:
        return Cancel()

    def verify_file(self, c: Sequence[str]) -> VerifyFile:
        return VerifyFile(c[0])

    def verify_dataset(self, c: Sequence[str]) -> VerifyDataset:
        return VerifyDataset(c[0])

    def verify_cmd(self, c: Sequence[VerifyFile | VerifyDataset]) -> Verify:
        return Verify(c[0])


def parse_idcams(text: str) -> tuple[Command, ...]:
    src = text if text.endswith("\n") else text + "\n"
    return _Build().transform(_PARSER.parse(src))

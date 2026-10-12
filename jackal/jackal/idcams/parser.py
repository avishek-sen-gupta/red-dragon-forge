"""IDCAMS control-language parser: text -> tuple[Command, ...]."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import TypeAlias, TypeVar

from jackal.gdg import Empty, Scratch
from jackal.idcams.commands import (
    Command,
    DefineCluster,
    DefineGdg,
    Delete,
    IfMaxcc,
    Repro,
    SetMaxcc,
)
from lark import Lark, Token, Transformer

_GRAMMAR = (files("jackal.idcams") / "grammar.lark").read_text()
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

    def OP(self, t: Token) -> str:
        text = str(t)
        return "EQ" if text == "=" else text

    def IF_FIELD(self, t: Token) -> str:
        return str(t)

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

    def if_cmd(self, c: Sequence[str | int]) -> IfMaxcc:
        test_field, op, value, set_value = c
        return IfMaxcc(
            op=str(op),
            value=int(value),
            set_value=int(set_value),
            test_field=str(test_field),
        )

    def set_cmd(self, c: Sequence[int]) -> SetMaxcc:
        return SetMaxcc(value=c[0])


def parse_idcams(text: str) -> tuple[Command, ...]:
    src = text if text.endswith("\n") else text + "\n"
    return _Build().transform(_PARSER.parse(src))

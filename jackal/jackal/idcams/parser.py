"""IDCAMS control-language parser over ams.lark: text -> the commands jackal runs (record 2026-10-12, one grammar)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import TypeAlias, TypeVar

from catnip.gdg import Empty, GdgOrder, Scratch
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
    NotExecuted,
    Repro,
    SetCc,
    Verb,
    Verify,
    VerifyDataset,
    VerifyFile,
)
from lark import Lark, Token, Transformer, Tree

logger = logging.getLogger(__name__)

_PARSER = Lark(
    (files("jackal.idcams") / "grammar" / "ams.lark").read_text(),
    start="start",
    parser="earley",
)
_CONTINUATION = "+"
_DEFAULT_KEYS = (64, 0)
_DEFAULT_RECORD_SIZE = 4089

_DROPPED = frozenset(
    {
        "account_param",
        "bufferspace_param",
        "bwo_param",
        "catalog_param",
        "cisz_param",
        "cylinders_alloc",
        "dataclass_param",
        "deletable_entry_type",
        "delete_norecovery_flag",
        "eattr_param",
        "erase_flag",
        "exceptionexit_param",
        "for_retention",
        "force_flag",
        "freespace_param",
        "frlog_param",
        "keylabel_param",
        "kilobytes_alloc",
        "log_param",
        "logreplicate_flag",
        "logstreamid_param",
        "managementclass_param",
        "megabytes_alloc",
        "messagelevel_param",
        "nodisconnect_flag",
        "noerase_flag",
        "noextended_flag",
        "noforce_flag",
        "nologreplicate_flag",
        "nomask_flag",
        "nonspanned_flag",
        "nopurge_flag",
        "noreuse_flag",
        "nowritecheck_flag",
        "obsolete_ignored",
        "owner_param",
        "records_alloc",
        "recovery_flag",
        "reuse_flag",
        "rlsenable_flag",
        "rlsquiesce_flag",
        "shareoptions_param",
        "speed_flag",
        "storageclass_param",
        "to_retention",
        "tracks_alloc",
        "verify_recover_flag",
        "volumes_param",
        "writecheck_flag",
    }
)


def _text(token: Token) -> str:
    return "".join(piece.strip() for piece in str(token).split(_CONTINUATION))


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
class _Indexed:
    pass


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
class _Entries:
    names: tuple[str, ...]


@dataclass(frozen=True)
class _InFile:
    ddname: str


@dataclass(frozen=True)
class _OutFile:
    ddname: str


@dataclass(frozen=True)
class _File:
    ddname: str


@dataclass(frozen=True)
class _Dataset:
    name: str


@dataclass(frozen=True)
class _DataParams:
    params: tuple[_Param, ...]


_Param: TypeAlias = (
    _Name
    | _Keys
    | _RecordSize
    | _Indexed
    | _Limit
    | _Extended
    | _Purge
    | _Entries
    | _InFile
    | _OutFile
    | _File
    | _Dataset
    | _DataParams
    | Tree[Token]
    | Empty
    | Scratch
    | GdgOrder
)
P = TypeVar(
    "P",
    _Name,
    _Keys,
    _RecordSize,
    _Limit,
    _Entries,
    _InFile,
    _OutFile,
    _File,
    _Dataset,
    Empty,
    Scratch,
    GdgOrder,
)


def _found(params: Sequence[_Param], kind: type[P], default: P) -> P:
    return next((p for p in params if isinstance(p, kind)), default)


def _required(params: Sequence[_Param], kind: type[P]) -> P:
    return next(p for p in params if isinstance(p, kind))


def _has(params: Sequence[_Param], kind: type[_Param]) -> bool:
    return any(isinstance(p, kind) for p in params)


def _members(param: _Param) -> tuple[_Param, ...]:
    match param:
        case _DataParams():
            return param.params
        case _:
            return (param,)


def _rule(param: _Param) -> tuple[str, ...]:
    match param:
        case Tree():
            return (str(param.data),)
        case _:
            return ()


def _unmodelled(params: Sequence[_Param]) -> tuple[str, ...]:
    return tuple(
        rule
        for q in params
        for p in _members(q)
        for rule in _rule(p)
        if rule not in _DROPPED
    )


def _not_executed(verb: Verb, reasons: tuple[str, ...]) -> NotExecuted:
    logger.warning(
        "IDCAMS %s is not executed: %s", verb.value, ", ".join(reasons) or verb.value
    )
    return NotExecuted(verb)


def _checked(
    verb: Verb, params: Sequence[_Param], extra: tuple[str, ...] = ()
) -> tuple[str, ...]:
    return (*_unmodelled(params), *extra)


def _component(params: Sequence[_Param], kind: type[P], default: P) -> P:
    data = next((p.params for p in params if isinstance(p, _DataParams)), ())
    return _found(params, kind, _found(data, kind, default))


def _cluster(params: Sequence[_Param]) -> DefineCluster:
    keys = _component(params, _Keys, _Keys(*_DEFAULT_KEYS))
    size = _component(params, _RecordSize, _RecordSize(_DEFAULT_RECORD_SIZE))
    return DefineCluster(
        name=_required(params, _Name).text,
        key_length=keys.length,
        key_offset=keys.offset,
        record_size=size.average,
    )


def _deleted(params: Sequence[_Param]) -> Delete:
    return Delete(_required(params, _Entries).names, purge=_has(params, _Purge))


def _uncatalogs_only(params: Sequence[_Param]) -> tuple[str, ...]:
    return ("NOSCRATCH",) if Scratch.NOSCRATCH in params else ()


def _gdg(params: Sequence[_Param]) -> DefineGdg:
    return DefineGdg(
        name=_required(params, _Name).text,
        limit=_required(params, _Limit).count,
        empty=_found(params, Empty, Empty.NOEMPTY),
        scratch=_found(params, Scratch, Scratch.NOSCRATCH),
        order=_found(params, GdgOrder, GdgOrder.LIFO),
        extended=_has(params, _Extended),
    )


def _verify_target(params: Sequence[_Param]) -> VerifyFile | VerifyDataset:
    if _has(params, _File):
        return VerifyFile(_required(params, _File).ddname)
    return VerifyDataset(_required(params, _Dataset).name)


def _copied(params: Sequence[_Param]) -> Repro | NotExecuted:
    if not (_has(params, _InFile) and _has(params, _OutFile)):
        return _not_executed(Verb.REPRO, ("INDATASET or OUTDATASET",))
    return Repro(_required(params, _InFile).ddname, _required(params, _OutFile).ddname)


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


_IfPart: TypeAlias = Cc | CcOp | Token | _Then | _Else
Part = TypeVar("Part", Cc, CcOp, _Then, _Else)


def _part(
    parts: Sequence[_IfPart], kind: type[Part], default: tuple[Part, ...] = ()
) -> Part:
    return next(p for p in (*parts, *default) if isinstance(p, kind))


def _number(parts: Sequence[_IfPart | Cc]) -> int:
    return next(int(p) for p in parts if isinstance(p, Token))


def _if(c: Sequence[_IfPart]) -> If:
    condition = Condition(_part(c, Cc), _part(c, CcOp), _number(c))
    otherwise = _part(c, _Else, (_Else(()),))
    return If(condition, _part(c, _Then).commands, otherwise.commands)


class _Build(Transformer[Token, tuple[Command, ...]]):
    def start(self, c: Sequence[Command]) -> tuple[Command, ...]:
        return tuple(c)

    def command(self, c: Sequence[Command]) -> Command:
        return c[0]

    def name_param(self, c: Sequence[Token]) -> _Name:
        return _Name(_text(c[0]))

    def keys_param(self, c: Sequence[Token]) -> _Keys:
        return _Keys(int(c[0]), int(c[1]))

    def recordsize_param(self, c: Sequence[Token]) -> _RecordSize:
        return _RecordSize(int(c[0]))

    def indexed_flag(self, c: Sequence[Token]) -> _Indexed:
        return _Indexed()

    def limit_param(self, c: Sequence[Token]) -> _Limit:
        return _Limit(int(c[0]))

    def empty_flag(self, c: Sequence[Token]) -> Empty:
        return Empty.EMPTY

    def noempty_flag(self, c: Sequence[Token]) -> Empty:
        return Empty.NOEMPTY

    def scratch_flag(self, c: Sequence[Token]) -> Scratch:
        return Scratch.SCRATCH

    def noscratch_flag(self, c: Sequence[Token]) -> Scratch:
        return Scratch.NOSCRATCH

    def gdgorder_param(self, c: Sequence[Token]) -> GdgOrder:
        return GdgOrder(str(c[0]))

    def extended_flag(self, c: Sequence[Token]) -> _Extended:
        return _Extended()

    def purge_flag(self, c: Sequence[Token]) -> _Purge:
        return _Purge()

    def delete_entries(self, c: Sequence[Token]) -> _Entries:
        return _Entries(tuple(map(_text, c)))

    def infile_param(self, c: Sequence[Token]) -> _InFile:
        return _InFile(_text(c[0]))

    def outfile_param(self, c: Sequence[Token]) -> _OutFile:
        return _OutFile(_text(c[0]))

    def file_param(self, c: Sequence[Token]) -> _File:
        return _File(_text(c[0]))

    def verify_dataset_param(self, c: Sequence[Token]) -> _Dataset:
        return _Dataset(_text(c[0]))

    def data_clause(self, c: Sequence[_Param]) -> _DataParams:
        return _DataParams(tuple(c))

    def index_clause(self, c: Sequence[_Param]) -> _DataParams:
        return _DataParams(tuple(p for p in c if isinstance(p, Tree)))

    def define_cluster(self, c: Sequence[_Param]) -> DefineCluster | NotExecuted:
        reasons = _checked(Verb.DEFINE_CLUSTER, c)
        if reasons:
            return _not_executed(Verb.DEFINE_CLUSTER, reasons)
        return _cluster(c)

    def define_gdg(self, c: Sequence[_Param]) -> DefineGdg | NotExecuted:
        reasons = _checked(Verb.DEFINE_GDG, c)
        if reasons:
            return _not_executed(Verb.DEFINE_GDG, reasons)
        return _gdg(c)

    def delete(self, c: Sequence[_Param]) -> Delete | NotExecuted:
        reasons = _checked(Verb.DELETE, c, _uncatalogs_only(c))
        if reasons:
            return _not_executed(Verb.DELETE, reasons)
        return _deleted(c)

    def repro(self, c: Sequence[_Param]) -> Repro | NotExecuted:
        reasons = _checked(Verb.REPRO, c)
        if reasons:
            return _not_executed(Verb.REPRO, reasons)
        return _copied(c)

    def verify(self, c: Sequence[_Param]) -> Verify | NotExecuted:
        reasons = _checked(Verb.VERIFY, c)
        if reasons:
            return _not_executed(Verb.VERIFY, reasons)
        return Verify(_verify_target(c))

    def define_alternateindex(self, c: Sequence[_Param]) -> NotExecuted:
        return _not_executed(Verb.DEFINE_ALTERNATEINDEX, ())

    def define_nonvsam(self, c: Sequence[_Param]) -> NotExecuted:
        return _not_executed(Verb.DEFINE_NONVSAM, ())

    def define_path(self, c: Sequence[_Param]) -> NotExecuted:
        return _not_executed(Verb.DEFINE_PATH, ())

    def alter(self, c: Sequence[_Param]) -> NotExecuted:
        return _not_executed(Verb.ALTER, ())

    def print(self, c: Sequence[_Param]) -> NotExecuted:
        return _not_executed(Verb.PRINT, ())

    def listcat(self, c: Sequence[_Param]) -> NotExecuted:
        return _not_executed(Verb.LISTCAT, ())

    def export(self, c: Sequence[_Param]) -> NotExecuted:
        return _not_executed(Verb.EXPORT, ())

    def import_cmd(self, c: Sequence[_Param]) -> NotExecuted:
        return _not_executed(Verb.IMPORT, ())

    def bldindex(self, c: Sequence[_Param]) -> NotExecuted:
        return _not_executed(Verb.BLDINDEX, ())

    def maxcc_field(self, c: Sequence[Token]) -> Cc:
        return Cc.MAXCC

    def lastcc_field(self, c: Sequence[Token]) -> Cc:
        return Cc.LASTCC

    def op_eq(self, c: Sequence[Token]) -> CcOp:
        return CcOp.EQ

    def op_ne(self, c: Sequence[Token]) -> CcOp:
        return CcOp.NE

    def op_gt(self, c: Sequence[Token]) -> CcOp:
        return CcOp.GT

    def op_lt(self, c: Sequence[Token]) -> CcOp:
        return CcOp.LT

    def op_ge(self, c: Sequence[Token]) -> CcOp:
        return CcOp.GE

    def op_le(self, c: Sequence[Token]) -> CcOp:
        return CcOp.LE

    def set_command(self, c: Sequence[_IfPart]) -> SetCc:
        return SetCc(_part(c, Cc), _number(c))

    def cancel_command(self, c: Sequence[Token]) -> Cancel:
        return Cancel()

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


def parse_idcams(text: str) -> tuple[Command, ...]:
    return _Build().transform(_PARSER.parse(text))

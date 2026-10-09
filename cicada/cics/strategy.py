"""CicsLoweringStrategy — implements RedDragonExtensionLoweringStrategy
directly (interpreter.cobol.red_dragon_extension_strategy)."""

from __future__ import annotations

import logging
from collections.abc import (
    Callable,
    Mapping,
    MutableMapping,
    MutableSequence,
    Sequence,
)
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias, TypeGuard, TypeVar, cast

from cics.builtins.system import (
    ASSIGN_SUBOPTIONS,
    DEFAULT_USERID,
    make_abend_builtin,
    make_abend_unhandled_builtin,
    make_abend_unsupported_builtin,
    make_asktime_builtin,
    make_assign_builtin,
    make_bif_deedit_builtin,
    make_formattime_builtin,
    make_handle_abend_builtin,
    make_handle_noop_builtin,
    make_init_eib_builtin,
    make_inquire_builtin,
    make_runtime_noop_builtin,
    make_writeq_td_builtin,
)
from cics.cell import Cell, Holder
from cics.conditions import RAISABLE, code_for
from cics.handler_labels import (
    HandlerLabels,
    collect_handler_labels,
    paragraph_names,
)
from cics.interval import StartQueue
from cics.statements import CicsOperand, ExecCicsStatement
from cics.strategy_stores import drain, note_unsupported, register, register_default
from cics.terminal import InputChannel, ScreenChannel
from cics.types import DEFAULT_TERMID
from cics.vsam.browse import BrowseStart
from cics.vsam.engine import VsamEngine
from cobol_asg.cobol_expression import BinOpNode, FieldRefNode, LiteralNode
from cobol_asg.ref_mod import (
    RefModBinOp,
    RefModLengthOf,
    RefModLiteral,
    RefModReference,
)
from interpreter.cobol.cobol_constants import BuiltinName
from interpreter.func_name import FuncName
from interpreter.instructions import (
    Binop,
    Branch,
    BranchIf,
    CallFunction,
    Const,
    Label_,
    LoadRegion,
    Return_,
    Suspend,
)
from interpreter.ir import CodeLabel
from interpreter.operator_kind import resolve_binop
from interpreter.register import NO_REGISTER, Register
from interpreter.types.type_expr import UNKNOWN

if TYPE_CHECKING:
    from cics.types import CicsContext, DispatchResult
    from cobol_asg.cobol_statements import CobolStatementType
    from cobol_asg.ref_mod import RefModExpr
    from interpreter.cobol.emit_context import EmitContext
    from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout
    from interpreter.project.types import LinkedProgram

logger = logging.getLogger(__name__)

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")

_BUILTIN_INIT_EIB = FuncName("__cics_init_eib")


class Absent(Protocol):
    """A value that is always falsy: ``None`` from a caller or parser that
    predates the fp gate, or ``NOT_SUPPLIED``. Code here never tests for it; it
    tests for the real type with ``isinstance``."""

    def __bool__(self) -> Literal[False]: ...


@dataclass(frozen=True)
class NotSupplied:
    def __bool__(self) -> Literal[False]:
        return False


NOT_SUPPLIED = NotSupplied()

Operand: TypeAlias = "CicsOperand | Absent"
Options: TypeAlias = "Mapping[str, Operand]"

_SYS_VERBS: Mapping[str, str] = MappingProxyType(
    {
        "ASSIGN": "__cics_assign",
        "ASKTIME": "__cics_asktime",
        "FORMATTIME": "__cics_formattime",
        "INQUIRE": "__cics_inquire",
        "HANDLE ABEND": "__cics_handle_abend",
        # HANDLE AID is still an explicit no-op — AID dispatch is out of scope for
        # the condition-handling work.
        "HANDLE AID": "__cics_handle_aid",
        # Nothing to release: this runtime emulates one task at a time, so a VSAM
        # record lock has no other task to exclude. A real no-op, not a gap --
        # see cicada-lkx.3.
        "UNLOCK": "__cics_unlock",
    }
)

# SYNCPOINT and SYNCPOINT ROLLBACK are distinct verb strings (see
# cics_visitor.py's Syncpoint/SyncpointRollback mapping) with their own
# dedicated lowerers (_lower_syncpoint / _lower_syncpoint_rollback) rather
# than a _SYS_VERBS entry: the VSAM engine writes through at the point of
# WRITE/REWRITE/DELETE, so neither has anything to do for VSAM, but a
# composed SQL runtime (squall) has a real pending unit of work — SYNCPOINT
# commits it, SYNCPOINT ROLLBACK undoes it. Both reach squall through the
# same name-convention hooks __cics_task_end_hook already uses.

# Verbs whose builtin returns a CICS response code to be written into EIBRESP
# (always) and the RESP(name) option's field (when present).
_RESP_PRODUCING_VERBS = frozenset({"INQUIRE"})

_VSAM_POINT_VERBS = frozenset({"READ", "WRITE", "REWRITE", "DELETE"})

# Implicit single cursor per file.
_VSAM_BROWSE_VERBS = frozenset({"STARTBR", "READNEXT", "READPREV", "ENDBR"})

_BMS_VERBS: Mapping[str, str] = MappingProxyType(
    {
        "SEND MAP": "__cics_send_map",
        "RECEIVE MAP": "__cics_receive_map",
        "SEND TEXT": "__cics_send_text",
    }
)

_SEND_MAP_OPTIONS = (
    "ERASE",
    "MAPONLY",
    "DATAONLY",
    "ALARM",
    "FRSET",
    "FREEKB",
    "CURSOR",
)

_REF_MOD_KINDS = (RefModLiteral, RefModReference, RefModLengthOf, RefModBinOp)

# STRING_SLICE length when a reference modification omits LENGTH.
_REST_OF_FIELD = 999999


def _is_present(opts: Options, key: str) -> bool:
    return isinstance(opts.get(key), CicsOperand)


def _operand_text(operand: Operand, default: str) -> str:
    return operand.text if isinstance(operand, CicsOperand) else default


def _names_field(
    operand: Operand, ctx: EmitContext, materialised: MaterialisedSectionedLayout
) -> TypeGuard[CicsOperand]:
    """A bare data-name that resolves to a field. A quoted literal never consults
    ``has_field``, so MAP('SGNMAP') cannot decode a same-named WS group."""
    return (
        isinstance(operand, CicsOperand)
        and not operand.is_literal
        and ctx.has_field(operand.text, materialised)
    )


def _emit_string(ctx: EmitContext, text: str) -> Register:
    reg = ctx.fresh_reg()
    ctx.emit_inst(Const.string(reg, text))
    return reg


def _emit_int(ctx: EmitContext, value: int) -> Register:
    reg = ctx.fresh_reg()
    ctx.emit_inst(Const.int_(reg, value))
    return reg


def _emit_empty_bytes(ctx: EmitContext) -> Register:
    reg = ctx.fresh_reg()
    ctx.emit_inst(Const(result_reg=reg, value=b"", type_expr=UNKNOWN))
    return reg


def _emit_binop(
    ctx: EmitContext, operator: str, left: Register, right: Register
) -> Register:
    result = ctx.fresh_reg()
    ctx.emit_inst(
        Binop(
            result_reg=result,
            operator=resolve_binop(operator),
            left=Register(str(left)),
            right=Register(str(right)),
        )
    )
    return result


def _emit_call(ctx: EmitContext, builtin: str, *args: Register) -> Register:
    result = ctx.fresh_reg()
    ctx.emit_inst(
        CallFunction(result_reg=result, func_name=FuncName(builtin), args=args)
    )
    return result


@dataclass(frozen=True)
class _ByteWindow:
    offset_reg: Register
    length: int


def _emit_ref_mod_offset(
    ctx: EmitContext,
    start: RefModExpr,
    offset_reg: Register,
    materialised: MaterialisedSectionedLayout,
) -> Register:
    from interpreter.cobol.lower_arithmetic import eval_ref_mod_expr

    start_1based = eval_ref_mod_expr(ctx, start, materialised)
    delta_reg = _emit_binop(ctx, "-", start_1based, ctx.const_to_reg(1))
    return _emit_binop(ctx, "+", offset_reg, delta_reg)


def _ref_mod_length(operand: CicsOperand, whole_length: int) -> int:
    """A literal LENGTH is honoured exactly; an omitted one reads to the end of the
    field. A data-name LENGTH cannot size a static LoadRegion, and silently reading
    the full field would read more bytes than asked and can clobber adjacent
    fields, so that case is loud (rare; CardDemo CICS ref-mod uses literals)."""
    length = operand.ref_mod_length
    if isinstance(length, RefModLiteral):
        return int(length.value)
    if isinstance(length, _REF_MOD_KINDS):
        raise NotImplementedError(
            f"CICS ref-mod with a data-name LENGTH in copy_in is not supported "
            f"(LoadRegion needs a compile-time int length): {operand.text!r}; "
            f"see red-dragon-6ddr"
        )
    return whole_length


def _copy_in_window(
    ctx: EmitContext,
    operand: CicsOperand,
    whole: _ByteWindow,
    materialised: MaterialisedSectionedLayout,
) -> _ByteWindow:
    """Reference modification (e.g. WS-FIELD(2:1)) reads a byte-slice: the offset
    advances by start-1 at runtime, since start may be a data-name."""
    start = operand.ref_mod_start
    if not isinstance(start, _REF_MOD_KINDS):
        return whole
    offset_reg = _emit_ref_mod_offset(ctx, start, whole.offset_reg, materialised)
    return _ByteWindow(offset_reg, _ref_mod_length(operand, whole.length))


def _emit_load_field(
    ctx: EmitContext, operand: CicsOperand, materialised: MaterialisedSectionedLayout
) -> Register:
    ref, region_reg = ctx.resolve_field_ref(
        operand.text, materialised, subscripts=operand.subscripts
    )
    whole = _ByteWindow(ref.offset_reg, ref.fl.byte_length)
    window = _copy_in_window(ctx, operand, whole, materialised)
    out = ctx.fresh_reg()
    ctx.emit_inst(
        LoadRegion(
            result_reg=out,
            region_reg=region_reg,
            offset_reg=window.offset_reg,
            length=window.length,
        )
    )
    return out


def emit_copy_in(
    ctx: EmitContext, operand: Operand, materialised: MaterialisedSectionedLayout
) -> Register:
    """If ``operand`` is a data item, LoadRegion its bytes into a fresh register and return it.

    Returns ``NO_REGISTER`` when ``operand`` is absent or a literal/unresolved name
    (caller falls back to Const).
    """
    if _names_field(operand, ctx, materialised):
        return _emit_load_field(ctx, operand, materialised)
    return NO_REGISTER


def _bytes_or_empty(ctx: EmitContext, copied: Register) -> Register:
    return copied if copied.is_present() else _emit_empty_bytes(ctx)


def _copy_in_or_empty(
    ctx: EmitContext, operand: Operand, materialised: MaterialisedSectionedLayout
) -> Register:
    return _bytes_or_empty(ctx, emit_copy_in(ctx, operand, materialised))


def _emit_slice_length(
    ctx: EmitContext, operand: CicsOperand, materialised: MaterialisedSectionedLayout
) -> Register:
    from interpreter.cobol.lower_arithmetic import eval_ref_mod_expr

    length = operand.ref_mod_length
    if isinstance(length, _REF_MOD_KINDS):
        return eval_ref_mod_expr(ctx, length, materialised)
    return ctx.const_to_reg(_REST_OF_FIELD)


def _emit_ref_mod_slice(
    ctx: EmitContext,
    operand: CicsOperand,
    start: RefModExpr,
    value_reg: Register,
    materialised: MaterialisedSectionedLayout,
) -> Register:
    """Slice ``value_reg`` per ``operand``'s reference modification (start:length).

    Mirrors the COBOL RefModNode lowering (condition_lowering.lower_expr_node):
    convert the 1-based start to 0-based (``start - 1``), then
    ``STRING_SLICE(value, start0, length)``. Reuses ``eval_ref_mod_expr`` for the
    start/length expressions so the COBOL machinery is the single source of truth.
    """
    from interpreter.cobol.lower_arithmetic import eval_ref_mod_expr

    start_1based = eval_ref_mod_expr(ctx, start, materialised)
    start_0based = _emit_binop(ctx, "-", start_1based, ctx.const_to_reg(1))
    length_reg = _emit_slice_length(ctx, operand, materialised)
    sliced = ctx.fresh_reg()
    ctx.emit_inst(
        CallFunction(
            result_reg=sliced,
            func_name=FuncName(BuiltinName.STRING_SLICE),
            args=(
                Register(str(value_reg)),
                Register(str(start_0based)),
                Register(str(length_reg)),
            ),
        )
    )
    return sliced


def _emit_field_value(
    ctx: EmitContext, operand: CicsOperand, materialised: MaterialisedSectionedLayout
) -> Register:
    ref, region_reg = ctx.resolve_field_ref(
        operand.text, materialised, subscripts=operand.subscripts
    )
    # ref.offset_reg includes the element offset of a subscripted operand
    # (e.g. TBL(IDX)), so the decode reads the indexed element, not element 1.
    value_reg = ctx.emit_decode_field(
        region_reg, ref.fl, ref.offset_reg, extent=ref.extent
    )
    start = operand.ref_mod_start
    if isinstance(start, _REF_MOD_KINDS):
        return _emit_ref_mod_slice(ctx, operand, start, value_reg, materialised)
    return value_reg


def emit_operand_value(
    ctx: EmitContext, operand: Operand, materialised: MaterialisedSectionedLayout
) -> Register:
    """Resolve a CICS operand to a register holding its runtime VALUE.

    A bare data-name that resolves to a field is decoded (and byte-sliced by any
    reference modification); a quoted literal, an unresolved bare name or numeric
    emits a Const of its text; an absent operand emits an empty Const.
    """
    if _names_field(operand, ctx, materialised):
        return _emit_field_value(ctx, operand, materialised)
    return _emit_string(ctx, _operand_text(operand, ""))


def _write_back_names(target: Operand | str) -> tuple[str, ...]:
    if isinstance(target, str):
        return (target,)
    data_name = isinstance(target, CicsOperand) and not target.is_literal
    return (_operand_text(target, ""),) if data_name else ()


def emit_copy_back_str(
    ctx: EmitContext,
    target: Operand | str,
    value_str_reg: Register,
    materialised: MaterialisedSectionedLayout,
) -> None:
    """Encode a string-valued result into the named field, if it is a data item.

    ``target`` may be a bare field name (str — for internally-known fields like
    EIBRESP) or a parsed ``CicsOperand``. A write-back target must be a data-name,
    so a quoted literal operand is a no-op (along with an absent one and unknown
    names). Write-back targets are plain data-names (RESP/APPLID/...), never
    subscripted, so no subscripts are threaded.
    """
    fields = [n for n in _write_back_names(target) if ctx.has_field(n, materialised)]
    if not fields:
        return
    ref, region_reg = ctx.resolve_field_ref(fields[0], materialised)
    ctx.emit_encode_and_write(
        region_reg, ref.fl, value_str_reg, ref.offset_reg, extent=ref.extent
    )


def condition_slot(verb: str, condition: str) -> int:
    """The DFH table subscript for a condition: DFHRESP code + 1, because COBOL
    OCCURS is 1-based.

    A name absent from CONDITION_CODES is a gap in this runtime's table rather
    than a fault in the program being compiled, so the bare KeyError is re-raised
    naming the statement it came from and how to close the gap. CICS defines many
    more conditions than the twenty here (QIDERR, DSIDERR, NOTAUTH, TERMERR,
    SYSIDERR...), so this is a path real corpus code will reach.
    """
    try:
        return code_for(condition) + 1
    except KeyError as exc:
        raise NotImplementedError(
            f"EXEC CICS {verb} names condition {condition!r}, which has no DFHRESP"
            " code in cics.conditions.CONDITION_CODES. Add it there with its code"
            " and regenerate cics/copybooks/DFHHANDLE.cpy; add it to RAISABLE only"
            " if this runtime actually raises it."
        ) from exc


def emit_indexed_write(
    ctx: EmitContext,
    name: str,
    index: int,
    value_str_reg: Register,
    materialised: MaterialisedSectionedLayout,
) -> None:
    """Write into a fixed element of a table. emit_copy_back_str deliberately
    does not thread subscripts, so the handler table needs its own path."""
    if not ctx.has_field(name, materialised):
        return
    ref, region_reg = ctx.resolve_field_ref(
        name, materialised, subscripts=(LiteralNode(str(index)),)
    )
    ctx.emit_encode_and_write(
        region_reg, ref.fl, value_str_reg, ref.offset_reg, extent=ref.extent
    )


def emit_resp_writeback(
    ctx: EmitContext,
    r_resp_result: Register,
    opts: Options,
    materialised: MaterialisedSectionedLayout,
) -> None:
    """Write a builtin's returned resp code into EIBRESP (always) and RESP(name) if present.

    ``r_resp_result`` is the numeric register returned by the service builtin.
    It is stringified, then encoded per each target field's layout — EIBRESP is
    ``PIC S9(8) COMP`` (binary), so the numeric string is packed correctly by
    ``emit_encode_and_write`` (same path as the GIVING clause in lower_call.py).
    """
    str_reg = ctx.emit_to_string(r_resp_result)
    emit_copy_back_str(ctx, "EIBRESP", str_reg, materialised)
    emit_copy_back_str(ctx, opts.get("RESP"), str_reg, materialised)


_CONDITION_TABLE_FIELDS = ("DFH-HANDLER", "DFH-RAISABLE", "EIBRESP")


def has_condition_tables(
    ctx: EmitContext, materialised: MaterialisedSectionedLayout
) -> bool:
    """Whether this module carries the state both halves of condition handling
    need — the dispatcher and every raise tail must agree, or a tail branches to
    a label no dispatcher defined."""
    return all(ctx.has_field(name, materialised) for name in _CONDITION_TABLE_FIELDS)


def _eibresp_subscript() -> tuple[BinOpNode, ...]:
    return (BinOpNode("+", FieldRefNode("EIBRESP"), LiteralNode("1")),)


def _emit_raisable_test(
    ctx: EmitContext, materialised: MaterialisedSectionedLayout
) -> Register:
    ref, region_reg = ctx.resolve_field_ref(
        "DFH-RAISABLE", materialised, subscripts=_eibresp_subscript()
    )
    flag_reg = ctx.emit_decode_field(
        region_reg, ref.fl, ref.offset_reg, extent=ref.extent
    )
    return _emit_binop(ctx, "==", flag_reg, ctx.const_to_reg("Y"))


def emit_raise_tail(
    ctx: EmitContext,
    opts: Options,
    materialised: MaterialisedSectionedLayout,
) -> None:
    """Branch to the dispatcher when the command raised a condition this runtime
    handles. RESP and NOHANDLE are the program's undertaking to check inline, so
    a command coding either does not raise (CICS)."""
    if "RESP" in opts or "NOHANDLE" in opts:
        return
    if not has_condition_tables(ctx, materialised):
        return
    cmp_reg = _emit_raisable_test(ctx, materialised)
    cont_lbl = ctx.fresh_label("cond_continue")
    ctx.emit_inst(
        BranchIf(
            cond_reg=cmp_reg,
            branch_targets=(CodeLabel("__cics_cond_dispatch"), cont_lbl),
        )
    )
    ctx.emit_inst(Label_(label=cont_lbl))


def _emit_resp_and_raise(
    ctx: EmitContext,
    r_res: Register,
    opts: Options,
    materialised: MaterialisedSectionedLayout,
) -> None:
    emit_resp_writeback(ctx, r_res, opts, materialised)
    emit_raise_tail(ctx, opts, materialised)


_LENGTH_OF = "LENGTH OF "


def _length_of_field(
    fname: str,
    fallback: int,
    ctx: EmitContext,
    materialised: MaterialisedSectionedLayout,
) -> int:
    if not ctx.has_field(fname, materialised):
        return fallback
    ref, _ = ctx.resolve_field_ref(fname, materialised)
    return ref.fl.byte_length


def _resolve_cics_length_option(
    opt: Operand,
    fallback: int,
    ctx: EmitContext,
    materialised: MaterialisedSectionedLayout,
) -> int:
    """Resolve a CICS LENGTH(…) option to an integer byte count.

    Handles:
      - digit literal: ``LENGTH(160)`` → 160
      - ``LENGTH OF fieldname``: compile-time field size
      - absent or unresolvable: return ``fallback``
    """
    text = _operand_text(opt, "").strip()
    if text.isdigit():
        return int(text)
    if text.upper().startswith(_LENGTH_OF):
        return _length_of_field(
            text[len(_LENGTH_OF) :].strip(), fallback, ctx, materialised
        )
    return fallback


def _field_byte_length(
    ctx: EmitContext, operand: Operand, materialised: MaterialisedSectionedLayout
) -> int:
    if not _names_field(operand, ctx, materialised):
        return 0
    ref, _ = ctx.resolve_field_ref(
        operand.text, materialised, subscripts=operand.subscripts
    )
    return ref.fl.byte_length


def _resolve_keylen(
    ctx: EmitContext,
    opts: Options,
    materialised: MaterialisedSectionedLayout,
) -> int:
    """Key length for a VSAM verb.

    Precedence: a digit-literal KEYLENGTH option, else the RIDFLD field's byte
    length, else 0.
    """
    keylength = _operand_text(opts.get("KEYLENGTH"), "").strip()
    if keylength.isdigit():
        return int(keylength)
    return _field_byte_length(ctx, opts.get("RIDFLD"), materialised)


_FORMATTIME_OUTPUTS = ("YYYYMMDD", "DATE", "DDMMYYYY", "DDMMYY", "YEAR", "TIME")
_DEFAULT_DATE_SEPARATOR = "/"


def _date_separator(opts: Options) -> str:
    """DATESEP present but bare means the CICS default separator."""
    if "DATESEP" not in opts:
        return ""
    return _operand_text(opts.get("DATESEP"), _DEFAULT_DATE_SEPARATOR)


def _browse_start(opts: Options) -> BrowseStart:
    return BrowseStart.EQUAL if "EQUAL" in opts else BrowseStart.GTEQ


def _resolve_into(
    ctx: EmitContext,
    operand: Operand,
    materialised: MaterialisedSectionedLayout,
) -> tuple[int, int]:
    """(offset, byte_length) of the INTO field, or (0, 0) if it is not a field."""
    if not _names_field(operand, ctx, materialised):
        return 0, 0
    ref, _ = ctx.resolve_field_ref(
        operand.text, materialised, subscripts=operand.subscripts
    )
    return ref.fl.offset, ref.fl.byte_length


def _emit_into_window(
    ctx: EmitContext, opts: Options, materialised: MaterialisedSectionedLayout
) -> tuple[Register, Register]:
    into_off, into_len = _resolve_into(ctx, opts.get("INTO"), materialised)
    r_off = _emit_int(ctx, into_off)
    return r_off, _emit_int(ctx, into_len)


_TIMING_OPTIONS = ("INTERVAL", "AFTER", "AT", "HOURS", "MINUTES", "SECONDS")


def _timing_operand(name: str, operand: Operand) -> str:
    return f"{name}({operand.text})" if isinstance(operand, CicsOperand) else name


def _timing_text(opts: Options) -> str:
    """The timing operands as written, or "" when none were coded.

    Recorded, never scheduled on: a region has no clock, so every START is
    dispatched as soon as the issuing task ends. Keeping the raw text lets a
    caller assert on what was asked for and ignored (StartQueue.ignored_delays).
    """
    return " ".join(
        _timing_operand(name, opts.get(name))
        for name in _TIMING_OPTIONS
        if name in opts
    )


def _emit_file_name(
    ctx: EmitContext, opts: Options, materialised: MaterialisedSectionedLayout
) -> Register:
    """FILE(...) and DATASET(...) are synonyms; the operand may be a literal or a
    data-name (resolved to its runtime value)."""
    return emit_operand_value(
        ctx, opts.get("FILE") or opts.get("DATASET"), materialised
    )


@dataclass(frozen=True)
class _RecordKey:
    file: Register
    key: Register
    key_length: Register


_PointEmitter: TypeAlias = (
    "Callable[[EmitContext, _RecordKey, Options, MaterialisedSectionedLayout], Register]"
)


def _emit_vsam_read(
    ctx: EmitContext,
    record: _RecordKey,
    opts: Options,
    materialised: MaterialisedSectionedLayout,
) -> Register:
    r_off, r_len = _emit_into_window(ctx, opts, materialised)
    return _emit_call(
        ctx, "__cics_read", record.file, record.key, record.key_length, r_off, r_len
    )


def _vsam_put(builtin: str) -> _PointEmitter:
    def emit(
        ctx: EmitContext,
        record: _RecordKey,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> Register:
        r_rec = _copy_in_or_empty(ctx, opts.get("FROM"), materialised)
        return _emit_call(
            ctx, builtin, record.file, record.key, record.key_length, r_rec
        )

    return emit


def _emit_vsam_delete(
    ctx: EmitContext,
    record: _RecordKey,
    opts: Options,
    materialised: MaterialisedSectionedLayout,
) -> Register:
    return _emit_call(ctx, "__cics_delete", record.file, record.key, record.key_length)


_VSAM_POINT_EMITTERS: Mapping[str, _PointEmitter] = MappingProxyType(
    {
        "READ": _emit_vsam_read,
        "WRITE": _vsam_put("__cics_write"),
        "REWRITE": _vsam_put("__cics_rewrite"),
        "DELETE": _emit_vsam_delete,
    }
)


_BrowseEmitter: TypeAlias = (
    "Callable[[EmitContext, Register, Options, MaterialisedSectionedLayout], Register]"
)


def _emit_vsam_startbr(
    ctx: EmitContext,
    r_file: Register,
    opts: Options,
    materialised: MaterialisedSectionedLayout,
) -> Register:
    r_key = _copy_in_or_empty(ctx, opts.get("RIDFLD"), materialised)
    r_klen = _emit_int(ctx, _resolve_keylen(ctx, opts, materialised))
    r_start = _emit_string(ctx, _browse_start(opts).name)
    return _emit_call(ctx, "__cics_startbr", r_file, r_key, r_klen, r_start)


def _vsam_read_browse(builtin: str) -> _BrowseEmitter:
    def emit(
        ctx: EmitContext,
        r_file: Register,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> Register:
        r_off, r_len = _emit_into_window(ctx, opts, materialised)
        return _emit_call(ctx, builtin, r_file, r_off, r_len)

    return emit


def _emit_vsam_endbr(
    ctx: EmitContext,
    r_file: Register,
    opts: Options,
    materialised: MaterialisedSectionedLayout,
) -> Register:
    return _emit_call(ctx, "__cics_endbr", r_file)


_VSAM_BROWSE_EMITTERS: Mapping[str, _BrowseEmitter] = MappingProxyType(
    {
        "STARTBR": _emit_vsam_startbr,
        "READNEXT": _vsam_read_browse("__cics_readnext"),
        "READPREV": _vsam_read_browse("__cics_readprev"),
        "ENDBR": _emit_vsam_endbr,
    }
)


def _symbolic_group_name(group_op: Operand, map_op: Operand, suffix: str) -> str:
    """The symbolic group is the STATIC FROM (SEND) / INTO (RECEIVE) operand. When
    omitted, BMS uses the map's own DSECT, named <mapname><suffix> (e.g. RECEIVE
    MAP('COSGN0A') with no INTO -> COSGN0AI); derivable only for a literal map
    name (a dynamic map always supplies FROM/INTO)."""
    if isinstance(group_op, CicsOperand):
        return group_op.text
    literal_map = isinstance(map_op, CicsOperand) and map_op.is_literal
    return _operand_text(map_op, "") + suffix if literal_map else ""


def _emit_map_field_names(
    ctx: EmitContext,
    verb: str,
    map_op: Operand,
    opts: Options,
    materialised: MaterialisedSectionedLayout,
) -> Register:
    group_op, suffix = (
        (opts.get("INTO"), "I") if verb == "RECEIVE MAP" else (opts.get("FROM"), "O")
    )
    group_name = _symbolic_group_name(group_op, map_op, suffix)
    leaves = ctx.group_leaf_names(group_name, materialised) if group_name else []
    base_names = [n[: -len(suffix)] for n in leaves if n.endswith(suffix)]
    r_names = ctx.fresh_reg()
    ctx.emit_inst(Const(result_reg=r_names, value=base_names, type_expr=UNKNOWN))
    return r_names


def _lower_send_text(
    ctx: EmitContext, opts: Options, materialised: MaterialisedSectionedLayout
) -> None:
    from_op = opts.get("FROM")
    r_text = (
        _emit_send_text_from(ctx, from_op, opts, materialised)
        if isinstance(from_op, CicsOperand)
        else _emit_string(ctx, _operand_text(opts.get("TEXT"), ""))
    )
    _emit_call(ctx, _BMS_VERBS["SEND TEXT"], r_text)


def _emit_send_text_from(
    ctx: EmitContext,
    from_op: CicsOperand,
    opts: Options,
    materialised: MaterialisedSectionedLayout,
) -> Register:
    r_text = emit_operand_value(ctx, from_op, materialised)
    fallback_len = _field_byte_length(ctx, from_op, materialised)
    length = _resolve_cics_length_option(
        opts.get("LENGTH"), fallback_len, ctx, materialised
    )
    if length and length != fallback_len:
        return _emit_fixed_slice(ctx, r_text, length)
    return r_text


def _emit_fixed_slice(ctx: EmitContext, value_reg: Register, length: int) -> Register:
    r_start = _emit_int(ctx, 0)
    r_len = _emit_int(ctx, length)
    sliced = ctx.fresh_reg()
    ctx.emit_inst(
        CallFunction(
            result_reg=sliced,
            func_name=FuncName(BuiltinName.STRING_SLICE),
            args=(
                Register(str(value_reg)),
                Register(str(r_start)),
                Register(str(r_len)),
            ),
        )
    )
    return sliced


def _emit_assign_output(
    ctx: EmitContext,
    subopt: str,
    target: Operand,
    materialised: MaterialisedSectionedLayout,
) -> None:
    r_res = _emit_call(ctx, "__cics_assign", _emit_string(ctx, subopt))
    emit_copy_back_str(ctx, target, ctx.emit_to_string(r_res), materialised)


def _emit_formattime_output(
    ctx: EmitContext,
    subopt: str,
    r_sep: Register,
    target: Operand,
    materialised: MaterialisedSectionedLayout,
) -> None:
    r_res = _emit_call(ctx, "__cics_formattime", _emit_string(ctx, subopt), r_sep)
    emit_copy_back_str(ctx, target, ctx.emit_to_string(r_res), materialised)


@dataclass(frozen=True)
class _Commarea:
    register: Register
    offset: int
    length: int


def _emit_link_commarea(
    ctx: EmitContext, ca_op: Operand, materialised: MaterialisedSectionedLayout
) -> _Commarea:
    if not (isinstance(ca_op, CicsOperand) and ctx.has_field(ca_op.text, materialised)):
        return _Commarea(_emit_empty_bytes(ctx), 0, 0)
    r_ca = _copy_in_or_empty(ctx, ca_op, materialised)
    offset, length = _resolve_into(ctx, ca_op, materialised)
    return _Commarea(r_ca, offset, length)


def _emit_deedit_length(
    ctx: EmitContext, length_op: Operand, materialised: MaterialisedSectionedLayout
) -> Register:
    """A data-name LENGTH resolves at runtime. Its register is allocated before
    that branch is chosen, so the register numbering matches either way."""
    literal_reg = ctx.fresh_reg()
    if isinstance(length_op, CicsOperand) and not length_op.is_literal:
        return emit_operand_value(ctx, length_op, materialised)
    ctx.emit_inst(Const.int_(literal_reg, int(_operand_text(length_op, "0"))))
    return literal_reg


def _as_builtin_list(holder: Holder[T]) -> list[T]:
    """flow.py and system.py predate Holder and still annotate the same
    one-element holder list as ``list``."""
    return cast("list[T]", holder)


def _as_builtin_queue(queue: MutableSequence[T]) -> list[T]:
    """system.py still annotates the TD queue it appends to as ``list``."""
    return cast("list[T]", queue)


def _as_builtin_dict(mapping: Mapping[K, V]) -> dict[K, V]:
    """flow.py, system.py and interval.py still annotate the mappings they only
    read as ``dict``; they read the caller's object, so later additions show."""
    return cast("dict[K, V]", mapping)


@dataclass(frozen=True)
class _Wiring:
    """The caller's shared objects, kept by identity: LINK and INQUIRE see
    programs added to the cache after construction, and the caller reads the
    TD queue the builtin appends to."""

    context_holder: list[CicsContext]
    result_holder: list[DispatchResult]
    program_cache: MutableMapping[str, LinkedProgram]
    td_queue: MutableSequence[str]


def _register_system_builtins(wiring: _Wiring, identity: tuple[str, str, str]) -> None:
    applid, sysid, userid = identity
    register("__cics_assign", make_assign_builtin(applid, sysid, userid))
    register("__cics_asktime", make_asktime_builtin())
    register("__cics_bif_deedit", make_bif_deedit_builtin())
    register("__cics_formattime", make_formattime_builtin())
    register(
        "__cics_inquire", make_inquire_builtin(_as_builtin_dict(wiring.program_cache))
    )
    register(
        "__cics_writeq_td", make_writeq_td_builtin(_as_builtin_queue(wiring.td_queue))
    )
    register("__cics_handle_abend", make_handle_abend_builtin())


def _register_flow_builtins(wiring: _Wiring, on_abend: Callable[[], None]) -> None:
    from cics.builtins.flow import (
        make_link_builtin,
        make_noop_hook_builtin,
        make_noop_task_end_hook_builtin,
        make_set_return_context_builtin,
        make_set_xctl_context_builtin,
    )

    # Defaults for three generic extension points another composed
    # coprocessor (e.g. squall) may independently claim — cicada always calls
    # these at task end / SYNCPOINT / SYNCPOINT ROLLBACK (see the RETURN,
    # _lower_syncpoint and _lower_syncpoint_rollback lowerings) with no idea
    # what, if anything, is registered under them.
    register_default("__cics_task_end_hook", make_noop_task_end_hook_builtin())
    register_default("__cics_syncpoint_hook", make_noop_hook_builtin())
    register_default("__cics_rollback_hook", make_noop_hook_builtin())
    _register_abend_builtins(wiring, on_abend)
    register(
        "__cics_set_return_context",
        make_set_return_context_builtin(wiring.result_holder),
    )
    register(
        "__cics_set_xctl_context", make_set_xctl_context_builtin(wiring.result_holder)
    )
    register(
        "__cics_link",
        make_link_builtin(
            _as_builtin_dict(wiring.program_cache),
            wiring.result_holder,
            wiring.context_holder,
            2_000_000,
        ),
    )


def _register_abend_builtins(wiring: _Wiring, on_abend: Callable[[], None]) -> None:
    register("__cics_handle_aid", make_handle_noop_builtin("HANDLE AID"))
    register(
        "__cics_unlock",
        make_runtime_noop_builtin(
            "EXEC CICS UNLOCK",
            "single-task emulation holds no lock another task could see",
        ),
    )
    register("__cics_abend", make_abend_builtin(wiring.result_holder, on_abend))
    register(
        "__cics_abend_unhandled",
        make_abend_unhandled_builtin(wiring.result_holder, on_abend),
    )
    register(
        "__cics_abend_unsupported",
        make_abend_unsupported_builtin(wiring.result_holder, on_abend),
    )


@dataclass(frozen=True)
class _Terminal:
    screen_queue: ScreenChannel
    input_queue: InputChannel
    receive_timeout: float


def _register_screen_builtins(wiring: _Wiring, terminal: _Terminal) -> None:
    from cics.builtins.screen import (
        make_apply_input_builtin,
        make_receive_map_builtin,
        make_send_map_builtin,
        make_send_text_builtin,
    )

    register(
        "__cics_send_map",
        make_send_map_builtin(terminal.screen_queue, wiring.context_holder),
    )
    register(
        "__cics_receive_map",
        make_receive_map_builtin(
            terminal.input_queue,
            wiring.context_holder,
            wiring.result_holder,
            timeout=terminal.receive_timeout,
        ),
    )
    # Conversational mode lowers RECEIVE MAP to SUSPEND + this builtin, which
    # applies the InputEvent the driver injects on resume.
    register("__cics_apply_input", make_apply_input_builtin())
    register("__cics_send_text", make_send_text_builtin(terminal.screen_queue))


def _register_vsam_builtins(engine: VsamEngine) -> None:
    from cics.builtins.vsam import (
        make_vsam_delete_builtin,
        make_vsam_endbr_builtin,
        make_vsam_read_builtin,
        make_vsam_readnext_builtin,
        make_vsam_readprev_builtin,
        make_vsam_rewrite_builtin,
        make_vsam_startbr_builtin,
        make_vsam_write_builtin,
    )

    register("__cics_read", make_vsam_read_builtin(engine))
    register("__cics_write", make_vsam_write_builtin(engine))
    register("__cics_rewrite", make_vsam_rewrite_builtin(engine))
    register("__cics_delete", make_vsam_delete_builtin(engine))
    register("__cics_startbr", make_vsam_startbr_builtin(engine))
    register("__cics_readnext", make_vsam_readnext_builtin(engine))
    register("__cics_readprev", make_vsam_readprev_builtin(engine))
    register("__cics_endbr", make_vsam_endbr_builtin(engine))


def _register_interval_builtins(
    start_queue: StartQueue, transid_to_program: Mapping[str, str], region_termid: str
) -> None:
    from cics.builtins.interval import make_retrieve_builtin, make_start_builtin

    transids = _as_builtin_dict(transid_to_program)
    register("__cics_start", make_start_builtin(start_queue, transids, region_termid))
    register("__cics_retrieve", make_retrieve_builtin(start_queue))


def _register_terminal_builtins(
    wiring: _Wiring,
    channels: tuple[ScreenChannel | Absent, InputChannel | Absent],
    receive_timeout: float,
) -> None:
    screen_queue, input_queue = channels
    if isinstance(screen_queue, ScreenChannel) and isinstance(
        input_queue, InputChannel
    ):
        _register_screen_builtins(
            wiring, _Terminal(screen_queue, input_queue, receive_timeout)
        )


def _register_io_builtins(
    wiring: _Wiring,
    channels: tuple[ScreenChannel | Absent, InputChannel | Absent],
    receive_timeout: float,
    vsam_engine: VsamEngine | Absent,
) -> None:
    _register_terminal_builtins(wiring, channels, receive_timeout)
    if isinstance(vsam_engine, VsamEngine):
        _register_vsam_builtins(vsam_engine)


_MULTIPLE_STRATEGIES = (
    " Multiple CicsLoweringStrategy instances in one process is unsupported."
)


def _default_on_abend() -> None:
    """Default on_abend: a CICS-only region has no composed SQL runtime, so
    there is nothing to roll back when a task abends."""


def _register_core_builtins(
    wiring: _Wiring,
    identity: tuple[str, str, str],
    on_abend: Callable[[], None],
) -> None:
    register(
        "__cics_init_eib",
        make_init_eib_builtin(wiring.context_holder),
        _MULTIPLE_STRATEGIES,
    )
    _register_system_builtins(wiring, identity)
    _register_flow_builtins(wiring, on_abend)


def _wiring(
    context_holder: Holder[CicsContext],
    result_holder: Holder[DispatchResult] | Absent,
    program_cache: MutableMapping[str, LinkedProgram],
    td_queue: MutableSequence[str] | Absent,
) -> _Wiring:
    results: Holder[DispatchResult] = (
        cast("Holder[DispatchResult]", [None])
        if not result_holder
        else cast("Holder[DispatchResult]", result_holder)
    )
    return _Wiring(
        context_holder=_as_builtin_list(context_holder),
        result_holder=_as_builtin_list(results),
        program_cache=program_cache,
        td_queue=td_queue if isinstance(td_queue, MutableSequence) else [],
    )


OWN_START_QUEUE = StartQueue()


@dataclass(frozen=True)
class _ModuleScan:
    """What this strategy gathers from the module it is lowering: the program's
    paragraph names (at the dict prepass) and its HANDLE CONDITION targets (at
    procedure entry)."""

    handler_labels: HandlerLabels
    paragraph_names: frozenset[str]


Lowerer: TypeAlias = (
    "Callable[[EmitContext, str, Options, MaterialisedSectionedLayout], None]"
)


class CicsLoweringStrategy:
    """Full CICS lowering strategy. Inject at CobolFrontend construction for CICS mode."""

    def __init__(
        self,
        context_holder: Holder[CicsContext],
        result_holder: Holder[DispatchResult] | Absent = NOT_SUPPLIED,
        td_queue: MutableSequence[str] | Absent = NOT_SUPPLIED,
        applid: str = "CARDDEMO",
        sysid: str = "SYS1",
        userid: str = DEFAULT_USERID,
        screen_queue: ScreenChannel | Absent = NOT_SUPPLIED,
        input_queue: InputChannel | Absent = NOT_SUPPLIED,
        vsam_engine: VsamEngine | Absent = NOT_SUPPLIED,
        receive_timeout: float = 30.0,
        conversational: bool = False,
        start_queue: StartQueue = OWN_START_QUEUE,
        region_termid: str = DEFAULT_TERMID,
        on_abend: Callable[[], None] = _default_on_abend,
        *,
        program_cache: MutableMapping[str, LinkedProgram],
        transid_to_program: Mapping[str, str],
        handler_source: MutableSequence[ExecCicsStatement],
        unsupported_verbs: set[str],
    ) -> None:
        self._handler_source = handler_source
        self._unsupported_verbs = unsupported_verbs
        self._scan = Cell(
            _ModuleScan(HandlerLabels(indices={}, conditions={}), frozenset())
        )
        self._start_queue = (
            StartQueue() if start_queue is OWN_START_QUEUE else start_queue
        )
        # Conversational mode lowers EXEC CICS RECEIVE MAP to a SUSPEND (yielding
        # to a run_resumable/resume driver) instead of a blocking input-queue read.
        self._conversational = conversational
        self._lowerers = self._verb_lowerers()
        wiring = _wiring(context_holder, result_holder, program_cache, td_queue)
        _register_core_builtins(wiring, (applid, sysid, userid), on_abend)
        _register_io_builtins(
            wiring, (screen_queue, input_queue), receive_timeout, vsam_engine
        )
        _register_interval_builtins(
            self._start_queue, transid_to_program, region_termid
        )

    def _verb_lowerers(self) -> Mapping[str, Lowerer]:
        families: tuple[tuple[Sequence[str], Lowerer], ...] = (
            (tuple(_SYS_VERBS), self._lower_system),
            (tuple(_BMS_VERBS), self._lower_bms),
            (tuple(_VSAM_POINT_VERBS), self._lower_vsam_point),
            (tuple(_VSAM_BROWSE_VERBS), self._lower_vsam_browse),
            (("HANDLE CONDITION", "IGNORE CONDITION"), self._lower_condition),
        )
        by_verb = {verb: lowerer for verbs, lowerer in families for verb in verbs}
        return MappingProxyType(
            {
                **by_verb,
                "RETURN": self._lower_return,
                "XCTL": self._lower_xctl,
                "ABEND": self._lower_abend,
                "SYNCPOINT": self._lower_syncpoint,
                "SYNCPOINT ROLLBACK": self._lower_syncpoint_rollback,
                "START": self._lower_start,
                "RETRIEVE": self._lower_retrieve,
                "ASSIGN": self._lower_assign,
                "FORMATTIME": self._lower_formattime,
                "WRITEQ TD": self._lower_writeq_td,
                "LINK": self._lower_link,
                "BIF DEEDIT": self._lower_bif_deedit,
            }
        )

    def handles(self, stmt: CobolStatementType | ExecCicsStatement) -> bool:
        return isinstance(stmt, ExecCicsStatement)

    def preprocess_program_dict(self, data: Mapping[str, V]) -> dict[str, V]:
        from cics.dfhresp_prepass import resolve_dfhresp_nodes

        logger.debug("DFHRESP prepass on program dict")
        # Same consume-and-clear discipline as handler_source: both are gathered
        # from this one module's parse and read once, at its procedure entry.
        self._scan.set(replace(self._scan.get(), paragraph_names=paragraph_names(data)))
        result = resolve_dfhresp_nodes(data)
        logger.debug("DFHRESP prepass done")
        return cast("dict[str, V]", result)

    def on_procedure_entry(
        self,
        ctx: EmitContext,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        # Consume-and-clear: handler_source is shared with every other module
        # compile_cobol lowers off the same dialect_parser, and each module is
        # fully parsed and lowered before the next starts.
        labels = collect_handler_labels(drain(self._handler_source))
        self._scan.set(replace(self._scan.get(), handler_labels=labels))
        ctx.emit_inst(
            CallFunction(
                result_reg=ctx.fresh_reg(),
                func_name=_BUILTIN_INIT_EIB,
                args=(),
            )
        )
        self._emit_dispatcher_if_needed(ctx, materialised)

    def _reject_unknown_handler_targets(self) -> None:
        """A handler naming a paragraph the module does not define compiles to a
        Branch whose label no block owns, and interpreter.cfg.build_cfg wires an
        edge only for a label it knows — so the task neither dispatches nor
        abends, it simply ends. Reject it while the program's own names are
        still in hand."""
        scan = self._scan.get()
        unknown = sorted(
            (paragraph, scan.handler_labels.conditions[paragraph])
            for paragraph in scan.handler_labels.indices
            if paragraph not in scan.paragraph_names
        )
        if not unknown:
            return
        named = ", ".join(
            f"{condition}({paragraph})" for paragraph, condition in unknown
        )
        raise NotImplementedError(
            f"EXEC CICS HANDLE CONDITION names {named}, but this module defines "
            "no such paragraph. The dispatcher would branch to a label no block "
            "owns, which ends the task silently instead of transferring control."
        )

    def _emit_dispatcher_if_needed(
        self, ctx: EmitContext, materialised: MaterialisedSectionedLayout
    ) -> None:
        """Emit the dispatcher at procedure entry, not after the module's last
        EXEC CICS statement: interpreter.cfg.build_cfg indexes labels over the
        complete instruction list before wiring any edge, so a forward
        reference to a not-yet-emitted ``para_<name>`` resolves like a backward
        one — the same mechanism lower_goto relies on for a GOTO to a later
        paragraph.

        Handlers registered but DFH-HANDLER or EIBRESP missing means forge-43l
        has bitten this module: source_prepass injects the copybooks into the
        main compiled source only, so a disk-resolved CALL callee must bring
        its own. Raising beats compiling a module whose handlers silently never
        dispatch.
        """
        self._reject_unknown_handler_targets()
        if has_condition_tables(ctx, materialised):
            # Entered only by a raise tail's Branch, so it must not be reachable
            # by falling through from the init-EIB call above.
            skip_lbl = ctx.fresh_label("cond_dispatch_skip")
            ctx.emit_inst(Branch(label=skip_lbl))
            self._emit_dispatcher(ctx, materialised)
            ctx.emit_inst(Label_(label=skip_lbl))
            return
        if self._scan.get().handler_labels:
            self._reject_missing_condition_tables(ctx, materialised)

    def _reject_missing_condition_tables(
        self, ctx: EmitContext, materialised: MaterialisedSectionedLayout
    ) -> None:
        missing = [
            name
            for name in _CONDITION_TABLE_FIELDS
            if not ctx.has_field(name, materialised)
        ]
        raise NotImplementedError(
            f"Module registers EXEC CICS HANDLE CONDITION handlers "
            f"({sorted(self._scan.get().handler_labels.indices)}) but is missing "
            f"{' and '.join(missing)} from its DATA DIVISION. "
            "build_cics_spec's source_prepass injects COPY DFHHANDLE. and "
            "COPY DFHEIBLK. into the main compiled source only "
            "(forge-43l) — a disk-resolved CALL callee that registers "
            "handlers must bring both copybooks itself: COPY DFHHANDLE. "
            "for DFH-HANDLER/DFH-RAISABLE, COPY DFHEIBLK. for EIBRESP."
        )

    def lower(
        self,
        ctx: EmitContext,
        stmt: ExecCicsStatement,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        lowerer = self._lowerers.get(stmt.verb, self._lower_unsupported)
        lowerer(ctx, stmt.verb, stmt.options, materialised)

    # ── Flow control ──────────────────────────────────────────────────────

    def _lower_return(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        if "TRANSID" in opts:
            r_transid = emit_operand_value(ctx, opts.get("TRANSID"), materialised)
            r_ca = _copy_in_or_empty(ctx, opts.get("COMMAREA"), materialised)
            _emit_call(ctx, "__cics_set_return_context", r_transid, r_ca)
        else:
            copied = emit_copy_in(ctx, opts.get("COMMAREA"), materialised)
            present = (copied,) if copied.is_present() else ()
            _emit_call(ctx, "__cics_set_return_context", *present)
        # Task end (both RETURN and RETURN TRANSID — but not XCTL, which
        # continues the same task/unit of work). Always emitted, regardless of
        # what (if anything) another composed coprocessor has registered under
        # this name.
        _emit_call(ctx, "__cics_task_end_hook")
        ctx.emit_inst(Return_())

    def _lower_xctl(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        r_prog = emit_operand_value(ctx, opts.get("PROGRAM"), materialised)
        r_ca = _copy_in_or_empty(ctx, opts.get("COMMAREA"), materialised)
        _emit_call(ctx, "__cics_set_xctl_context", r_prog, r_ca)
        ctx.emit_inst(Return_())

    def _lower_abend(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        r_code = _emit_string(ctx, _operand_text(opts.get("ABCODE"), "UNKN"))
        _emit_call(ctx, "__cics_abend", r_code)
        ctx.emit_inst(Return_())

    def _lower_syncpoint(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        """EXEC CICS SYNCPOINT: commit the pending unit of work.

        Does NOT close cursors. Real CICS closes non-WITH-HOLD cursors at
        syncpoint too, but every squall-composed program observed so far
        (COTRTLIC) opens, fetches and closes each cursor within one
        paragraph inside a single task, so no cursor is ever open across one
        of its syncpoints — closing here would be more faithful and equally
        harmless today, but not closing is simpler and cannot break the
        observed programs. A future WITH HOLD program makes this a
        deliberate revisit, not a surprise.
        """
        _emit_call(ctx, "__cics_syncpoint_hook")

    def _lower_syncpoint_rollback(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        """EXEC CICS SYNCPOINT ROLLBACK: undo the pending unit of work and
        close every cursor. Neither CardDemo program uses this verb today —
        left unregistered it fell through to _lower_unsupported's loud abend
        (forge-1zu.15)."""
        _emit_call(ctx, "__cics_rollback_hook")

    def _lower_start(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        r_transid = emit_operand_value(ctx, opts.get("TRANSID"), materialised)
        r_data = _copy_in_or_empty(ctx, opts.get("FROM"), materialised)
        r_termid = emit_operand_value(ctx, opts.get("TERMID"), materialised)
        r_reqid = emit_operand_value(ctx, opts.get("REQID"), materialised)
        r_timing = _emit_string(ctx, _timing_text(opts))
        r_res = _emit_call(
            ctx, "__cics_start", r_transid, r_data, r_termid, r_reqid, r_timing
        )
        _emit_resp_and_raise(ctx, r_res, opts, materialised)

    def _lower_retrieve(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        r_off, r_len = _emit_into_window(ctx, opts, materialised)
        r_res = _emit_call(ctx, "__cics_retrieve", r_off, r_len)
        _emit_resp_and_raise(ctx, r_res, opts, materialised)

    # ── BMS screen verbs ──────────────────────────────────────────────────

    def _lower_bms(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        if verb == "SEND TEXT":
            _lower_send_text(ctx, opts, materialised)
            return
        # MAP name (may be a dynamic data-name) -> runtime value via the resolver.
        map_op = opts.get("MAP", opts.get("MAPNAME"))
        r_map = emit_operand_value(ctx, map_op, materialised)
        r_names = _emit_map_field_names(ctx, verb, map_op, opts, materialised)
        r_res = self._emit_map_call(ctx, verb, r_map, r_names, opts, materialised)
        _emit_resp_and_raise(ctx, r_res, opts, materialised)

    def _emit_map_call(
        self,
        ctx: EmitContext,
        verb: str,
        r_map: Register,
        r_names: Register,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> Register:
        if verb == "RECEIVE MAP" and self._conversational:
            # Conversational: SUSPEND (yield the map name to the resume driver),
            # then apply the InputEvent the driver injects into the WS fields.
            r_evt = ctx.fresh_reg()
            ctx.emit_inst(Suspend(result_reg=r_evt, operand_reg=r_map))
            return _emit_call(ctx, "__cics_apply_input", r_evt, r_names)
        if verb == "RECEIVE MAP":
            return _emit_call(ctx, _BMS_VERBS[verb], r_map, r_names)
        r_mapset = emit_operand_value(ctx, opts.get("MAPSET"), materialised)
        r_flags = ctx.fresh_reg()
        ctx.emit_inst(
            Const(
                result_reg=r_flags,
                value=[o for o in _SEND_MAP_OPTIONS if o in opts],
                type_expr=UNKNOWN,
            )
        )
        r_cursor = emit_operand_value(ctx, opts.get("CURSOR"), materialised)
        return _emit_call(
            ctx, _BMS_VERBS[verb], r_map, r_names, r_mapset, r_flags, r_cursor
        )

    # ── ASSIGN / FORMATTIME: write each output sub-option to its field ────

    def _lower_assign(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        for subopt in (s for s in ASSIGN_SUBOPTIONS if _is_present(opts, s)):
            _emit_assign_output(ctx, subopt, opts.get(subopt), materialised)

    def _lower_formattime(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        r_sep = _emit_string(ctx, _date_separator(opts))
        for subopt in (s for s in _FORMATTIME_OUTPUTS if _is_present(opts, s)):
            _emit_formattime_output(ctx, subopt, r_sep, opts.get(subopt), materialised)

    # ── VSAM ──────────────────────────────────────────────────────────────

    def _lower_vsam_point(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        r_file = _emit_file_name(ctx, opts, materialised)
        r_key = _copy_in_or_empty(ctx, opts.get("RIDFLD"), materialised)
        r_klen = _emit_int(ctx, _resolve_keylen(ctx, opts, materialised))
        record = _RecordKey(r_file, r_key, r_klen)
        r_res = _VSAM_POINT_EMITTERS[verb](ctx, record, opts, materialised)
        _emit_resp_and_raise(ctx, r_res, opts, materialised)

    def _lower_vsam_browse(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        r_file = _emit_file_name(ctx, opts, materialised)
        r_res = _VSAM_BROWSE_EMITTERS[verb](ctx, r_file, opts, materialised)
        _emit_resp_and_raise(ctx, r_res, opts, materialised)

    # ── WRITEQ TD ─────────────────────────────────────────────────────────

    def _lower_writeq_td(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        r_from = emit_operand_value(ctx, opts.get("FROM"), materialised)
        r_queue = emit_operand_value(ctx, opts.get("QUEUE"), materialised)
        r_res = _emit_call(ctx, "__cics_writeq_td", r_from, r_queue)
        _emit_resp_and_raise(ctx, r_res, opts, materialised)

    # ── Condition handler registration ────────────────────────────────────

    def _lower_condition(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        for condition, operand in opts.items():
            self._emit_condition_entry(ctx, verb, (condition, operand), materialised)

    def _handler_index(self, handles: bool, operand: Operand) -> int:
        labels = self._scan.get().handler_labels
        registers = handles and isinstance(operand, CicsOperand)
        return labels.index_of(_operand_text(operand, "")) if registers else 0

    def _emit_condition_entry(
        self,
        ctx: EmitContext,
        verb: str,
        entry: tuple[str, Operand],
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        condition, operand = entry
        handles = verb == "HANDLE CONDITION"
        slot = condition_slot(verb, condition)
        r_idx = _emit_int(ctx, self._handler_index(handles, operand))
        emit_indexed_write(
            ctx, "DFH-HANDLER", slot, ctx.emit_to_string(r_idx), materialised
        )
        # Handler index 0 already means "never registered", whose dispatch
        # action is the system default (abend). IGNORE must not collapse into
        # that, so the ignored/default distinction lives in the raisable flag: an
        # ignored condition simply stops being raised, which is precisely "no
        # action taken". HANDLE re-arms the flag so a HANDLE after an IGNORE works
        # again — but only for conditions this runtime actually raises, since
        # writing 'Y' unconditionally would widen RAISABLE past the set
        # cics.conditions declares.
        if condition in RAISABLE:
            r_flag = _emit_string(ctx, "Y" if handles else "N")
            emit_indexed_write(ctx, "DFH-RAISABLE", slot, r_flag, materialised)
        elif handles:
            _warn_undispatchable_handler(condition, operand)

    # ── System verbs ──────────────────────────────────────────────────────

    def _lower_system(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        r_res = _emit_call(ctx, _SYS_VERBS[verb])
        if verb in _RESP_PRODUCING_VERBS:
            _emit_resp_and_raise(ctx, r_res, opts, materialised)

    # ── LINK ──────────────────────────────────────────────────────────────

    def _lower_link(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        r_prog = emit_operand_value(ctx, opts.get("PROGRAM"), materialised)
        commarea = _emit_link_commarea(ctx, opts.get("COMMAREA"), materialised)
        ca_len = _resolve_cics_length_option(
            opts.get("LENGTH"), commarea.length, ctx, materialised
        )
        r_off = _emit_int(ctx, commarea.offset)
        r_len = _emit_int(ctx, ca_len)
        r_res = _emit_call(ctx, "__cics_link", r_prog, commarea.register, r_off, r_len)
        _emit_resp_and_raise(ctx, r_res, opts, materialised)

    # ── BIF DEEDIT ────────────────────────────────────────────────────────

    def _lower_bif_deedit(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        """Strip non-digit editing characters from a field in place. FIELD(name)
        LENGTH(n): read the field bytes, keep only 0xF0-0xF9 (EBCDIC digits),
        left-justify, right-pad with '0' to LENGTH, write back."""
        field_op = opts.get("FIELD")
        r_field = _copy_in_or_empty(ctx, field_op, materialised)
        r_len = _emit_deedit_length(ctx, opts.get("LENGTH"), materialised)
        r_res = _emit_call(ctx, "__cics_bif_deedit", r_field, r_len)
        emit_copy_back_str(ctx, field_op, ctx.emit_to_string(r_res), materialised)

    def _lower_unsupported(
        self,
        ctx: EmitContext,
        verb: str,
        opts: Options,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        note_unsupported(self._unsupported_verbs, verb)
        logger.warning(
            "CicsLoweringStrategy: unimplemented verb %r — emitting an abend", verb
        )
        r_verb = _emit_string(ctx, verb)
        _emit_call(ctx, "__cics_abend_unsupported", r_verb)
        # Ends the task, as EXEC CICS ABEND's own lowering does. Without it the
        # program runs on into whatever followed the unsupported statement and
        # that statement's own result overwrites the abend.
        ctx.emit_inst(Return_())

    def _emit_decode_eibresp(
        self, ctx: EmitContext, materialised: MaterialisedSectionedLayout
    ) -> Register:
        ref, region_reg = ctx.resolve_field_ref("EIBRESP", materialised)
        return ctx.emit_decode_field(
            region_reg, ref.fl, ref.offset_reg, extent=ref.extent
        )

    def _emit_handler_match(
        self, ctx: EmitContext, idx_reg: Register, handler: tuple[str, int]
    ) -> None:
        name, index = handler
        cmp_reg = _emit_binop(ctx, "==", idx_reg, ctx.const_to_reg(index))
        match_lbl = ctx.fresh_label("cond_match")
        next_lbl = ctx.fresh_label("cond_next")
        ctx.emit_inst(BranchIf(cond_reg=cmp_reg, branch_targets=(match_lbl, next_lbl)))
        ctx.emit_inst(Label_(label=match_lbl))
        ctx.emit_inst(Branch(label=CodeLabel(f"para_{name}")))
        ctx.emit_inst(Label_(label=next_lbl))

    def _emit_dispatcher(
        self, ctx: EmitContext, materialised: MaterialisedSectionedLayout
    ) -> None:
        """One per program. Entered by a Branch, so it takes no arguments: it
        reads EIBRESP, which emit_resp_writeback has already written."""
        ctx.emit_inst(Label_(label=CodeLabel("__cics_cond_dispatch")))
        ref, region_reg = ctx.resolve_field_ref(
            "DFH-HANDLER", materialised, subscripts=_eibresp_subscript()
        )
        idx_reg = ctx.emit_decode_field(
            region_reg, ref.fl, ref.offset_reg, extent=ref.extent
        )
        for handler in self._scan.get().handler_labels.indices.items():
            self._emit_handler_match(ctx, idx_reg, handler)
        r_resp = self._emit_decode_eibresp(ctx, materialised)
        _emit_call(ctx, "__cics_abend_unhandled", r_resp)
        ctx.emit_inst(Return_())


def _warn_undispatchable_handler(condition: str, operand: Operand) -> None:
    logger.warning(
        "EXEC CICS HANDLE CONDITION %s(%s) registers a handler "
        "this runtime can never dispatch to: %s is not among the "
        "conditions it raises (cics.conditions.RAISABLE). The "
        "command that fails with %s will write EIBRESP and "
        "continue inline.",
        condition,
        _operand_text(operand, ""),
        condition,
        condition,
    )

"""CicsLoweringStrategy — implements RedDragonExtensionLoweringStrategy
directly (interpreter.cobol.red_dragon_extension_strategy)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cics.builtins.system import (
    ASSIGN_SUBOPTIONS,
    DEFAULT_USERID,
    make_init_eib_builtin,
    make_assign_builtin,
    make_asktime_builtin,
    make_formattime_builtin,
    make_inquire_builtin,
    make_writeq_td_builtin,
    make_handle_abend_builtin,
    make_handle_noop_builtin,
    make_runtime_noop_builtin,
    make_abend_builtin,
    make_abend_unhandled_builtin,
    make_abend_unsupported_builtin,
)
from interpreter.cobol.cobol_constants import BuiltinName
from cobol_asg.cobol_expression import BinOpNode, FieldRefNode, LiteralNode
from cobol_asg.ref_mod import RefModLiteral
from interpreter.func_name import FuncName
from interpreter.ir import CodeLabel
from interpreter.operator_kind import resolve_binop
from interpreter.register import Register
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
from interpreter.types.type_expr import UNKNOWN

from cics.conditions import RAISABLE, code_for
from cics.handler_labels import (
    HandlerLabels,
    collect_handler_labels,
    paragraph_names,
)
from cics.interval import StartQueue
from cics.statements import ExecCicsStatement
from cics.types import DEFAULT_TERMID
from cics.vsam.browse import BrowseStart

if TYPE_CHECKING:
    from cics.terminal import InputChannel, ScreenChannel
    from interpreter.cobol.emit_context import EmitContext
    from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout
    from cics.types import CicsContext
    from cics.statements import CicsOperand

logger = logging.getLogger(__name__)

_BUILTIN_INIT_EIB = FuncName("__cics_init_eib")

_SYS_VERBS: dict[str, str] = {
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

# Verbs whose builtin returns a CICS response code to be written into EIBRESP
# (always) and the RESP(name) option's field (when present). Only INQUIRE among
# the current system verbs produces a resp code; D extends this set with the
# VSAM verbs (READ/WRITE/REWRITE/DELETE/STARTBR/...).
_RESP_PRODUCING_VERBS: set[str] = {"INQUIRE"}

# VSAM point operations.
_VSAM_POINT_VERBS: set[str] = {"READ", "WRITE", "REWRITE", "DELETE"}

# VSAM browse operations (implicit single cursor per file).
_VSAM_BROWSE_VERBS: set[str] = {"STARTBR", "READNEXT", "READPREV", "ENDBR"}

_BMS_VERBS: dict[str, str] = {
    "SEND MAP": "__cics_send_map",
    "RECEIVE MAP": "__cics_receive_map",
    "SEND TEXT": "__cics_send_text",
}


def emit_copy_in(
    ctx: "EmitContext",
    operand: "CicsOperand | None",
    materialised: "MaterialisedSectionedLayout",
) -> "Register | None":
    """If ``operand`` is a data item, LoadRegion its bytes into a fresh register and return it.

    Returns ``None`` when ``operand`` is ``None`` or a literal/unresolved name
    (caller falls back to Const).
    """
    if (
        operand is None
        or operand.is_literal
        or not ctx.has_field(operand.text, materialised)
    ):
        return None
    ref, region_reg = ctx.resolve_field_ref(
        operand.text, materialised, subscripts=operand.subscripts
    )
    offset_reg = ref.offset_reg
    length = ref.fl.byte_length
    # Reference modification (e.g. WS-FIELD(2:1)) reads a byte-slice: advance the
    # offset by start-1 and read `length` bytes. The offset is adjusted at
    # runtime via a Binop (start may be a data-name); the LoadRegion length field
    # is a compile-time int, so a literal length is honoured exactly. An omitted
    # LENGTH reads to the end of the field; a non-literal (data-name) ref-mod
    # LENGTH cannot size a static LoadRegion and raises NotImplementedError (rare;
    # CardDemo CICS ref-mod uses literal lengths).
    if operand.ref_mod_start is not None:
        from interpreter.cobol.lower_arithmetic import (  # noqa: PLC0415
            eval_ref_mod_expr,
        )
        from interpreter.operator_kind import resolve_binop  # noqa: PLC0415
        from interpreter.register import Register  # noqa: PLC0415

        start_1based = eval_ref_mod_expr(ctx, operand.ref_mod_start, materialised)
        one_reg = ctx.const_to_reg(1)
        delta_reg = ctx.fresh_reg()
        ctx.emit_inst(
            Binop(
                result_reg=delta_reg,
                operator=resolve_binop("-"),
                left=Register(str(start_1based)),
                right=Register(str(one_reg)),
            )
        )
        adj_offset = ctx.fresh_reg()
        ctx.emit_inst(
            Binop(
                result_reg=adj_offset,
                operator=resolve_binop("+"),
                left=Register(str(offset_reg)),
                right=Register(str(delta_reg)),
            )
        )
        offset_reg = adj_offset
        if isinstance(operand.ref_mod_length, RefModLiteral):
            length = int(operand.ref_mod_length.value)
        elif operand.ref_mod_length is None:
            # No explicit LENGTH: read from the start offset to the end of the
            # field (existing behavior — `length` is already the full byte length).
            pass
        else:
            # A data-name (or other non-literal) ref-mod LENGTH cannot size a
            # static LoadRegion: silently reading the full field is observably
            # wrong (it reads more bytes than the ref-mod asked for and can
            # clobber adjacent fields), so make the unsupported case loud.
            raise NotImplementedError(
                f"CICS ref-mod with a data-name LENGTH in copy_in is not supported "
                f"(LoadRegion needs a compile-time int length): {operand.text!r}; "
                f"see red-dragon-6ddr"
            )
    out = ctx.fresh_reg()
    ctx.emit_inst(
        LoadRegion(
            result_reg=out,
            region_reg=region_reg,
            offset_reg=offset_reg,
            length=length,
        )
    )
    return out


def _emit_ref_mod_slice(
    ctx: "EmitContext",
    operand: "CicsOperand",
    value_reg: "Register",
    materialised: "MaterialisedSectionedLayout",
) -> "Register":
    """Slice ``value_reg`` per ``operand``'s reference modification (start:length).

    Mirrors the COBOL RefModNode lowering (condition_lowering.lower_expr_node):
    convert the 1-based start to 0-based (``start - 1``), then
    ``STRING_SLICE(value, start0, length)``. ``length`` defaults to a large
    sentinel when omitted. Reuses ``eval_ref_mod_expr`` for the start/length
    expressions so the COBOL machinery is the single source of truth.
    """
    from interpreter.cobol.lower_arithmetic import eval_ref_mod_expr  # noqa: PLC0415
    from interpreter.operator_kind import resolve_binop  # noqa: PLC0415
    from interpreter.register import Register  # noqa: PLC0415

    assert operand.ref_mod_start is not None
    start_1based = eval_ref_mod_expr(ctx, operand.ref_mod_start, materialised)
    one_reg = ctx.const_to_reg(1)
    start_0based = ctx.fresh_reg()
    ctx.emit_inst(
        Binop(
            result_reg=start_0based,
            operator=resolve_binop("-"),
            left=Register(str(start_1based)),
            right=Register(str(one_reg)),
        )
    )
    if operand.ref_mod_length is not None:
        length_reg = eval_ref_mod_expr(ctx, operand.ref_mod_length, materialised)
    else:
        length_reg = ctx.const_to_reg(999999)
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


def emit_operand_value(
    ctx: "EmitContext",
    operand: "CicsOperand | None",
    materialised: "MaterialisedSectionedLayout",
) -> "Register":
    """Resolve a CICS operand to a register holding its runtime VALUE.

    Branches on the STRUCTURAL operand kind carried by ``CicsOperand``:
    a bare data-name that resolves to a field is decoded to a register; a quoted
    literal (or an unresolved bare name / numeric) emits a Const. A quoted literal
    NEVER consults ``has_field`` — that fixes the BMS symbolic-map name collision
    (e.g. MAP('SGNMAP') must not decode a same-named WS group). Returns a Register.
    """
    if operand is None:
        r = ctx.fresh_reg()
        ctx.emit_inst(Const.string(r, ""))
        return r
    if not operand.is_literal and ctx.has_field(operand.text, materialised):
        ref, region_reg = ctx.resolve_field_ref(
            operand.text, materialised, subscripts=operand.subscripts
        )
        # ref.offset_reg carries the resolved offset, including the element
        # offset for a subscripted operand (e.g. TBL(IDX)); pass it so the
        # decode reads the indexed element, not the base (element 1).
        value_reg = ctx.emit_decode_field(
            region_reg, ref.fl, ref.offset_reg, extent=ref.extent
        )
        # Reference modification (e.g. WS-MSG(1:8)) byte-slices the decoded value.
        if operand.ref_mod_start is not None:
            return _emit_ref_mod_slice(ctx, operand, value_reg, materialised)
        return value_reg
    r = ctx.fresh_reg()
    ctx.emit_inst(Const.string(r, operand.text))
    return r


def emit_copy_back_str(
    ctx: "EmitContext",
    target: "CicsOperand | str | None",
    value_str_reg: "Register",
    materialised: "MaterialisedSectionedLayout",
) -> None:
    """Encode a string-valued result into the named field, if it is a data item.

    ``target`` may be a bare field name (str — for internally-known fields like
    EIBRESP) or a parsed ``CicsOperand``. A write-back target must be a data-name,
    so a quoted literal operand is a no-op (along with ``None`` and unknown names).
    """
    if target is None:
        return
    if isinstance(target, str):
        name = target
    elif target.is_literal:
        return
    else:
        name = target.text
    if not ctx.has_field(name, materialised):
        return
    # write-back targets are plain data-names (RESP/APPLID/...), never subscripted; no subscripts to thread
    ref, region_reg = ctx.resolve_field_ref(name, materialised)
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
    ctx: "EmitContext",
    name: str,
    index: int,
    value_str_reg: "Register",
    materialised: "MaterialisedSectionedLayout",
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
    ctx: "EmitContext",
    r_resp_result: "Register",
    opts: dict[str, "CicsOperand | None"],
    materialised: "MaterialisedSectionedLayout",
) -> None:
    """Write a builtin's returned resp code into EIBRESP (always) and RESP(name) if present.

    ``r_resp_result`` is the numeric register returned by the service builtin.
    It is stringified, then encoded per each target field's layout — EIBRESP is
    ``PIC S9(8) COMP`` (binary), so the numeric string is packed correctly by
    ``emit_encode_and_write`` (same path as the GIVING clause in lower_call.py).
    Reusable by D for the VSAM verbs.
    """
    str_reg = ctx.emit_to_string(r_resp_result)
    emit_copy_back_str(ctx, "EIBRESP", str_reg, materialised)
    emit_copy_back_str(ctx, opts.get("RESP"), str_reg, materialised)


_CONDITION_TABLE_FIELDS = ("DFH-HANDLER", "DFH-RAISABLE", "EIBRESP")


def has_condition_tables(
    ctx: "EmitContext", materialised: "MaterialisedSectionedLayout"
) -> bool:
    """Whether this module carries the state both halves of condition handling
    need — the dispatcher and every raise tail must agree, or a tail branches to
    a label no dispatcher defined."""
    return all(ctx.has_field(name, materialised) for name in _CONDITION_TABLE_FIELDS)


def emit_raise_tail(
    ctx: "EmitContext",
    opts: dict[str, "CicsOperand | None"],
    materialised: "MaterialisedSectionedLayout",
) -> None:
    """Branch to the dispatcher when the command raised a condition this runtime
    handles. RESP and NOHANDLE are the program's undertaking to check inline, so
    a command coding either does not raise (CICS)."""
    if "RESP" in opts or "NOHANDLE" in opts:
        return
    if not has_condition_tables(ctx, materialised):
        return
    ref, region_reg = ctx.resolve_field_ref(
        "DFH-RAISABLE",
        materialised,
        subscripts=(BinOpNode("+", FieldRefNode("EIBRESP"), LiteralNode("1")),),
    )
    flag_reg = ctx.emit_decode_field(
        region_reg, ref.fl, ref.offset_reg, extent=ref.extent
    )
    y_reg = ctx.const_to_reg("Y")
    cmp_reg = ctx.fresh_reg()
    ctx.emit_inst(
        Binop(
            result_reg=cmp_reg,
            operator=resolve_binop("=="),
            left=Register(str(flag_reg)),
            right=Register(str(y_reg)),
        )
    )
    cont_lbl = ctx.fresh_label("cond_continue")
    ctx.emit_inst(
        BranchIf(
            cond_reg=cmp_reg,
            branch_targets=(CodeLabel("__cics_cond_dispatch"), cont_lbl),
        )
    )
    ctx.emit_inst(Label_(label=cont_lbl))


def _resolve_cics_length_option(
    opt: "CicsOperand | None",
    fallback: int,
    ctx: "EmitContext",
    materialised: "MaterialisedSectionedLayout",
) -> int:
    """Resolve a CICS LENGTH(…) option to an integer byte count.

    Handles:
      - digit literal: ``LENGTH(160)`` → 160
      - ``LENGTH OF fieldname``: compile-time field size
      - absent or unresolvable: return ``fallback``
    """
    if opt is None:
        return fallback
    text = opt.text.strip()
    if text.isdigit():
        return int(text)
    if text.upper().startswith("LENGTH OF "):
        fname = text[len("LENGTH OF ") :].strip()
        if ctx.has_field(fname, materialised):
            ref, _ = ctx.resolve_field_ref(fname, materialised)
            return ref.fl.byte_length
    return fallback


def _resolve_keylen(
    ctx: "EmitContext",
    opts: dict[str, "CicsOperand | None"],
    materialised: "MaterialisedSectionedLayout",
) -> int:
    """Key length for a VSAM verb.

    Precedence: a digit-literal KEYLENGTH option, else the RIDFLD field's byte
    length, else 0.
    """
    keylength = opts.get("KEYLENGTH")
    if keylength is not None and keylength.text.strip().isdigit():
        return int(keylength.text.strip())
    ridfld = opts.get("RIDFLD")
    if (
        ridfld is not None
        and not ridfld.is_literal
        and ctx.has_field(ridfld.text, materialised)
    ):
        ref, _ = ctx.resolve_field_ref(
            ridfld.text, materialised, subscripts=ridfld.subscripts
        )
        return ref.fl.byte_length
    return 0


_FORMATTIME_OUTPUTS = ("YYYYMMDD", "DATE", "DDMMYYYY", "DDMMYY", "YEAR", "TIME")
_DEFAULT_DATE_SEPARATOR = "/"


def _date_separator(opts: dict[str, "CicsOperand | None"]) -> str:
    """DATESEP present but bare means the CICS default separator."""
    if "DATESEP" not in opts:
        return ""
    operand = opts["DATESEP"]
    return operand.text if operand is not None else _DEFAULT_DATE_SEPARATOR


def _browse_start(opts: dict[str, "CicsOperand | None"]) -> BrowseStart:
    return BrowseStart.EQUAL if "EQUAL" in opts else BrowseStart.GTEQ


def _resolve_into(
    ctx: "EmitContext",
    operand: "CicsOperand | None",
    materialised: "MaterialisedSectionedLayout",
) -> tuple[int, int]:
    """(offset, byte_length) of the INTO field, or (0, 0) if it is not a field."""
    if (
        operand is not None
        and not operand.is_literal
        and ctx.has_field(operand.text, materialised)
    ):
        ref, _ = ctx.resolve_field_ref(
            operand.text, materialised, subscripts=operand.subscripts
        )
        return ref.fl.offset, ref.fl.byte_length
    return 0, 0


_TIMING_OPTIONS = ("INTERVAL", "AFTER", "AT", "HOURS", "MINUTES", "SECONDS")


def _timing_text(opts: dict[str, "CicsOperand | None"]) -> str:
    """The timing operands as written, or "" when none were coded.

    Recorded, never scheduled on: a region has no clock, so every START is
    dispatched as soon as the issuing task ends. Keeping the raw text lets a
    caller assert on what was asked for and ignored (StartQueue.ignored_delays).
    """
    present = [
        f"{name}({opts[name].text})" if opts.get(name) is not None else name
        for name in _TIMING_OPTIONS
        if name in opts
    ]
    return " ".join(present)


def _register(table: dict, name: str, fn: object) -> None:  # type: ignore[type-arg]
    key = FuncName(name)
    if key in table:
        logger.warning("Builtins.TABLE already contains %s — overwriting.", key)
    table[key] = fn


def _register_default(table: dict, name: str, fn: object) -> None:  # type: ignore[type-arg]
    """Register fn under name only if nothing is registered there yet — for a
    generic extension point another coprocessor may independently claim by
    registering its own real implementation over this default (see
    __cics_task_end_hook). Order-independent: if the other coprocessor
    constructs first, its real registration is already present and this
    call leaves it alone; if it constructs later, its own (overwriting)
    registration replaces this default.
    """
    key = FuncName(name)
    table.setdefault(key, fn)


def _operand_text(opt: "CicsOperand | None") -> str | None:
    return opt.text if opt is not None else None


_OWN_START_QUEUE = StartQueue()  # sentinel: "I was not given one — make my own"


class CicsLoweringStrategy:
    """Full CICS lowering strategy. Inject at CobolFrontend construction for CICS mode."""

    def __init__(
        self,
        context_holder: "list[CicsContext]",
        result_holder: list | None = None,  # type: ignore[type-arg]
        program_cache: dict | None = None,  # type: ignore[type-arg]
        td_queue: list[str] | None = None,
        applid: str = "CARDDEMO",
        sysid: str = "SYS1",
        userid: str = DEFAULT_USERID,
        screen_queue: "ScreenChannel | None" = None,
        input_queue: "InputChannel | None" = None,
        vsam_engine: object = None,
        receive_timeout: float = 30.0,
        conversational: bool = False,
        start_queue: StartQueue = _OWN_START_QUEUE,
        transid_to_program: dict[
            str, str
        ] = {},  # never mutated: membership + lookup only
        region_termid: str = DEFAULT_TERMID,
        *,
        handler_source: list[ExecCicsStatement],
        unsupported_verbs: set[str],
    ) -> None:
        self._context_holder = context_holder
        self._handler_source = handler_source
        self._unsupported_verbs = unsupported_verbs
        self._handler_labels = HandlerLabels(indices={}, conditions={})
        self._paragraph_names: frozenset[str] = frozenset()
        self._start_queue = (
            StartQueue() if start_queue is _OWN_START_QUEUE else start_queue
        )
        # Conversational mode lowers EXEC CICS RECEIVE MAP to a SUSPEND (yielding
        # to a run_resumable/resume driver) instead of a blocking input-queue read.
        self._conversational = conversational
        # Deferred imports to avoid violating project-no-vm-internals import contract.
        from interpreter.vm.builtins import Builtins  # noqa: PLC0415
        from cics.builtins.flow import (  # noqa: PLC0415
            make_set_return_context_builtin,
            make_set_xctl_context_builtin,
            make_link_builtin,
            make_noop_task_end_hook_builtin,
        )

        if _BUILTIN_INIT_EIB in Builtins.TABLE:
            logger.warning(
                "Builtins.TABLE already contains %s — overwriting. "
                "Multiple CicsLoweringStrategy instances in one process is unsupported.",
                _BUILTIN_INIT_EIB,
            )
        init_eib = make_init_eib_builtin(context_holder)
        Builtins.TABLE[_BUILTIN_INIT_EIB] = init_eib

        _holder: list = result_holder if result_holder is not None else [None]
        td = td_queue if td_queue is not None else []
        prog_cache = {} if program_cache is None else program_cache

        _register(
            Builtins.TABLE, "__cics_assign", make_assign_builtin(applid, sysid, userid)
        )
        _register(Builtins.TABLE, "__cics_asktime", make_asktime_builtin())
        _register(Builtins.TABLE, "__cics_formattime", make_formattime_builtin())
        _register(Builtins.TABLE, "__cics_inquire", make_inquire_builtin(prog_cache))
        _register(Builtins.TABLE, "__cics_writeq_td", make_writeq_td_builtin(td))
        _register(Builtins.TABLE, "__cics_handle_abend", make_handle_abend_builtin())
        # Default for a generic task-end extension point another composed
        # coprocessor (e.g. squall) may independently claim — cicada always
        # calls this at task end (see the RETURN lowering below) with no idea
        # what, if anything, is registered under it.
        _register_default(
            Builtins.TABLE, "__cics_task_end_hook", make_noop_task_end_hook_builtin()
        )
        _register(
            Builtins.TABLE,
            "__cics_handle_aid",
            make_handle_noop_builtin("HANDLE AID"),
        )
        _register(
            Builtins.TABLE,
            "__cics_unlock",
            make_runtime_noop_builtin(
                "EXEC CICS UNLOCK",
                "single-task emulation holds no lock another task could see",
            ),
        )
        _register(Builtins.TABLE, "__cics_abend", make_abend_builtin(_holder))
        _register(
            Builtins.TABLE,
            "__cics_abend_unhandled",
            make_abend_unhandled_builtin(_holder),
        )
        _register(
            Builtins.TABLE,
            "__cics_abend_unsupported",
            make_abend_unsupported_builtin(_holder),
        )
        _register(
            Builtins.TABLE,
            "__cics_set_return_context",
            make_set_return_context_builtin(_holder),
        )
        _register(
            Builtins.TABLE,
            "__cics_set_xctl_context",
            make_set_xctl_context_builtin(_holder),
        )

        _register(
            Builtins.TABLE,
            "__cics_link",
            make_link_builtin(prog_cache, _holder, context_holder, 2_000_000),
        )

        if screen_queue is not None and input_queue is not None:
            from cics.builtins.screen import (  # noqa: PLC0415
                make_send_map_builtin,
                make_receive_map_builtin,
                make_apply_input_builtin,
                make_send_text_builtin,
            )

            _register(
                Builtins.TABLE,
                "__cics_send_map",
                make_send_map_builtin(screen_queue, context_holder),
            )
            _register(
                Builtins.TABLE,
                "__cics_receive_map",
                make_receive_map_builtin(
                    input_queue, context_holder, _holder, timeout=receive_timeout
                ),
            )
            # Conversational mode lowers RECEIVE MAP to SUSPEND + this builtin,
            # which applies the InputEvent the driver injects on resume.
            _register(
                Builtins.TABLE,
                "__cics_apply_input",
                make_apply_input_builtin(),
            )
            _register(
                Builtins.TABLE,
                "__cics_send_text",
                make_send_text_builtin(screen_queue),
            )

        if vsam_engine is not None:
            from cics.builtins.vsam import (  # noqa: PLC0415
                make_vsam_read_builtin,
                make_vsam_write_builtin,
                make_vsam_rewrite_builtin,
                make_vsam_delete_builtin,
                make_vsam_startbr_builtin,
                make_vsam_readnext_builtin,
                make_vsam_readprev_builtin,
                make_vsam_endbr_builtin,
            )

            _register(
                Builtins.TABLE, "__cics_read", make_vsam_read_builtin(vsam_engine)
            )
            _register(
                Builtins.TABLE, "__cics_write", make_vsam_write_builtin(vsam_engine)
            )
            _register(
                Builtins.TABLE,
                "__cics_rewrite",
                make_vsam_rewrite_builtin(vsam_engine),
            )
            _register(
                Builtins.TABLE, "__cics_delete", make_vsam_delete_builtin(vsam_engine)
            )
            _register(
                Builtins.TABLE,
                "__cics_startbr",
                make_vsam_startbr_builtin(vsam_engine),
            )
            _register(
                Builtins.TABLE,
                "__cics_readnext",
                make_vsam_readnext_builtin(vsam_engine),
            )
            _register(
                Builtins.TABLE,
                "__cics_readprev",
                make_vsam_readprev_builtin(vsam_engine),
            )
            _register(
                Builtins.TABLE,
                "__cics_endbr",
                make_vsam_endbr_builtin(vsam_engine),
            )

        from cics.builtins.interval import (  # noqa: PLC0415
            make_retrieve_builtin,
            make_start_builtin,
        )

        _register(
            Builtins.TABLE,
            "__cics_start",
            make_start_builtin(self._start_queue, transid_to_program, region_termid),
        )
        _register(
            Builtins.TABLE, "__cics_retrieve", make_retrieve_builtin(self._start_queue)
        )

    def handles(self, stmt: object) -> bool:
        return isinstance(stmt, ExecCicsStatement)

    def preprocess_program_dict(self, data: dict) -> dict:
        from cics.dfhresp_prepass import (
            resolve_dfhresp_nodes,
        )  # noqa: PLC0415

        logger.debug("DFHRESP prepass on program dict")
        # Same consume-and-clear discipline as handler_source: both are gathered
        # from this one module's parse and read once, at its procedure entry.
        self._paragraph_names = paragraph_names(data)
        result = resolve_dfhresp_nodes(data)  # type: ignore[return-value]
        logger.debug("DFHRESP prepass done")
        return result

    def on_procedure_entry(
        self,
        ctx: "EmitContext",
        materialised: "MaterialisedSectionedLayout",
    ) -> None:
        # Consume-and-clear: handler_source is shared with every other module
        # compile_cobol lowers off the same dialect_parser, and each module is
        # fully parsed and lowered before the next starts.
        self._handler_labels = collect_handler_labels(self._handler_source)
        self._handler_source.clear()
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
        unknown = sorted(
            (paragraph, self._handler_labels.conditions[paragraph])
            for paragraph in self._handler_labels.indices
            if paragraph not in self._paragraph_names
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
        self, ctx: "EmitContext", materialised: "MaterialisedSectionedLayout"
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
        if self._handler_labels:
            missing = [
                name
                for name in _CONDITION_TABLE_FIELDS
                if not ctx.has_field(name, materialised)
            ]
            raise NotImplementedError(
                f"Module registers EXEC CICS HANDLE CONDITION handlers "
                f"({sorted(self._handler_labels.indices)}) but is missing "
                f"{' and '.join(missing)} from its DATA DIVISION. "
                "build_cics_spec's source_prepass injects COPY DFHHANDLE. and "
                "COPY DFHEIBLK. into the main compiled source only "
                "(forge-43l) — a disk-resolved CALL callee that registers "
                "handlers must bring both copybooks itself: COPY DFHHANDLE. "
                "for DFH-HANDLER/DFH-RAISABLE, COPY DFHEIBLK. for EIBRESP."
            )

    def lower(
        self,
        ctx: "EmitContext",
        stmt: "ExecCicsStatement",
        materialised: "MaterialisedSectionedLayout",
    ) -> None:
        verb = stmt.verb
        opts = stmt.options

        # ── Flow control ──────────────────────────────────────────────────
        if verb == "RETURN":
            if "TRANSID" in opts:
                r_transid = emit_operand_value(ctx, opts.get("TRANSID"), materialised)
                r_ca = emit_copy_in(ctx, opts.get("COMMAREA"), materialised)
                if r_ca is None:
                    r_ca = ctx.fresh_reg()
                    ctx.emit_inst(Const(result_reg=r_ca, value=b"", type_expr=UNKNOWN))
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName("__cics_set_return_context"),
                        args=(r_transid, r_ca),
                    )
                )
            else:
                r_ca = emit_copy_in(ctx, opts.get("COMMAREA"), materialised)
                return_args = (r_ca,) if r_ca is not None else ()
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName("__cics_set_return_context"),
                        args=return_args,
                    )
                )
            # Task end (both RETURN and RETURN TRANSID — but not XCTL, which
            # continues the same task/unit of work below). Always emitted,
            # regardless of what (if anything) another composed coprocessor
            # has registered under this name.
            ctx.emit_inst(
                CallFunction(
                    result_reg=ctx.fresh_reg(),
                    func_name=FuncName("__cics_task_end_hook"),
                    args=(),
                )
            )
            ctx.emit_inst(Return_())
            return

        if verb == "XCTL":
            r_prog = emit_operand_value(ctx, opts.get("PROGRAM"), materialised)
            r_ca = emit_copy_in(ctx, opts.get("COMMAREA"), materialised)
            if r_ca is None:
                r_ca = ctx.fresh_reg()
                ctx.emit_inst(Const(result_reg=r_ca, value=b"", type_expr=UNKNOWN))
            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName("__cics_set_xctl_context"),
                    args=(r_prog, r_ca),
                )
            )
            ctx.emit_inst(Return_())
            return

        if verb == "ABEND":
            abcode = opts.get("ABCODE")
            r_code = ctx.fresh_reg()
            ctx.emit_inst(
                Const.string(r_code, abcode.text if abcode is not None else "UNKN")
            )
            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName("__cics_abend"),
                    args=(r_code,),
                )
            )
            ctx.emit_inst(Return_())
            return

        if verb == "START":
            r_transid = emit_operand_value(ctx, opts.get("TRANSID"), materialised)
            r_data = emit_copy_in(ctx, opts.get("FROM"), materialised)
            if r_data is None:
                r_data = ctx.fresh_reg()
                ctx.emit_inst(Const(result_reg=r_data, value=b"", type_expr=UNKNOWN))
            r_termid = emit_operand_value(ctx, opts.get("TERMID"), materialised)
            r_reqid = emit_operand_value(ctx, opts.get("REQID"), materialised)
            r_timing = ctx.fresh_reg()
            ctx.emit_inst(Const.string(r_timing, _timing_text(opts)))
            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName("__cics_start"),
                    args=(r_transid, r_data, r_termid, r_reqid, r_timing),
                )
            )
            emit_resp_writeback(ctx, r_res, opts, materialised)
            emit_raise_tail(ctx, opts, materialised)
            return

        if verb == "RETRIEVE":
            into_off, into_len = _resolve_into(ctx, opts.get("INTO"), materialised)
            r_off = ctx.fresh_reg()
            ctx.emit_inst(Const.int_(r_off, into_off))
            r_len = ctx.fresh_reg()
            ctx.emit_inst(Const.int_(r_len, into_len))
            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName("__cics_retrieve"),
                    args=(r_off, r_len),
                )
            )
            emit_resp_writeback(ctx, r_res, opts, materialised)
            emit_raise_tail(ctx, opts, materialised)
            return

        # ── BMS screen verbs ──────────────────────────────────────────────
        bms_builtin = _BMS_VERBS.get(verb)
        if bms_builtin:
            if verb == "SEND TEXT":
                text_op = opts.get("TEXT")
                r_text = ctx.fresh_reg()
                ctx.emit_inst(
                    Const.string(r_text, text_op.text if text_op is not None else "")
                )
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName(bms_builtin),
                        args=(r_text,),
                    )
                )
                return
            # MAP name (may be a dynamic data-name) -> runtime value via the resolver.
            map_op = opts.get("MAP", opts.get("MAPNAME"))
            r_map = emit_operand_value(ctx, map_op, materialised)
            # The symbolic group is the STATIC FROM (SEND) / INTO (RECEIVE) operand.
            # When omitted, BMS uses the map's own DSECT, named <mapname><suffix>
            # (e.g. RECEIVE MAP('COSGN0A') with no INTO -> COSGN0AI); derivable
            # only for a literal map name (a dynamic map always supplies FROM/INTO).
            if verb == "RECEIVE MAP":
                group_op, suffix = opts.get("INTO"), "I"
            else:  # SEND MAP
                group_op, suffix = opts.get("FROM"), "O"
            if group_op is not None:
                group_name = group_op.text
            elif map_op is not None and map_op.is_literal:
                group_name = map_op.text + suffix
            else:
                group_name = ""
            leaves = (
                ctx.group_leaf_names(group_name, materialised) if group_name else []
            )
            base_names = [n[: -len(suffix)] for n in leaves if n.endswith(suffix)]
            r_names = ctx.fresh_reg()
            ctx.emit_inst(
                Const(result_reg=r_names, value=base_names, type_expr=UNKNOWN)
            )

            if verb == "RECEIVE MAP" and self._conversational:
                # Conversational: SUSPEND (yield the map name to the resume driver),
                # then apply the InputEvent the driver injects into the WS fields.
                r_evt = ctx.fresh_reg()
                ctx.emit_inst(Suspend(result_reg=r_evt, operand_reg=r_map))
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName("__cics_apply_input"),
                        args=(r_evt, r_names),
                    )
                )
                emit_resp_writeback(ctx, r_res, opts, materialised)
                emit_raise_tail(ctx, opts, materialised)
                return

            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName(bms_builtin),
                    args=(r_map, r_names),
                )
            )
            emit_resp_writeback(ctx, r_res, opts, materialised)
            emit_raise_tail(ctx, opts, materialised)
            return

        # ── ASSIGN / FORMATTIME: write each output sub-option to its field ──
        if verb == "ASSIGN":
            for subopt in ASSIGN_SUBOPTIONS:
                field_name = opts.get(subopt)
                if field_name is None:
                    continue
                r_key = ctx.fresh_reg()
                ctx.emit_inst(Const.string(r_key, subopt))
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName("__cics_assign"),
                        args=(r_key,),
                    )
                )
                str_reg = ctx.emit_to_string(r_res)
                emit_copy_back_str(ctx, field_name, str_reg, materialised)
            return

        if verb == "FORMATTIME":
            r_sep = ctx.fresh_reg()
            ctx.emit_inst(Const.string(r_sep, _date_separator(opts)))
            for subopt in _FORMATTIME_OUTPUTS:
                field_name = opts.get(subopt)
                if field_name is None:
                    continue
                r_key = ctx.fresh_reg()
                ctx.emit_inst(Const.string(r_key, subopt))
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName("__cics_formattime"),
                        args=(r_key, r_sep),
                    )
                )
                str_reg = ctx.emit_to_string(r_res)
                emit_copy_back_str(ctx, field_name, str_reg, materialised)
            return

        # ── VSAM point operations ─────────────────────────────────────────
        if verb in _VSAM_POINT_VERBS:
            # FILE(...) and DATASET(...) are synonyms; the operand may be a
            # literal or a data-name (resolved to its runtime value).
            r_file = emit_operand_value(
                ctx, opts.get("FILE") or opts.get("DATASET"), materialised
            )
            r_key = emit_copy_in(ctx, opts.get("RIDFLD"), materialised)
            if r_key is None:
                r_key = ctx.fresh_reg()
                ctx.emit_inst(Const(result_reg=r_key, value=b"", type_expr=UNKNOWN))
            klen = _resolve_keylen(ctx, opts, materialised)
            r_klen = ctx.fresh_reg()
            ctx.emit_inst(Const.int_(r_klen, klen))

            if verb == "READ":
                into_off, into_len = _resolve_into(ctx, opts.get("INTO"), materialised)
                r_off = ctx.fresh_reg()
                ctx.emit_inst(Const.int_(r_off, into_off))
                r_len = ctx.fresh_reg()
                ctx.emit_inst(Const.int_(r_len, into_len))
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName("__cics_read"),
                        args=(r_file, r_key, r_klen, r_off, r_len),
                    )
                )
            elif verb in ("WRITE", "REWRITE"):
                r_rec = emit_copy_in(ctx, opts.get("FROM"), materialised)
                if r_rec is None:
                    r_rec = ctx.fresh_reg()
                    ctx.emit_inst(Const(result_reg=r_rec, value=b"", type_expr=UNKNOWN))
                name = "__cics_write" if verb == "WRITE" else "__cics_rewrite"
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName(name),
                        args=(r_file, r_key, r_klen, r_rec),
                    )
                )
            else:  # DELETE
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName("__cics_delete"),
                        args=(r_file, r_key, r_klen),
                    )
                )
            emit_resp_writeback(ctx, r_res, opts, materialised)
            emit_raise_tail(ctx, opts, materialised)
            return

        # ── VSAM browse operations (implicit single cursor per file) ───────
        if verb in _VSAM_BROWSE_VERBS:
            # FILE(...) and DATASET(...) are synonyms; the operand may be a
            # literal or a data-name (resolved to its runtime value).
            r_file = emit_operand_value(
                ctx, opts.get("FILE") or opts.get("DATASET"), materialised
            )
            if verb == "STARTBR":
                r_key = emit_copy_in(ctx, opts.get("RIDFLD"), materialised)
                if r_key is None:
                    r_key = ctx.fresh_reg()
                    ctx.emit_inst(Const(result_reg=r_key, value=b"", type_expr=UNKNOWN))
                klen = _resolve_keylen(ctx, opts, materialised)
                r_klen = ctx.fresh_reg()
                ctx.emit_inst(Const.int_(r_klen, klen))
                r_start = ctx.fresh_reg()
                ctx.emit_inst(Const.string(r_start, _browse_start(opts).name))
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName("__cics_startbr"),
                        args=(r_file, r_key, r_klen, r_start),
                    )
                )
            elif verb in ("READNEXT", "READPREV"):
                into_off, into_len = _resolve_into(ctx, opts.get("INTO"), materialised)
                r_off = ctx.fresh_reg()
                ctx.emit_inst(Const.int_(r_off, into_off))
                r_len = ctx.fresh_reg()
                ctx.emit_inst(Const.int_(r_len, into_len))
                name = "__cics_readnext" if verb == "READNEXT" else "__cics_readprev"
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName(name),
                        args=(r_file, r_off, r_len),
                    )
                )
            else:  # ENDBR
                r_res = ctx.fresh_reg()
                ctx.emit_inst(
                    CallFunction(
                        result_reg=r_res,
                        func_name=FuncName("__cics_endbr"),
                        args=(r_file,),
                    )
                )
            emit_resp_writeback(ctx, r_res, opts, materialised)
            emit_raise_tail(ctx, opts, materialised)
            return

        # ── WRITEQ TD ────────────────────────────────────────────────────
        if verb == "WRITEQ TD":
            r_from = emit_operand_value(ctx, opts.get("FROM"), materialised)
            r_queue = emit_operand_value(ctx, opts.get("QUEUE"), materialised)
            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName("__cics_writeq_td"),
                    args=(r_from, r_queue),
                )
            )
            emit_resp_writeback(ctx, r_res, opts, materialised)
            emit_raise_tail(ctx, opts, materialised)
            return

        # ── Condition handler registration ────────────────────────────────
        if verb in ("HANDLE CONDITION", "IGNORE CONDITION"):
            handles = verb == "HANDLE CONDITION"
            for condition, operand in opts.items():
                slot = condition_slot(verb, condition)
                index = (
                    self._handler_labels.index_of(operand.text)
                    if handles and operand is not None
                    else 0
                )
                r_idx = ctx.fresh_reg()
                ctx.emit_inst(Const.int_(r_idx, index))
                emit_indexed_write(
                    ctx, "DFH-HANDLER", slot, ctx.emit_to_string(r_idx), materialised
                )
                # Handler index 0 already means "never registered", whose dispatch
                # action is the system default (abend). IGNORE must not collapse
                # into that, so the ignored/default distinction lives in the
                # raisable flag: an ignored condition simply stops being raised,
                # which is precisely "no action taken". HANDLE re-arms the flag so
                # a HANDLE after an IGNORE works again — but only for conditions
                # this runtime actually raises, since writing 'Y' unconditionally
                # would widen RAISABLE past the set cics.conditions declares.
                if condition in RAISABLE:
                    r_flag = ctx.fresh_reg()
                    ctx.emit_inst(Const.string(r_flag, "Y" if handles else "N"))
                    emit_indexed_write(ctx, "DFH-RAISABLE", slot, r_flag, materialised)
                elif handles:
                    logger.warning(
                        "EXEC CICS HANDLE CONDITION %s(%s) registers a handler "
                        "this runtime can never dispatch to: %s is not among the "
                        "conditions it raises (cics.conditions.RAISABLE). The "
                        "command that fails with %s will write EIBRESP and "
                        "continue inline.",
                        condition,
                        getattr(operand, "text", ""),
                        condition,
                        condition,
                    )
            return

        # ── System verbs ──────────────────────────────────────────────────
        builtin_name = _SYS_VERBS.get(verb)
        if builtin_name:
            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName(builtin_name),
                    args=(),
                )
            )
            if verb in _RESP_PRODUCING_VERBS:
                emit_resp_writeback(ctx, r_res, opts, materialised)
                emit_raise_tail(ctx, opts, materialised)
            return

        # ── LINK ─────────────────────────────────────────────────────────────
        if verb == "LINK":
            r_prog = emit_operand_value(ctx, opts.get("PROGRAM"), materialised)
            ca_op = opts.get("COMMAREA")
            if ca_op is not None and ctx.has_field(ca_op.text, materialised):
                r_ca = emit_copy_in(ctx, ca_op, materialised)
                if r_ca is None:
                    r_ca = ctx.fresh_reg()
                    ctx.emit_inst(Const(result_reg=r_ca, value=b"", type_expr=UNKNOWN))
                ca_offset, ca_len = _resolve_into(ctx, ca_op, materialised)
            else:
                r_ca = ctx.fresh_reg()
                ctx.emit_inst(Const(result_reg=r_ca, value=b"", type_expr=UNKNOWN))
                ca_offset, ca_len = 0, 0
            ca_len = _resolve_cics_length_option(
                opts.get("LENGTH"), ca_len, ctx, materialised
            )
            r_off = ctx.fresh_reg()
            ctx.emit_inst(Const.int_(r_off, ca_offset))
            r_len = ctx.fresh_reg()
            ctx.emit_inst(Const.int_(r_len, ca_len))
            r_res = ctx.fresh_reg()
            ctx.emit_inst(
                CallFunction(
                    result_reg=r_res,
                    func_name=FuncName("__cics_link"),
                    args=(r_prog, r_ca, r_off, r_len),
                )
            )
            emit_resp_writeback(ctx, r_res, opts, materialised)
            emit_raise_tail(ctx, opts, materialised)
            return

        self._unsupported_verbs.add(verb)
        logger.warning(
            "CicsLoweringStrategy: unimplemented verb %r — emitting an abend", verb
        )
        r_verb = ctx.fresh_reg()
        ctx.emit_inst(Const.string(r_verb, verb))
        ctx.emit_inst(
            CallFunction(
                result_reg=ctx.fresh_reg(),
                func_name=FuncName("__cics_abend_unsupported"),
                args=(r_verb,),
            )
        )
        # Ends the task, as EXEC CICS ABEND's own lowering does. Without it the
        # program runs on into whatever followed the unsupported statement and
        # that statement's own result overwrites the abend.
        ctx.emit_inst(Return_())

    def _emit_decode_eibresp(
        self, ctx: "EmitContext", materialised: "MaterialisedSectionedLayout"
    ) -> "Register":
        ref, region_reg = ctx.resolve_field_ref("EIBRESP", materialised)
        return ctx.emit_decode_field(
            region_reg, ref.fl, ref.offset_reg, extent=ref.extent
        )

    def _emit_dispatcher(
        self, ctx: "EmitContext", materialised: "MaterialisedSectionedLayout"
    ) -> None:
        """One per program. Entered by a Branch, so it takes no arguments: it
        reads EIBRESP, which emit_resp_writeback has already written."""
        ctx.emit_inst(Label_(label=CodeLabel("__cics_cond_dispatch")))
        ref, region_reg = ctx.resolve_field_ref(
            "DFH-HANDLER",
            materialised,
            subscripts=(BinOpNode("+", FieldRefNode("EIBRESP"), LiteralNode("1")),),
        )
        idx_reg = ctx.emit_decode_field(
            region_reg, ref.fl, ref.offset_reg, extent=ref.extent
        )
        for name, index in self._handler_labels.indices.items():
            k_reg = ctx.const_to_reg(index)
            cmp_reg = ctx.fresh_reg()
            ctx.emit_inst(
                Binop(
                    result_reg=cmp_reg,
                    operator=resolve_binop("=="),
                    left=Register(str(idx_reg)),
                    right=Register(str(k_reg)),
                )
            )
            match_lbl = ctx.fresh_label("cond_match")
            next_lbl = ctx.fresh_label("cond_next")
            ctx.emit_inst(
                BranchIf(cond_reg=cmp_reg, branch_targets=(match_lbl, next_lbl))
            )
            ctx.emit_inst(Label_(label=match_lbl))
            ctx.emit_inst(Branch(label=CodeLabel(f"para_{name}")))
            ctx.emit_inst(Label_(label=next_lbl))
        r_resp = self._emit_decode_eibresp(ctx, materialised)
        ctx.emit_inst(
            CallFunction(
                result_reg=ctx.fresh_reg(),
                func_name=FuncName("__cics_abend_unhandled"),
                args=(r_resp,),
            )
        )
        ctx.emit_inst(Return_())

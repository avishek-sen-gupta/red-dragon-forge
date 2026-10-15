"""Unit tests for CICS system service builtins."""

from tests.covers import covers, NotLanguageFeature
from cics.builtins.system import (
    make_assign_builtin,
    make_asktime_builtin,
    make_formattime_builtin,
    make_writeq_td_builtin,
    make_handle_abend_builtin,
    make_handle_noop_builtin,
    make_abend_builtin,
    make_abend_unhandled_builtin,
    make_abend_unsupported_builtin,
    make_inquire_builtin,
)
from cics.types import DispatchKind, DispatchResult
from interpreter.vm.vm_types import VMState, BuiltinResult
from interpreter.types.typed_value import typed
from interpreter.types.type_expr import UNKNOWN


def _vm() -> VMState:
    return VMState()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_assign_builtin_is_callable():
    builtin = make_assign_builtin(applid="CARDDEMO", sysid="SYS1")
    result = builtin([], _vm())
    assert isinstance(result, BuiltinResult)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_assign_builtin_returns_applid_for_applid_key():
    builtin = make_assign_builtin(applid="CARDDEMO", sysid="SYS1")
    result = builtin([typed("APPLID", UNKNOWN)], _vm())
    assert isinstance(result, BuiltinResult)
    assert result.value == "CARDDEMO"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_assign_builtin_returns_sysid_for_sysid_key():
    builtin = make_assign_builtin(applid="CARDDEMO", sysid="SYS1")
    result = builtin([typed("SYSID", UNKNOWN)], _vm())
    assert result.value == "SYS1"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_assign_builtin_returns_empty_for_unknown_key():
    builtin = make_assign_builtin(applid="CARDDEMO", sysid="SYS1")
    result = builtin([typed("BOGUS", UNKNOWN)], _vm())
    assert result.value == ""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_asktime_builtin_returns_positive_integer():
    builtin = make_asktime_builtin()
    result = builtin([], _vm())
    assert isinstance(result, BuiltinResult)
    assert isinstance(result.value, int)
    assert result.value > 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_formattime_builtin_returns_yyyymmdd():
    import re

    builtin = make_formattime_builtin()
    result = builtin([], _vm())
    assert isinstance(result, BuiltinResult)
    assert re.fullmatch(
        r"\d{8}", str(result.value)
    ), f"Expected YYYYMMDD, got {result.value!r}"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_formattime_builtin_returns_yyyymmdd_for_key():
    import re

    builtin = make_formattime_builtin()
    result = builtin([typed("YYYYMMDD", UNKNOWN)], _vm())
    assert isinstance(result, BuiltinResult)
    assert re.fullmatch(
        r"\d{8}", str(result.value)
    ), f"Expected YYYYMMDD, got {result.value!r}"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_formattime_builtin_returns_time_for_time_key():
    import re

    builtin = make_formattime_builtin()
    result = builtin([typed("TIME", UNKNOWN)], _vm())
    assert re.fullmatch(
        r"\d{6}", str(result.value)
    ), f"Expected HHMMSS, got {result.value!r}"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_writeq_td_appends_to_queue():
    queue: list[str] = []
    builtin = make_writeq_td_builtin(queue.append)
    args = [typed("SOME DATA", UNKNOWN), typed("CSMT", UNKNOWN)]
    builtin(args, _vm())
    assert len(queue) == 1
    assert "SOME DATA" in queue[0]
    assert "CSMT" in queue[0]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_handle_abend_is_noop():
    builtin = make_handle_abend_builtin()
    result = builtin([], _vm())
    assert isinstance(result, BuiltinResult)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_handle_noop_builtin_is_callable_noop():
    # HANDLE CONDITION / HANDLE AID are explicit no-ops for now (deferred to the
    # HANDLE-machinery follow-up). They must ignore their registration args and
    # return cleanly without touching VM state.
    builtin = make_handle_noop_builtin("HANDLE CONDITION")
    result = builtin([typed("PGMIDERR", UNKNOWN), typed("ERR-PARA", UNKNOWN)], _vm())
    assert isinstance(result, BuiltinResult)
    assert result.value is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_abend_builtin_sets_dispatch_result():
    holder: list[DispatchResult | None] = [None]
    builtin = make_abend_builtin(holder)
    args = [typed("CICS", UNKNOWN)]
    builtin(args, _vm())
    assert holder[0] is not None
    assert holder[0].kind == DispatchKind.ABEND
    assert holder[0].abcode == "CICS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_abend_builtin_default_on_abend_is_a_noop():
    """Forward regression guard: no composed SQL runtime supplied a rollback
    callable -- must not raise. (This already held before on_abend existed;
    it is not sensitive to the on_abend wiring itself.)"""
    holder: list[DispatchResult | None] = [None]
    builtin = make_abend_builtin(holder)

    builtin([typed("CICS", UNKNOWN)], _vm())

    assert holder[0].kind == DispatchKind.ABEND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_abend_builtin_records_the_abend_even_when_on_abend_raises():
    """forge-6jj's failure shape, reintroduced in the abend path itself: an
    unknown-program XCTL once abended internally but crashed the driver
    instead of painting the abend on screen. A raising rollback callable (a
    dropped Db2 connection, say) must not do the same -- result_holder must
    already carry the ABEND DispatchResult before on_abend runs, and a raise
    from on_abend must not propagate past this builtin."""
    holder: list[DispatchResult | None] = [None]

    def _boom() -> None:
        raise RuntimeError("db2 connection dropped")

    builtin = make_abend_builtin(holder, on_abend=_boom)

    builtin([typed("CICS", UNKNOWN)], _vm())  # must not raise

    assert holder[0].kind == DispatchKind.ABEND
    assert holder[0].abcode == "CICS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_abend_unhandled_builtin_records_the_abend_even_when_on_abend_raises():
    holder: list[DispatchResult | None] = [None]

    def _boom() -> None:
        raise RuntimeError("db2 connection dropped")

    builtin = make_abend_unhandled_builtin(holder, on_abend=_boom)

    builtin([typed(27, UNKNOWN)], _vm())  # must not raise

    assert holder[0].kind == DispatchKind.ABEND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_abend_unsupported_builtin_records_the_abend_even_when_on_abend_raises():
    holder: list[DispatchResult | None] = [None]

    def _boom() -> None:
        raise RuntimeError("db2 connection dropped")

    builtin = make_abend_unsupported_builtin(holder, on_abend=_boom)

    builtin([typed("FOO", UNKNOWN)], _vm())  # must not raise

    assert holder[0].kind == DispatchKind.ABEND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_abend_builtin_calls_on_abend():
    """A half-finished task's writes must not stay pending until some
    unrelated later task's RETURN commits them -- EXEC CICS ABEND must run
    the composed rollback callable (task-6 brief)."""
    calls: list[int] = []
    holder: list[DispatchResult | None] = [None]
    builtin = make_abend_builtin(holder, on_abend=lambda: calls.append(1))

    builtin([typed("CICS", UNKNOWN)], _vm())

    assert calls == [1]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_abend_unhandled_builtin_calls_on_abend():
    calls: list[int] = []
    holder: list[DispatchResult | None] = [None]
    builtin = make_abend_unhandled_builtin(holder, on_abend=lambda: calls.append(1))

    builtin([typed(27, UNKNOWN)], _vm())

    assert calls == [1]
    assert holder[0].kind == DispatchKind.ABEND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_abend_unsupported_builtin_calls_on_abend():
    calls: list[int] = []
    holder: list[DispatchResult | None] = [None]
    builtin = make_abend_unsupported_builtin(holder, on_abend=lambda: calls.append(1))

    builtin([typed("FOO", UNKNOWN)], _vm())

    assert calls == [1]
    assert holder[0].kind == DispatchKind.ABEND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_inquire_program_found():
    cache = {"COSGN00C": object()}
    builtin = make_inquire_builtin(cache)
    args = [typed("COSGN00C", UNKNOWN)]
    result = builtin(args, _vm())
    assert isinstance(result, BuiltinResult)
    assert result.value == 0  # NORMAL


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_inquire_program_not_found():
    cache: dict = {}
    builtin = make_inquire_builtin(cache)
    args = [typed("MISSING", UNKNOWN)]
    result = builtin(args, _vm())
    assert result.value == 27  # PGMIDERR


def _formatted(*args: str) -> str:
    return str(
        make_formattime_builtin()([typed(a, UNKNOWN) for a in args], _vm()).value
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_formattime_ddmmyyyy_puts_the_day_first():
    import re

    assert re.fullmatch(r"\d{8}", _formatted("DDMMYYYY"))
    assert _formatted("DDMMYYYY")[4:] == _formatted("YYYYMMDD")[:4]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_formattime_ddmmyy_uses_a_two_digit_year():
    import re

    assert re.fullmatch(r"\d{6}", _formatted("DDMMYY"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_formattime_year_returns_four_digits():
    assert _formatted("YEAR") == _formatted("YYYYMMDD")[:4]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_formattime_datesep_separates_the_date_parts():
    import re

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _formatted("YYYYMMDD", "-"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_formattime_datesep_does_not_reach_the_time():
    import re

    assert re.fullmatch(r"\d{6}", _formatted("TIME", "-"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_formattime_warns_on_an_unimplemented_suboption(caplog):
    _formatted("MILLISECONDS")

    assert "MILLISECONDS" in caplog.text


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_assign_builtin_returns_the_configured_userid():
    builtin = make_assign_builtin(applid="CARDDEMO", sysid="SYS1", userid="TESTUSR1")

    assert builtin([typed("USERID", UNKNOWN)], _vm()).value == "TESTUSR1"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_assign_builtin_warns_on_an_unimplemented_suboption(caplog):
    make_assign_builtin()([typed("NETNAME", UNKNOWN)], _vm())

    assert "NETNAME" in caplog.text

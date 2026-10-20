"""FORMATTIME as IR: an ABSTIME's calendar date and time of day, rendered per output option."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from types import MappingProxyType

from cics.dat_form import DatForm
from interpreter.cobol.cobol_constants import BuiltinName
from interpreter.cobol.ir_emitter import IrEmitter
from interpreter.register import Register

_MS_PER_DAY = 86_400_000
_MS_PER_HOUR = 3_600_000
_MS_PER_MINUTE = 60_000
_MS_PER_SECOND = 1_000
_DAYS_TO_CIVIL_EPOCH = 693_901
_DAYS_PER_ERA = 146_097


@dataclass(frozen=True)
class _Parts:
    """Each date and time part as text: zero-padded, the year in two and four digits."""

    yyyy: Register
    yy: Register
    mm: Register
    dd: Register
    hh: Register
    mi: Register
    ss: Register


@dataclass(frozen=True)
class FormattedTime:
    """One ABSTIME's outputs, emitted on request, joined by the statement's separators."""

    e: IrEmitter
    parts: _Parts
    year: Register
    separators: tuple[Register, Register]

    def output(self, suboption: str) -> Register:
        return _OUTPUTS[suboption](self)

    def date(self, order: Callable[[_Parts], Sequence[Register]]) -> Register:
        return _joined(self.e, order(self.parts), self.separators[0])

    def by_datform(self, two_digit: bool) -> Register:
        datform = self.e.call("__cics_datform")
        orders = _DATFORM_ORDERS if two_digit else _FULL_DATFORM_ORDERS
        return self.e.choose(
            "datform_date",
            self.date(orders[DatForm.MMDDYY]),
            self.e.binop("==", datform, self.e.text(DatForm.MMDDYY.value)),
            lambda: self.e.choose(
                "datform_date_dd",
                self.date(orders[DatForm.DDMMYY]),
                self.e.binop("==", datform, self.e.text(DatForm.DDMMYY.value)),
                lambda: self.date(orders[DatForm.YYMMDD]),
            ),
        )

    def time(self) -> Register:
        parts = self.parts
        return _joined(self.e, (parts.hh, parts.mi, parts.ss), self.separators[1])


def _joined(e: IrEmitter, parts: Sequence[Register], separator: Register) -> Register:
    first, *rest = parts
    return reduce(
        lambda joined, part: e.call(
            BuiltinName.STRING_CONCAT_PAIR,
            e.call(BuiltinName.STRING_CONCAT_PAIR, joined, separator),
            part,
        ),
        rest,
        first,
    )


def _text(e: IrEmitter, value: Register) -> Register:
    return e.call(BuiltinName.COBOL_TO_TEXT, value)


def _two_digits(e: IrEmitter, value: Register) -> Register:
    padded = _text(e, e.binop("+", value, e.int_(100)))
    return e.call(BuiltinName.STRING_SLICE, padded, e.int_(1), e.int_(2))


def _div(e: IrEmitter, value: Register, by: int) -> Register:
    return e.binop("//", value, e.int_(by))


def _year_of_era(e: IrEmitter, doe: Register) -> Register:
    leap_terms = e.binop(
        "-",
        e.binop("+", e.binop("-", doe, _div(e, doe, 1460)), _div(e, doe, 36524)),
        _div(e, doe, 146096),
    )
    return _div(e, leap_terms, 365)


def _day_of_year(e: IrEmitter, doe: Register, yoe: Register) -> Register:
    year_start = e.binop(
        "-",
        e.binop("+", e.binop("*", yoe, e.int_(365)), _div(e, yoe, 4)),
        _div(e, yoe, 100),
    )
    return e.binop("-", doe, year_start)


def _month_and_day(e: IrEmitter, doy: Register) -> tuple[Register, Register]:
    mp = _div(e, e.binop("+", e.binop("*", doy, e.int_(5)), e.int_(2)), 153)
    month_start = _div(e, e.binop("+", e.binop("*", mp, e.int_(153)), e.int_(2)), 5)
    day = e.binop("+", e.binop("-", doy, month_start), e.int_(1))
    month = e.binop(
        "+", e.binop("%", e.binop("+", mp, e.int_(2)), e.int_(12)), e.int_(1)
    )
    return month, day


def _civil_date(e: IrEmitter, days: Register) -> tuple[Register, Register, Register]:
    z = e.binop("+", days, e.int_(_DAYS_TO_CIVIL_EPOCH))
    era = _div(e, z, _DAYS_PER_ERA)
    doe = e.binop("-", z, e.binop("*", era, e.int_(_DAYS_PER_ERA)))
    yoe = _year_of_era(e, doe)
    month, day = _month_and_day(e, _day_of_year(e, doe, yoe))
    january_or_february = _div(e, e.binop("-", e.int_(14), month), 12)
    year = e.binop(
        "+",
        e.binop("+", yoe, e.binop("*", era, e.int_(400))),
        january_or_february,
    )
    return year, month, day


def _clock(e: IrEmitter, ms_of_day: Register) -> tuple[Register, Register, Register]:
    hour = _div(e, ms_of_day, _MS_PER_HOUR)
    minute = e.binop("%", _div(e, ms_of_day, _MS_PER_MINUTE), e.int_(60))
    second = e.binop("%", _div(e, ms_of_day, _MS_PER_SECOND), e.int_(60))
    return hour, minute, second


def emit_formatted_time(
    e: IrEmitter, abstime: Register, separators: tuple[Register, Register]
) -> FormattedTime:
    days = _div(e, abstime, _MS_PER_DAY)
    year, month, day = _civil_date(e, days)
    hour, minute, second = _clock(e, e.binop("%", abstime, e.int_(_MS_PER_DAY)))
    parts = _Parts(
        yyyy=_text(e, year),
        yy=_two_digits(e, e.binop("%", year, e.int_(100))),
        mm=_two_digits(e, month),
        dd=_two_digits(e, day),
        hh=_two_digits(e, hour),
        mi=_two_digits(e, minute),
        ss=_two_digits(e, second),
    )
    return FormattedTime(e, parts, year, separators)


_DATFORM_ORDERS: Mapping[DatForm, Callable[[_Parts], Sequence[Register]]] = (
    MappingProxyType(
        {
            DatForm.MMDDYY: lambda p: (p.mm, p.dd, p.yy),
            DatForm.DDMMYY: lambda p: (p.dd, p.mm, p.yy),
            DatForm.YYMMDD: lambda p: (p.yy, p.mm, p.dd),
        }
    )
)

_FULL_DATFORM_ORDERS: Mapping[DatForm, Callable[[_Parts], Sequence[Register]]] = (
    MappingProxyType(
        {
            DatForm.MMDDYY: lambda p: (p.mm, p.dd, p.yyyy),
            DatForm.DDMMYY: lambda p: (p.dd, p.mm, p.yyyy),
            DatForm.YYMMDD: lambda p: (p.yyyy, p.mm, p.dd),
        }
    )
)

_OUTPUTS: Mapping[str, Callable[[FormattedTime], Register]] = MappingProxyType(
    {
        "YYYYMMDD": lambda f: f.date(lambda p: (p.yyyy, p.mm, p.dd)),
        "DDMMYYYY": lambda f: f.date(lambda p: (p.dd, p.mm, p.yyyy)),
        "YYMMDD": lambda f: f.date(lambda p: (p.yy, p.mm, p.dd)),
        "DDMMYY": lambda f: f.date(lambda p: (p.dd, p.mm, p.yy)),
        "MMDDYY": lambda f: f.date(lambda p: (p.mm, p.dd, p.yy)),
        "DATE": lambda f: f.by_datform(two_digit=True),
        "FULLDATE": lambda f: f.by_datform(two_digit=False),
        "DATEFORM": lambda f: f.e.call("__cics_datform"),
        "TIME": lambda f: f.time(),
        "YEAR": lambda f: f.year,
    }
)

FORMATTIME_OUTPUTS: tuple[str, ...] = tuple(_OUTPUTS)

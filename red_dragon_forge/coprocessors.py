"""The coprocessors a build may name, and the check that each one's required programs are linked."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from cics.coprocessor import build_cics_spec
from interpreter.project.coprocessor_compile import CoprocessorSpec
from squall.coprocessor import build_sql_spec
from squall.db2_stubs import DB2_STUB_PROGRAMS

from red_dragon_forge.coprocessor import Coprocessor
from red_dragon_forge.coprocessor_name import CoprocessorName
from red_dragon_forge.missing_required_program import MissingRequiredProgram


def _conversational_cics() -> CoprocessorSpec:
    return build_cics_spec(conversational=True)


def _cics() -> CoprocessorSpec:
    return build_cics_spec()


COPROCESSORS: Mapping[CoprocessorName, Coprocessor] = {
    coprocessor.name: coprocessor
    for coprocessor in (
        Coprocessor("sql", build_sql_spec, DB2_STUB_PROGRAMS),
        Coprocessor("cics", _cics, ()),
        Coprocessor("cics-conversational", _conversational_cics, ()),
    )
}


def require_linked(
    coprocessors: Sequence[CoprocessorName], linked: Collection[str], where: str
) -> None:
    missing = tuple(
        (name, program)
        for name in coprocessors
        for program in COPROCESSORS[name].required
        if program not in linked
    )
    if missing:
        raise MissingRequiredProgram(
            "; ".join(
                f"coprocessor {name} requires {program} in {where}"
                for name, program in missing
            )
        )

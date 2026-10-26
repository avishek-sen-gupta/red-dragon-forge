"""env.toml picks its mode by the one section present, and stops naming any fault before anything runs."""

from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

import pytest
from cics.dat_form import DatForm
from cics.region_clock import LOCAL_CLOCK
from litter.manifest import Manifest
from litter.transaction import Transaction

from red_dragon_forge.cics_command import CicsEnv
from red_dragon_forge.cics_run import CicsRun
from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.env_config import EnvConfig, load_env_config, run_mode
from red_dragon_forge.jcl_command import JclEnv
from red_dragon_forge.jcl_run import JclRun
from red_dragon_forge.plain_command import PlainEnv
from red_dragon_forge.plain_run import PlainRun
from red_dragon_forge.run_mode import RunMode
from red_dragon_forge.tolerant_section import TolerantSection

_TOP = 'package = "out/app.zip"\n[paths]\nsystem = "system"\n'
_PLAIN = '[plain]\nprogram = "CBXXXX"\n[plain.files]\nACCTFILE = "APP.ACCT"\n'
_JCL = '[jcl]\njob = "jcl/READ.jcl"\n'
_CICS = '[cics]\ninitial_transid = "CC00"\n'
_MANIFEST = Manifest(
    programs=("CBACT01C", "COSGN00C"),
    coprocessors=("cics", "sql"),
    transactions=(
        Transaction("CC00", "COSGN00C"),
        Transaction("CT02", "COTRN02C"),
    ),
    files=(),
    mapsets=(),
)


_ENV_OF: Mapping[RunMode, type[PlainEnv | JclEnv | CicsEnv]] = {
    RunMode.PLAIN: PlainEnv,
    RunMode.JCL: JclEnv,
    RunMode.CICS: CicsEnv,
}


def _written(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "env.toml"
    path.write_text(text)
    return path


def _loaded(path: Path) -> EnvConfig:
    return load_env_config(path, _ENV_OF[run_mode(path)])


def _section(path: Path) -> PlainRun | JclRun | CicsRun:
    match _loaded(path):
        case PlainEnv(plain=plain):
            return plain
        case JclEnv(jcl=jcl):
            return jcl
        case CicsEnv(cics=cics):
            return cics
        case _:
            raise AssertionError(f"{path} names no mode")


@pytest.mark.parametrize(
    ("sections", "message"),
    [
        ("", "env.toml: exactly one of [plain], [jcl], [cics] is required; found none"),
        (
            _PLAIN + _JCL,
            "env.toml: exactly one of [plain], [jcl], [cics] is required;"
            " found [plain], [jcl]",
        ),
        ("[cics]\nport = 3271\n", "env.toml: [cics] initial_transid is required"),
    ],
)
def test_an_env_toml_without_one_runnable_mode_names_its_fault(
    tmp_path: Path, sections: str, message: str
) -> None:
    with pytest.raises(ConfigError) as refused:
        _loaded(_written(tmp_path, _TOP + sections))

    assert str(refused.value) == message


def test_the_section_present_picks_the_mode(tmp_path: Path) -> None:
    plain = _section(_written(tmp_path, _TOP + _PLAIN))
    jcl = _section(_written(tmp_path, _TOP + _JCL))
    cics = _section(_written(tmp_path, _TOP + _CICS))

    assert (plain, jcl, cics) == (
        PlainRun(program="CBXXXX", files={"ACCTFILE": "APP.ACCT"}),
        JclRun(job=Path("jcl/READ.jcl")),
        CicsRun(initial_transid="CC00"),
    )


def test_tolerances_are_off_unless_named(tmp_path: Path) -> None:
    unnamed = _loaded(_written(tmp_path, _TOP + _PLAIN)).tolerant
    named = _loaded(
        _written(
            tmp_path,
            _TOP
            + "[tolerant]\npermit_unresolved_call_targets = true\n"
            + "permit_missing_host_variables = true\n"
            + _PLAIN,
        )
    ).tolerant

    assert (unnamed, named) == (
        TolerantSection(
            permit_unresolved_call_targets=False, permit_missing_host_variables=False
        ),
        TolerantSection(
            permit_unresolved_call_targets=True, permit_missing_host_variables=True
        ),
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "tolerant = true\n" + _TOP + _PLAIN,
            "env.toml: tolerant: Input should be a valid dictionary or instance of"
            " TolerantSection",
        ),
        (
            "[plain\n",
            "env.toml: Expected ']' at the end of a table declaration (at line 1, column 7)",
        ),
    ],
)
def test_an_env_toml_that_does_not_parse_names_its_fault(
    tmp_path: Path, text: str, message: str
) -> None:
    with pytest.raises(ConfigError) as refused:
        _loaded(_written(tmp_path, text))

    assert str(refused.value) == message


@pytest.mark.parametrize(
    ("sections", "message"),
    [
        (_PLAIN, "env.toml: [sql] is required: out/app.zip was built with sql"),
        ("[sql]\n" + _PLAIN, "env.toml: program CBXXXX is not in out/app.zip"),
        (
            '[sql]\n[cics]\ninitial_transid = "ZZ99"\n',
            "env.toml: transaction ZZ99 is not in out/app.zip",
        ),
        (
            '[sql]\n[cics]\ninitial_transid = "CT02"\n',
            "env.toml: transaction CT02 runs COTRN02C, which is not in out/app.zip",
        ),
    ],
)
def test_an_env_toml_the_package_cannot_satisfy_names_its_fault(
    tmp_path: Path, sections: str, message: str
) -> None:
    path = _written(tmp_path, _TOP + sections)
    config = _loaded(path)

    with pytest.raises(ConfigError) as refused:
        config.check_against(path, _MANIFEST)

    assert str(refused.value) == message


def test_a_cics_region_clock_follows_its_timezone_and_datform(tmp_path: Path) -> None:
    named = _section(
        _written(
            tmp_path, _TOP + _CICS + 'timezone = "Asia/Kolkata"\ndatform = "DDMMYY"\n'
        )
    )
    unnamed = _section(_written(tmp_path, _TOP + _CICS))

    assert isinstance(named, CicsRun) and isinstance(unnamed, CicsRun)
    clock, local = named.clock(), unnamed.clock()
    assert (clock.now().utcoffset(), clock.datform, local.now, local.datform) == (
        timedelta(hours=5, minutes=30),
        DatForm.DDMMYY,
        LOCAL_CLOCK.now,
        DatForm.MMDDYY,
    )


def test_an_unknown_timezone_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as refused:
        _loaded(_written(tmp_path, _TOP + _CICS + 'timezone = "Mars/Base"\n'))

    assert str(refused.value) == "env.toml: cics.timezone: invalid timezone: Mars/Base"

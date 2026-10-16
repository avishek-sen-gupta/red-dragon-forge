"""env.toml picks its mode by the one section present, and stops naming any fault before anything runs."""

from pathlib import Path

import pytest
from litter.manifest import Manifest
from litter.transaction import Transaction

from red_dragon_forge.cics_run import CicsRun
from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.env_config import check_against, load_env_config
from red_dragon_forge.jcl_run import JclRun
from red_dragon_forge.plain_run import PlainRun
from red_dragon_forge.tolerant_section import TolerantSection

_TOP = 'package = "out/app.zip"\n[paths]\nsystem = "system"\n'
_PLAIN = '[plain]\nprogram = "CBXXXX"\n[plain.files]\nACCTFILE = "APP.ACCT"\n'
_JCL = '[jcl]\njob = "jcl/READ.jcl"\n'
_CICS = '[cics]\ninitial_transid = "CC00"\n'
_MANIFEST = Manifest(
    programs=("CBACT01C", "COSGN00C"),
    coprocessors=("cics", "sql"),
    transactions=(Transaction("CC00", "COSGN00C"),),
    files=(),
    mapsets=(),
)


def _written(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "env.toml"
    path.write_text(text)
    return path


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
        load_env_config(_written(tmp_path, _TOP + sections))

    assert str(refused.value) == message


def test_the_section_present_picks_the_mode(tmp_path: Path) -> None:
    plain = load_env_config(_written(tmp_path, _TOP + _PLAIN))[1]
    jcl = load_env_config(_written(tmp_path, _TOP + _JCL))[1]
    cics = load_env_config(_written(tmp_path, _TOP + _CICS))[1]

    assert (plain, jcl, cics) == (
        PlainRun(program="CBXXXX", files={"ACCTFILE": "APP.ACCT"}),
        JclRun(job=Path("jcl/READ.jcl")),
        CicsRun(initial_transid="CC00"),
    )


def test_tolerances_are_off_unless_named(tmp_path: Path) -> None:
    unnamed = load_env_config(_written(tmp_path, _TOP + _PLAIN))[0].tolerant
    named = load_env_config(
        _written(
            tmp_path,
            _TOP
            + "[tolerant]\npermit_unresolved_call_targets = true\n"
            + "permit_missing_host_variables = true\n"
            + _PLAIN,
        )
    )[0].tolerant

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
        load_env_config(_written(tmp_path, text))

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
    ],
)
def test_an_env_toml_the_package_cannot_satisfy_names_its_fault(
    tmp_path: Path, sections: str, message: str
) -> None:
    path = _written(tmp_path, _TOP + sections)
    config, mode = load_env_config(path)

    with pytest.raises(ConfigError) as refused:
        check_against(path, config, mode, _MANIFEST)

    assert str(refused.value) == message

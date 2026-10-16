"""build.toml parses into typed sections on arrival; a CICS build without [cics] and an unknown coprocessor stop naming the fault."""

from pathlib import Path

import pytest

from red_dragon_forge.build_cics import BuildCics
from red_dragon_forge.build_config import BuildConfig, load_build_config
from red_dragon_forge.build_paths import BuildPaths
from red_dragon_forge.build_section import BuildSection
from red_dragon_forge.config_error import ConfigError

_BUILD = """\
[paths]
source_dirs = ["app/cbl", "stubs"]
source_exts = [".cbl", ".CBL"]
copybook_dirs = ["app/cpy"]
copybook_exts = ["cpy", "CPY"]

[build]
name = "carddemo"
programs = ["COSGN00C", "CBACT01C", "DSNTIAC"]
link = ["COSGN00C", "DSNTIAC"]
coprocessors = [{coprocessors}]
tolerant = true
out_dir = "out"
"""

_CICS = """
[cics]
bms_dirs = ["app/bms"]
csd_files = ["app/csd/CARDDEMO.CSD"]
"""


def _written(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "build.toml"
    path.write_text(text)
    return path


def test_build_toml_parses_into_its_sections(tmp_path: Path) -> None:
    path = _written(tmp_path, _BUILD.format(coprocessors='"cics", "sql"') + _CICS)

    assert load_build_config(path) == BuildConfig(
        paths=BuildPaths(
            source_dirs=(Path("app/cbl"), Path("stubs")),
            source_exts=(".cbl", ".CBL"),
            copybook_dirs=(Path("app/cpy"),),
            copybook_exts=("cpy", "CPY"),
        ),
        build=BuildSection(
            name="carddemo",
            programs=("COSGN00C", "CBACT01C", "DSNTIAC"),
            link=("COSGN00C", "DSNTIAC"),
            coprocessors=("cics", "sql"),
            tolerant=True,
            out_dir=Path("out"),
        ),
        cics=BuildCics(
            bms_dirs=(Path("app/bms"),), csd_files=(Path("app/csd/CARDDEMO.CSD"),)
        ),
    )


@pytest.mark.parametrize(
    ("coprocessors", "message"),
    [
        ('"cics"', "build.toml: [cics] is required when coprocessors include cics"),
        (
            '"cics-conversational"',
            "build.toml: [cics] is required when coprocessors include cics",
        ),
        (
            '"sql", "ims"',
            "build.toml: build.coprocessors.1: Input should be 'sql', 'cics' or"
            " 'cics-conversational'",
        ),
    ],
)
def test_a_build_toml_that_describes_no_build_names_its_fault(
    tmp_path: Path, coprocessors: str, message: str
) -> None:
    path = _written(tmp_path, _BUILD.format(coprocessors=coprocessors))

    with pytest.raises(ConfigError) as refused:
        load_build_config(path)

    assert str(refused.value) == message


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            _BUILD.format(coprocessors="").replace(
                'name = "carddemo"', 'name = "../x"'
            ),
            "build.toml: build.name: String should match pattern"
            " '^[A-Za-z0-9][A-Za-z0-9_.-]*$'",
        ),
        (
            _BUILD.format(coprocessors="").replace('"CBACT01C", "DSNTIAC"]', '"../X"]'),
            "build.toml: build.programs.1: String should match pattern"
            " '^[A-Z#@$][A-Z0-9#@$]{0,7}$'",
        ),
        (
            "[paths\n",
            "build.toml: Expected ']' at the end of a table declaration (at line 1, column 7)",
        ),
    ],
)
def test_a_build_toml_that_does_not_parse_names_its_fault(
    tmp_path: Path, text: str, message: str
) -> None:
    with pytest.raises(ConfigError) as refused:
        load_build_config(_written(tmp_path, text))

    assert str(refused.value) == message


def test_a_missing_build_toml_names_itself(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as refused:
        load_build_config(tmp_path / "build.toml")

    assert str(refused.value) == f"{tmp_path / 'build.toml'}: No such file or directory"

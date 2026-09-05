from pathlib import Path

import pytest

from cobble.parsing.config import ParseConfig, load_parse_config

_FULL = """
[parse]
cobol_dir = "/corpus"
cobol_globs = ["src/*.cbl", "online/*.cbl"]
copybook_dirs = ["sym", "/corpus/layouts"]
copybook_extensions = ["cpy", "txt"]
bridge_jar = "../vendor/red-dragon/proleap-bridge/target/bridge-shaded.jar"
asg_dir = "out-parsed"
"""


def _written(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "parse.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_parse_config_reads_every_field(tmp_path: Path) -> None:
    assert load_parse_config(_written(tmp_path, _FULL)) == ParseConfig(
        cobol_dir=Path("/corpus"),
        cobol_globs=("src/*.cbl", "online/*.cbl"),
        copybook_dirs=(Path("sym"), Path("/corpus/layouts")),
        copybook_extensions=("cpy", "txt"),
        bridge_jar=Path("../vendor/red-dragon/proleap-bridge/target/bridge-shaded.jar"),
        asg_dir=Path("out-parsed"),
    )


def test_a_parse_config_with_no_parse_table_raises(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="parse"):
        load_parse_config(_written(tmp_path, '[srccfg]\nasg_dir = "x"\n'))


def test_a_parse_config_missing_a_required_key_names_it(tmp_path: Path) -> None:
    """A guessed default here is a run that parses nothing and reports success."""
    text = "\n".join(
        line for line in _FULL.splitlines() if not line.startswith("asg_dir")
    )
    with pytest.raises(KeyError, match="asg_dir"):
        load_parse_config(_written(tmp_path, text))


def test_a_parse_config_expands_a_home_relative_path(tmp_path: Path) -> None:
    """A corpus lives outside the repo, so ~ is the natural way to write its path
    and a literal "~" directory is never what was meant."""
    text = _FULL.replace('cobol_dir = "/corpus"', 'cobol_dir = "~/corpus"')
    assert load_parse_config(_written(tmp_path, text)).cobol_dir == (
        Path.home() / "corpus"
    )

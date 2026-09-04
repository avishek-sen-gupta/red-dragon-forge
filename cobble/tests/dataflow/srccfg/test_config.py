"""Config loading: every value required, nothing defaulted quietly.

A wrong path here does not fail -- it produces an empty run that reads exactly like
a corpus with no members, which is the expensive way to find out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobble.dataflow.srccfg.config import SrcCfgConfig, load_srccfg_config


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_a_complete_config_loads_both_paths(tmp_path: Path) -> None:
    config = load_srccfg_config(
        _write(
            tmp_path / "srccfg.toml",
            f"""
[srccfg]
asg_dir = "{tmp_path}/parsed"
out_dir = "{tmp_path}/srccfg"
""",
        )
    )

    assert config == SrcCfgConfig(
        asg_dir=tmp_path / "parsed", out_dir=tmp_path / "srccfg"
    )


def test_a_missing_key_raises_and_names_the_key_and_the_file(tmp_path: Path) -> None:
    """No default: an asg_dir guessed from the cwd points at nothing and the run
    reports zero members, which is indistinguishable from success on an empty
    corpus."""
    path = _write(tmp_path / "srccfg.toml", '[srccfg]\nasg_dir = "/x"\n')

    with pytest.raises(KeyError) as caught:
        load_srccfg_config(path)

    assert "out_dir" in str(caught.value)
    assert str(path) in str(caught.value)


def test_an_empty_value_is_missing_rather_than_a_relative_path(tmp_path: Path) -> None:
    """out_dir = "" resolves to the cwd, and a run that writes 3,779 files into a
    repo root is worse than a run that refuses."""
    path = _write(tmp_path / "srccfg.toml", '[srccfg]\nasg_dir = "/x"\nout_dir = ""\n')

    with pytest.raises(KeyError):
        load_srccfg_config(path)


def test_a_config_with_no_srccfg_table_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "srccfg.toml", '[other]\nasg_dir = "/x"\n')

    with pytest.raises(KeyError) as caught:
        load_srccfg_config(path)

    assert "srccfg" in str(caught.value)


def test_a_path_is_expanded_so_a_tilde_config_is_not_a_literal_directory(
    tmp_path: Path,
) -> None:
    """~ in a hand-written TOML is the commonest way to create a directory called
    "~" in the repo."""
    config = load_srccfg_config(
        _write(
            tmp_path / "srccfg.toml",
            '[srccfg]\nasg_dir = "~/parsed"\nout_dir = "~/srccfg"\n',
        )
    )

    assert config.asg_dir == Path.home() / "parsed"

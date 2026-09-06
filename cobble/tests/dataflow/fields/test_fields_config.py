"""Config loading: every value required, nothing defaulted quietly.

A wrong path here does not fail -- it produces an empty run that reads exactly like
a corpus with no members, which is the expensive way to find out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.fields.config import FieldsConfig, load_fields_config


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_a_complete_config_loads_both_paths(tmp_path: Path) -> None:
    config = load_fields_config(
        _write(
            tmp_path / "fields.toml",
            f'[fields]\nasg_dir = "{tmp_path}/parsed"\nout_dir = "{tmp_path}/fields"\n',
        )
    )

    assert config == FieldsConfig(
        asg_dir=tmp_path / "parsed", out_dir=tmp_path / "fields"
    )


def test_a_missing_key_raises_and_names_the_key_and_the_file(tmp_path: Path) -> None:
    path = _write(tmp_path / "fields.toml", '[fields]\nasg_dir = "/x"\n')

    with pytest.raises(KeyError) as caught:
        load_fields_config(path)

    assert "out_dir" in str(caught.value)
    assert str(path) in str(caught.value)


def test_an_empty_value_is_missing_rather_than_a_relative_path(tmp_path: Path) -> None:
    path = _write(tmp_path / "fields.toml", '[fields]\nasg_dir = "/x"\nout_dir = ""\n')

    with pytest.raises(KeyError):
        load_fields_config(path)


def test_a_config_with_no_fields_table_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "fields.toml", '[srccfg]\nasg_dir = "/x"\n')

    with pytest.raises(KeyError) as caught:
        load_fields_config(path)

    assert "fields" in str(caught.value)


def test_a_path_is_expanded_so_a_tilde_config_is_not_a_literal_directory(
    tmp_path: Path,
) -> None:
    config = load_fields_config(
        _write(
            tmp_path / "fields.toml",
            '[fields]\nasg_dir = "~/parsed"\nout_dir = "~/fields"\n',
        )
    )

    assert config.asg_dir == Path.home() / "parsed"

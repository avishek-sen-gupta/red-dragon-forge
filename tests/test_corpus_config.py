from pathlib import Path

import pytest

from corpus_config import (
    BmsConfig,
    CorpusConfig,
    _bms_config_from_dict,
    _corpus_config_from_dict,
    load_bms_config,
    load_corpus_config,
)


def test_corpus_config_from_dict_full() -> None:
    data = {
        "cobol_dir": "vendor/carddemo/app/cbl",
        "cobol_globs": ["*.cbl"],
        "jcl_dir": "vendor/carddemo/app/jcl",
        "jcl_globs": ["*.jcl", "*.JCL"],
        "proclib_dirs": ["vendor/carddemo/app/proc"],
        "csd_files": ["vendor/carddemo/app/csd/CARDDEMO.CSD"],
        "copybook_dirs": ["sym", "vendor/carddemo/app/cpy"],
        "out_dir": "out",
    }
    config = _corpus_config_from_dict(data)
    assert config == CorpusConfig(
        cobol_dir=Path("vendor/carddemo/app/cbl"),
        cobol_globs=("*.cbl",),
        jcl_dir=Path("vendor/carddemo/app/jcl"),
        jcl_globs=("*.jcl", "*.JCL"),
        proclib_dirs=(Path("vendor/carddemo/app/proc"),),
        csd_files=(Path("vendor/carddemo/app/csd/CARDDEMO.CSD"),),
        copybook_dirs=(Path("sym"), Path("vendor/carddemo/app/cpy")),
        out_dir=Path("out"),
    )


def test_corpus_config_from_dict_missing_optional_fields_default_to_empty_tuple() -> (
    None
):
    data = {
        "cobol_dir": "cbl",
        "cobol_globs": ["*.cbl"],
        "jcl_dir": "jcl",
        "jcl_globs": ["*.jcl"],
        "copybook_dirs": ["cpy"],
        "out_dir": "out",
    }
    config = _corpus_config_from_dict(data)
    assert config.csd_files == ()
    assert config.proclib_dirs == ()


def test_corpus_config_from_dict_empty_csd_files_is_valid() -> None:
    data = {
        "cobol_dir": "cbl",
        "cobol_globs": ["*.cbl"],
        "jcl_dir": "jcl",
        "jcl_globs": ["*.jcl"],
        "copybook_dirs": ["cpy"],
        "out_dir": "out",
        "csd_files": [],
    }
    assert _corpus_config_from_dict(data).csd_files == ()


def test_corpus_config_from_dict_missing_required_key_raises() -> None:
    with pytest.raises(KeyError, match="cobol_dir"):
        _corpus_config_from_dict({})


def test_bms_config_from_dict() -> None:
    data = {"bms_dir": "app/bms", "macros_dir": "bms-macros", "sym_dir": "sym"}
    assert _bms_config_from_dict(data) == BmsConfig(
        bms_dir=Path("app/bms"), macros_dir=Path("bms-macros"), sym_dir=Path("sym")
    )


def test_bms_config_from_dict_missing_required_key_raises() -> None:
    with pytest.raises(KeyError, match="bms_dir"):
        _bms_config_from_dict({})


def test_load_corpus_config_reads_yaml_file(tmp_path: Path) -> None:
    config_path = tmp_path / "test.yaml"
    config_path.write_text(
        "corpus:\n"
        "  cobol_dir: cbl\n"
        '  cobol_globs: ["*.cbl"]\n'
        "  jcl_dir: jcl\n"
        '  jcl_globs: ["*.jcl"]\n'
        '  copybook_dirs: ["cpy"]\n'
        "  out_dir: out\n"
    )
    config = load_corpus_config(config_path)
    assert config.cobol_dir == Path("cbl")
    assert config.csd_files == ()


def test_load_bms_config_reads_yaml_file(tmp_path: Path) -> None:
    config_path = tmp_path / "test.yaml"
    config_path.write_text(
        "bms:\n" "  bms_dir: app/bms\n" "  macros_dir: bms-macros\n" "  sym_dir: sym\n"
    )
    config = load_bms_config(config_path)
    assert config.bms_dir == Path("app/bms")


def test_load_corpus_config_missing_corpus_section_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "test.yaml"
    config_path.write_text("bms:\n  bms_dir: x\n  macros_dir: y\n  sym_dir: z\n")
    with pytest.raises(KeyError, match="corpus"):
        load_corpus_config(config_path)

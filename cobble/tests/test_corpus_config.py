from pathlib import Path

import pytest

from cobble.cics.synth_csd import TransidRule
from cobble.corpus_config import (
    DEFAULT_BMS_GLOBS,
    DEFAULT_COPYBOOK_EXTENSIONS,
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
        "copybook_extensions": ["cpy", "txt"],
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
        copybook_extensions=("cpy", "txt"),
        out_dir=Path("out"),
    )


def test_corpus_config_omitting_copybook_extensions_keeps_the_shipped_defaults() -> (
    None
):
    # A config written before the key existed must resolve copybooks exactly as
    # it did before, so the fallback is the bridge's own historical list.
    data = {
        "cobol_dir": "cbl",
        "cobol_globs": ["*.cbl"],
        "jcl_dir": "jcl",
        "jcl_globs": ["*.jcl"],
        "copybook_dirs": ["cpy"],
        "out_dir": "out",
    }
    config = _corpus_config_from_dict(data)
    assert config.copybook_extensions == DEFAULT_COPYBOOK_EXTENSIONS
    assert config.copybook_extensions == (
        "",
        "cpy",
        "CPY",
        "cob",
        "cbl",
        "copy",
        "COPY",
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


def _minimal(**overrides) -> dict:
    return {
        "cobol_dir": "cbl",
        "cobol_globs": ["*.cbl"],
        "jcl_dir": "jcl",
        "jcl_globs": ["*.jcl"],
        "copybook_dirs": ["cpy"],
        "out_dir": "out",
        **overrides,
    }


def test_corpus_config_reads_the_transid_naming_conventions() -> None:
    """Which member serves which transaction is encoded in the member names, and
    that encoding differs per site. It belongs in the config for the same reason
    the directories do: a wrong convention has to be correctable where the corpus
    is described, not in cobble's source.
    """
    data = _minimal(
        transid_rules=[
            {"member_pattern": r"^PGM(?P<tail>.{3})$", "transid_template": "T{tail}"},
            {"member_pattern": r"^OLD(?P<tail>.{3})$", "transid_template": "T{tail}"},
        ]
    )

    assert _corpus_config_from_dict(data).transid_rules == (
        TransidRule(member_pattern=r"^PGM(?P<tail>.{3})$", transid_template="T{tail}"),
        TransidRule(member_pattern=r"^OLD(?P<tail>.{3})$", transid_template="T{tail}"),
    )


def test_corpus_config_omitting_transid_rules_means_no_convention() -> None:
    """A corpus with a real CSD needs no convention at all, so the key is optional
    and its absence is an empty tuple rather than a guess."""
    assert _corpus_config_from_dict(_minimal()).transid_rules == ()


def test_a_transid_rule_missing_its_template_raises() -> None:
    """Half a rule would derive the transaction "" for every member it matches."""
    data = _minimal(transid_rules=[{"member_pattern": "^PGM...$"}])

    with pytest.raises(KeyError, match="transid_template"):
        _corpus_config_from_dict(data)


def test_bms_config_from_dict() -> None:
    data = {
        "bms_dir": "app/bms",
        "bms_globs": ["MAP*.txt"],
        "macros_dir": "bms-macros",
        "sym_dir": "sym",
    }
    assert _bms_config_from_dict(data) == BmsConfig(
        bms_dir=Path("app/bms"),
        bms_globs=("MAP*.txt",),
        macros_dir=Path("bms-macros"),
        sym_dir=Path("sym"),
    )


def test_bms_config_omitting_bms_globs_keeps_the_shipped_default() -> None:
    data = {"bms_dir": "app/bms", "macros_dir": "bms-macros", "sym_dir": "sym"}
    config = _bms_config_from_dict(data)
    assert config.bms_globs == DEFAULT_BMS_GLOBS
    assert config.bms_globs == ("*.bms",)


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

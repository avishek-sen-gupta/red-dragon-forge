from pathlib import Path

import pytest
from cobble.bms_table import DEFAULT_BMS_GLOBS, BmsTable
from cobble.cics.synth_csd import TransidRule
from cobble.corpus_config import (
    BmsConfig,
    CorpusConfig,
    _bms_config,
    _corpus_config,
    load_bms_config,
    load_corpus_config,
)
from cobble.corpus_table import DEFAULT_COPYBOOK_EXTENSIONS, CorpusTable
from pydantic import ValidationError


def _corpus_config_from_dict(data: dict) -> CorpusConfig:
    return _corpus_config(CorpusTable.model_validate(data))


def _bms_config_from_dict(data: dict) -> BmsConfig:
    return _bms_config(BmsTable.model_validate(data))


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
        "asg_dir": "parsed",
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
        asg_dir=Path("parsed"),
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
        "asg_dir": "parsed",
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
        "asg_dir": "parsed",
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
        "asg_dir": "parsed",
        "csd_files": [],
    }
    assert _corpus_config_from_dict(data).csd_files == ()


def test_corpus_config_from_dict_missing_required_key_raises() -> None:
    with pytest.raises(ValidationError, match="cobol_dir"):
        _corpus_config_from_dict({})


def _minimal(**overrides) -> dict:
    return {
        "cobol_dir": "cbl",
        "cobol_globs": ["*.cbl"],
        "jcl_dir": "jcl",
        "jcl_globs": ["*.jcl"],
        "copybook_dirs": ["cpy"],
        "asg_dir": "parsed",
        **overrides,
    }


def test_a_corpus_config_names_the_parsed_asg_cache() -> None:
    """cobble-build reads ASGs, it does not make them: a parse is 4-7 seconds of JVM
    per member, and cobble-parse-corpus has already paid it. The cache directory is
    an input to this stage exactly like cobol_dir is."""
    assert _corpus_config_from_dict(_minimal(asg_dir="out-parsed")).asg_dir == Path(
        "out-parsed"
    )


def test_a_corpus_config_missing_its_asg_dir_raises() -> None:
    """Required, not defaulted. A guessed path here is a build that finds no ASGs and
    reports an empty graph as a successful one."""
    data = {k: v for k, v in _minimal().items() if k != "asg_dir"}

    with pytest.raises(ValidationError, match="asg_dir"):
        _corpus_config_from_dict(data)


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

    with pytest.raises(ValidationError, match="transid_template"):
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
    with pytest.raises(ValidationError, match="bms_dir"):
        _bms_config_from_dict({})


def test_load_corpus_config_reads_toml_file(tmp_path: Path) -> None:
    config_path = tmp_path / "test.toml"
    config_path.write_text(
        "[corpus]\n"
        'cobol_dir = "cbl"\n'
        'cobol_globs = ["*.cbl"]\n'
        'jcl_dir = "jcl"\n'
        'jcl_globs = ["*.jcl"]\n'
        'copybook_dirs = ["cpy"]\n'
        'asg_dir = "parsed"\n'
    )
    config = load_corpus_config(config_path)
    assert config.cobol_dir == Path("cbl")
    assert config.csd_files == ()


def test_load_bms_config_reads_toml_file(tmp_path: Path) -> None:
    config_path = tmp_path / "test.toml"
    config_path.write_text(
        "[bms]\n"
        'bms_dir = "app/bms"\n'
        'macros_dir = "bms-macros"\n'
        'sym_dir = "sym"\n'
    )
    config = load_bms_config(config_path)
    assert config.bms_dir == Path("app/bms")


def test_load_corpus_config_missing_corpus_section_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "test.toml"
    config_path.write_text('[bms]\nbms_dir = "x"\nmacros_dir = "y"\nsym_dir = "z"\n')
    with pytest.raises(ValidationError, match="corpus"):
        load_corpus_config(config_path)


def test_a_corpus_config_with_transid_rules_reads_them_as_a_table_array(
    tmp_path: Path,
) -> None:
    """TOML spells a list of mappings as [[corpus.transid_rules]], and the CSD a
    site never exported is reconstructed from these -- so an empty tuple here is a
    corpus whose every transaction resolves to UNRESOLVED."""
    config_path = tmp_path / "test.toml"
    config_path.write_text(
        "[corpus]\n"
        'cobol_dir = "cbl"\n'
        'cobol_globs = ["*.cbl"]\n'
        'jcl_dir = "jcl"\n'
        'jcl_globs = ["*.jcl"]\n'
        'copybook_dirs = ["cpy"]\n'
        'asg_dir = "parsed"\n'
        "\n"
        "[[corpus.transid_rules]]\n"
        'member_pattern = "ACCT*"\n'
        'transid_template = "T{suffix}"\n'
    )
    config = load_corpus_config(config_path)
    assert [r.member_pattern for r in config.transid_rules] == ["ACCT*"]


def test_a_config_still_naming_out_dir_loads(tmp_path: Path) -> None:
    """out_dir left the corpus config when every stage took its output path on the
    command line; a config written before that still loads, the key unread."""
    config_path = tmp_path / "test.toml"
    config_path.write_text(
        "[corpus]\n"
        'cobol_dir = "cbl"\n'
        'cobol_globs = ["*.cbl"]\n'
        'jcl_dir = "jcl"\n'
        'jcl_globs = ["*.jcl"]\n'
        'copybook_dirs = ["cpy"]\n'
        'asg_dir = "parsed"\n'
        'out_dir = "out"\n'
    )
    assert load_corpus_config(config_path).asg_dir == Path("parsed")

"""Corpus-to-CSD plumbing for generate_csd: which members are scanned, how they
are keyed, and where the result lands.

The synthesis itself is tested in tests/cics/test_synth_csd.py; what is left here
is the shell -- and the keying matters, because build_graph resolves a CICS
program to a file by upper-cased stem, so a CSD naming members any other way
produces a worklist that resolves to nothing.
"""

from pathlib import Path

import pytest
from cobble.cics.synth_csd import SYNTHETIC_TRANSID_PREFIX, TransidRule
from cobble.corpus_config import CorpusConfig
from cobble.corpus_table import DEFAULT_COPYBOOK_EXTENSIONS
from cobble.generate_csd import (
    _parse_args,
    synthesise_from_corpus,
    write_csd,
)

_RULE = TransidRule(member_pattern=r"^PGM(?P<tail>.{3})$", transid_template="T{tail}")


def _config(tmp_path: Path, **overrides) -> CorpusConfig:
    defaults = dict(
        cobol_dir=tmp_path / "cbl",
        cobol_globs=("*.cbl",),
        jcl_dir=tmp_path / "jcl",
        jcl_globs=("*.jcl",),
        proclib_dirs=(),
        csd_files=(),
        copybook_dirs=(tmp_path / "cpy",),
        copybook_extensions=DEFAULT_COPYBOOK_EXTENSIONS,
        asg_dir=tmp_path / "parsed",
        transid_rules=(_RULE,),
    )
    return CorpusConfig(**{**defaults, **overrides})


def _member(tmp_path: Path, name: str, *lines: str) -> None:
    cbl = tmp_path / "cbl"
    cbl.mkdir(parents=True, exist_ok=True)
    (cbl / name).write_bytes(
        "\n".join(f"      {line}" for line in lines).encode("latin-1")
    )


def test_a_lower_case_file_name_still_names_an_upper_case_member(
    tmp_path: Path,
) -> None:
    """build_graph resolves a CICS program by upper-cased stem, so a CSD naming
    the member any other way yields a worklist entry that resolves to nothing.
    End to end, because the normalisation is synthesise_csd's, not this module's.
    """
    _member(tmp_path, "pgm001.cbl", "EXEC CICS RETURN TRANSID('T001') END-EXEC.")

    result = synthesise_from_corpus(_config(tmp_path))

    assert [(d.transid, d.program) for d in result.defines] == [("T001", "PGM001")]


def test_only_the_members_the_cobol_globs_select_are_scanned(tmp_path: Path) -> None:
    """The corpus directory holds more than COBOL. A member the run will never
    parse must not appear in the CSD, or the flow stage reports it missing."""
    _member(tmp_path, "PGM002.cbl", "EXEC CICS SEND MAP('SOMEMAP') END-EXEC.")
    _member(tmp_path, "PGM003.jcl", "EXEC CICS SEND MAP('SOMEMAP') END-EXEC.")

    result = synthesise_from_corpus(_config(tmp_path))

    assert [d.program for d in result.defines] == ["PGM002"]


def test_the_csd_lands_where_out_says_and_parses_back(tmp_path: Path) -> None:
    """The directory may not exist yet -- this stage can run before any graph build."""
    _member(tmp_path, "PGM004.cbl", "EXEC CICS SEND MAP('SOMEMAP') END-EXEC.")
    config = _config(tmp_path)

    out = tmp_path / "generated" / "corpus.csd"

    assert write_csd(synthesise_from_corpus(config), out) == out
    assert out.read_text(encoding="utf-8") == (
        f"DEFINE TRANSACTION({SYNTHETIC_TRANSID_PREFIX}PGM004) "
        "PROGRAM(PGM004) GROUP(SYNTHETIC)\n"
    )


def test_the_csd_has_no_default_destination() -> None:
    assert _parse_args(["--config", "c.toml", "--out", "gen/corpus.csd"]).out == Path(
        "gen/corpus.csd"
    )

    with pytest.raises(SystemExit) as refused:
        _parse_args(["--config", "c.toml"])
    assert refused.value.code == 2

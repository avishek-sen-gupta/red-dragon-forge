from pathlib import Path

from cobble.corpus_config import CorpusConfig
from cobble.parsing.expand_corpus import expand_with, pending
from cobble.parsing.parse_corpus import Job
from cobol_asg.cobol_parser import ProLeapCobolParser
from tests.parsing.bridges import CannedBridge, RejectingBridge


def _config(tmp_path: Path) -> CorpusConfig:
    (tmp_path / "cbl").mkdir()
    return CorpusConfig(
        cobol_dir=tmp_path / "cbl",
        cobol_globs=("*.cbl",),
        jcl_dir=tmp_path / "jcl",
        jcl_globs=("*.jcl",),
        proclib_dirs=(),
        csd_files=(),
        copybook_dirs=(),
        copybook_extensions=("cpy",),
        asg_dir=tmp_path / "asg",
    )


def _members(config: CorpusConfig, *names: str) -> None:
    for name in names:
        (config.cobol_dir / name).write_text("       PROGRAM-ID. X.\n")


def _out_dir(tmp_path: Path) -> Path:
    out = tmp_path / "expanded"
    out.mkdir()
    return out


def _job(config: CorpusConfig, out: Path, name: str) -> Job:
    source = config.cobol_dir / name
    return Job(source, out / f"{source.stem}.cbl")


def test_pending_is_every_member_with_neither_an_expansion_nor_a_failure(
    tmp_path: Path,
) -> None:
    """The stage resumes on its OWN output, not on the ASG cache. That is the
    whole reason it is a stage rather than a flag on cobble-parse-corpus: a
    corpus whose ASGs are already built would otherwise skip every member and
    write nothing."""
    config = _config(tmp_path)
    out = _out_dir(tmp_path)
    _members(config, "A.cbl", "B.cbl", "C.cbl")
    (out / "A.cbl").write_text("       PROGRAM-ID. A.\n")
    (out / "B.fail").write_text("CobolParseError: could not find copy book")

    todo, done = pending(config, out)

    assert [job.stem for job in todo] == ["C"]
    assert done == 2


def test_each_pending_job_writes_where_the_expanded_cache_expects_it(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    out = _out_dir(tmp_path)
    _members(config, "A.cbl")

    assert pending(config, out)[0][0].dest == out / "A.cbl"


def test_expanding_a_member_writes_the_bridge_text_byte_for_byte(
    tmp_path: Path,
) -> None:
    """latin-1 on the way out, matching RealSubprocessRunner and the bridge's own
    SOURCE_CHARSET. Any other codec mangles a high byte in a VALUE literal, and
    the expansion stops being the text the lexer was handed."""
    config = _config(tmp_path)
    out = _out_dir(tmp_path)
    _members(config, "A.cbl")
    parser = ProLeapCobolParser(
        CannedBridge("       01 WS-SIGN PIC X VALUE 'é'.\n"), "bridge.jar"
    )

    result = expand_with(parser, _job(config, out, "A.cbl"))

    assert result.ok is True
    assert (out / "A.cbl").read_bytes() == b"       01 WS-SIGN PIC X VALUE '\xe9'.\n"


def test_a_member_the_bridge_rejects_is_recorded_where_the_expansion_would_go(
    tmp_path: Path,
) -> None:
    """A missing copybook is permanent until the copybook arrives, so the failure
    is written beside the expansions to make the next run's skip cheap."""
    config = _config(tmp_path)
    out = _out_dir(tmp_path)
    _members(config, "A.cbl")
    parser = ProLeapCobolParser(
        RejectingBridge("could not find copy book"), "bridge.jar"
    )

    result = expand_with(parser, _job(config, out, "A.cbl"))

    assert result.ok is False
    assert (out / "A.fail").read_text() == ("CobolParseError: could not find copy book")
    assert not (out / "A.cbl").exists()

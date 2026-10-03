from pathlib import Path

import pytest

from cobble.corpus_config import CorpusConfig
from tests.parsing.bridges import CannedBridge, RejectingBridge
from cobble.parsing.parse_corpus import Job, bridge_jar, parse_with, pending
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import SubprocessRunner


def _config(tmp_path: Path) -> CorpusConfig:
    (tmp_path / "cbl").mkdir()
    (tmp_path / "asg").mkdir()
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


def test_an_unparsed_corpus_is_entirely_pending(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _members(config, "A.cbl", "B.cbl")

    todo, done = pending(config)

    assert sorted(job.stem for job in todo) == ["A", "B"]
    assert done == 0


def test_a_member_with_a_cached_asg_is_not_parsed_again(tmp_path: Path) -> None:
    """4-7 seconds of JVM per member is what makes the run resumable at all."""
    config = _config(tmp_path)
    _members(config, "A.cbl", "B.cbl")
    (config.asg_dir / "A.json").write_text("{}")

    todo, done = pending(config)

    assert [job.stem for job in todo] == ["B"]
    assert done == 1


def test_a_member_that_failed_before_is_retried(tmp_path: Path) -> None:
    """A .fail records the last attempt, not a verdict: the copybook may have
    arrived, or the bridge been fixed, since. Only an ASG counts as done."""
    config = _config(tmp_path)
    _members(config, "A.cbl")
    (config.asg_dir / "A.fail").write_text("boom")

    todo, done = pending(config)

    assert ([job.stem for job in todo], done) == (["A"], 0)


def test_force_parses_every_member_whatever_is_cached(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _members(config, "A.cbl", "B.cbl", "C.cbl")
    (config.asg_dir / "A.json").write_text("{}")
    (config.asg_dir / "B.fail").write_text("boom")

    todo, done = pending(config, force=True)

    assert (sorted(job.stem for job in todo), done) == (["A", "B", "C"], 0)


def test_each_pending_job_writes_where_the_cache_expects_it(tmp_path: Path) -> None:
    """The destination is asg_cache's name for the member, not a name parse_corpus
    invents -- otherwise the writer and every reader disagree."""
    config = _config(tmp_path)
    _members(config, "A.cbl")

    assert pending(config)[0][0].dest == config.asg_dir / "A.json"


def test_the_bridge_jar_comes_from_the_environment(tmp_path: Path) -> None:
    jar = tmp_path / "bridge.jar"
    jar.write_bytes(b"")

    assert bridge_jar({"PROLEAP_BRIDGE_JAR": str(jar)}) == jar


def test_an_unset_bridge_jar_names_the_script_that_exports_it() -> None:
    with pytest.raises(SystemExit, match="bridge-env.sh"):
        bridge_jar({})


def test_an_unbuilt_bridge_jar_names_the_target_that_builds_it(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="make setup"):
        bridge_jar({"PROLEAP_BRIDGE_JAR": str(tmp_path / "absent.jar")})


def _job(config: CorpusConfig, name: str) -> Job:
    source = config.cobol_dir / name
    return Job(source, config.asg_dir / f"{source.stem}.json")


def _parser(bridge: SubprocessRunner) -> ProLeapCobolParser:
    return ProLeapCobolParser(bridge, "bridge.jar")


def test_a_member_the_parser_cannot_turn_into_an_asg_is_recorded_as_its_failure(
    tmp_path: Path,
) -> None:
    """Both arms of "this member is data cobble cannot handle": the bridge
    rejecting the source, and bridge output that will not deserialise. A corpus
    member that will not parse is data, not a bug, so it is recorded and never
    retried."""
    config = _config(tmp_path)
    _members(config, "A.cbl", "B.cbl")

    rejected = parse_with(
        _parser(RejectingBridge("could not find copy book")), _job(config, "A.cbl")
    )
    undeserialisable = parse_with(_parser(CannedBridge("{")), _job(config, "B.cbl"))

    assert (rejected.ok, undeserialisable.ok) == (False, False)
    assert (config.asg_dir / "A.fail").read_text() == (
        "CobolParseError: could not find copy book"
    )
    assert (config.asg_dir / "B.fail").read_text().startswith("JSONDecodeError:")


def test_a_parsed_member_is_written_where_the_cache_expects_it(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    _members(config, "A.cbl")

    result = parse_with(_parser(CannedBridge("{}")), _job(config, "A.cbl"))

    assert result.ok is True
    assert (config.asg_dir / "A.json").read_text() == "{}"


def test_a_failure_to_WRITE_is_not_blamed_on_the_member(tmp_path: Path) -> None:
    """The write used to sit inside the same catch as the parse, so a full disk
    or an unwritable asg_dir was recorded as "this member is unparseable" -- for
    every member, permanently, because a .fail is never retried. A run-wide fault
    must end the run instead (red-dragon-forge-jbh)."""
    config = _config(tmp_path)
    _members(config, "A.cbl")
    # dest unwritable, its directory fine -- so recording a .fail WOULD succeed,
    # which is what makes this test able to tell the two behaviours apart.
    (config.asg_dir / "A.json").mkdir()

    with pytest.raises(OSError):
        parse_with(_parser(CannedBridge("{}")), _job(config, "A.cbl"))

    assert not (config.asg_dir / "A.fail").exists()


def test_a_reparse_replaces_the_other_outcome(tmp_path: Path) -> None:
    """A member that now parses loses its old .fail, and one that now fails loses
    its old ASG: a stale ASG would be read as current by every later stage."""
    config = _config(tmp_path)
    _members(config, "A.cbl", "B.cbl")
    (config.asg_dir / "A.fail").write_text("boom")
    (config.asg_dir / "B.json").write_text("{}")

    parse_with(_parser(CannedBridge("{}")), _job(config, "A.cbl"))
    parse_with(
        _parser(RejectingBridge("could not find copy book")), _job(config, "B.cbl")
    )

    assert sorted(path.name for path in config.asg_dir.iterdir()) == [
        "A.json",
        "B.fail",
    ]

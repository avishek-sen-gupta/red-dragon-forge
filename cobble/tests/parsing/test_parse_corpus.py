from pathlib import Path

import pytest

from cobble.corpus_config import CorpusConfig
from cobble.parsing.parse_corpus import bridge_jar, pending


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
        out_dir=tmp_path / "out",
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


def test_a_member_that_failed_before_is_not_retried(tmp_path: Path) -> None:
    """A missing copybook is permanent until the copybook arrives, so a retry is
    pure cost -- and on one corpus it is 328 members' worth of it."""
    config = _config(tmp_path)
    _members(config, "A.cbl")
    (config.asg_dir / "A.fail").write_text("boom")

    assert pending(config) == ([], 1)


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

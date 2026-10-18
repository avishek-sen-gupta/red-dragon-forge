"""Pre-flight COBOL diagnostic.

The build's COBOL phase is 3779 JVM subprocesses and dies on the first program
the bridge rejects, so what you learn from a failed 40-minute run is one program's
name. This runs the same parse, keeps going, and reports every rejection at once.

Grouping is the point rather than a nicety: 227 programs failing one way is a
config or a corpus-shape problem with one fix, and 227 failing 40 ways is not. The
grouping is done on a signature with the source text and the numbers stripped out,
which is also what makes it safe to log -- a ProLeap message quotes the program's
own source, so the messages themselves stay in the JSON.
"""

import json
import logging
from collections.abc import Sequence
from pathlib import Path

import pytest

from cobble.corpus_config import CorpusConfig
from cobble.diagnosis.cobol import (
    CheckResult,
    check_programs,
    find_unparseable,
    main,
    signature,
    tally,
)
from cobol_asg.subprocess_runner import CobolParseError

# What the bridge actually wrote to stderr for the program that killed a prod run,
# with the corpus's own text left in so the stripping is tested against the real
# shape. The temp .cbl path is the BRIDGE's (it reads the program on stdin and
# writes it out to parse it), which is why the message cannot name the member.
REAL_STDERR = """ProLeap bridge failed (exit 1): Aug 28, 2026 3:49:30 PM org.reddragon.bridge.Main resolveInputFile
INFO: Reading COBOL source from stdin...
Aug 28, 2026 3:49:31 PM org.reddragon.bridge.Main main
INFO: Parsing COBOL file: /var/folders/1l/x/T/cobol-bridge-3854485783305517276.cbl (format=FIXED)
SLF4J: No SLF4J providers were found.
Exception in thread "main" io.proleap.cobol.asg.exception.CobolParserException: syntax error in line 1:7 mismatched input 'S' expecting {<EOF>, ID, IDENTIFICATION}
\tat io.proleap.cobol.asg.runner.ThrowingErrorListener.syntaxError(ThrowingErrorListener.java:22)
\tat org.antlr.v4.runtime.Parser.notifyErrorListeners(Parser.java:544)
"""


def _touch(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _write_config_toml(tmp_path: Path) -> Path:
    return _touch(
        tmp_path / "corpus.toml",
        f"""
[corpus]
cobol_dir = "{tmp_path}/cbl"
cobol_globs = ["*.cbl"]
jcl_dir = "{tmp_path}/jcl"
jcl_globs = ["*.jcl"]
copybook_dirs = ["{tmp_path}/cpy"]
copybook_extensions = ["", "cpy"]
asg_dir = "{tmp_path}/parsed"
""",
    )


def _parsed(tmp_path: Path, program: str) -> CheckResult:
    return CheckResult(path=tmp_path / "cbl" / f"{program}.cbl")


def _rejected(tmp_path: Path, program: str, message: str = REAL_STDERR) -> CheckResult:
    return CheckResult(
        path=tmp_path / "cbl" / f"{program}.cbl",
        kind="CobolParseError",
        message=message,
    )


# --- the signature: what makes two failures the same failure -------------------


def test_the_signature_is_the_parser_exception_line_out_of_the_java_noise() -> None:
    """Four of the seven lines the bridge wrote are its own logging, and the stack
    trace below says where ProLeap noticed, not what is wrong."""
    assert signature(REAL_STDERR).startswith(
        "io.proleap.cobol.asg.exception.CobolParserException:"
    )
    assert "SLF4J" not in signature(REAL_STDERR)
    assert "ThrowingErrorListener" not in signature(REAL_STDERR)


def test_the_signature_strips_the_source_text_the_message_quoted() -> None:
    """The security property, and what makes grouping work at all. 'S' is a byte of
    the program: it must not reach a log, and two programs whose stray byte differs
    are still the same failure."""
    signed = signature(REAL_STDERR)
    assert "'S'" not in signed
    assert "mismatched input ?" in signed


def test_the_signature_strips_line_and_column_numbers() -> None:
    """Otherwise every program is its own group, since no two of them go wrong on
    the same line."""
    assert "line ?:?" in signature(REAL_STDERR)
    assert "1:7" not in signature(REAL_STDERR)


def test_the_signature_keeps_the_grammar_vocabulary_that_says_what_was_expected() -> (
    None
):
    """What the parser expected is ProLeap's grammar, not the corpus's text, and it
    is the part that says which fix applies."""
    assert "expecting {<EOF>, ID, IDENTIFICATION}" in signature(REAL_STDERR)


def test_two_programs_that_go_wrong_the_same_way_share_a_signature() -> None:
    other = REAL_STDERR.replace("line 1:7", "line 4:12").replace(
        "input 'S'", "input 'Z'"
    )
    assert signature(other) == signature(REAL_STDERR)


def test_a_copybook_failure_signature_carries_no_searched_directory() -> None:
    """cobol_parser enriches a missing-copybook error with the directories it
    searched, which are corpus paths, and the underlying message names the
    copybook. Neither may reach the log."""
    message = (
        "Copybook not found (searched directories: ['/corpus/prod/copylib']). "
        "Underlying parser error: ProLeap bridge failed (exit 1): "
        'Exception in thread "main" java.lang.RuntimeException: '
        "Could not find copy book 'CUSTREC' in the copy book directories"
    )
    signed = signature(message)
    assert "/corpus/prod/copylib" not in signed
    assert "CUSTREC" not in signed
    assert "Could not find copy book" in signed


def test_a_message_with_no_recognisable_exception_line_is_still_a_signature() -> None:
    """A bridge that dies before ProLeap runs -- a missing JAR, an OOM killer --
    still has to group, or the report loses the members it happened to."""
    assert signature("java: command not found") != ""


# --- the tally and the JSON ----------------------------------------------------


def test_the_tally_counts_programs_parsed_and_rejected(tmp_path: Path) -> None:
    counted = tally(
        (
            _parsed(tmp_path, "GOODONE"),
            _parsed(tmp_path, "ALSOFINE"),
            _rejected(tmp_path, "BADPROG"),
        )
    )
    assert (counted.parsed, counted.failed) == (2, 1)


def test_an_empty_corpus_tallies_to_zeroes() -> None:
    counted = tally(())
    assert (counted.parsed, counted.failed) == (0, 0)


def test_a_rejected_program_is_reported_with_its_type_message_and_signature(
    tmp_path: Path,
) -> None:
    found = find_unparseable((_rejected(tmp_path, "BADPROG"),))
    assert found["BADPROG.cbl"]["type"] == "CobolParseError"
    assert "mismatched input 'S'" in found["BADPROG.cbl"]["message"]
    assert found["BADPROG.cbl"]["signature"] == signature(REAL_STDERR)


def test_a_corpus_that_parses_whole_reports_nothing(tmp_path: Path) -> None:
    assert find_unparseable((_parsed(tmp_path, "GOODONE"),)) == {}


def test_programs_are_labelled_by_filename_so_two_libraries_stay_distinct(
    tmp_path: Path,
) -> None:
    one = CheckResult(path=tmp_path / "libA" / "SAME.cbl", kind="E", message="a")
    two = CheckResult(path=tmp_path / "libB" / "SAME.cbl", kind="E", message="b")
    assert sorted(find_unparseable((one, two))) == ["libA/SAME.cbl", "libB/SAME.cbl"]


# --- the CLI ------------------------------------------------------------------


def _fake_check(tmp_path: Path):
    """Stands in for the bridge, so the CLI tests need no JVM."""

    def check(
        config: CorpusConfig, paths: Sequence[Path], max_workers: int
    ) -> list[CheckResult]:
        return [
            _parsed(tmp_path, "GOODONE"),
            _rejected(tmp_path, "BADPROG"),
            _rejected(tmp_path, "OTHERBAD"),
        ]

    return check


def test_the_json_goes_to_stdout_when_no_output_is_given(
    tmp_path: Path, capsys
) -> None:
    exit_code = main(
        ["--config", str(_write_config_toml(tmp_path))], check=_fake_check(tmp_path)
    )
    assert exit_code == 0
    assert sorted(json.loads(capsys.readouterr().out)) == [
        "BADPROG.cbl",
        "OTHERBAD.cbl",
    ]


def test_an_output_path_receives_the_json_and_stdout_stays_clean(
    tmp_path: Path, capsys
) -> None:
    out = tmp_path / "reports" / "unparseable.json"
    exit_code = main(
        ["--config", str(_write_config_toml(tmp_path)), "--output", str(out)],
        check=_fake_check(tmp_path),
    )
    assert exit_code == 0
    assert "BADPROG.cbl" in json.loads(out.read_text())
    assert capsys.readouterr().out == ""


def test_the_summary_carries_the_counts(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.INFO)
    main(["--config", str(_write_config_toml(tmp_path))], check=_fake_check(tmp_path))
    assert "1 of 3 program(s) parsed" in caplog.text
    assert "2 failed" in caplog.text


def test_the_summary_groups_the_failures_by_signature(tmp_path: Path, caplog) -> None:
    """Two programs, one way of failing, one line saying so with a count of 2 --
    that is the difference between one fix and a survey."""
    caplog.set_level(logging.INFO)
    main(["--config", str(_write_config_toml(tmp_path))], check=_fake_check(tmp_path))
    assert "mismatched input ?" in caplog.text
    assert "2  io.proleap" in caplog.text


def test_the_summary_names_no_program_and_quotes_no_source(
    tmp_path: Path, caplog
) -> None:
    """A program name is a corpus identifier and a ProLeap message quotes the
    program's own bytes, so the log gets counts and stripped signatures only."""
    caplog.set_level(logging.INFO)
    main(["--config", str(_write_config_toml(tmp_path))], check=_fake_check(tmp_path))
    assert "BADPROG" not in caplog.text
    assert "OTHERBAD" not in caplog.text
    assert "'S'" not in caplog.text
    assert "cobol-bridge-3854485783305517276" not in caplog.text


def test_the_check_is_handed_the_worker_count_from_the_flag(tmp_path: Path) -> None:
    def check(
        config: CorpusConfig, paths: Sequence[Path], max_workers: int
    ) -> list[CheckResult]:
        raise AssertionError(f"workers={max_workers}")

    with pytest.raises(AssertionError, match="workers=9"):
        main(
            ["--config", str(_write_config_toml(tmp_path)), "--max-workers", "9"],
            check=check,
        )


def test_the_exit_status_is_zero_even_when_programs_fail(tmp_path: Path) -> None:
    """It reports, it does not gate -- unlike the build, which today dies on the
    first rejection."""
    assert (
        main(
            ["--config", str(_write_config_toml(tmp_path))], check=_fake_check(tmp_path)
        )
        == 0
    )


# --- the production check: the pool, the parser, the scratch file ---------------


class RejectingParser:
    """A bridge stand-in that rejects the sources named and writes ASG JSON for the
    rest, recording where it was asked to write."""

    def __init__(self, rejected: bytes):
        self._rejected = rejected
        self.wrote: tuple[Path, ...] = ()

    def parse_to_file(self, source: bytes, out_path: Path) -> Path:
        self.wrote = (*self.wrote, out_path)
        if source == self._rejected:
            raise CobolParseError(REAL_STDERR)
        out_path.write_text('{"programs": [{"program_id": "OK"}]}', encoding="utf-8")
        return out_path


def _program(tmp_path: Path, name: str, source: bytes) -> Path:
    path = tmp_path / "cbl" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source)
    return path


def test_the_check_reports_one_result_per_program_and_keeps_going(
    tmp_path: Path,
) -> None:
    """The whole reason this module exists: the build stops at the first rejection,
    and a report cannot."""
    programs = (
        _program(tmp_path, "GOODONE.cbl", b"fine"),
        _program(tmp_path, "BADPROG.cbl", b"junk"),
        _program(tmp_path, "ALSOFINE.cbl", b"also fine"),
    )
    results = check_programs(programs, RejectingParser(b"junk"), max_workers=2)
    assert len(results) == 3
    rejected = tuple(r for r in results if r.kind)
    assert [r.path.name for r in rejected] == ["BADPROG.cbl"]
    assert rejected[0].kind == "CobolParseError"


def test_the_check_leaves_no_asg_json_behind(tmp_path: Path) -> None:
    """3779 ASGs at ~300KB each is gigabytes to answer a yes or no, so each one is
    unlinked as soon as the bridge has written it."""
    parser = RejectingParser(b"junk")
    check_programs((_program(tmp_path, "GOODONE.cbl", b"fine"),), parser)
    assert parser.wrote  # the bridge really was asked to write one
    assert not any(path.exists() for path in parser.wrote)


def test_two_programs_of_the_same_name_get_their_own_scratch_file(
    tmp_path: Path,
) -> None:
    """The scratch name is the program's position, not its stem: these run
    concurrently and two libraries can hold the same name."""
    one = _program(tmp_path / "libA", "SAME.cbl", b"fine")
    two = _program(tmp_path / "libB", "SAME.cbl", b"also fine")
    parser = RejectingParser(b"junk")
    check_programs((one, two), parser)
    assert len(frozenset(parser.wrote)) == 2

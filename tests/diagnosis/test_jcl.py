"""Pre-flight JCL diagnostic.

A corpus build parses every JCL member in a JVM subprocess before it draws a
single edge, so a member the grammar rejects is found hours in and only as a
warning among thousands. This runs that phase and nothing else, which is what the
grammar work on the onboarding corpus needed over and over: the four numbers that
say where the corpus stands -- parsed, failed, steps, DDs -- plus, per failing
member, what the bridge said about it.

The split of channels is the same as its copybook sibling's and matters more here.
An ANTLR error quotes the input it choked on, so a parse message carries corpus
source text. Messages therefore go in the JSON, which the caller places, and the
logged summary carries counts only.
"""

import json
import logging
from collections.abc import Sequence
from pathlib import Path

import pytest

from cobble.diagnosis.jcl import (
    SweepResult,
    find_unparseable,
    main,
    tally,
)


def _touch(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _write_config_yaml(tmp_path: Path) -> Path:
    return _touch(
        tmp_path / "corpus.yaml",
        f"""
corpus:
  cobol_dir: {tmp_path}/cbl
  cobol_globs: ["*.cbl"]
  jcl_dir: {tmp_path}/jcl
  jcl_globs: ["*.jcl"]
  copybook_dirs: [{tmp_path}/cpy]
  copybook_extensions: ["", "cpy"]
  out_dir: {tmp_path}/out
""",
    )


def _parsed(tmp_path: Path, member: str, steps: int, dds: int) -> SweepResult:
    return SweepResult(path=tmp_path / "jcl" / f"{member}.jcl", steps=steps, dds=dds)


def _failed(tmp_path: Path, member: str, kind: str, message: str) -> SweepResult:
    return SweepResult(
        path=tmp_path / "jcl" / f"{member}.jcl", kind=kind, message=message
    )


# --- the tally: the four columns the onboarding ledger records -----------------


def test_the_tally_counts_parsed_members_and_their_steps_and_dds(
    tmp_path: Path,
) -> None:
    counted = tally(
        (
            _parsed(tmp_path, "A", steps=3, dds=10),
            _parsed(tmp_path, "B", steps=2, dds=7),
        )
    )
    assert (counted.parsed, counted.failed, counted.steps, counted.dds) == (2, 0, 5, 17)


def test_a_failed_member_contributes_no_steps_or_dds(tmp_path: Path) -> None:
    """A member that did not parse has no steps to count, so the steps and DDs
    columns describe the members that parsed and only those."""
    counted = tally(
        (
            _parsed(tmp_path, "A", steps=3, dds=10),
            _failed(tmp_path, "B", "JclParseError", "no viable alternative"),
        )
    )
    assert (counted.parsed, counted.failed, counted.steps, counted.dds) == (1, 1, 3, 10)


def test_an_empty_corpus_tallies_to_zeroes(tmp_path: Path) -> None:
    counted = tally(())
    assert (counted.parsed, counted.failed, counted.steps, counted.dds) == (0, 0, 0, 0)


# --- the JSON: per failing member, what the bridge said ------------------------


def test_a_failing_member_is_reported_with_its_error_type_and_message(
    tmp_path: Path,
) -> None:
    found = find_unparseable(
        (
            _failed(
                tmp_path, "BADJOB", "JclParseError", "line 4:48 no viable alternative"
            ),
        )
    )
    assert found == {
        "BADJOB.jcl": {
            "type": "JclParseError",
            "message": "line 4:48 no viable alternative",
        }
    }


def test_a_corpus_that_parses_whole_reports_nothing(tmp_path: Path) -> None:
    """An empty mapping, not an absent entry: the JSON is diffed between runs to
    see whether a grammar fix moved the number, and 860 of 860 has to be
    expressible."""
    assert find_unparseable((_parsed(tmp_path, "A", steps=1, dds=1),)) == {}


def test_members_are_labelled_by_filename_so_two_libraries_stay_distinct(
    tmp_path: Path,
) -> None:
    """Two members of the same name in different libraries are two entries, since
    the report exists to say which file to open."""
    one = SweepResult(path=tmp_path / "libA" / "SAME.jcl", kind="E", message="a")
    two = SweepResult(path=tmp_path / "libB" / "SAME.jcl", kind="E", message="b")
    assert sorted(find_unparseable((one, two))) == ["libA/SAME.jcl", "libB/SAME.jcl"]


# --- the CLI ------------------------------------------------------------------


def _fake_sweep(tmp_path: Path):
    """Stands in for the parser, so the CLI tests need no JVM."""

    def sweep(paths: Sequence[Path], max_workers: int) -> list[SweepResult]:
        return [
            _parsed(tmp_path, "GOOD", steps=4, dds=9),
            _failed(tmp_path, "BADJOB", "JclParseError", "line 4:48 at '//STEP1 EXEC'"),
        ]

    return sweep


def test_the_json_goes_to_stdout_when_no_output_is_given(
    tmp_path: Path, capsys
) -> None:
    exit_code = main(
        ["--config", str(_write_config_yaml(tmp_path))], sweep=_fake_sweep(tmp_path)
    )
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "BADJOB.jcl": {
            "type": "JclParseError",
            "message": "line 4:48 at '//STEP1 EXEC'",
        }
    }


def test_an_output_path_receives_the_json_and_stdout_stays_clean(
    tmp_path: Path, capsys
) -> None:
    out = tmp_path / "reports" / "unparseable.json"
    exit_code = main(
        ["--config", str(_write_config_yaml(tmp_path)), "--output", str(out)],
        sweep=_fake_sweep(tmp_path),
    )
    assert exit_code == 0
    assert "BADJOB.jcl" in json.loads(out.read_text())
    assert capsys.readouterr().out == ""


def test_the_summary_carries_the_four_columns(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.INFO)
    main(["--config", str(_write_config_yaml(tmp_path))], sweep=_fake_sweep(tmp_path))
    for expected in ("parsed", "failed", "steps", "DDs"):
        assert expected in caplog.text


def test_the_summary_counts_failures_by_error_type(tmp_path: Path, caplog) -> None:
    """Which failures share a cause is the whole question a grammar fix asks, and
    the type is the part of an error that carries no corpus text."""
    caplog.set_level(logging.INFO)
    main(["--config", str(_write_config_yaml(tmp_path))], sweep=_fake_sweep(tmp_path))
    assert "JclParseError" in caplog.text


def test_the_summary_names_no_member_and_quotes_no_message(
    tmp_path: Path, caplog
) -> None:
    """The security property. A member name is a corpus identifier and an ANTLR
    message quotes corpus source, so neither may reach a log anyone tails -- they
    go only to the JSON, whose destination the caller chose."""
    caplog.set_level(logging.INFO)
    main(["--config", str(_write_config_yaml(tmp_path))], sweep=_fake_sweep(tmp_path))
    assert "BADJOB" not in caplog.text
    assert "//STEP1 EXEC" not in caplog.text


def test_the_output_path_is_logged_and_the_member_names_are_not(
    tmp_path: Path, caplog
) -> None:
    caplog.set_level(logging.INFO)
    out = tmp_path / "unparseable.json"
    main(
        ["--config", str(_write_config_yaml(tmp_path)), "--output", str(out)],
        sweep=_fake_sweep(tmp_path),
    )
    assert f"Wrote {out}" in caplog.text
    assert "BADJOB" not in caplog.text


def test_the_sweep_is_handed_the_worker_count_from_the_flag(tmp_path: Path) -> None:
    """The sweep is 860 JVM subprocesses on the corpus that motivated this, so the
    flag has to reach the store rather than sit in the help text."""

    def sweep(paths: Sequence[Path], max_workers: int) -> list[SweepResult]:
        raise AssertionError(f"workers={max_workers}")

    with pytest.raises(AssertionError, match="workers=9"):
        main(
            ["--config", str(_write_config_yaml(tmp_path)), "--max-workers", "9"],
            sweep=sweep,
        )


def test_the_exit_status_is_zero_even_when_members_fail(tmp_path: Path) -> None:
    """This reports, it does not gate: a corpus is onboarded with members that do
    not parse, and a non-zero exit would make that state unscriptable."""
    assert (
        main(
            ["--config", str(_write_config_yaml(tmp_path))], sweep=_fake_sweep(tmp_path)
        )
        == 0
    )

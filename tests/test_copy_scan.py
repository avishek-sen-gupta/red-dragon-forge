"""The batch COPY scan client.

The bridge's ``-scan-copy`` mode answers which copybooks a corpus names without
resolving any of them, in one JVM for the whole corpus. Resolution is the step
that fails, and it fails one member at a time only after a full ASG parse has
already been built, so asking first is worth a dedicated mode.

These tests pin the wire contract in both directions: what reaches the java
command line and stdin, and how each JSON line comes back. The scan itself is
ProLeap's ``CobolPreprocessor.g4``; what is cobble's to get right is the framing.
"""

from pathlib import Path

from cobble.copy_scan import CopyRef, scan_copy_statements
from cobble.interpreter.cobol.subprocess_runner import SubprocessRunner


class RecordingRunner(SubprocessRunner):
    """Captures the command and stdin it was handed, returns canned JSON Lines."""

    def __init__(self, stdout: str = "") -> None:
        self.command: list[str] = []
        self.input_data: str = ""
        self.calls = 0
        self._stdout = stdout

    def run(self, command: list[str], input_data: str) -> str:
        self.command = command
        self.input_data = input_data
        self.calls += 1
        return self._stdout


def test_the_bridge_is_invoked_in_scan_copy_mode() -> None:
    runner = RecordingRunner()

    scan_copy_statements([Path("/src/PROGA.cbl")], runner, "bridge.jar")

    assert runner.command == ["java", "-jar", "bridge.jar", "-scan-copy"]


def test_the_paths_are_sent_newline_separated_on_stdin() -> None:
    """One JVM for the whole corpus is the entire reason this is a batch: per
    member, JVM startup dominates everything the scan actually does."""
    runner = RecordingRunner()

    scan_copy_statements(
        [Path("/src/PROGA.cbl"), Path("/src/PROGB.cbl")], runner, "b.jar"
    )

    assert runner.input_data == "/src/PROGA.cbl\n/src/PROGB.cbl\n"
    assert runner.calls == 1


def test_each_json_line_becomes_a_scan_result() -> None:
    runner = RecordingRunner(
        '{"file":"/src/PROGA.cbl","errors":0,'
        '"copies":[{"name":"CUSTREC","line":12},{"name":"ORDREC","line":30}]}\n'
        '{"file":"/src/PROGB.cbl","errors":0,"copies":[]}\n'
    )

    results = scan_copy_statements([Path("/src/PROGA.cbl")], runner, "b.jar")

    assert [r.path for r in results] == [Path("/src/PROGA.cbl"), Path("/src/PROGB.cbl")]
    assert results[0].copies == (CopyRef("CUSTREC", 12), CopyRef("ORDREC", 30))
    assert results[0].errors == 0
    assert results[0].message is None
    assert results[1].copies == ()


def test_a_member_with_syntax_errors_still_reports_the_copies_it_found() -> None:
    """ANTLR recovers and keeps reporting COPYs after a syntax error, so a
    non-zero count means the list may be incomplete -- not that it is empty."""
    runner = RecordingRunner(
        '{"file":"/src/PROGA.cbl","errors":3,"copies":[{"name":"CUSTREC","line":12}]}\n'
    )

    (result,) = scan_copy_statements([Path("/src/PROGA.cbl")], runner, "b.jar")

    assert result.errors == 3
    assert result.copies == (CopyRef("CUSTREC", 12),)


def test_a_member_the_bridge_could_not_read_carries_its_message() -> None:
    runner = RecordingRunner(
        '{"file":"/src/GONE.cbl","errors":1,"copies":[],'
        '"message":"NoSuchFileException: /src/GONE.cbl"}\n'
    )

    (result,) = scan_copy_statements([Path("/src/GONE.cbl")], runner, "b.jar")

    assert result.message == "NoSuchFileException: /src/GONE.cbl"
    assert result.copies == ()


def test_blank_output_lines_are_ignored() -> None:
    runner = RecordingRunner('\n{"file":"/src/PROGA.cbl","errors":0,"copies":[]}\n\n')

    results = scan_copy_statements([Path("/src/PROGA.cbl")], runner, "b.jar")

    assert [r.path for r in results] == [Path("/src/PROGA.cbl")]


def test_an_empty_path_list_does_not_start_a_jvm() -> None:
    """Starting a JVM to scan nothing is a second of latency for no answer, and
    an empty corpus is a legitimate state during onboarding."""
    runner = RecordingRunner()

    assert scan_copy_statements([], runner, "b.jar") == []
    assert runner.calls == 0

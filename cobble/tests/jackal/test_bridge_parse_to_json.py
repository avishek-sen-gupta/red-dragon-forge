"""JclBridgeParser.parse_to_json — the bridge's JSON without building a Job.

JclStore caches what the bridge emitted rather than what it deserialized to, so
it needs the raw JSON. The bridge already hands its output back as a string, so
this is the same subprocess call as ``parse()`` minus the deserialization —
which is exactly what makes a disk-backed store cheap here.
"""

from collections.abc import Sequence

import pytest

from cobble.jackal.jcl.bridge_parser import JclBridgeParser, JclParseError

_MINIMAL_JOB = '{"name": "PAYROLL", "steps": []}'


class RecordingRunner:
    """Captures what it was handed and returns canned bridge output."""

    def __init__(self, stdout: str = _MINIMAL_JOB) -> None:
        self._stdout = stdout
        self.command: tuple[str, ...] = ()
        self.input_data: str = ""

    def run(self, command: Sequence[str], input_data: str) -> str:
        self.command = tuple(command)
        self.input_data = input_data
        return self._stdout


def test_parse_to_json_returns_the_bridge_output_verbatim() -> None:
    runner = RecordingRunner()
    parser = JclBridgeParser(runner, "bridge.jar")  # type: ignore[arg-type]
    assert parser.parse_to_json("//A JOB") == _MINIMAL_JOB


def test_parse_to_json_invokes_the_same_command_as_parse() -> None:
    runner = RecordingRunner()
    JclBridgeParser(runner, "bridge.jar").parse_to_json("//A JOB")  # type: ignore[arg-type]
    assert runner.command == ("java", "-jar", "bridge.jar")
    assert runner.input_data == "//A JOB"


def test_parse_to_json_rejects_output_that_is_not_json() -> None:
    """A truncated or empty bridge response must fail here rather than be cached
    and fail later on get(), where the member it belongs to is harder to name."""
    runner = RecordingRunner(stdout="{ oops")
    parser = JclBridgeParser(runner, "bridge.jar")  # type: ignore[arg-type]
    with pytest.raises(JclParseError, match="malformed"):
        parser.parse_to_json("//A JOB")

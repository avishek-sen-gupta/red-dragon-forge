"""ProLeapCobolParser command construction.

The bridge resolves copybooks by name + extension, so which extensions it
searches is corpus shape, not a cobble constant (a corpus whose members are
all .txt resolves nothing under the bridge's built-in list). These tests pin
how that reaches the java command line.
"""

from pathlib import Path

from cobble.interpreter.cobol.subprocess_runner import SubprocessRunner
from cobble.interpreter.cobol.cobol_parser import ProLeapCobolParser

_MINIMAL_ASG = '{"data_fields": [], "sections": [], "paragraphs": []}'


class RecordingRunner(SubprocessRunner):
    """Captures the command it was handed and returns a canned ASG."""

    def __init__(self) -> None:
        self.command: list[str] = []

    def run(self, command: list[str], input_data: str) -> str:
        self.command = command
        return _MINIMAL_ASG


def _command_for(**kwargs: object) -> list[str]:
    runner = RecordingRunner()
    ProLeapCobolParser(runner, "bridge.jar", **kwargs).parse(b"")  # type: ignore[arg-type]
    return runner.command


def test_parse_passes_each_copybook_extension_as_a_repeated_flag() -> None:
    command = _command_for(copybook_extensions=["cpy", "txt"])
    assert command == [
        "java",
        "-jar",
        "bridge.jar",
        "-copybook-ext",
        "cpy",
        "-copybook-ext",
        "txt",
    ]


def test_parse_omits_the_extension_flag_when_no_extensions_configured() -> None:
    """No flag means the bridge keeps its own default list."""
    assert "-copybook-ext" not in _command_for()


def test_parse_emits_copybook_dirs_before_extensions() -> None:
    command = _command_for(copybook_dirs=[Path("sym")], copybook_extensions=["cpy"])
    assert command == [
        "java",
        "-jar",
        "bridge.jar",
        "-copybook-dir",
        "sym",
        "-copybook-ext",
        "cpy",
    ]

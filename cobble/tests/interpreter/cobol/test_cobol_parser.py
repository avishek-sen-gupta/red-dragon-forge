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
        self.input_data: str = ""

    def run(self, command: list[str], input_data: str) -> str:
        self.command = command
        self.input_data = input_data
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


def test_parse_accepts_a_member_that_is_not_valid_utf_8() -> None:
    """Members are 8-bit text. 0xA6 0xA6 is not legal UTF-8, and a strict decode
    raised UnicodeDecodeError before the source reached the bridge."""
    runner = RecordingRunner()
    ProLeapCobolParser(runner, "bridge.jar").parse(b"      * \xa6\xa6")
    assert runner.input_data == "      * ¦¦"


def test_parse_to_file_accepts_a_member_that_is_not_valid_utf_8(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    ProLeapCobolParser(runner, "bridge.jar").parse_to_file(
        b"      * \xa6\xa6", tmp_path / "out.ast.json"
    )
    assert runner.input_data == "      * ¦¦"


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

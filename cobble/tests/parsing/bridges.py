"""Bridges that answer without starting a JVM, for the two corpus-walk stages."""

from collections.abc import Sequence

from cobol_asg.subprocess_runner import CobolParseError, SubprocessRunner


class CannedBridge(SubprocessRunner):
    """A bridge that answers with fixed text."""

    def __init__(self, output: str) -> None:
        self._output = output

    def run(self, command: Sequence[str], input_data: str) -> str:
        return self._output


class RejectingBridge(SubprocessRunner):
    """A bridge that fails the way a missing copybook fails."""

    def __init__(self, message: str) -> None:
        self._message = message

    def run(self, command: Sequence[str], input_data: str) -> str:
        raise CobolParseError(self._message)

"""Lines serve ACCEPT one 80-byte card each until they end; with none supplied the value is unknown."""

from infrastructure.zos.access_methods.access_result import AccessCondition
from interpreter.cobol.io_provider import IOResult
from interpreter.vm.vm import Operators
from tests.covers import NotLanguageFeature, covers
from zos.cobol.io.system_input import line_input, unsupplied


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_each_line_is_one_card_until_the_lines_end() -> None:
    read = line_input(iter(["00000050\n", "LAST"]))

    assert (read(), read(), read(), unsupplied()) == (
        IOResult(AccessCondition.OK, "00000050".ljust(80)),
        IOResult(AccessCondition.OK, "LAST".ljust(80)),
        IOResult(AccessCondition.END_OF_FILE, None),
        Operators.UNCOMPUTABLE,
    )

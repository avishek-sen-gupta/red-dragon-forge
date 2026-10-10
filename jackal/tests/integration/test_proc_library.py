"""A PROC member is read from a directory library as 8-bit mainframe text."""

from pathlib import Path

from jackal.expansion import DirectoryProcLibrary
from jackal.jcl.parser import parse_proc
from jackal.model import ProcRef
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_member_with_bytes_above_0x7f_is_read_byte_for_byte(tmp_path: Path) -> None:
    text = "//HIGH PROC\n//P1 EXEC PGM=IEFBR14,PARM='CAF\xe9'\n// PEND\n"
    (tmp_path / "HIGH.prc").write_bytes(text.encode("latin-1"))
    assert DirectoryProcLibrary((tmp_path,)).find(ProcRef("HIGH")) == parse_proc(text)

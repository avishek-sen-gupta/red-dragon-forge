"""catnip install: a declaration validated whole, then loaded into a system catalog."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from catnip.dataset import Dataset
from catnip.declaration import load_declaration
from catnip.declaration_error import DeclarationError
from catnip.install import install
from catnip.labels import KsdsLabel, PathView, RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged, SystemCatalog
from cobol_asg.file_enums import OpenMode
from tests.covers import NotLanguageFeature, covers

_GOOD = """\
data_dir = "{data}"

[[sequential]]
dsn = "T.SEQ"
from = "seq.ps"
recfm = "FB"
lrecl = 4

[[ksds]]
dsn = "T.KSDS"
from = "ksds.ps"
lrecl = 8
key_offset = 0
key_length = 3

[[ksds.aix]]
dsn = "T.AIX"
path = "T.PATH"
key_offset = 3
key_length = 3
unique = false

[[ksds]]
dsn = "T.EMPTY"
lrecl = 8
key_offset = 0
key_length = 3
"""


def _declared(tmp_path: Path, text: str, files: Mapping[str, bytes]) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    for name, content in files.items():
        (data / name).write_bytes(content)
    declaration = tmp_path / "data.toml"
    declaration.write_text(text.format(data=data))
    return declaration


def _read_three(path: Dataset) -> list[bytes]:
    drv = path.opened(OpenMode.INPUT)
    through = [drv.read_seq().data for _ in range(3)]
    drv.close()
    return through


_FILES = {"seq.ps": b"abcdefgh", "ksds.ps": b"003AAAzz001BBBxx002AAAyy"}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_declaration_installs_sorted_clusters_indexes_and_paths(tmp_path):
    system = SystemCatalog(tmp_path / "system")
    installed = install(load_declaration(_declared(tmp_path, _GOOD, _FILES)), system)
    path = system.lookup("T.PATH")
    through = _read_three(path)

    assert installed == ("T.SEQ", "T.KSDS", "T.AIX", "T.PATH", "T.EMPTY")
    assert system.lookup("T.SEQ").label == SequentialLabel(RecordFormat.FB, 4)
    assert system.lookup("T.KSDS").path.read_bytes() == b"001BBBxx002AAAyy003AAAzz"
    assert system.lookup("T.EMPTY").path.read_bytes() == b""
    assert path.label == PathView("T.KSDS", KsdsLabel(8, 0, 3), 3, 3, False)
    assert through == [b"002AAAyy", b"003AAAzz", b"001BBBxx"]


@pytest.mark.parametrize(
    ("change", "files", "message"),
    [
        (
            (
                "lrecl = 8\nkey_offset = 0\nkey_length = 3\n\n[[ksds.aix]]",
                "lrecl = 7\nkey_offset = 0\nkey_length = 3\n\n[[ksds.aix]]",
            ),
            _FILES,
            "T.KSDS: from: ksds.ps holds 24 bytes, not a whole number of 7-byte records",
        ),
        (
            ("key_offset = 3\nkey_length = 3", "key_offset = 6\nkey_length = 3"),
            _FILES,
            "T.AIX: key_offset: key 6+3 overruns the 8-byte record",
        ),
        (
            ("unique = false", "unique = true"),
            _FILES,
            "T.AIX: unique: alternate key b'AAA' repeats",
        ),
        (
            ("", ""),
            {**_FILES, "ksds.ps": b"001AAAzz001BBBxx"},
            "T.KSDS: from: primary key b'001' repeats",
        ),
        (('dsn = "T.EMPTY"', 'dsn = "T.SEQ"'), _FILES, "T.SEQ: dsn: declared twice"),
        (
            ('from = "seq.ps"', 'from = "nope.ps"'),
            _FILES,
            "T.SEQ: from: nope.ps does not exist",
        ),
    ],
)
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_invalid_declaration_installs_nothing_and_names_the_field(
    tmp_path, change, files, message
):
    text = _GOOD.replace(*change)
    system = SystemCatalog(tmp_path / "system")

    with pytest.raises(DeclarationError) as error:
        install(load_declaration(_declared(tmp_path, text, files)), system)

    assert str(error.value) == message
    assert SystemCatalog(tmp_path / "system").lookup("T.SEQ") == NotCataloged()

"""catnip install: a declaration validated whole, then loaded into a system catalog."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

import pytest
from catnip.cli import run
from catnip.dataset import Dataset
from catnip.declaration import load_declaration
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
        (
            ('from = "seq.ps"\n', ""),
            _FILES,
            "[[sequential]] T.SEQ: from: Field required",
        ),
        (
            ('dsn = "T.SEQ"\n', ""),
            _FILES,
            "[[sequential]] entry 1: dsn: Field required",
        ),
        (
            (
                "key_offset = 0\nkey_length = 3\n\n[[ksds.aix]]",
                "key_offset = 0\nkey_lenth = 3\n\n[[ksds.aix]]",
            ),
            _FILES,
            "[[ksds]] T.KSDS: key_length: Field required",
        ),
        (
            ('recfm = "FB"', 'recfm "FB"'),
            _FILES,
            "{declaration}: Expected '=' after a key in a key/value pair (at line 6, column 7)",
        ),
        (
            ('dsn = "T.EMPTY"\nlrecl = 8', 'dsn = "T.EMPTY"\nlrecl = 0'),
            _FILES,
            "[[ksds]] T.EMPTY: lrecl: Input should be greater than 0",
        ),
        (
            ("key_offset = 3\nkey_length = 3", "key_offset = -1\nkey_length = 3"),
            _FILES,
            "[[ksds.aix]] T.AIX: key_offset: Input should be greater than or equal to 0",
        ),
        (
            (
                '[[ksds]]\ndsn = "T.EMPTY"',
                '[[gdg]]\nname = "T.GDG"\nlimit = 0\nempty = "NOEMPTY"\n'
                'scratch = "NOSCRATCH"\norder = "LIFO"\n\n[[ksds]]\ndsn = "T.EMPTY"',
            ),
            _FILES,
            "[[gdg]] T.GDG: limit: Input should be greater than 0",
        ),
        (
            (
                '[[sequential]]\ndsn = "T.SEQ"\nfrom = "seq.ps"\n',
                'gdg = [1]\n\n[[sequential]]\ndsn = "T.SEQ"\n',
            ),
            _FILES,
            "[[sequential]] entry 1: from: Field required",
        ),
    ],
)
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_invalid_declaration_installs_nothing_and_names_the_field(
    tmp_path, caplog, change, files, message
):
    declaration = _declared(tmp_path, _GOOD.replace(*change), files)
    root = tmp_path / "system"

    with caplog.at_level(logging.ERROR, logger="catnip.cli"):
        code = run(["install", str(declaration), "--system", str(root)])

    assert code == 1
    assert caplog.messages == [message.format(declaration=declaration)]
    assert [p for p in root.rglob("*") if p.is_file()] == []
    assert SystemCatalog(root).lookup("T.SEQ") == NotCataloged()

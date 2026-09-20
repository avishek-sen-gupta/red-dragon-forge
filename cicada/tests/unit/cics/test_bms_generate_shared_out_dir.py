"""Pins forge-6o7's fix: generate_symbolic_copybooks must be first-wins when
several bms_dirs are generated into one shared out_dir (task 10 of the
2026-09-19-carddemo-db2-tier plan), matching cics.bms.catalog.MapCatalog's
ChainMap merge for load_catalog. Before the fix, the LAST bms_dir to define a
given map name silently overwrote an earlier directory's symbolic copybook on
disk, even though the catalog itself kept the earlier map's DFHMSD/DFHMDI
data -- a contradiction between the two merge directions that would surface,
far from its cause, as a blank TN3270 screen for whichever map lost the
overwrite.

Uses a stand-in for the hlasm_export / bms_copybook_gen subprocess pipeline
(monkeypatched) rather than the real toolchain -- this pins the file-merge
policy in cics.bms.generate, not the external pipeline itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cics.bms.generate import generate_symbolic_copybooks


def _fake_run(args, capture_output=False, check=False, input=None):
    if "bms_copybook_gen" in " ".join(str(a) for a in args):
        # Second stage of the pipeline: echo the export stage's stdout back
        # unchanged, so the final written content still identifies its source.
        return SimpleNamespace(stdout=input, returncode=0)
    # First stage (hlasm_export <bms_file> ...): tag the output with the
    # source path so the two bms_dirs below produce distinguishable content.
    bms_file = args[1]
    return SimpleNamespace(stdout=f"EXPORT-OF:{bms_file}".encode(), returncode=0)


@pytest.fixture(autouse=True)
def _stub_subprocess(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run)


def test_second_bms_dir_does_not_overwrite_the_first_dirs_same_named_map(
    tmp_path: Path,
) -> None:
    dir_a = tmp_path / "bms_a"
    dir_b = tmp_path / "bms_b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "COLLIDE.bms").write_text("* map A\n")
    (dir_b / "COLLIDE.bms").write_text("* map B\n")
    out_dir = tmp_path / "sym"

    written_a = generate_symbolic_copybooks(
        bms_dir=dir_a, out_dir=out_dir, hlasm_export_bin="hlasm_export"
    )
    written_b = generate_symbolic_copybooks(
        bms_dir=dir_b, out_dir=out_dir, hlasm_export_bin="hlasm_export"
    )

    # The second generation must have skipped the collision entirely -- no
    # file written for it on the second call.
    assert written_a == [out_dir / "COLLIDE.cpy"]
    assert written_b == []

    content = (out_dir / "COLLIDE.cpy").read_text()
    assert str(dir_a / "COLLIDE.bms") in content
    assert str(dir_b / "COLLIDE.bms") not in content

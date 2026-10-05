"""The return-to-caller idiom, compiled by the real bridge, linked end to end."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from cobble.dataflow.combine.cli import cli
from tests.dataflow.combine.corpus_toml import CONFIG

PROGA = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-FROM          PIC X(8).
           05  WS-REST          PIC X(12).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGA' TO WS-FROM.
           EXEC CICS XCTL PROGRAM('PROGB') COMMAREA(WS-AREA) END-EXEC.
"""

PROGB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NEXT              PIC X(8).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-FROM          PIC X(8).
           05  LK-REST          PIC X(12).
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF LK-FROM = SPACES
               MOVE 'PROGM' TO WS-NEXT
           ELSE
               MOVE LK-FROM TO WS-NEXT
           END-IF.
           EXEC CICS XCTL PROGRAM(WS-NEXT)
               COMMAREA(DFHCOMMAREA) END-EXEC.
"""


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_return_to_caller_links_end_to_end(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path], tmp_path: Path
) -> None:
    out = fixpoint_corpus({"PROGA": PROGA, "PROGB": PROGB})
    config = tmp_path / "corpus.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"), encoding="utf-8")
    combined = tmp_path / "combined"

    assert (
        cli(
            [
                "--config",
                str(config),
                "--fixpoint-dir",
                str(out),
                "--out-dir",
                str(combined),
                "--all",
            ]
        )
        == 0
    )

    single = [
        (r["caller"], r["candidates"], r["reasons"])
        for r in _rows(out / "targets.jsonl")
    ]
    linked = [
        (r["caller"], r["candidates"], r["reasons"], r["outside"])
        for r in _rows(combined / "targets.jsonl")
    ]
    links = sorted(
        (
            r["caller"],
            r["callee"],
            r["caller_extent"],
            r["callee_extent"],
            r["discovered"],
        )
        for r in _rows(combined / "links.jsonl")
    )
    assert single == [("PROGB", ["PROGM"], ["inbound-linkage"])]
    assert linked == [("PROGB", ["PROGA", "PROGM"], [], [])]
    assert links == [
        (
            "PROGA",
            "PROGB",
            "WS-AREA@working_storage[0:20]",
            "DFHCOMMAREA@linkage[0:20]",
            False,
        ),
        (
            "PROGB",
            "PROGA",
            "DFHCOMMAREA@linkage[0:20]",
            "DFHCOMMAREA@linkage[0:20]",
            True,
        ),
    ]

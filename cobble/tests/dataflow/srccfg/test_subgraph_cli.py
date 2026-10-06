"""cobble-srccfg-subgraph: a CFG file in, a rendered DOT/PNG/SVG picture out."""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.srccfg.bundle import Bundle, bundle_jsonl
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.subgraph_cli import main


def _cfg(program: str = "PROGA") -> Cfg:
    return Cfg(
        program=program,
        nodes=(
            Node(id="MAIN#label", kind=NodeKind.LABEL, paragraph="MAIN"),
            Node(
                id="MAIN/0",
                kind=NodeKind.CALL,
                paragraph="MAIN",
                transfer="PERFORM",
                target="A",
            ),
            Node(id="A#label", kind=NodeKind.LABEL, paragraph="A"),
            Node(
                id="A/0",
                kind=NodeKind.ASSIGN,
                paragraph="A",
                transfer="MOVE",
                writes=("WS-C",),
            ),
        ),
        edges=(
            Edge(source="MAIN#label", target="MAIN/0", kind=EdgeKind.FLOW),
            Edge(source="MAIN/0", target="A#label", kind=EdgeKind.PERFORM),
            Edge(source="A#label", target="A/0", kind=EdgeKind.FLOW),
        ),
    )


def _cfg_file(tmp_path: Path, *cfgs: Cfg) -> Path:
    path = tmp_path / "cfg.jsonl"
    path.write_text(
        bundle_jsonl(Bundle(seed=cfgs[0].program, cfgs=cfgs)), encoding="utf-8"
    )
    return path


def test_writes_dot_png_and_svg(tmp_path: Path) -> None:
    out = tmp_path / "sub"
    assert (
        main(
            [
                "--cfg",
                str(_cfg_file(tmp_path, _cfg())),
                "--program",
                "PROGA",
                "--prefix",
                "MAIN/0",
                "--prefix",
                "A/0",
                "--out",
                str(out),
            ]
        )
        == 0
    )

    assert out.with_suffix(".dot").is_file()
    assert out.with_suffix(".png").is_file()
    assert out.with_suffix(".svg").is_file()
    dot_text = out.with_suffix(".dot").read_text()
    assert '"MAIN/0"' in dot_text
    assert '"A/0"' in dot_text
    assert '"A#label"' in dot_text  # bridged in to keep it connected


def test_balance_writes_a_balanced_sibling_and_renders_from_it(tmp_path: Path) -> None:
    out = tmp_path / "sub"
    assert (
        main(
            [
                "--cfg",
                str(_cfg_file(tmp_path, _cfg())),
                "--program",
                "PROGA",
                "--prefix",
                "MAIN/0",
                "--prefix",
                "A/0",
                "--out",
                str(out),
                "--balance",
            ]
        )
        == 0
    )

    assert (tmp_path / "sub-balanced.dot").is_file()
    assert out.with_suffix(".svg").is_file()


def test_a_missing_program_is_an_error_naming_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = tmp_path / "sub"
    assert (
        main(
            [
                "--cfg",
                str(_cfg_file(tmp_path, _cfg())),
                "--program",
                "NOPE",
                "--prefix",
                "MAIN/0",
                "--out",
                str(out),
            ]
        )
        == 1
    )
    assert "NOPE" in caplog.text
    assert not out.with_suffix(".dot").exists()


def test_two_unrelated_pieces_are_a_hard_error_not_a_disconnected_render(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    isolated = Cfg(
        program="PROGA",
        nodes=(
            *_cfg().nodes,
            Node(id="Z#label", kind=NodeKind.LABEL, paragraph="Z"),
            Node(
                id="Z/0",
                kind=NodeKind.ASSIGN,
                paragraph="Z",
                transfer="MOVE",
                writes=("WS-Z",),
            ),
        ),
        edges=(*_cfg().edges, Edge(source="Z#label", target="Z/0", kind=EdgeKind.FLOW)),
    )
    out = tmp_path / "sub"

    assert (
        main(
            [
                "--cfg",
                str(_cfg_file(tmp_path, isolated)),
                "--program",
                "PROGA",
                "--prefix",
                "MAIN/0",
                "--prefix",
                "Z/0",
                "--out",
                str(out),
            ]
        )
        == 1
    )
    assert "genuinely unrelated" in caplog.text
    assert not out.with_suffix(".dot").exists()


def test_cross_program_render_merges_both_programs(tmp_path: Path) -> None:
    out = tmp_path / "sub"
    assert (
        main(
            [
                "--cfg",
                str(_cfg_file(tmp_path, _cfg("PROGA"), _cfg("PROGB"))),
                "--program",
                "PROGA",
                "--program",
                "PROGB",
                "--prefix",
                "MAIN/0",
                "--prefix",
                "A/0",
                "--out",
                str(out),
            ]
        )
        == 0
    )

    assert out.with_suffix(".svg").is_file()

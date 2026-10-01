"""Every explainer page teaches the answer cobble actually reaches on its example."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest
from cobble.dataflow.fields.emit_extents import emit
from cobble.dataflow.fixpoint import rows
from cobble.dataflow.fixpoint.build_corpus import cli
from cobble.knowledge_graph.graph_file import read_graph
from cobble.parsing.parse_corpus import Job, parse_one
from pydantic import BaseModel, ConfigDict, Field

FORGE = Path(__file__).resolve().parents[3]
EXPLAINERS = FORGE / "docs" / "explainers"
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"
OPENING = '<script type="application/json" id="example">'
CLOSING = "</script>"
PAGES = ("fixpoints.html", "reaching-definitions.html")


class Check(StrEnum):
    FLOWS = "flows"
    DEFS = "defs"
    TARGETS = "targets"


class _Defs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node: str
    extent: str
    definers: tuple[str, ...]


class _Target(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node: str
    expression: str
    candidates: tuple[str, ...]
    reasons: tuple[str, ...]


class _Expected(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    checks: tuple[Check, ...] = Field(min_length=1)
    flows: tuple[tuple[str, str], ...] = ()
    defs: tuple[_Defs, ...] = ()
    targets: tuple[_Target, ...] = ()


class _Example(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    member: str
    program: str
    expected: _Expected


def _example(page: str) -> _Example:
    html = (EXPLAINERS / page).read_text(encoding="utf-8")
    assert html.count(OPENING) == 1, f"{page} needs exactly one example block"
    return _Example.model_validate_json(
        html.partition(OPENING)[2].partition(CLOSING)[0]
    )


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def _analysed(example: _Example, workspace: Path) -> Path:
    source = workspace / f"{example.member}.cbl"
    source.write_text(example.program, encoding="utf-8")
    cache = workspace / "parsed"
    cache.mkdir()
    parsed = parse_one(
        Job(source, cache / f"{example.member}.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert parsed.ok, parsed.error
    extents = workspace / "extents.jsonl"
    assert emit(cache, extents, (), max_workers=1) == 0
    out = workspace / "out"
    cli(
        [
            "--asg-dir",
            str(cache),
            "--out-dir",
            str(out),
            "--extents",
            str(extents),
            "--member",
            example.member,
            "--max-workers",
            "1",
            "--min-coverage",
            "0",
        ]
    )
    return out


def _flows(out: Path) -> frozenset[tuple[str, str]]:
    _, edges = read_graph(out / "graph.jsonl")
    return frozenset((edge.source, edge.target) for edge in edges)


def _defs(out: Path) -> frozenset[_Defs]:
    return frozenset(
        _Defs(
            node=rows.text(row, "node"),
            extent=rows.text(row, "extent"),
            definers=rows.strings(row, "definers"),
        )
        for row in rows.read(out / "defs.jsonl")
    )


def _targets(out: Path) -> frozenset[_Target]:
    return frozenset(
        _Target(
            node=rows.text(row, "node"),
            expression=rows.text(row, "expression"),
            candidates=rows.strings(row, "candidates"),
            reasons=rows.strings(row, "reasons"),
        )
        for row in rows.read(out / "targets.jsonl")
    )


@pytest.mark.parametrize("page", PAGES)
def test_the_page_teaches_cobbles_answer(page: str, tmp_path: Path) -> None:
    expected = _example(page).expected
    out = _analysed(_example(page), tmp_path)

    if Check.FLOWS in expected.checks:
        assert _flows(out) == frozenset(expected.flows)
    if Check.DEFS in expected.checks:
        assert _defs(out) == frozenset(expected.defs)
    if Check.TARGETS in expected.checks:
        assert _targets(out) == frozenset(expected.targets)


def test_the_index_links_exactly_the_pages_on_disk() -> None:
    on_disk = {path.name for path in EXPLAINERS.glob("*.html")} - {"index.html"}
    index = (EXPLAINERS / "index.html").read_text(encoding="utf-8")
    linked = {page for page in on_disk if f'href="{page}"' in index}
    assert (on_disk, linked) == (set(PAGES), set(PAGES))

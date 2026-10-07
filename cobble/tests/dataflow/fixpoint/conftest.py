"""Invented COBOL, compiled by the real bridge and run through extents and the fixpoint."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from cobble.dataflow.fields.emit_extents import emit
from cobble.dataflow.fixpoint.build_corpus import cli

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


@pytest.fixture(scope="session")
def fixpoint_out(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[str, str], Path]:
    """Parse ``source`` as ``member``, lay it out, run the fixpoint; the out-dir."""

    def run(member: str, source: str) -> Path:
        return _fixpoint(tmp_path_factory, ("--member", member), {member: source}, ())

    return run


@pytest.fixture(scope="session")
def fixpoint_corpus(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[Mapping[str, str]], Path]:
    """Parse every program into one cache and run the fixpoint over all of them; the
    out-dir, whose parent holds the extents."""

    def run(sources: Mapping[str, str]) -> Path:
        return _fixpoint(tmp_path_factory, ("--all",), sources, ())

    return run


@pytest.fixture(scope="session")
def fixpoint_corpus_with(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[Mapping[str, str], tuple[str, ...]], Path]:
    """``fixpoint_corpus`` with extra fixpoint arguments."""

    def run(sources: Mapping[str, str], extra: tuple[str, ...]) -> Path:
        return _fixpoint(tmp_path_factory, ("--all",), sources, extra)

    return run


def _fixpoint(
    tmp_path_factory: pytest.TempPathFactory,
    selection: tuple[str, ...],
    sources: Mapping[str, str],
    extra: tuple[str, ...],
) -> Path:
    from cobble.parsing.parse_corpus import Job, parse_one

    workspace = tmp_path_factory.mktemp(next(iter(sources)).lower())
    cache = workspace / "parsed"
    cache.mkdir()
    for name, source in sources.items():
        program = workspace / f"{name}.cbl"
        program.write_text(source, encoding="utf-8")
        parsed = parse_one(
            Job(program, cache / f"{name}.json"), str(_bridge_jar()), (), ("cpy",)
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
            *selection,
            "--max-workers",
            "1",
            *extra,
        ]
    )
    return out

"""Invented COBOL, compiled by the real bridge and run through extents and the fixpoint."""

from __future__ import annotations

from collections.abc import Callable
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
    from cobble.parsing.parse_corpus import Job, parse_one

    def run(member: str, source: str) -> Path:
        workspace = tmp_path_factory.mktemp(member.lower())
        program = workspace / f"{member}.cbl"
        program.write_text(source, encoding="utf-8")
        cache = workspace / "parsed"
        cache.mkdir()
        parsed = parse_one(
            Job(program, cache / f"{member}.json"), str(_bridge_jar()), (), ("cpy",)
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
                member,
                "--max-workers",
                "1",
            ]
        )
        return out

    return run

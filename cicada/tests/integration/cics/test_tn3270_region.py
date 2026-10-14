"""Proves build_region's ``extra_specs`` seam (task 9 of the
2026-09-19-carddemo-db2-tier plan) actually composes a caller-supplied
:class:`CoprocessorSpec` into ``compile_program``, not merely that
``build_region`` accepts the parameter without dropping it.

Cicada cannot import squall (the import-linter contract
``cicada-squall-jackal-independence`` forbids ``cics`` -> ``squall``), so this
uses a local no-op stand-in spec rather than squall's real SQL spec -- task 10
supplies that one from ``red_dragon_forge``, the one package allowed to import
both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tests.integration.cics.tn3270_helpers import region_toml
from cics.tn3270.config import load_config
from cics.tn3270.region import build_region
from interpreter.project.coprocessor_compile import CoprocessorSpec
from tests.covers import NotLanguageFeature, covers
from tests.integration.cics.tn3270_helpers import REPO_ROOT
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

pytestmark = pytest.mark.carddemo_e2e

_CONFIG = Path(__file__).parents[3] / "config" / "carddemo-tn3270.toml"


class _NoOpStrategy:
    """Satisfies RedDragonExtensionLoweringStrategy (see
    interpreter/frontend_extension_lowering.py) without handling any
    statement -- ``handles`` always returns False, so ``lower`` is never
    called and this strategy has no effect on any compiled program."""

    name = "noop"

    def handles(self, stmt: Any) -> bool:
        return False

    def preprocess_program_dict(self, data: dict) -> dict:
        return data

    def on_procedure_entry(self, ctx: Any, materialised: Any) -> None:
        return None

    def lower(self, ctx: Any, stmt: Any, materialised: Any) -> None:
        raise AssertionError("never called: handles() always returns False")


@dataclass
class _Recorder:
    sources: list[str] = field(default_factory=list)


def _stub_spec(recorder: _Recorder) -> CoprocessorSpec:
    def source_prepass(text: str) -> str:
        recorder.sources.append(text)
        return text

    return CoprocessorSpec(
        name="stub", make_strategy=_NoOpStrategy, source_prepass=source_prepass
    )


_PROGRAM_ID = re.compile(r"PROGRAM-ID\.\s+([A-Z0-9-]+)", re.IGNORECASE)


def _program_id(source: str) -> str:
    return _PROGRAM_ID.search(source).group(1)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extra_specs_prepass_runs_for_every_compiled_program(
    tmp_path, bridge_jar, monkeypatch, carddemo_system
):
    """Against pre-task-9 code, build_region has no extra_specs parameter at
    all, so this call raises TypeError before ever reaching a spec -- this
    test fails there. A build_region that accepted the parameter but never
    threaded it into compile_program would leave recorder.sources empty; only
    a build_region that actually composes it produces one recorded source
    per compiled program, each containing that program's own name. Compiled
    programs include static callees: COTRN02C calls CSUTLDTC, found in the
    CardDemo source directory, which calls the Language Environment stub
    CEEDAYS, found in the LE stub directory."""
    monkeypatch.setenv("FORGE_ROOT", str(REPO_ROOT))
    config = load_config(region_toml(_CONFIG, carddemo_system))
    recorder = _Recorder()

    build_region(config, bridge_jar, tmp_path, extra_specs=[_stub_spec(recorder)])

    assert sorted(_program_id(text) for text in recorder.sources) == sorted(
        (*config.programs, "CSUTLDTC", "CEEDAYS")
    )

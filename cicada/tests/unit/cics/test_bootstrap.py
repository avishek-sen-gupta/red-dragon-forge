"""Unit tests for the CICS region bootstrap wiring (no ProLeap required).

These tests exercise the assembly logic of ``run_carddemo_region`` — CSD
parsing, program-cache construction keyed by program name, fail-fast on a
missing source — by stubbing out the real compile + dispatcher loop. They do
NOT execute real COBOL (that is the JAR-gated integration test).
"""

from __future__ import annotations

import queue

from cics.entered_program import EnteredProgram

import pytest

from cics import bootstrap
from cics.dispatcher import parse_csd
from cics.types import CicsContext, DispatchKind, DispatchResult
from interpreter.func_name import FuncName
from interpreter.types.type_expr import UNKNOWN
from interpreter.types.typed_value import typed
from interpreter.vm.builtins import Builtins
from interpreter.vm.vm_types import VMState
from tests.covers import covers, NotLanguageFeature


@pytest.fixture(autouse=True)
def _restore_builtins_table():
    before = dict(Builtins.TABLE)
    yield
    Builtins.TABLE.clear()
    Builtins.TABLE.update(before)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_run_region_fails_fast_on_missing_source(monkeypatch):
    """A CSD program with no matching source raises before the loop starts."""

    def _boom(*a, **k):  # the loop must never be reached
        raise AssertionError("dispatcher loop should not run on missing source")

    monkeypatch.setattr(bootstrap, "_run_dispatcher_with_runner", _boom)

    with pytest.raises(Exception) as exc:
        bootstrap.run_carddemo_region(
            transid_to_program={"CC00": "SGNPGM"},
            program_sources={},  # SGNPGM has no source
            parser=object(),
            entry_transid="CC00",
            screen_queue=queue.Queue(),
            input_queue=queue.Queue(),
        )
    assert "SGNPGM" in str(exc.value)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_run_region_builds_program_cache_keyed_by_program_name(monkeypatch):
    """Each distinct CSD program is compiled into the cache keyed by program name."""
    compiled: dict[str, object] = {}

    def _fake_compile(source, parser, strategy, **kwargs):
        sentinel = object()
        compiled[source] = sentinel
        return sentinel

    captured: dict[str, object] = {}

    def _fake_loop(
        run_fn, program_cache, transid_to_program, initial_context, sq, iq, **kwargs
    ):
        captured["program_cache"] = program_cache
        captured["transid_to_program"] = transid_to_program
        captured["initial_context"] = initial_context
        return DispatchResult(kind=DispatchKind.RETURN)

    monkeypatch.setattr(bootstrap, "compile_cics_program", _fake_compile)
    monkeypatch.setattr(bootstrap, "_run_dispatcher_with_runner", _fake_loop)

    result = bootstrap.run_carddemo_region(
        transid_to_program={"CC00": "SGNPGM", "CM00": "MENUPGM"},
        program_sources={"SGNPGM": b"src-sgn", "MENUPGM": b"src-menu"},
        parser=object(),
        entry_transid="CC00",
        screen_queue=queue.Queue(),
        input_queue=queue.Queue(),
    )

    assert result.kind == DispatchKind.RETURN
    cache = captured["program_cache"]
    assert set(cache.keys()) == {"SGNPGM", "MENUPGM"}
    # Cache values are the sentinels the (stubbed) compile produced, each
    # entered by its own program name.
    assert cache["SGNPGM"] == EnteredProgram("SGNPGM", compiled[b"src-sgn"])
    assert cache["MENUPGM"] == EnteredProgram("MENUPGM", compiled[b"src-menu"])
    # The loop is driven at the entry transid.
    ctx = captured["initial_context"]
    assert isinstance(ctx, CicsContext)
    assert ctx.transid == "CC00"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_run_region_from_csd_wires_transid_mapping(monkeypatch, tmp_path):
    """A CSD parsed by parse_csd names the programs the region compiles and runs."""
    csd = tmp_path / "region.csd"
    csd.write_text(
        "DEFINE TRANSACTION(CC00) PROGRAM(SGNPGM)\n"
        "DEFINE TRANSACTION(CM00) PROGRAM(MENUPGM)\n"
    )

    monkeypatch.setattr(
        bootstrap,
        "compile_cics_program",
        lambda source, parser, strategy, **kwargs: object(),
    )

    captured: dict[str, object] = {}

    def _fake_loop(
        run_fn, program_cache, transid_to_program, initial_context, sq, iq, **kwargs
    ):
        captured["transid_to_program"] = transid_to_program
        captured["program_cache"] = program_cache
        return DispatchResult(kind=DispatchKind.RETURN)

    monkeypatch.setattr(bootstrap, "_run_dispatcher_with_runner", _fake_loop)

    bootstrap.run_carddemo_region(
        transid_to_program=parse_csd(csd),
        program_sources={"SGNPGM": b"a", "MENUPGM": b"b"},
        parser=object(),
        entry_transid="CC00",
        screen_queue=queue.Queue(),
        input_queue=queue.Queue(),
    )

    assert captured["transid_to_program"] == {"CC00": "SGNPGM", "CM00": "MENUPGM"}
    assert set(captured["program_cache"].keys()) == {"SGNPGM", "MENUPGM"}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_run_region_threads_the_start_queue_and_termid_into_the_loop(monkeypatch):
    """The region's StartQueue goes to BOTH the coprocessor (which queues a
    START) and the dispatcher loop (which drains it) — otherwise a START on this
    path is validated, queued, and never run."""
    captured: dict[str, object] = {}

    def _fake_loop(
        run_fn, program_cache, transid_to_program, initial_context, sq, iq, **kwargs
    ):
        captured["loop_start_queue"] = kwargs["start_queue"]
        captured["loop_region_termid"] = kwargs["region_termid"]
        return DispatchResult(kind=DispatchKind.RETURN)

    monkeypatch.setattr(
        bootstrap,
        "compile_cics_program",
        lambda source, parser, strategy, **kwargs: object(),
    )
    monkeypatch.setattr(bootstrap, "_run_dispatcher_with_runner", _fake_loop)

    bootstrap.run_carddemo_region(
        transid_to_program={"CC00": "SGNPGM"},
        program_sources={"SGNPGM": b"src"},
        parser=object(),
        entry_transid="CC00",
        screen_queue=queue.Queue(),
        input_queue=queue.Queue(),
        region_termid="T009",
    )

    start_args = [typed(text, UNKNOWN) for text in ("CC00", "", "T009", "", "")]
    resp = Builtins.TABLE[FuncName("__cics_start")](start_args, VMState()).value
    queued = captured["loop_start_queue"].pop_runnable("T009")

    assert (resp, tuple(req.transid for req in queued)) == (0, ("CC00",))
    assert captured["loop_region_termid"] == "T009"

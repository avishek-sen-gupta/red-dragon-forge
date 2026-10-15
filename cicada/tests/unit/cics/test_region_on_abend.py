"""Pins build_region's on_abend seam (task 10 of the
2026-09-19-carddemo-db2-tier plan): before this, build_region had no
on_abend parameter at all, so a composed Db2 region's dispatcher-level
abends (unknown XCTL/RETURN-TRANSID target, terminal-read timeout) never
reached squall's rollback -- Task 6 threaded on_abend through the CICS
runtime and the dispatcher, but build_region itself never forwarded a
caller-supplied callable into that internal call (now install_cics_runtime).

Every other module-level collaborator is monkeypatched to a stub so this
stays a pure unit test of the wiring, not a full compile+run (which needs a
real bridge_jar and CardDemo checkout -- see test_region_e2e.py for that)."""

from __future__ import annotations

from types import SimpleNamespace

import cics.tn3270.region as region_mod


def test_build_region_forwards_on_abend_to_install_cics_runtime(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_install_cics_runtime(context_holder, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(region_mod, "install_cics_runtime", fake_install_cics_runtime)
    monkeypatch.setattr(region_mod, "_vsam_engine", lambda config: object())
    monkeypatch.setattr(
        region_mod, "_parser", lambda config, bridge_jar, sym_dir: object()
    )
    monkeypatch.setattr(
        region_mod, "_compiled", lambda config, parser, spec, extra_specs: {}
    )
    monkeypatch.setattr(
        region_mod,
        "_region",
        lambda config, wiring, programs, on_abend: captured.update(
            region_on_abend=on_abend
        ),
    )
    monkeypatch.setattr(region_mod, "_catalog", lambda config: object())
    monkeypatch.setattr(
        region_mod, "PseudoConversationalDriver", lambda *a, **k: object()
    )

    def sentinel() -> None:
        return None

    # type: ignore below is test scaffolding, not an ibm_db-style stub gap:
    # SimpleNamespace stands in for a real RegionConfig (every collaborator
    # that would read its actual fields is monkeypatched to a stub above),
    # so pyright correctly flags the substitution -- it is not forced by any
    # third-party type stub.
    config = SimpleNamespace(transactions={})
    region_mod.build_region(config, "bridge.jar", tmp_path, on_abend=sentinel)  # type: ignore[reportArgumentType]

    assert captured["on_abend"] is sentinel
    assert captured["region_on_abend"] is sentinel


def test_build_region_default_on_abend_is_the_module_noop(monkeypatch, tmp_path):
    """No caller-supplied on_abend keeps a CICS-only region's current
    behaviour exactly -- the default forwarded to install_cics_runtime is a
    genuine no-op, not None (install_cics_runtime's own default would otherwise
    have to special-case None)."""
    captured: dict = {}

    def fake_install_cics_runtime(context_holder, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(region_mod, "install_cics_runtime", fake_install_cics_runtime)
    monkeypatch.setattr(region_mod, "_vsam_engine", lambda config: object())
    monkeypatch.setattr(
        region_mod, "_parser", lambda config, bridge_jar, sym_dir: object()
    )
    monkeypatch.setattr(
        region_mod, "_compiled", lambda config, parser, spec, extra_specs: {}
    )
    monkeypatch.setattr(
        region_mod, "_region", lambda config, wiring, programs, on_abend: object()
    )
    monkeypatch.setattr(region_mod, "_catalog", lambda config: object())
    monkeypatch.setattr(
        region_mod, "PseudoConversationalDriver", lambda *a, **k: object()
    )

    # type: ignore below is test scaffolding (SimpleNamespace substituting for
    # RegionConfig), not a third-party stub gap -- see the identical note in
    # the test above.
    config = SimpleNamespace(transactions={})
    region_mod.build_region(config, "bridge.jar", tmp_path)  # type: ignore[reportArgumentType]

    assert captured["on_abend"] is region_mod._region_noop
    assert captured["on_abend"]() is None

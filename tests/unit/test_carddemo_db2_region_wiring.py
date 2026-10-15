"""Unit test for build_db2_region's OWN on_abend wiring (task 10 review,
round 1, CRITICAL 2): the integration abend test
(tests/integration/test_carddemo_db2_abend_rollback.py) composes
build_cics_spec/build_sql_spec by hand -- it never calls
red_dragon_forge.carddemo_db2_region.build_db2_region itself, so nothing
previously caught ``on_abend=backend.rollback`` being dropped from that
function's own call to build_region. Every collaborator here is a stub, so
this stays a fast, DB-free test of the wiring line itself, isolated from
build_region's own on_abend forwarding (covered separately by
cicada/tests/unit/cics/test_region_on_abend.py) and from the rollback
mechanism itself (covered by the integration abend test)."""

from __future__ import annotations

from types import SimpleNamespace

import red_dragon_forge.carddemo_db2_region as region_mod


class _FakeBackend:
    """Stands in for squall.backends.db2.Db2Backend: records the connection
    it was built over and exposes the same no-arg ``rollback`` shape
    build_db2_region is expected to hand to build_region as on_abend."""

    def __init__(self, conn):
        self.conn = conn

    def rollback(self) -> None:
        pass


def test_build_db2_region_forwards_backend_rollback_as_on_abend(monkeypatch, tmp_path):
    captured: dict = {}
    fake_conn = object()

    monkeypatch.setattr(region_mod.ibm_db, "connect", lambda *a, **k: fake_conn)
    monkeypatch.setattr(region_mod, "Db2Backend", _FakeBackend)

    def fake_install_sql_runtime(**kwargs):
        captured["sql_runtime_kwargs"] = kwargs

    monkeypatch.setattr(region_mod, "install_sql_runtime", fake_install_sql_runtime)

    def fake_build_sql_spec():
        return "the-sql-spec"

    monkeypatch.setattr(region_mod, "build_sql_spec", fake_build_sql_spec)

    def fake_build_region(config, bridge_jar, work_dir, extra_specs=(), on_abend=None):
        captured["on_abend"] = on_abend
        captured["extra_specs"] = extra_specs
        return "the-served-region"

    monkeypatch.setattr(region_mod, "build_region", fake_build_region)

    # type: ignore below is test scaffolding (SimpleNamespace substituting
    # for RegionConfig, whose real fields every collaborator here is
    # monkeypatched away from reading) -- not a third-party stub gap.
    config = SimpleNamespace(copybook_dirs=())
    region, conn = region_mod.build_db2_region(config, "jar.jar", tmp_path, "dsn-string")  # type: ignore[reportArgumentType]

    assert region == "the-served-region"
    assert conn is fake_conn
    assert captured["extra_specs"] == ("the-sql-spec",)

    backend = captured["sql_runtime_kwargs"]["connections"]["CARDDEMO"]
    assert isinstance(backend, _FakeBackend)
    assert backend.conn is fake_conn

    # The actual assertion: on_abend must be THIS backend's own bound
    # rollback method, not some other callable (or None/a no-op) -- deleting
    # `on_abend=backend.rollback` from build_db2_region's call to
    # build_region makes this fail (fake_build_region's own default is
    # None), and passing a different backend's rollback would fail the
    # `__self__ is backend` check even though `==` alone might not catch it.
    assert captured["on_abend"] == backend.rollback
    assert captured["on_abend"].__self__ is backend

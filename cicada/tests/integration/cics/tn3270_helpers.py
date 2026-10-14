"""Shared scaffolding for TN3270 wire tests: bring up a served region, drive it
with a real s3270 emulator, and slice vendored EBCDIC flat files for fixtures.

Flow-specific knowledge (field names, menu options) belongs in the test that
uses this, not here.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import pytest

from cics.tn3270.config import RegionConfig
from cics.tn3270.region import ServedRegion, build_region
from cics.tn3270.session import run_session
from cics.tn3270.wire import bind, serve_forever

# Repo root. A caller sets this as the FORGE_ROOT env var before load_config,
# so a config's hlasm_export path can expand its ${FORGE_ROOT}/... prefix.
REPO_ROOT = Path(__file__).parents[4]


@dataclass(frozen=True)
class ServedSession:
    """A running TN3270 server plus the region it is serving."""

    port: int
    region: ServedRegion


def _serve_until_closed(server, session) -> None:
    """``serve_forever`` until ``served_session`` closes ``server`` out from
    under its blocking ``accept()`` on the way out — the expected shutdown
    signal here, not an unhandled thread exception for pytest to warn about."""
    try:
        serve_forever(server, session)
    except OSError:
        pass


@contextmanager
def served_session(
    config: RegionConfig, bridge_jar: str, work_dir: Path
) -> Iterator[ServedSession]:
    """Build a region from ``config`` and serve it over TN3270 on an
    ephemeral loopback port for the duration of the context.

    The listening socket and its daemon thread are torn down on exit; the
    thread is daemonic so a hung connection cannot block interpreter exit."""
    region = build_region(config, bridge_jar, work_dir)
    server = bind("127.0.0.1", 0)
    session = partial(
        run_session,
        driver=region.driver,
        catalog=region.catalog,
        initial_transid=config.initial_transid,
    )
    thread = threading.Thread(
        target=_serve_until_closed, args=(server, session), daemon=True
    )
    thread.start()
    try:
        yield ServedSession(server.getsockname()[1], region)
    finally:
        server.close()


def records(data_dir: Path, name: str, length: int) -> list[bytes]:
    """Slice a vendored fixed-length flat file into its fixed-width records."""
    data = (data_dir / name).read_bytes()
    return [data[at : at + length] for at in range(0, len(data), length)]


class S3270:
    """A thin wrapper over the ``s3270`` scripting protocol: connect the
    emulator, drive it via typed input, read what is on screen as text,
    and stop the process."""

    def __init__(self) -> None:
        if shutil.which("s3270") is None:
            pytest.fail(
                "s3270 is not installed; install the x3270 suite (brew install x3270)"
            )
        self.proc = subprocess.Popen(
            ["s3270", "-model", "2"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

    def connect(self, port: int) -> None:
        self.run(f"Connect(127.0.0.1:{port})")
        self.run("Wait(10,InputField)")

    def run(self, command: str) -> list[str]:
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()
        lines = []
        while (raw := self.proc.stdout.readline()) and (
            line := raw.rstrip("\n")
        ) not in ("ok", "error"):
            lines.append(line)
        if not raw:
            pytest.fail(f"s3270 closed its output during {command}: {lines}")
        assert line == "ok", f"{command} failed: {lines}"
        return [line[len("data: ") :] for line in lines if line.startswith("data: ")]

    def screen(self) -> str:
        return "\n".join(self.run("Ascii()"))

    def enter(self, aid: str = "Enter") -> str:
        self.run(aid)
        self.run("Wait(30,InputField)")
        return self.screen()

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait()


def region_toml(config: Path, system: Path) -> Path:
    """The region TOML at ``config``, rewritten beside ``system`` to name it as the region's system."""
    region = system.parent / config.name
    region.write_text(
        config.read_text().replace(
            'system = "/tmp/carddemo-system"', f'system = "{system}"'
        )
    )
    return region

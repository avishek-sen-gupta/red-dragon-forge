"""Shared scaffolding for TN3270 wire tests: bring up a served region, drive it
with a real s3270 emulator, and slice vendored EBCDIC flat files for fixtures.

Flow-specific knowledge (field names, menu options) belongs in the test that
uses this, not here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import pytest

from catnip.system_catalog import SystemCatalog
from cics.bms.export import exported_mapsets, fresh_symbolic_copybooks
from cics.coprocessor import build_cics_spec
from cics.csd_parse import parse_csd, parse_csd_files
from cics.tn3270.region import CICS_COPYBOOKS, ServedRegion, assemble_region
from cics.tn3270.session import run_session
from cics.tn3270.wire import bind, serve_forever
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from litter.build import build
from litter.cics_file import CicsFile
from litter.open import open_package
from litter.transaction import Transaction

REPO_ROOT = Path(__file__).parents[4]
_STUBS = REPO_ROOT / "cicada" / "cics" / "stubs"
_INITIAL_TRANSID = "CC00"


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


def _source(app: Path, program: str) -> Path:
    found = [
        source
        for source in (app / "cbl" / f"{program}.cbl", _STUBS / f"{program}.cbl")
        if source.is_file()
    ]
    return found[0]


def carddemo_package(
    work_dir: Path, bridge_jar: str, programs: tuple[str, ...]
) -> Path:
    """A litter package linking ``programs`` from CardDemo's online tree, with
    every transaction, file and mapset its CSD and BMS directory define --
    as forge-build builds config/carddemo/build.toml, restricted to the
    programs a flow reaches."""
    app = Path(os.environ["CARDDEMO_HOME"])
    csd = app / "csd" / "CARDDEMO.CSD"
    sym = work_dir / "sym"
    fresh_symbolic_copybooks((app / "bms",), os.environ["HLASM_EXPORT"], sym)
    copybook_dirs = (sym, app / "cpy", app / "cpy-bms", CICS_COPYBOOKS)
    return build(
        name="carddemo",
        programs=programs,
        link=programs,
        sources={name: _source(app, name) for name in programs},
        parser=ProLeapCobolParser(
            RealSubprocessRunner(), bridge_jar, copybook_dirs=list(copybook_dirs)
        ),
        specs=(build_cics_spec(),),
        copybook_dirs=copybook_dirs,
        work_dir=work_dir / "units",
        out_dir=work_dir / "out",
        transactions=tuple(
            Transaction(transid, program)
            for transid, program in sorted(parse_csd(csd).items())
        ),
        files=tuple(CicsFile(name, dsn) for name, dsn in parse_csd_files(csd).items()),
        mapsets=exported_mapsets(
            (app / "bms",), os.environ["HLASM_EXPORT"], work_dir / "maps"
        ),
        tolerant=False,
    )


@contextmanager
def served_session(package: Path, system: Path) -> Iterator[ServedSession]:
    """Serve the region assembled from ``package`` over TN3270 on an
    ephemeral loopback port for the duration of the context.

    The listening socket and its daemon thread are torn down on exit; the
    thread is daemonic so a hung connection cannot block interpreter exit."""
    region = assemble_region(open_package(package), SystemCatalog(system))
    server = bind("127.0.0.1", 0)
    session = partial(
        run_session,
        driver=region.driver,
        catalog=region.catalog,
        initial_transid=_INITIAL_TRANSID,
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

"""CICS file-control adapter over the shared red-dragon access-method engine.

``VsamEngine`` is a thin CICS adapter: the backing ``.dat`` file IS the store.
Point ops (read/write/rewrite/delete) open a driver per call; browse ops keep
one open driver instance per cursor. Driver selection is by ``key_offset``:
``0`` -> ``open_driver(INDEXED)`` (binary search over a key-sorted file); ``>0``
-> ``open_alternate_key_driver`` (linear scan, read-only). The adapter maps the
neutral ``AccessCondition`` to CICS EIBRESP and owns the genuinely-CICS state
(FCT enable/disable, last-read-for-update held key, task-scoped browse cursors).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from interpreter.cobol.access_result import AccessCondition
from interpreter.cobol.file_drivers import (
    FileOrganizationDriver,
    open_alternate_key_driver,
    open_driver,
)
from cobol_asg.file_enums import FileOrganization, OpenMode

from cics.vsam.browse import BrowseStart
from cics.vsam.eibresp import (
    RESP_DISABLED,
    RESP_ENDFILE,
    RESP_NORMAL,
    RESP_NOTFND,
    to_eibresp,
)

# Re-export the EIBRESP codes from their home in eibresp.py for back-compat:
# callers (builtins, tests) import RESP_* from cics.vsam.engine.
from cics.vsam.eibresp import RESP_DUPREC, RESP_IOERR  # noqa: F401
from cics.vsam.fct import FctConfig

logger = logging.getLogger(__name__)

# Browse cursor key: (task_id, file_name, cursor_id).
_CursorKey = tuple[str, str, str]


@dataclass(frozen=True)
class _DatasetGeom:
    """The record geometry + backing-file path for one configured dataset."""

    record_length: int
    key_offset: int
    key_length: int
    path: Path


class VsamEngine:
    """CICS file-control adapter over the file-resident access-method drivers.

    One backing ``.dat`` file per dataset under ``vsam_dir`` is the store. The
    base KSDS clusters (``key_offset == 0``) are key-sorted on disk so the
    ``IndexedDriver`` binary search applies; alternate-key datasets
    (``key_offset > 0``) are read by linear scan.
    """

    def __init__(self, config: FctConfig, vsam_dir: Path) -> None:
        self._config = config
        self._vsam_dir = Path(vsam_dir)
        self._datasets: dict[str, _DatasetGeom] = {}
        # Last record key READ per file. EXEC CICS DELETE / REWRITE without a
        # RIDFLD operate on the record most recently read for update; a keyless
        # DELETE / REWRITE falls back to this held key.
        self._held_key: dict[str, bytes] = {}
        # One open driver instance per browse cursor.
        self._browse: dict[_CursorKey, FileOrganizationDriver] = {}

    def load_all(self) -> None:
        """Materialize each configured dataset's backing-file path (the seeded
        ``.dat``). No record loading — the file is the store."""
        for name, cfg in self._config.datasets.items():
            canonical = name.upper()
            geom = _DatasetGeom(
                record_length=cfg.record_length,
                key_offset=cfg.key_offset,
                key_length=cfg.key_length,
                path=self._vsam_dir / f"{canonical}.dat",
            )
            # An unseeded enabled dataset still needs a backing file so reads
            # return NOT_FOUND (empty file) rather than crashing on open.
            self._ensure_backing(geom)
            self._datasets[canonical] = geom
            logger.info("VSAM: registered %s -> %s", canonical, geom.path)

    def dataset_count(self) -> int:
        return len(self._datasets)

    def _geom(self, file_name: str) -> _DatasetGeom | None:
        return self._datasets.get(file_name.upper().strip("'\""))

    def _open(
        self, file_name: str, mode: OpenMode, key_length: int
    ) -> FileOrganizationDriver | None:
        """Open a driver for an FCT-enabled dataset, routed by ``key_offset``.

        Returns None when the file is not an enabled FCT entry (the caller maps
        that to ``RESP_DISABLED``). ``key_offset > 0`` -> alternate-key linear
        scan (read-only); ``key_offset == 0`` -> INDEXED binary search. The
        driver is opened with the EFFECTIVE key length (the FCT's pinned width,
        or the operation's ``key_length`` when the FCT leaves it unpinned) so the
        driver's own key extraction (write/rewrite derive the key from the
        record) slices the right bytes.
        """
        geom = self._geom(file_name)
        if geom is None:
            return None
        klen = self._klen(geom, key_length)
        if geom.key_offset > 0:
            return open_alternate_key_driver(
                geom.path,
                mode,
                geom.record_length,
                geom.key_offset,
                klen,
            )
        return open_driver(
            FileOrganization.INDEXED,
            geom.path,
            mode,
            geom.record_length,
            geom.key_offset,
            klen,
        )

    @staticmethod
    def _klen(geom: _DatasetGeom, key_length: int) -> int:
        return geom.key_length or key_length

    # ── Point operations ──────────────────────────────────────────────

    def read(
        self, file_name: str, key: bytes, key_length: int
    ) -> tuple[bytes | None, int]:
        """READ FILE. Returns (record_bytes, eibresp)."""
        geom = self._geom(file_name)
        if geom is None:
            return None, RESP_DISABLED
        klen = self._klen(geom, key_length)
        search = key[:klen]
        drv = self._open(file_name, OpenMode.INPUT, key_length)
        assert drv is not None
        result = drv.read_key(search)
        drv.close()
        if result.condition is AccessCondition.OK:
            # Hold this key so a subsequent RIDFLD-less DELETE / REWRITE targets
            # exactly this record.
            self._held_key[file_name.upper()] = search
            return result.data, RESP_NORMAL
        return None, to_eibresp(result.condition)

    def write(self, file_name: str, key: bytes, key_length: int, record: bytes) -> int:
        """WRITE FILE. Returns eibresp."""
        geom = self._geom(file_name)
        if geom is None:
            return RESP_DISABLED
        drv = self._open(file_name, OpenMode.IO, key_length)
        assert drv is not None
        result = drv.write(record)
        drv.close()
        return to_eibresp(result.condition)

    def rewrite(
        self, file_name: str, key: bytes, key_length: int, record: bytes
    ) -> int:
        """REWRITE FILE. Returns eibresp.

        EXEC CICS REWRITE has no RIDFLD: the key comes from the FROM record's
        own key field. The IndexedDriver derives the key from the record when
        passed an empty key, so a keyless REWRITE works directly.
        """
        geom = self._geom(file_name)
        if geom is None:
            return RESP_DISABLED
        klen = self._klen(geom, key_length)
        match_key = key[:klen] if key else b""
        drv = self._open(file_name, OpenMode.IO, key_length)
        assert drv is not None
        result = drv.rewrite(record, match_key)
        drv.close()
        return to_eibresp(result.condition)

    def delete(self, file_name: str, key: bytes, key_length: int) -> int:
        """DELETE FILE. Returns eibresp."""
        geom = self._geom(file_name)
        if geom is None:
            return RESP_DISABLED
        klen = self._klen(geom, key_length)
        # EXEC CICS DELETE has no RIDFLD when it follows a READ ... UPDATE: the
        # target is the record most recently read for this file (held key).
        match_key = key[:klen] if key else self._held_key.get(file_name.upper(), b"")
        if not match_key:
            return RESP_NOTFND
        drv = self._open(file_name, OpenMode.IO, key_length)
        assert drv is not None
        result = drv.delete(match_key)
        drv.close()
        if result.condition is AccessCondition.OK:
            self._held_key.pop(file_name.upper(), None)
        return to_eibresp(result.condition)

    # ── Browse operations ─────────────────────────────────────────────

    def startbr(
        self,
        file_name: str,
        key: bytes,
        key_length: int,
        cursor_key: _CursorKey,
        start: BrowseStart = BrowseStart.GTEQ,
    ) -> int:
        """STARTBR FILE. Positions a per-cursor driver at the key per ``start``."""
        geom = self._geom(file_name)
        if geom is None:
            return RESP_DISABLED
        klen = self._klen(geom, key_length)
        drv = self._open(file_name, OpenMode.INPUT, key_length)
        assert drv is not None
        result = drv.start(key[:klen], start.value)
        missed = result.condition is not AccessCondition.OK
        if missed and start is BrowseStart.EQUAL:
            return RESP_NOTFND
        # A past-end GTEQ leaves the cursor at EOF, which the seek-last idiom
        # (STARTBR HIGH-VALUES then READPREV) depends on — still a valid start.
        self._browse[cursor_key] = drv
        return RESP_NORMAL

    def readnext(
        self, file_name: str, cursor_key: _CursorKey
    ) -> tuple[bytes | None, int]:
        """READNEXT FILE. Returns (record, eibresp)."""
        result = self._browse[cursor_key].read_seq()
        if result.condition is AccessCondition.OK:
            return result.data, RESP_NORMAL
        return None, to_eibresp(result.condition)

    def readprev(
        self, file_name: str, cursor_key: _CursorKey
    ) -> tuple[bytes | None, int]:
        """READPREV FILE. Returns (record, eibresp).

        The driver's cursor handles the READNEXT->READPREV reversal directly
        (the first READPREV after a READNEXT re-reads that record).
        """
        result = self._browse[cursor_key].read_prev()
        if result.condition is AccessCondition.OK:
            return result.data, RESP_NORMAL
        return None, to_eibresp(result.condition)

    def endbr(self, file_name: str, cursor_key: _CursorKey) -> int:
        """ENDBR FILE. Closes and drops the cursor's driver."""
        self._browse.pop(cursor_key).close()
        return RESP_NORMAL

    @staticmethod
    def _ensure_backing(geom: _DatasetGeom) -> None:
        """A WRITE/REWRITE/DELETE opens the backing file in place (r+b). Create
        an empty backing file for a dataset that has never been seeded so the
        first WRITE has a file to insert into."""
        if not geom.path.exists():
            geom.path.parent.mkdir(parents=True, exist_ok=True)
            geom.path.write_bytes(b"")

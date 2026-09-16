# pyright: standard
"""JclStore — a per-run, parallel, disk-backed cache of parsed JCL members.

A corpus build parses every member twice, each time in a fresh JVM: once to
populate the corpus index (``corpus_index_builder._index_jcl``) and once to build
the graph (``build_graph._build_jcl_graph``). The two passes cannot be fused — a
member's DDs resolve against data sets other members write, so the index has to
be complete before any graph edge is drawn — which leaves caching the first
pass's work as the way to stop paying for it twice.

Holding the parsed ``Job`` per member is the obvious form of that and does not
scale: a corpus is hundreds of members. So this keeps only what the bridge
emitted, as JSON on disk, and deserializes exactly one ``Job`` at a time on
``get()``. Peak memory is one member, as it is today. ``AstStore`` carries the
same design for COBOL ASGs.

The cache is per run — ``temp_jcl_store`` removes it on the way out — so a
grammar change cannot be served stale output. That is why this needs no jar
hashing and no cache versioning.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tqdm import tqdm

from cobble.path_utils import ensure_dir
from cobol_asg.source_text import decode_source
from jackal.jcl.bridge_parser import JclParseError, job_from_bridge_json
from jackal.model import Job


class JclJsonParser(Protocol):
    """The one thing the store needs of a bridge: JSON for a member's text."""

    def parse_to_json(self, text: str) -> str: ...


@dataclass(frozen=True)
class _Cached:
    """A member whose bridge output is on disk."""

    key: str
    path: Path


@dataclass(frozen=True)
class _Failed:
    """A member the bridge or the filesystem rejected, and what it raised."""

    key: str
    error: Exception


def _key(path: Path) -> str:
    # FULL md5 hex, never truncated: truncation collides at corpus scale.
    return hashlib.md5(str(path).encode()).hexdigest()


def _parse_one(path: Path, parser: JclJsonParser, cache_dir: Path) -> _Cached | _Failed:
    """One member's bridge output, written to the cache. Runs on a worker thread.

    A member cobble cannot read is corpus shape, not a bug: both callers already
    report those per member and carry on. So a failure is held against its member
    and re-raised from ``get()``, where that reporting already lives — one bad
    member must not abort the pass.

    The cache filename carries the stem for a human reading the directory, and the
    key for uniqueness: two libraries can hold members of the same name.
    """
    key = _key(path)
    try:
        out = parser.parse_to_json(decode_source(path.read_bytes()))
    except (JclParseError, OSError) as exc:
        return _Failed(key, exc)
    dest = cache_dir / f"{path.stem}-{key}.jcl.json"
    dest.write_text(out, encoding="utf-8")
    return _Cached(key, dest)


class JclStore:
    """Parse-once, get-many store of Job, backed by bridge JSON on disk."""

    def __init__(self, cache_dir: Path, max_workers: int = 4) -> None:
        ensure_dir(cache_dir)
        self._dir = cache_dir
        self._max_workers = max_workers
        self._cached: dict[str, Path] = {}
        self._failures: dict[str, Exception] = {}

    @property
    def cache_dir(self) -> Path:
        return self._dir

    def parse_all(self, paths: Sequence[Path], parser: JclJsonParser) -> None:
        """Parse every member in parallel, replacing whatever was cached before.

        This is where a corpus build's JCL time now goes, and the only place it
        goes: ``_index_jcl`` was serial, so the pass it replaces ran one JVM at a
        time. See ``_parse_one`` for what happens to a member that fails.

        The bar is not decoration. This runs before the index, before any
        extractor and before GraphWriter opens its output, so it is the first
        thing a run does and on a real corpus it is minutes of subprocesses --
        exactly the stretch ``_index_jcl`` used to cover and warns about, where
        silence is indistinguishable from a hang. tqdm writes to stderr, so it
        survives a stdout pipe.
        """
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = [
                executor.submit(_parse_one, path, parser, self._dir) for path in paths
            ]
            results = [
                future.result()
                for future in tqdm(
                    as_completed(futures),
                    total=len(futures),
                    desc="parse JCL",
                    unit="file",
                )
            ]
        self._cached = {r.key: r.path for r in results if isinstance(r, _Cached)}
        self._failures = {r.key: r.error for r in results if isinstance(r, _Failed)}

    def get(self, path: Path) -> Job:
        """The member's Job, deserialized now.

        Re-raises what parsing this member raised, so a caller sees the same
        exception at the same point it would have from parsing directly. A member
        that was never parsed is a bug in the caller, not corpus shape, and says
        so rather than quietly parsing it here.
        """
        key = _key(path)
        if key in self._failures:
            raise self._failures[key]
        if key not in self._cached:
            raise KeyError(f"{path} was not in the set handed to parse_all")
        return job_from_bridge_json(self._cached[key].read_text(encoding="utf-8"))


@contextmanager
def temp_jcl_store(max_workers: int = 4) -> Iterator[JclStore]:
    """A store whose cache is a temp directory, removed on the way out."""
    with tempfile.TemporaryDirectory() as tmp:
        yield JclStore(Path(tmp), max_workers)

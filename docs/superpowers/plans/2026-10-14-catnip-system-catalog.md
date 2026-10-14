# catnip — the System Catalog as Its Own Component — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract jackal's system catalog into a workspace package, `catnip`, that jackal and cicada share. It catalogs alternate indexes and paths, and installs data from a declaration. cicada's file control works on cataloged datasets in place.

**Architecture:**
- red-dragon gains an `AlternateIndexDriver`: a fixed-length base file read and written in alternate-key order.
- catnip takes jackal's labels, `Dataset`, `SystemCatalog`, GDG bases and the RDW codec. It adds AIX and path entries, and `catnip install <data.toml>`.
- cicada's `VsamEngine` is built from a CICS-file-to-`Dataset` map, resolved through the CSD and the catalog. Its seeded copies are deleted.

**Tech Stack:** Python 3.13, uv workspace, pydantic v2 (catalog and declaration wire models), pytest, import-linter, red-dragon (vendored submodule; upstream at `~/code/red-dragon`).

**Spec:** `docs/superpowers/specs/2026-10-14-catnip-system-catalog-design.md` (decisions N1–N12)

## Global Constraints

- `vendor/red-dragon` is never edited in the forge. Change `~/code/red-dragon`, run its tests, commit, push, then `git -C vendor/red-dragon fetch && git -C vendor/red-dragon checkout <sha>` and commit the bump.
- catnip imports none of `cics`, `squall`, `jackal`, `red_dragon_forge`, `cobble`. cobble may not import catnip.
- **Code style:**
  - frozen dataclasses;
  - no `Any` or `object`;
  - no `None` defaults;
  - no comments beyond a one-line module or class header;
  - JSON and TOML are parsed into pydantic models at the boundary;
  - logging, never print.
- **Tests:**
  - one test per behaviour, with concrete equality assertions;
  - no mocking or monkeypatching (the existing `test_region_on_abend.py` monkeypatch is only adjusted, never extended);
  - temp files only under `tmp_path`.
- New tests must be mutation-checked: break the covered code in its two most obvious ways and see the test fail.
- **The gate:** before every commit, run `make fmt`, `uv run pyright`, `uv run lint-imports`, and `pre-commit run python-fp-lint-check --hook-stage manual --all-files`. Then run the suites the task names, and before the final commit of Tasks 2, 3 and 5, `make test-all` with `. ./bridge-env.sh` sourced and `make db2-up` running. `--no-verify` is never used.
- If Talisman flags a line containing "key" or "password" in a new file, stop and ask the user. Never edit `.talismanrc` unasked.
- Run `bd export -o issues/issues.jsonl` before any commit that changes beads.
- Never name an external codebase under analysis in a tracked artifact. CardDemo is a vendored public corpus that the repo already names, so it is fine.
- Each commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Y8tAV2ducgCCVspgN11inx
  ```
- **Behaviour rules:**
  - A read that finds more records with the same alternate key reports `AccessCondition.DUPLICATES_FOLLOW`: COBOL status `"02"`, CICS RESP `DUPKEY` (15). A `DELETE` through a non-unique path deletes the first record of the run and also reports `DUPKEY` when more follow (IBM CICS TS 5.5, EXEC CICS DELETE, DUPKEY RESP2 140).
  - **Duplicate order (N4):** sorted by alternate key, with duplicates in primary-key order. The z/OS arrival order is deferred (red-dragon-forge-zqxf).

## Review Focus

1. **The order of duplicate alternate keys changes in CardDemo screens.** cicada's old CXACAIX copy kept the seed file's order. A path returns primary-key order, which is what z/OS's `BLDINDEX` produces after `REPRO`.
   - If a CardDemo end-to-end assertion depends on which card an account shows first, check the expected value against the CARDXREF records sorted by card number.
   - Change the assertion only when certain, and only with a ruling in the ledger.
   - The CCXREF-to-CXACAIX test in Task 5 pins the new behaviour.
2. **A KSDS seed with a repeated primary key fails `catnip install`.** Task 4's CardDemo install test proves every declared seed loads; DALYTRAN.PS loaded as TRANSACT is the likeliest to fail. If one does, it's a finding to report, not a reason to weaken validation.
3. **`load_config(path, system)` signature change.** Every caller has to pass a system directory: the cicada CLI, the DB2 CLI, the root DB2 tests and the tn3270 tests. Task 5's tn3270 tests exercise a region started against an installed system.
4. **A region started against a system missing a CSD file's DSN must fail at startup, not at first READ.** That's Task 5's `test_a_region_over_an_uncataloged_dsn_stops_at_startup`.
5. **Writing through a path.** CardDemo never writes through a path, but the driver supports it. Task 1's write, rewrite and delete test covers it; check that the base file stays sorted by primary key afterwards.

---

### Task 1: red-dragon — the alternate-index driver and "more duplicates follow"

**Files (in `~/code/red-dragon`):**
- Modify: `interpreter/cobol/access_result.py` (add `DUPLICATES_FOLLOW`)
- Modify: `interpreter/cobol/real_file_provider.py:21-32` (`_FILE_STATUS`: `"02"`)
- Create: `interpreter/cobol/alternate_index_driver.py`
- Test: `tests/unit/cobol/test_alternate_index_driver.py`

**Files (forge, in the bump commit):**
- Modify: `cicada/cics/vsam/eibresp.py` (add `RESP_DUPKEY = 15`, map `DUPLICATES_FOLLOW`)
- Test: `cicada/tests/unit/cics/test_vsam_eibresp.py` (create)

**Interfaces:**
- Produces:
  - `interpreter.cobol.access_result.AccessCondition.DUPLICATES_FOLLOW`;
  - `interpreter.cobol.alternate_index_driver.AlternateIndexDriver(primary_key_offset: int, primary_key_length: int, unique: bool)`, which implements `FileOrganizationDriver` (`open(path, mode, record_length, key_offset, key_length)` takes the **alternate** key);
  - `open_alternate_index_driver(path: Path, mode: OpenMode, record_length: int, primary_key_offset: int, primary_key_length: int, key_offset: int, key_length: int, unique: bool) -> FileOrganizationDriver`;
  - `cics.vsam.eibresp.RESP_DUPKEY = 15`.

- [ ] **Step 1: Confirm DUPKEY's RESP value from IBM.** Find the EIBRESP value table in IBM's CICS TS API reference (the "EIBRESP" / "RESP values" appendix of `https://www.ibm.com/docs/en/SSGMCP_5.5.0/pdf/api-reference_pdf.pdf`) and confirm `DUPKEY = 15`. cicada's `cics/conditions.py:21` already uses 15. Ledger the source. If IBM says otherwise, stop and tell the user.

- [ ] **Step 2: Write the failing driver tests**

```python
"""AlternateIndexDriver: a sorted base file read and written in alternate-key order."""

from __future__ import annotations

from pathlib import Path

from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from interpreter.cobol.alternate_index_driver import open_alternate_index_driver
from interpreter.cobol.real_file_provider import to_ioresult

_BASE = (b"001BBBxx", b"002AAAyy", b"003AAAzz", b"004CCCww")


def _base(tmp_path: Path, records: tuple[bytes, ...] = _BASE) -> Path:
    path = tmp_path / "base"
    path.write_bytes(b"".join(records))
    return path


def _path(base: Path, mode: OpenMode, unique: bool = False):
    return open_alternate_index_driver(base, mode, 8, 0, 3, 3, 3, unique)


def _walk(read) -> list[tuple[AccessCondition, bytes | None]]:
    out = []
    while (r := read()).condition is not AccessCondition.END_OF_FILE:
        out.append((r.condition, r.data))
    return out


def test_reads_and_browses_by_alternate_key_reporting_duplicates(tmp_path):
    drv = _path(_base(tmp_path), OpenMode.INPUT)
    point = drv.read_key(b"AAA")
    missing = drv.read_key(b"ZZZ")
    drv.start(b"AAA", ">=")
    forward = _walk(drv.read_seq)
    backward = _walk(drv.read_prev)
    drv.close()

    assert (point.condition, point.data) == (
        AccessCondition.DUPLICATES_FOLLOW,
        b"002AAAyy",
    )
    assert missing.condition is AccessCondition.NOT_FOUND
    assert forward == [
        (AccessCondition.DUPLICATES_FOLLOW, b"002AAAyy"),
        (AccessCondition.OK, b"003AAAzz"),
        (AccessCondition.OK, b"001BBBxx"),
        (AccessCondition.OK, b"004CCCww"),
    ]
    assert backward == [
        (AccessCondition.OK, b"004CCCww"),
        (AccessCondition.OK, b"001BBBxx"),
        (AccessCondition.DUPLICATES_FOLLOW, b"003AAAzz"),
        (AccessCondition.OK, b"002AAAyy"),
    ]


def test_start_positions_by_relational_operator(tmp_path):
    drv = _path(_base(tmp_path), OpenMode.INPUT)
    equal = (drv.start(b"BBB", "=").condition, drv.read_seq().data)
    after = (drv.start(b"AAA", ">").condition, drv.read_seq().data)
    absent = drv.start(b"ABC", "=").condition
    past_end = drv.start(b"ZZZ", ">=").condition
    drv.close()

    assert equal == (AccessCondition.OK, b"001BBBxx")
    assert after == (AccessCondition.OK, b"001BBBxx")
    assert absent is AccessCondition.NOT_FOUND
    assert past_end is AccessCondition.NOT_FOUND


def test_writes_rewrites_and_deletes_through_the_path_land_in_the_base(tmp_path):
    base = _base(tmp_path)
    drv = _path(base, OpenMode.IO)
    wrote = drv.write(b"000AAAqq").condition
    rewrote = drv.rewrite(b"004AAAww").condition
    deleted = drv.delete(b"AAA").condition
    drv.start(b"", ">=")
    seen = [data for _, data in _walk(drv.read_seq)]
    drv.close()

    assert (wrote, rewrote, deleted) == (
        AccessCondition.OK,
        AccessCondition.OK,
        AccessCondition.DUPLICATES_FOLLOW,
    )
    assert seen == [b"002AAAyy", b"003AAAzz", b"004AAAww", b"001BBBxx"]
    assert base.read_bytes() == b"001BBBxx002AAAyy003AAAzz004AAAww"


def test_a_unique_alternate_key_rejects_a_repeat(tmp_path):
    drv = _path(_base(tmp_path, (b"001BBBxx", b"002AAAyy")), OpenMode.IO, unique=True)
    repeated = drv.write(b"003AAAzz").condition
    moved_onto = drv.rewrite(b"001AAAxx").condition
    drv.close()

    assert (repeated, moved_onto) == (
        AccessCondition.DUPLICATE_KEY,
        AccessCondition.DUPLICATE_KEY,
    )


def test_more_duplicates_follow_is_cobol_status_02():
    result = to_ioresult(AccessResult(AccessCondition.DUPLICATES_FOLLOW, b"x"))

    assert (result.status, result.data) == ("02", "x")
```

- [ ] **Step 3: Run them and see them fail**

Run: `cd ~/code/red-dragon && uv run pytest tests/unit/cobol/test_alternate_index_driver.py -q`
Expected: FAIL, with `ModuleNotFoundError: interpreter.cobol.alternate_index_driver`.

- [ ] **Step 4: Add the condition and its COBOL status**

In `interpreter/cobol/access_result.py`, add to `AccessCondition` after `OK`:

```python
    DUPLICATES_FOLLOW = "DUPLICATES_FOLLOW"
```

In `interpreter/cobol/real_file_provider.py`, add to `_FILE_STATUS`:

```python
    AccessCondition.DUPLICATES_FOLLOW: "02",
```

- [ ] **Step 5: Write the driver**

`interpreter/cobol/alternate_index_driver.py`:

```python
# pyright: standard
"""A fixed-length base file, sorted by its primary key, read and written in the order of an alternate key."""

from __future__ import annotations

import bisect
from pathlib import Path

from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from interpreter.cobol.file_drivers import FileOrganizationDriver, IndexedDriver

_WRITE_MODES = frozenset({OpenMode.OUTPUT, OpenMode.EXTEND, OpenMode.IO})
_Entry = tuple[bytes, bytes]


def _alternate(entry: _Entry) -> bytes:
    return entry[0]


class AlternateIndexDriver:
    """Reads by alternate key; duplicates in primary-key order; writes go to the base file."""

    def __init__(
        self, primary_key_offset: int, primary_key_length: int, unique: bool
    ) -> None:
        self._poff = primary_key_offset
        self._plen = primary_key_length
        self._unique = unique
        self._base = IndexedDriver()
        self._view: list[_Entry] = []
        self._cursor = 0
        self._last = 0
        self._rl = 0
        self._koff = 0
        self._klen = 0
        self._mode = OpenMode.INPUT

    def open(
        self,
        path: Path,
        mode: OpenMode,
        record_length: int,
        key_offset: int,
        key_length: int,
    ) -> None:
        self._rl, self._koff, self._klen, self._mode = (
            record_length,
            key_offset,
            key_length,
            mode,
        )
        data = b"" if mode == OpenMode.OUTPUT else path.read_bytes()
        self._view = sorted(
            self._entry(data[i : i + record_length])
            for i in range(0, len(data), record_length)
        )
        self._cursor = 0
        self._last = 0
        self._base.open(path, mode, record_length, self._poff, self._plen)

    def close(self) -> None:
        self._base.close()

    def _entry(self, record: bytes) -> _Entry:
        return (
            record[self._koff : self._koff + self._klen],
            record[self._poff : self._poff + self._plen],
        )

    def _first(self, key: bytes) -> int:
        return bisect.bisect_left(self._view, key, key=_alternate)

    def _holds(self, slot: int, key: bytes) -> bool:
        return 0 <= slot < len(self._view) and self._view[slot][0] == key

    def _record(self, slot: int, follows: bool) -> AccessResult:
        self._last = slot
        found = self._base.read_key(self._view[slot][1])
        condition = (
            AccessCondition.DUPLICATES_FOLLOW if follows else AccessCondition.OK
        )
        return AccessResult(condition=condition, data=found.data)

    def read_key(self, key: bytes) -> AccessResult:
        slot = self._first(key)
        if not self._holds(slot, key):
            return AccessResult(condition=AccessCondition.NOT_FOUND)
        return self._record(slot, self._holds(slot + 1, key))

    def start(self, key: bytes, relop: str) -> AccessResult:
        if relop in ("=", "=="):
            slot = self._first(key)
            if not self._holds(slot, key):
                return AccessResult(condition=AccessCondition.NOT_FOUND)
            self._cursor = slot
            return AccessResult(condition=AccessCondition.OK)
        if relop == ">":
            slot = bisect.bisect_right(self._view, key, key=_alternate)
            if slot >= len(self._view):
                return AccessResult(condition=AccessCondition.NOT_FOUND)
            self._cursor = slot
            return AccessResult(condition=AccessCondition.OK)
        self._cursor = self._first(key)
        if self._cursor >= len(self._view):
            return AccessResult(condition=AccessCondition.NOT_FOUND)
        return AccessResult(condition=AccessCondition.OK)

    def read_seq(self) -> AccessResult:
        if self._cursor >= len(self._view):
            return AccessResult(condition=AccessCondition.END_OF_FILE)
        slot = self._cursor
        self._cursor += 1
        return self._record(slot, self._holds(slot + 1, self._view[slot][0]))

    def read_prev(self) -> AccessResult:
        if self._cursor < 1:
            return AccessResult(condition=AccessCondition.END_OF_FILE)
        self._cursor -= 1
        slot = self._cursor
        return self._record(slot, self._holds(slot - 1, self._view[slot][0]))

    def _taken(self, key: bytes) -> bool:
        return self._unique and self._holds(self._first(key), key)

    def write(self, data: bytes, key: bytes = b"") -> AccessResult:
        if self._mode not in _WRITE_MODES:
            return AccessResult(condition=AccessCondition.WRITE_NOT_PERMITTED)
        entry = self._entry(data[: self._rl].ljust(self._rl))
        if self._taken(entry[0]):
            return AccessResult(condition=AccessCondition.DUPLICATE_KEY)
        result = self._base.write(data)
        if result.condition is AccessCondition.OK:
            bisect.insort(self._view, entry)
        return result

    def rewrite(self, data: bytes, key: bytes = b"") -> AccessResult:
        entry = self._entry(data[: self._rl].ljust(self._rl))
        old = self._base.read_key(entry[1])
        if old.condition is not AccessCondition.OK or old.data is None:
            return AccessResult(condition=AccessCondition.NOT_FOUND)
        before = self._entry(old.data)
        if before[0] != entry[0] and self._taken(entry[0]):
            return AccessResult(condition=AccessCondition.DUPLICATE_KEY)
        result = self._base.rewrite(data)
        if result.condition is AccessCondition.OK:
            self._view.remove(before)
            bisect.insort(self._view, entry)
        return result

    def _target(self, key: bytes) -> int:
        if not key:
            return self._last if self._last < len(self._view) else len(self._view)
        slot = self._first(key)
        return slot if self._holds(slot, key) else len(self._view)

    def delete(self, key: bytes = b"") -> AccessResult:
        slot = self._target(key)
        if slot >= len(self._view):
            return AccessResult(condition=AccessCondition.NOT_FOUND)
        entry = self._view[slot]
        follows = self._holds(slot + 1, entry[0])
        result = self._base.delete(entry[1])
        if result.condition is not AccessCondition.OK:
            return result
        self._view.pop(slot)
        self._cursor -= 1 if self._cursor > slot else 0
        condition = (
            AccessCondition.DUPLICATES_FOLLOW if follows else AccessCondition.OK
        )
        return AccessResult(condition=condition)


def open_alternate_index_driver(
    path: Path,
    mode: OpenMode,
    record_length: int,
    primary_key_offset: int,
    primary_key_length: int,
    key_offset: int,
    key_length: int,
    unique: bool,
) -> FileOrganizationDriver:
    """Open an AlternateIndexDriver over a base file sorted by its primary key."""
    drv = AlternateIndexDriver(primary_key_offset, primary_key_length, unique)
    drv.open(path, mode, record_length, key_offset, key_length)
    return drv
```

- [ ] **Step 6: Run the tests until they pass**

Run: `cd ~/code/red-dragon && uv run pytest tests/unit/cobol/test_alternate_index_driver.py -q`
Expected: 5 passed. Then mutation-check:
- make `_record` always return `OK`: the first test must fail;
- make `write` skip `insort`: the third test must fail.

Restore both.

- [ ] **Step 7: Run red-dragon's suite and commit upstream**

Run: `cd ~/code/red-dragon && uv run pytest -q -x` (and red-dragon's own pre-commit gate)
Expected: all pass.

```bash
cd ~/code/red-dragon
git add interpreter/cobol/access_result.py interpreter/cobol/real_file_provider.py interpreter/cobol/alternate_index_driver.py tests/unit/cobol/test_alternate_index_driver.py
git commit -m "feat(cobol): AlternateIndexDriver — read and write a sorted base file in alternate-key order; DUPLICATES_FOLLOW (status 02)"
git push origin main
```

- [ ] **Step 8: Write the failing forge test**

`cicada/tests/unit/cics/test_vsam_eibresp.py`:

```python
"""CICS file control's RESP for each access-method condition."""

from interpreter.cobol.access_result import AccessCondition

from cics.vsam.eibresp import RESP_DUPKEY, to_eibresp
from tests.covers import covers
from interpreter.cobol.features import CobolFeature


@covers(CobolFeature.EXEC_CICS)
def test_more_duplicates_follow_is_dupkey():
    assert (RESP_DUPKEY, to_eibresp(AccessCondition.DUPLICATES_FOLLOW)) == (15, 15)
```

Bump the submodule first: `git -C vendor/red-dragon fetch && git -C vendor/red-dragon checkout origin/main`. Then run: `. ./bridge-env.sh && cd cicada && uv run --no-sync python -m pytest tests/unit/cics/test_vsam_eibresp.py -q`
Expected: FAIL, with `ImportError: cannot import name 'RESP_DUPKEY'`.

- [ ] **Step 9: Map it**

In `cicada/cics/vsam/eibresp.py`, add `RESP_DUPKEY = 15` after `RESP_DUPREC = 14`, and the entry `AccessCondition.DUPLICATES_FOLLOW: RESP_DUPKEY,` in `_EIBRESP`.

- [ ] **Step 10: Run, gate, commit the bump**

Run: `. ./bridge-env.sh && cd cicada && uv run --no-sync python -m pytest -q -x`
Expected: all pass.

```bash
git add vendor/red-dragon cicada/cics/vsam/eibresp.py cicada/tests/unit/cics/test_vsam_eibresp.py
git commit -m "chore(vendor): bump red-dragon — AlternateIndexDriver; cicada maps DUPLICATES_FOLLOW to DUPKEY"
git push origin main
```

---

### Task 2: catnip — move the catalog out of jackal unchanged

**Files:**
- Move (`git mv`) from `jackal/jackal/` to `catnip/catnip/`: `labels.py`, `dataset.py`, `system_catalog.py`, `gdg.py`, `catalog_stores.py`, `variable_records.py`
- Create: `catnip/pyproject.toml`, `catnip/catnip/__init__.py`, `catnip/tests/__init__.py`, `catnip/tests/unit/__init__.py`, `catnip/tests/covers.py` (copy of `jackal/tests/covers.py`)
- Move: `jackal/tests/unit/test_system_catalog.py` and `jackal/tests/unit/test_variable_records.py` to `catnip/tests/unit/`
- Modify:
  - every importer listed below;
  - root `pyproject.toml` (workspace members);
  - `jackal/pyproject.toml`;
  - `.importlinter`;
  - `pyrightconfig.json`;
  - `Makefile` (`BLACK_PATHS`, `test-all`);
  - `.pre-commit-config.yaml`
- `jackal/jackal/system_catalog_removal.py` stays in jackal, importing `SystemCatalog` from catnip.

**Interfaces:**
- Produces: the modules `catnip.labels`, `catnip.dataset`, `catnip.system_catalog`, `catnip.gdg`, `catnip.catalog_stores` and `catnip.variable_records`, with identical public names. There are no `jackal.labels`-style aliases left.

- [ ] **Step 1: Create the package**

`catnip/pyproject.toml`:

```toml
[project]
name = "catnip"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["pydantic>=2.0", "red-dragon"]

[tool.uv.sources]
red-dragon = { path = "../vendor/red-dragon", editable = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[dependency-groups]
dev = [
    "black>=26.5.1",
    "pre-commit>=4.6.0",
    "pyright>=1.1.410",
    "pytest>=9.1.1",
]

[tool.hatch.build.targets.wheel]
packages = ["catnip"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.black]
target-version = ["py313"]
extend-exclude = "/vendor/"
```

`catnip/catnip/__init__.py`: `"""catnip — the system catalog: labelled datasets, alternate indexes and paths, shared by every Forge runtime."""`

- [ ] **Step 2: Move the modules and tests, then rewrite the imports**

```bash
mkdir -p catnip/catnip catnip/tests/unit
for m in labels dataset system_catalog gdg catalog_stores variable_records; do git mv jackal/jackal/$m.py catnip/catnip/$m.py; done
git mv jackal/tests/unit/test_system_catalog.py jackal/tests/unit/test_variable_records.py catnip/tests/unit/
cp jackal/tests/covers.py catnip/tests/covers.py
touch catnip/tests/__init__.py catnip/tests/unit/__init__.py
rg -l 'jackal\.(labels|dataset|system_catalog|gdg|catalog_stores|variable_records)\b' -g '*.py' . --glob '!vendor/**' \
  | xargs sed -i '' -E 's/jackal\.(labels|dataset|system_catalog|gdg|catalog_stores|variable_records)\b/catnip.\1/g'
```

In `catnip/tests/unit/test_system_catalog.py`, change line 4 from `from jackal.catalog import Dataset` to `from catnip.dataset import Dataset`.

- [ ] **Step 3: Workspace and dependencies**
  - Root `pyproject.toml`: set `[tool.uv.workspace] members = ["cicada", "squall", "jackal", "cobble", "catnip"]`.
  - `jackal/pyproject.toml`: set `dependencies = ["lark>=1.1", "red-dragon", "catnip"]`, and add `catnip = { workspace = true }` under `[tool.uv.sources]`.
  - Run `uv lock && uv sync --all-packages`.

- [ ] **Step 4: Gates and contracts**
  - **`.importlinter`:**
    - add `catnip` to `root_packages`;
    - remove the `jackal.system_catalog` line from `layered-architecture`;
    - add `catnip` to `cobble-no-runtime`'s `forbidden_modules`;
    - add `catnip` to `nothing-imports-cobble`'s sources only if that contract lists sources by package (it lists cics, squall, jackal, red_dragon_forge, so add catnip);
    - append this contract:

    ```ini
    [importlinter:contract:catnip-imports-no-runtime]
    name = catnip is the system's catalog — it imports no runtime
    type = forbidden
    source_modules =
        catnip
    forbidden_modules =
        cics
        squall
        jackal
        cobble
        red_dragon_forge
    ```
  - **`pyrightconfig.json`:** add `"catnip/catnip"` to `include`.
  - **`Makefile`:**
    - add `catnip/catnip catnip/tests` to `BLACK_PATHS`;
    - in `test-all`, add `cd catnip && $(PYTEST)` before the jackal line.
  - **`.pre-commit-config.yaml`:**
    - add `catnip/catnip|catnip/tests` to the Black `files` regex, and `catnip/catnip` to Pyright's;
    - add `catnip/` to `tests-jackal`'s `files` (`^(jackal/|catnip/|vendor/red-dragon(/|$))`) and to `tests-forge`'s;
    - add this hook beside `tests-jackal`:

    ```yaml
          - id: tests-catnip
            name: catnip test suite
            entry: bash -c 'cd catnip && uv run --no-sync python -m pytest -x -q'
            language: system
            pass_filenames: false
            files: ^(catnip/|vendor/red-dragon(/|$))
    ```

    Copy the other keys of the `tests-jackal` hook exactly.

- [ ] **Step 5: Verify nothing changed in behaviour**

Run: `cd catnip && uv run --no-sync python -m pytest -q`, then `. ./bridge-env.sh && uv run --no-sync pytest jackal/tests -q`, then `uv run lint-imports`, `uv run pyright`, and `make test`.
Expected: everything passes, with the same jackal test outcomes as before the move apart from the two relocated files. `rg 'jackal\.(labels|dataset|system_catalog|gdg|catalog_stores|variable_records)' --glob '!vendor/**' --glob '!docs/**'` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add -A catnip jackal tests red_dragon_forge pyproject.toml uv.lock .importlinter pyrightconfig.json Makefile .pre-commit-config.yaml
git commit -m "refactor(catnip): move the system catalog out of jackal into its own package (red-dragon-forge-zave)"
git push origin main
```

---

### Task 3: catnip — alternate indexes and paths

**Files:**
- Create: `catnip/catnip/alternate_index.py`, `catnip/catnip/catalog_path.py`, `catnip/catnip/catalog_error.py`
- Modify: `catnip/catnip/labels.py` (add `PathView`, extend `DatasetLabel`), `catnip/catnip/dataset.py` (open a path), `catnip/catnip/system_catalog.py` (AIX and path entries, wire, cascade), `jackal/jackal/cobol_files.py:93-99,160-180` (a path is indexed and opens through `Dataset.opened`)
- Test: `catnip/tests/unit/test_alternate_indexes.py`; `jackal/tests/integration/test_cobol_path.py`; fixture `jackal/tests/integration/fixtures/cbl/ALTREAD.cbl`

**Interfaces:**
- Consumes: `open_alternate_index_driver` (Task 1).
- Produces:
  - `catnip.alternate_index.AlternateIndex(dsn: str, base: str, key_offset: int, key_length: int, unique: bool)`;
  - `catnip.catalog_path.CatalogPath(dsn: str, aix: str)`;
  - `catnip.catalog_error.CatalogError(ValueError)`;
  - `catnip.labels.PathView(base: KsdsLabel, key_offset: int, key_length: int, unique: bool)`, with `DatasetLabel = Label | LabelPending | PathView`;
  - `SystemCatalog.define_aix(aix: AlternateIndex) -> AlternateIndex` and `SystemCatalog.define_path(path: CatalogPath) -> Dataset`;
  - `SystemCatalog.lookup(path_dsn)` returns `Dataset(path_dsn, <base file>, PathView(...))`;
  - `SystemCatalog.remove(dsn)` cascades, as N3 requires.

- [ ] **Step 1: Write the failing catnip tests**

`catnip/tests/unit/test_alternate_indexes.py`:

```python
"""Alternate indexes and paths in the system catalog."""

from __future__ import annotations

import pytest
from cobol_asg.file_enums import OpenMode

from catnip.alternate_index import AlternateIndex
from catnip.catalog_error import CatalogError
from catnip.catalog_path import CatalogPath
from catnip.dataset import Dataset
from catnip.labels import KsdsLabel, PathView, RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged, SystemCatalog
from tests.covers import NotLanguageFeature, covers

_KSDS = KsdsLabel(8, 0, 3)
_AIX = AlternateIndex("T.AIX", "T.KSDS", 3, 3, False)
_PATH = CatalogPath("T.PATH", "T.AIX")


def _system(tmp_path) -> SystemCatalog:
    system = SystemCatalog(tmp_path / "system")
    system.create("T.KSDS", _KSDS).path.write_bytes(b"001BBBxx002AAAyy003AAAzz")
    system.define_aix(_AIX)
    system.define_path(_PATH)
    return system


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_path_survives_reopening_and_opens_the_base_in_alternate_key_order(tmp_path):
    _system(tmp_path)
    reopened = SystemCatalog(tmp_path / "system")
    path = reopened.lookup("T.PATH")
    drv = path.opened(OpenMode.INPUT)
    seen = [drv.read_seq().data for _ in range(3)]
    drv.close()

    assert path == Dataset(
        "T.PATH",
        tmp_path / "system" / "datasets" / "T.KSDS",
        PathView(_KSDS, 3, 3, False),
    )
    assert seen == [b"002AAAyy", b"003AAAzz", b"001BBBxx"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_removing_a_cluster_removes_its_alternate_indexes_and_paths(tmp_path):
    system = _system(tmp_path)
    system.remove("T.KSDS")
    reopened = SystemCatalog(tmp_path / "system")

    assert (reopened.lookup("T.KSDS"), reopened.lookup("T.PATH")) == (
        NotCataloged(),
        NotCataloged(),
    )
    assert (tmp_path / "system" / "datasets" / "T.KSDS").exists() is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_alternate_index_needs_a_cataloged_cluster_and_a_path_needs_its_index(tmp_path):
    system = SystemCatalog(tmp_path / "system")
    system.create("T.SEQ", SequentialLabel(RecordFormat.FB, 8))

    with pytest.raises(CatalogError) as over_sequential:
        system.define_aix(AlternateIndex("T.AIX", "T.SEQ", 3, 3, False))
    with pytest.raises(CatalogError) as without_index:
        system.define_path(CatalogPath("T.PATH", "T.MISSING"))

    assert str(over_sequential.value) == "T.AIX: base cluster T.SEQ is not a cataloged KSDS"
    assert str(without_index.value) == "T.PATH: alternate index T.MISSING is not cataloged"
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd catnip && uv run --no-sync python -m pytest tests/unit/test_alternate_indexes.py -q`
Expected: FAIL, with `ModuleNotFoundError: catnip.alternate_index`.

- [ ] **Step 3: The types**

`catnip/catnip/catalog_error.py`:

```python
"""A catalog request the catalog's contents cannot satisfy."""


class CatalogError(ValueError):
    pass
```

`catnip/catnip/alternate_index.py`:

```python
"""An alternate index: a second key position over a cataloged KSDS."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlternateIndex:
    dsn: str
    base: str
    key_offset: int
    key_length: int
    unique: bool

    def __post_init__(self) -> None:
        if self.key_offset < 0 or self.key_length <= 0:
            raise ValueError(
                f"{self.dsn}: key offset {self.key_offset}, length {self.key_length}"
            )
```

`catnip/catnip/catalog_path.py`:

```python
"""A path: the name a program opens to read a cluster through one of its alternate indexes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogPath:
    dsn: str
    aix: str
```

In `catnip/catnip/labels.py`, add the following after `LabelPending`, and replace the `DatasetLabel` alias:

```python
@dataclass(frozen=True)
class PathView:
    """A path's label: its base cluster's label read through an alternate key."""

    base: KsdsLabel
    key_offset: int
    key_length: int
    unique: bool


DatasetLabel: TypeAlias = Label | LabelPending | PathView
```

- [ ] **Step 4: Open a path**

In `catnip/catnip/dataset.py`:
- import `open_alternate_index_driver` from `interpreter.cobol.alternate_index_driver`, and `PathView`;
- add `case PathView(): return _through_path(self.path, mode, self.label)` before `case _`;
- add:

```python
def _through_path(path: Path, mode: OpenMode, label: PathView) -> FileOrganizationDriver:
    return open_alternate_index_driver(
        path,
        mode,
        label.base.lrecl,
        label.base.key_offset,
        label.base.key_length,
        label.key_offset,
        label.key_length,
        label.unique,
    )
```

- [ ] **Step 5: Catalog AIXs and paths**

In `catnip/catnip/system_catalog.py`:
- add wire models;
- extend `_CatalogWire` with `aixs: tuple[_AixWire, ...] = ()` and `paths: tuple[_PathWire, ...] = ()`;
- load them in `__init__` into `self._aixs: Table[str, AlternateIndex]` and `self._paths: Table[str, CatalogPath]`;
- write them in `_write`;
- add the methods below.

`_keyed_or_pending_wire` now receives `KsdsLabel | LabelPending | PathView`. Add `case PathView(): raise CatalogError(f"a path's view is never stored as a dataset label")`. Paths are only ever built by `lookup`, so this arm records an invariant.

```python
class _AixWire(_Wire):
    dsn: str
    base: str
    key_offset: int
    key_length: int
    unique: bool

    def model(self) -> AlternateIndex:
        return AlternateIndex(
            self.dsn, self.base, self.key_offset, self.key_length, self.unique
        )


class _PathWire(_Wire):
    dsn: str
    aix: str

    def model(self) -> CatalogPath:
        return CatalogPath(self.dsn, self.aix)
```

```python
    def define_aix(self, aix: AlternateIndex) -> AlternateIndex:
        match self.lookup(aix.base):
            case Dataset(label=KsdsLabel()):
                self._aixs.put(aix.dsn, aix)
                self._write()
                return aix
            case _:
                raise CatalogError(
                    f"{aix.dsn}: base cluster {aix.base} is not a cataloged KSDS"
                )

    def define_path(self, path: CatalogPath) -> Dataset:
        if not self._aixs.has(path.aix):
            raise CatalogError(
                f"{path.dsn}: alternate index {path.aix} is not cataloged"
            )
        self._paths.put(path.dsn, path)
        self._write()
        return self._through(path)

    def _through(self, path: CatalogPath) -> Dataset:
        aix = self._aixs.get(path.aix)
        base = self._entries.get(aix.base)
        return Dataset(
            path.dsn,
            base.path,
            PathView(_ksds(base), aix.key_offset, aix.key_length, aix.unique),
        )

    def lookup(self, dsn: str) -> Dataset | NotCataloged:
        if self._entries.has(dsn):
            return self._entries.get(dsn)
        if self._paths.has(dsn):
            return self._through(self._paths.get(dsn))
        return NotCataloged()

    def remove(self, dsn: str) -> None:
        if self._paths.has(dsn):
            self._paths.take(dsn)
        elif self._aixs.has(dsn):
            self._drop_aix(dsn)
        else:
            self._drop_cluster(dsn)
        self._write()

    def _drop_cluster(self, dsn: str) -> None:
        self._entries.take(dsn).path.unlink(missing_ok=True)
        tuple(self._drop_aix(a.dsn) for a in self._aixs.values() if a.base == dsn)

    def _drop_aix(self, dsn: str) -> None:
        self._aixs.take(dsn)
        tuple(self._paths.take(p.dsn) for p in self._paths.values() if p.aix == dsn)
```

Add a module-level `_ksds(dataset: Dataset) -> KsdsLabel` that matches `case KsdsLabel(): return label` and otherwise raises `CatalogError(f"{dataset.dsn}: an alternate index's base is not a KSDS")`. This check is needed because `catalog.json` is editable by hand. If python-fp-lint flags the side-effecting comprehensions, replace each with a small loop-free helper that returns the doomed names and then `tuple(map(table.take, names))`. Follow whatever the linter accepts, without suppressing it.

- [ ] **Step 6: Run the catnip tests**

Run: `cd catnip && uv run --no-sync python -m pytest -q`
Expected: all pass. Then mutation-check:
- have `_drop_cluster` skip the AIX cascade: the second test must fail;
- swap `key_offset` and `key_length` in `_through`: the first must fail.

- [ ] **Step 7: Write the failing jackal test**

`jackal/tests/integration/fixtures/cbl/ALTREAD.cbl`:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALTREAD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT XREF-FILE ASSIGN TO XREFDD
                  ORGANIZATION IS INDEXED
                  ACCESS MODE IS SEQUENTIAL
                  RECORD KEY IS XREF-ALT.
           SELECT OUT-FILE ASSIGN TO OUTDD
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  XREF-FILE.
       01  XREF-REC.
           05  XREF-KEY  PIC X(3).
           05  XREF-ALT  PIC X(3).
           05  XREF-TAIL PIC X(2).
       FD  OUT-FILE.
       01  OUT-REC      PIC X(8).
       WORKING-STORAGE SECTION.
       01  EOF-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT XREF-FILE.
           OPEN OUTPUT OUT-FILE.
           PERFORM UNTIL EOF-FLAG = 'Y'
               READ XREF-FILE NEXT
                   AT END MOVE 'Y' TO EOF-FLAG
                   NOT AT END
                       MOVE XREF-REC TO OUT-REC
                       WRITE OUT-REC
               END-READ
           END-PERFORM.
           CLOSE XREF-FILE.
           CLOSE OUT-FILE.
           GOBACK.
```

`jackal/tests/integration/test_cobol_path.py`:

```python
"""A batch program reads a cluster through a path, in alternate-key order."""

from pathlib import Path

import pytest
from interpreter.cobol.ebcdic_table import EbcdicTable

from catnip.alternate_index import AlternateIndex
from catnip.catalog_path import CatalogPath
from catnip.labels import KsdsLabel
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET, run_cobol_step
from jackal.program_compiler import ProgramCompiler
from jackal.results import Completed
from tests.covers import NotLanguageFeature, covers
from tests.model_build import allocated, dd, disp, program
from tests.system_build import job_catalog, system, upload

CBL = Path(__file__).parent / "fixtures" / "cbl"


def _ebcdic(text: bytes) -> bytes:
    return bytes(EbcdicTable.ascii_to_ebcdic(text))


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_program_reads_a_cluster_through_its_path(tmp_path, bridge_jar):
    upload(
        tmp_path,
        "J.KSDS",
        _ebcdic(b"001BBBxx002AAAyy003AAAzz"),
        KsdsLabel(8, 0, 3),
    )
    system(tmp_path).define_aix(AlternateIndex("J.AIX", "J.KSDS", 3, 3, False))
    system(tmp_path).define_path(CatalogPath("J.PATH", "J.AIX"))
    cat = job_catalog(tmp_path)
    step = program(
        "S1",
        "ALTREAD",
        (dd("XREFDD", "J.PATH", disp("SHR")), dd("OUTDD", "J.OUT", disp("NEW", "PASS"))),
    )
    rc = run_cobol_step(
        step,
        ProgramCompiler(bridge_jar, (), (CBL,), ()).compiled(
            (CBL / "ALTREAD.cbl").read_text()
        ),
        allocated(step, cat),
        cat.workdir,
        budget=DEFAULT_PROGRAM_STEP_BUDGET,
        relabeller=cat,
    )

    assert rc == Completed(0)
    assert cat.resolve("J.OUT").path.read_bytes() == _ebcdic(
        b"002AAAyy003AAAzz001BBBxx"
    )
```

Note that the alternate keys are EBCDIC bytes, so their order is EBCDIC order. `AAA` sorts below `BBB` in EBCDIC too.

Run: `. ./bridge-env.sh && uv run --no-sync pytest jackal/tests/integration/test_cobol_path.py -q`
Expected: FAIL. Either the open is refused with status 39, because `_indexed_conflict` rejects `PathView`, or the records come back in primary-key order.

- [ ] **Step 8: jackal opens a path through its dataset**

In `jackal/jackal/cobol_files.py`:
- `_indexed_conflict`: `case KsdsLabel() | PathView(): return False`.
- `_driver`: before the `_variable` check, add:

```python
        if self._datasets.has(filename) and _through_path(
            self._datasets.get(filename).label
        ):
            return self._datasets.get(filename).opened(mode)
```

with

```python
def _through_path(label: DatasetLabel) -> bool:
    match label:
        case PathView():
            return True
        case _:
            return False
```

Then run `uv run pyright` and handle every `DatasetLabel` match it reports. A `PathView` behaves as its `base` `KsdsLabel`, for example in `dcb_label.liked_label`: `case PathView(): return <the KsdsLabel arm applied to label.base>`.

- [ ] **Step 9: Run and commit**

Run: `cd catnip && uv run --no-sync python -m pytest -q`, then `. ./bridge-env.sh && uv run --no-sync pytest jackal/tests -q`, then `make test-all`.
Expected: all pass. Mutation-check: make `_through_path` return `False`, and the jackal test must fail.

```bash
git add catnip jackal
git commit -m "feat(catnip): alternate indexes and paths; a batch program reads a cluster through its path (red-dragon-forge-zave)"
git push origin main
```

---

### Task 4: `catnip install` and CardDemo's declaration

**Files:**
- Create:
  - `catnip/catnip/declaration.py` (the TOML wire, parsed into domain dataclasses)
  - `catnip/catnip/declaration_error.py`
  - `catnip/catnip/install.py`
  - `catnip/catnip/cli.py`
  - `config/carddemo/data.toml`
- Modify:
  - `catnip/pyproject.toml` (`[project.scripts] catnip = "catnip.cli:main"`)
  - `Makefile` (remove `jackal-install` and its help and `.PHONY` entries; add `catnip-install-carddemo SYSTEM=DIR` running `uv run --no-sync catnip install config/carddemo/data.toml --system "$(SYSTEM)"`)
- Delete: `red_dragon_forge/carddemo_jackal_install.py`
- Test:
  - `catnip/tests/unit/test_install.py`
  - rename `tests/integration/test_carddemo_jackal_install.py` to `tests/integration/test_carddemo_data_install.py` with `git mv`, then rewrite it

**Interfaces:**
- Consumes: `SystemCatalog.create/add/define_aix/define_path/catalog_gdg`, `AlternateIndex`, `CatalogPath` (Task 3).
- Produces:
  - `catnip.declaration.load_declaration(path: Path) -> Declaration`;
  - `Declaration(data_dir: Path, sequential: tuple[SequentialEntry, ...], ksds: tuple[KsdsEntry, ...], gdg: tuple[GdgEntry, ...])`;
  - `SequentialEntry(dsn: str, seed: Path, recfm: RecordFormat, lrecl: int)`;
  - `KsdsEntry(dsn: str, seed: Path | Unseeded, lrecl: int, key_offset: int, key_length: int, aix: tuple[AixEntry, ...])`;
  - `AixEntry(dsn: str, path: str, key_offset: int, key_length: int, unique: bool)`;
  - `GdgEntry(name: str, limit: int, empty: Empty, scratch: Scratch, order: GdgOrder)`;
  - `Unseeded()`;
  - `catnip.install.install(declaration: Declaration, system: SystemCatalog) -> tuple[str, ...]`, which returns the installed DSNs in declaration order and raises `DeclarationError` naming the dataset and field.

- [ ] **Step 1: Write the failing install tests**

`catnip/tests/unit/test_install.py`:

```python
"""catnip install: a declaration validated whole, then loaded into a system catalog."""

from __future__ import annotations

from pathlib import Path

import pytest
from cobol_asg.file_enums import OpenMode

from catnip.declaration import load_declaration
from catnip.declaration_error import DeclarationError
from catnip.install import install
from catnip.labels import KsdsLabel, PathView, RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged, SystemCatalog
from tests.covers import NotLanguageFeature, covers

_GOOD = """\
data_dir = "{data}"

[[sequential]]
dsn = "T.SEQ"
from = "seq.ps"
recfm = "FB"
lrecl = 4

[[ksds]]
dsn = "T.KSDS"
from = "ksds.ps"
lrecl = 8
key_offset = 0
key_length = 3

[[ksds.aix]]
dsn = "T.AIX"
path = "T.PATH"
key_offset = 3
key_length = 3
unique = false

[[ksds]]
dsn = "T.EMPTY"
lrecl = 8
key_offset = 0
key_length = 3
"""


def _declared(tmp_path: Path, text: str, files: dict[str, bytes]) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    for name, content in files.items():
        (data / name).write_bytes(content)
    declaration = tmp_path / "data.toml"
    declaration.write_text(text.format(data=data))
    return declaration


_FILES = {"seq.ps": b"abcdefgh", "ksds.ps": b"003AAAzz001BBBxx002AAAyy"}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_declaration_installs_sorted_clusters_indexes_and_paths(tmp_path):
    system = SystemCatalog(tmp_path / "system")
    installed = install(load_declaration(_declared(tmp_path, _GOOD, _FILES)), system)
    path = system.lookup("T.PATH")
    drv = path.opened(OpenMode.INPUT)
    through = [drv.read_seq().data for _ in range(3)]
    drv.close()

    assert installed == ("T.SEQ", "T.KSDS", "T.AIX", "T.PATH", "T.EMPTY")
    assert system.lookup("T.SEQ").label == SequentialLabel(RecordFormat.FB, 4)
    assert system.lookup("T.KSDS").path.read_bytes() == b"001BBBxx002AAAyy003AAAzz"
    assert system.lookup("T.EMPTY").path.read_bytes() == b""
    assert path.label == PathView(KsdsLabel(8, 0, 3), 3, 3, False)
    assert through == [b"002AAAyy", b"003AAAzz", b"001BBBxx"]


@pytest.mark.parametrize(
    ("change", "files", "message"),
    [
        (("lrecl = 8\nkey_offset = 0\nkey_length = 3\n\n[[ksds.aix]]", "lrecl = 7\nkey_offset = 0\nkey_length = 3\n\n[[ksds.aix]]"), _FILES, "T.KSDS: from: ksds.ps holds 24 bytes, not a whole number of 7-byte records"),
        (("key_offset = 3\nkey_length = 3", "key_offset = 6\nkey_length = 3"), _FILES, "T.AIX: key_offset: key 6+3 overruns the 8-byte record"),
        (("unique = false", "unique = true"), _FILES, "T.AIX: unique: alternate key b'AAA' repeats"),
        (("", ""), {**_FILES, "ksds.ps": b"001AAAzz001BBBxx"}, "T.KSDS: from: primary key b'001' repeats"),
        (('dsn = "T.EMPTY"', 'dsn = "T.SEQ"'), _FILES, "T.SEQ: dsn: declared twice"),
        (('from = "seq.ps"', 'from = "nope.ps"'), _FILES, "T.SEQ: from: nope.ps does not exist"),
    ],
)
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_invalid_declaration_installs_nothing_and_names_the_field(
    tmp_path, change, files, message
):
    text = _GOOD.replace(*change)
    system = SystemCatalog(tmp_path / "system")

    with pytest.raises(DeclarationError) as error:
        install(load_declaration(_declared(tmp_path, text, files)), system)

    assert str(error.value) == message
    assert SystemCatalog(tmp_path / "system").lookup("T.SEQ") == NotCataloged()
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd catnip && uv run --no-sync python -m pytest tests/unit/test_install.py -q`
Expected: FAIL, with `ModuleNotFoundError: catnip.declaration`.

- [ ] **Step 3: The declaration**

`catnip/catnip/declaration_error.py`:

```python
"""A data declaration that cannot be installed, naming the dataset and the field at fault."""


class DeclarationError(ValueError):
    pass
```

`catnip/catnip/declaration.py`: the pydantic wire models (`extra="forbid"`, frozen) mirror the TOML in spec N8.
- `from` is aliased to `seed`. It is required for `[[sequential]]` and optional for `[[ksds]]`.
- The wire's `model()` methods build frozen dataclasses: `Declaration`, `SequentialEntry`, `KsdsEntry`, `AixEntry`, `GdgEntry`, and `Unseeded()` for an absent KSDS `from`.
- `data_dir` goes through `os.path.expandvars`. A `$` left after expansion raises `DeclarationError(f"data_dir: unset environment variable in {raw!r}")`.
- `seed` paths are joined to `data_dir`.

`load_declaration(path)` is `_DeclarationWire.model_validate(tomllib.loads(path.read_text("utf-8"))).model()`. One class per file: put each dataclass in its own module if python-fp-lint or review asks for it. The wire classes are private and stay in `declaration.py`.

- [ ] **Step 4: Validation and loading**

`catnip/catnip/install.py`:
- `_problems(declaration) -> Iterator[str]` yields messages in the formats the test asserts, in declaration order:
  - per dataset: duplicate DSN (across sequential, KSDS, AIX, path and GDG names), `from` missing, size not a multiple of `lrecl`, key overrun, repeated primary key, repeated alternate key in a unique AIX.
- `install` raises `DeclarationError(next(problems))` if there is any problem.
- Otherwise it loads:
  - sequential: `system.add(dsn, seed, SequentialLabel(recfm, lrecl))`;
  - KSDS: `system.create(dsn, KsdsLabel(...)).path.write_bytes(<records sorted by primary key>)`;
  - each AIX: `system.define_aix(AlternateIndex(aix.dsn, k.dsn, ...))` then `system.define_path(CatalogPath(aix.path, aix.dsn))`;
  - each GDG: `system.catalog_gdg(GdgBase(name, limit, empty, scratch, order, ()))`.
- It logs one `INFO` line per DSN and returns the DSNs in that order.

`catnip/catnip/cli.py`:

```python
"""catnip's command line: install a data declaration into a system directory."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from catnip.declaration import load_declaration
from catnip.declaration_error import DeclarationError
from catnip.install import install
from catnip.system_catalog import SystemCatalog

logger = logging.getLogger(__name__)


def run(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="catnip")
    sub = parser.add_subparsers(dest="cmd", required=True)
    installing = sub.add_parser("install", help="install a data declaration")
    installing.add_argument("declaration", type=Path)
    installing.add_argument("--system", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        install(load_declaration(args.declaration), SystemCatalog(args.system))
    except DeclarationError as error:
        logger.error("%s", error)
        return 1
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return run(sys.argv[1:])
```

- [ ] **Step 5: Run the catnip tests**

Run: `cd catnip && uv run --no-sync python -m pytest -q`
Expected: all pass. Mutation-check:
- drop the sort in KSDS loading: the first test must fail;
- skip the size check: the first parametrised case must fail.

- [ ] **Step 6: CardDemo's declaration**

Write `config/carddemo/data.toml`. Start with `data_dir = "${FORGE_ROOT}/vendor/carddemo/app/data/EBCDIC"`.

**Sequential datasets:** one `[[sequential]]` with `recfm = "FB"` for each of these, as `(DSN, lrecl)`:
- (USRSEC.PS, 80)
- (ACCTDATA.PS, 300)
- (CARDDATA.PS, 150)
- (CUSTDATA.PS, 500)
- (CARDXREF.PS, 50)
- (DALYTRAN.PS.INIT, 350)
- (DALYTRAN.PS, 350)
- (DISCGRP.PS, 50)
- (TRANCATG.PS, 60)
- (TRANTYPE.PS, 60)
- (TCATBALF.PS, 50)

Each `dsn` and `from` is `AWS.M2.CARDDEMO.<name>`.

**Clusters:** a `[[ksds]]` for each, with the values from CardDemo's IDCAMS JCL:

| dsn (`AWS.M2.CARDDEMO.` + …) | from (`AWS.M2.CARDDEMO.` + …) | lrecl | key_offset | key_length | aix |
|---|---|---|---|---|---|
| USRSEC.VSAM.KSDS | USRSEC.PS | 80 | 0 | 8 | — |
| ACCTDATA.VSAM.KSDS | ACCTDATA.PS | 300 | 0 | 11 | — |
| CARDDATA.VSAM.KSDS | CARDDATA.PS | 150 | 0 | 16 | CARDDATA.VSAM.AIX / CARDDATA.VSAM.AIX.PATH, 16, 11, false |
| CUSTDATA.VSAM.KSDS | CUSTDATA.PS | 500 | 0 | 9 | — |
| CARDXREF.VSAM.KSDS | CARDXREF.PS | 50 | 0 | 16 | CARDXREF.VSAM.AIX / CARDXREF.VSAM.AIX.PATH, 25, 11, false |
| TRANSACT.VSAM.KSDS | DALYTRAN.PS | 350 | 0 | 16 | TRANSACT.VSAM.AIX / TRANSACT.VSAM.AIX.PATH, 304, 26, false |
| DISCGRP.VSAM.KSDS | DISCGRP.PS | 50 | 0 | 16 | — |
| TRANCATG.VSAM.KSDS | TRANCATG.PS | 60 | 0 | 6 | — |
| TRANTYPE.VSAM.KSDS | TRANTYPE.PS | 60 | 0 | 2 | — |
| TCATBALF.VSAM.KSDS | TCATBALF.PS | 50 | 0 | 17 | — |

Put one TOML comment above TRANSACT: `# CardDemo ships no TRANSACT seed; DALYTRAN.PS has the same layout (TRANFILE.jcl loads DALYTRAN.PS.INIT, a single record).`

- [ ] **Step 7: Rewrite the root install test**

`git mv tests/integration/test_carddemo_jackal_install.py tests/integration/test_carddemo_data_install.py`. Keep its two behaviours and every assertion, re-expressed over the declaration:
1. `test_every_declared_carddemo_dataset_agrees_with_its_copybook_and_its_file`:
   - the test holds `_COPYBOOKS: dict[str, str]`, mapping each declared DSN to the copybook the old table named;
   - each KSDS takes its seed's copybook;
   - it asserts each declared `lrecl` equals the copybook's record length (ProLeap, as before);
   - it asserts each seed's size is a whole number of records;
   - it asserts the EBCDIC directory listing equals the declared seed files plus the two `UNDECLARED` DSNs, which move into the test with their reasons.
2. `test_an_installed_carddemo_system_holds_each_dataset_and_runs_acctfile`:
   - `install(load_declaration(Path("config/carddemo/data.toml")), SystemCatalog(root))`, with `FORGE_ROOT` resolved from the repo root, never from the shell;
   - a sequential dataset's bytes equal its source;
   - `CARDXREF.VSAM.KSDS`'s bytes are its source's records sorted by the 16-byte primary key;
   - `lookup("AWS.M2.CARDDEMO.CARDXREF.VSAM.AIX.PATH").label == PathView(KsdsLabel(50, 0, 16), 25, 11, False)`;
   - the ACCTFILE job still gives `[Completed(0)] * 3`;
   - the reopened `ACCTDATA.VSAM.KSDS` label is `KsdsLabel(300, 0, 11)`.

`load_declaration` expands `${FORGE_ROOT}`. The test supplies it by declaring through a copy of the file with `data_dir` replaced by the vendored path, written under `tmp_path`.

- [ ] **Step 8: Remove the old installer, run everything, commit**

```bash
git rm red_dragon_forge/carddemo_jackal_install.py
```

Edit the `Makefile` as listed under Files. Run `make test-all`.
Expected: all pass. `rg "carddemo_jackal_install|jackal-install" --glob '!docs/**'` prints nothing.

```bash
git add catnip config/carddemo/data.toml tests Makefile red_dragon_forge
git commit -m "feat(catnip): catnip install — a validated data declaration; CardDemo's own data.toml replaces make jackal-install (red-dragon-forge-zave)"
git push origin main
```

---

### Task 5: cicada's file control on catnip

**Files:**
- Create:
  - `cicada/cics/vsam/file_table.py`: `cics_files(system, dsnames) -> Mapping[str, Dataset]` and `FileTableError`
  - `cicada/tests/vsam_system.py`: the test helper
  - `cicada/tests/integration/cics/test_vsam_catalog.py`
- Modify:
  - `cicada/pyproject.toml` (depend on `catnip`, `{ workspace = true }`)
  - `cicada/cics/vsam/engine.py`
  - `cicada/cics/vsam/fct.py` (delete it if no user remains)
  - `cicada/cics/vsam/format.py` (keep `read_flat_file`; delete `write_flat_file` if no user remains)
  - `cicada/cics/vsam/dump.py` (`--dsn` and `--system` replace `--data`)
  - `cicada/cics/tn3270/config.py`, `region.py`, `cli.py`
  - `cicada/config/carddemo-tn3270.toml`, `carddemo-db2-tn3270.toml`
  - `cicada/cobol_harness/vsam.py` if that path exists; otherwise wherever the survey placed the harness
  - `docs/presentation/capture/cics_flow.py`
  - `red_dragon_forge/carddemo_db2_cli.py` (`--system`)
  - `red_dragon_forge/carddemo_db2_region.py`
  - the root tests `tests/integration/test_carddemo_db2_headless.py`, `test_carddemo_db2_region.py` and `tests/unit/test_carddemo_db2_region_wiring.py`
  - every cicada test listed in Step 6
- Delete: `cicada/cics/vsam/seed.py`, `cicada/tests/unit/cics/test_vsam_seed.py`, `cicada/tests/unit/cics/test_vsam_format.py` (if `write_flat_file` goes)

**Interfaces:**
- Consumes: `SystemCatalog`, `Dataset`, `PathView`, `KsdsLabel` (Tasks 2–3); `install` and `load_declaration` (Task 4); `cics.csd_parse.parse_csd_files(csd_path) -> dict[str, str]`.
- Produces:
  - `VsamEngine(files: Mapping[str, Dataset])`; the per-operation methods keep their signatures;
  - `cics_files(system: SystemCatalog, dsnames: Mapping[str, str]) -> dict[str, Dataset]`;
  - `RegionConfig` without `data_dir` and `datasets`, with `system: Path` and `csd_files: tuple[Path, ...]`;
  - `load_config(path: Path, system: Path) -> RegionConfig`.

- [ ] **Step 1: Write the failing behaviour tests**

`cicada/tests/integration/cics/test_vsam_catalog.py`:

```python
"""cicada's file control over the system catalog: one cluster, read through its path."""

from __future__ import annotations

import logging

import pytest

from catnip.system_catalog import SystemCatalog
from cics.vsam.engine import RESP_NORMAL, VsamEngine
from cics.vsam.eibresp import RESP_DUPKEY
from cics.vsam.file_table import FileTableError, cics_files
from interpreter.cobol.features import CobolFeature
from tests.covers import covers
from tests.vsam_system import SeedAix, SeedCluster, build_test_system

_XREF = SeedCluster(
    "CCXREF",
    lrecl=8,
    key_length=3,
    records=(b"001AAAxx", b"002BBByy"),
    aix=(SeedAix("CXACAIX", key_offset=3, key_length=3, unique=False),),
)


@covers(CobolFeature.EXEC_CICS)
def test_a_record_written_through_the_cluster_is_read_through_its_path(tmp_path):
    system, dsnames = build_test_system(tmp_path, (_XREF,))
    engine = VsamEngine(cics_files(system, dsnames))

    wrote = engine.write("CCXREF", b"000", 3, b"000AAAzz")
    first = engine.read("CXACAIX", b"AAA", 3)
    restarted = VsamEngine(cics_files(SystemCatalog(tmp_path / "system"), dsnames))
    after_restart = restarted.read("CCXREF", b"000", 3)

    assert wrote == RESP_NORMAL
    assert first == (b"000AAAzz", RESP_DUPKEY)
    assert after_restart == (b"000AAAzz", RESP_NORMAL)


@covers(CobolFeature.EXEC_CICS)
def test_a_region_over_an_uncataloged_dsn_stops_at_startup(tmp_path):
    system, _ = build_test_system(tmp_path, (_XREF,))

    with pytest.raises(FileTableError) as error:
        cics_files(system, {"ACCTDAT": "NO.SUCH.KSDS"})

    assert str(error.value) == "CICS file ACCTDAT: NO.SUCH.KSDS is not cataloged"


@covers(CobolFeature.EXEC_CICS)
def test_a_key_shorter_than_declared_logs_both_lengths(tmp_path, caplog):
    system, dsnames = build_test_system(tmp_path, (_XREF,))
    engine = VsamEngine(cics_files(system, dsnames))

    with caplog.at_level(logging.WARNING, logger="cics.vsam.engine"):
        engine.read("CXACAIX", b"AA", 2)

    assert caplog.messages == [
        "CXACAIX (TEST.CCXREF.PATH): NOTFND; declared key 3 bytes at offset 3, program key 2 bytes"
    ]


@pytest.mark.xfail(
    reason="AIX duplicates come back in primary-key order, z/OS returns arrival order (red-dragon-forge-zqxf)",
    strict=True,
)
@covers(CobolFeature.EXEC_CICS)
def test_duplicate_alternate_keys_come_back_in_the_order_they_were_written(tmp_path):
    system, dsnames = build_test_system(tmp_path, (_XREF,))
    engine = VsamEngine(cics_files(system, dsnames))

    engine.write("CCXREF", b"000", 3, b"000AAAzz")
    first = engine.read("CXACAIX", b"AAA", 3)

    assert first == (b"001AAAxx", RESP_DUPKEY)
```

`cicada/tests/vsam_system.py`:

```python
"""Test helper: a catnip system holding test clusters and their paths, and the CICS file table over it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from catnip.alternate_index import AlternateIndex
from catnip.catalog_path import CatalogPath
from catnip.labels import KsdsLabel
from catnip.system_catalog import SystemCatalog


@dataclass(frozen=True)
class SeedAix:
    file: str
    key_offset: int
    key_length: int
    unique: bool


@dataclass(frozen=True)
class SeedCluster:
    file: str
    lrecl: int
    key_length: int
    records: tuple[bytes, ...]
    aix: tuple[SeedAix, ...] = ()


def _cluster(system: SystemCatalog, cluster: SeedCluster) -> Mapping[str, str]:
    dsn = f"TEST.{cluster.file}"
    label = KsdsLabel(cluster.lrecl, 0, cluster.key_length)
    ordered = sorted(cluster.records, key=lambda r: r[: cluster.key_length])
    system.create(dsn, label).path.write_bytes(b"".join(ordered))
    paths = {
        aix.file: _path(system, dsn, aix) for aix in cluster.aix
    }
    return {cluster.file: dsn, **paths}


def _path(system: SystemCatalog, base: str, aix: SeedAix) -> str:
    system.define_aix(
        AlternateIndex(f"{base}.AIX", base, aix.key_offset, aix.key_length, aix.unique)
    )
    system.define_path(CatalogPath(f"{base}.PATH", f"{base}.AIX"))
    return f"{base}.PATH"


def build_test_system(
    root: Path, clusters: Sequence[SeedCluster]
) -> tuple[SystemCatalog, dict[str, str]]:
    system = SystemCatalog(root / "system")
    dsnames = {
        name: dsn for c in clusters for name, dsn in _cluster(system, c).items()
    }
    return system, dsnames
```

- [ ] **Step 2: Run them and see them fail**

Run: `. ./bridge-env.sh && cd cicada && uv add --package cicada catnip` (or edit `cicada/pyproject.toml` and `uv sync --all-packages`), then `uv run --no-sync python -m pytest tests/integration/cics/test_vsam_catalog.py -q`
Expected: FAIL, with `ModuleNotFoundError: cics.vsam.file_table`.

- [ ] **Step 3: The file table**

`cicada/cics/vsam/file_table.py`:

```python
"""A region's CICS files, each resolved to its cataloged cluster or path."""

from __future__ import annotations

from collections.abc import Mapping

from catnip.dataset import Dataset
from catnip.labels import KsdsLabel, PathView
from catnip.system_catalog import NotCataloged, SystemCatalog


class FileTableError(ValueError):
    pass


def _resolved(system: SystemCatalog, name: str, dsn: str) -> Dataset:
    match system.lookup(dsn):
        case Dataset(label=KsdsLabel() | PathView()) as dataset:
            return dataset
        case Dataset():
            raise FileTableError(f"CICS file {name}: {dsn} is not a KSDS or path")
        case NotCataloged():
            raise FileTableError(f"CICS file {name}: {dsn} is not cataloged")


def cics_files(system: SystemCatalog, dsnames: Mapping[str, str]) -> dict[str, Dataset]:
    return {name.upper(): _resolved(system, name.upper(), dsn) for name, dsn in dsnames.items()}
```

- [ ] **Step 4: The engine over datasets**

Rewrite `cicada/cics/vsam/engine.py`:
- `__init__(self, files: Mapping[str, Dataset])` stores them. `load_all` and `_ensure_backing` are deleted, and so is `dataset_count`; if a caller uses it, return `len(self._files)`.
- `_shape(label) -> _Shape(lrecl, key_offset, key_length)`: a `KsdsLabel` gives its own fields; a `PathView` gives `base.lrecl` with its own key position.
- `_open(file, mode)` returns `self._files[name].opened(mode)`, or `None` for an unknown file, which the callers map to `RESP_DISABLED` as today.
- Key slicing uses `shape.key_length`. The "unpinned key length" fallback is deleted.
- `_RETURNS_RECORD = frozenset({AccessCondition.OK, AccessCondition.DUPLICATES_FOLLOW})`. `read`, `readnext` and `readprev` return `(result.data, to_eibresp(result.condition))` when the condition is in it, and `(None, to_eibresp(...))` otherwise. The held key is set on any record-returning read.
- **N10 logging:**
  - On `read`, `startbr` and `delete`: when the result is `NOT_FOUND` and `key_length != shape.key_length`, log `logger.warning("%s (%s): NOTFND; declared key %d bytes at offset %d, program key %d bytes", name, dataset.dsn, shape.key_length, shape.key_offset, key_length)`.
  - On `write` and `rewrite`: when `len(record) != shape.lrecl`, log `"%s (%s): declared record length %d, program record %d bytes"`.
- Update the module docstring to one header line: `"""CICS file control over the system catalog's datasets: a cluster or a path per CICS file."""`.

- [ ] **Step 5: Run the new tests**

Run: `cd cicada && uv run --no-sync python -m pytest tests/integration/cics/test_vsam_catalog.py -q`
Expected: 3 passed, 1 xfailed. Mutation-check:
- return `RESP_NORMAL` for `DUPLICATES_FOLLOW` reads: the first test must fail;
- drop the log: the third must fail.

- [ ] **Step 6: Migrate every engine construction site.** The pattern is:
  - the test's records go into a `SeedCluster` (with `SeedAix` entries where the old FCT had `key_offset > 0`);
  - `seed_vsam` / `seed_records` / `FctConfig` / `VsamEngine(fct, dir)` / `load_all` become `VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))`.

  A CICS file the old FCT seeded as an alternate-key copy becomes a path over the cluster holding those records. Name the cluster after the base file: CXACAIX → `SeedCluster("CCXREF", 50, 16, …, aix=(SeedAix("CXACAIX", 25, 11, False),))`. A test that seeded only CXACAIX now declares CCXREF too.

  Worked example, `test_carddemo_card_view.py`: replace `_write_seed_files`, `_FCT_YAML` and `_make_engine` with:

```python
_CLUSTERS = (
    SeedCluster("USRSEC", 80, 8, (_usrsec_record(_USER_ID, "First1", "Last1", _USER_PWD, "U"),)),
    SeedCluster("CARDDAT", 150, 16, (_card_record(),)),
)


def _make_engine(tmp_path: Path) -> VsamEngine:
    return VsamEngine(cics_files(*build_test_system(tmp_path, _CLUSTERS)))
```

  Do the same in each file below. Where a test asserted on `.dat` files (`read_flat_file(vsam_dir / "X.dat")`), it now reads `system.lookup(dsn).path`.
  - `cicada/tests/integration/cics/`:
    - card_update, user_list, user_add, card_list, add_transaction, reports, tran_list, account_view, card_view, tran_view, bill_pay, zbank_conversational, user_delete, user_update, account_update;
    - signon_real (two sites);
    - vsam_roundtrip, vsam_browse, condition_handling, vsam_persistence, vsam_dump_e2e.
  - `cicada/tests/unit/cics/`:
    - `test_vsam_builtins.py`;
    - `test_vsam_engine.py` (its `_engine_offset` cases become paths);
    - `test_tn3270_config.py` (see Step 7).
  - `cobol_harness/vsam.py` builds its engine the same way.
  - `docs/presentation/capture/cics_flow.py`: `RecordingVsamEngine` subclasses the new engine, and its seeding becomes `build_test_system`-style catalog creation. Import nothing from `tests`; write the three-line create-and-write inline.

- [ ] **Step 7: The region**
  - **`config.py`:**
    - delete `_dataset` and the `data_dir`/`datasets` fields;
    - add `system: Path` and `csd_files: tuple[Path, ...]` (from `[paths] csd_files`, via `_path`);
    - `load_config(path: Path, system: Path) -> RegionConfig`.
  - **`region.py`:**
    - `_vsam_engine(config: RegionConfig) -> VsamEngine` returns `VsamEngine(cics_files(SystemCatalog(config.system), _dsnames(config.csd_files)))`;
    - `_dsnames` merges `parse_csd_files` over the files in order, a later file winning;
    - `build_region` calls `_vsam_engine(config)`;
    - delete the old imports.
  - **`cli.py`:** add `--system DIR` (required), and pass it to `load_config`.
  - **Both region TOMLs:** delete `data_dir` and every `[datasets.*]` table, and add under `[paths]`: `csd_files = ["${CARDDEMO_HOME}/csd/CARDDEMO.CSD"]`.
  - **`test_tn3270_config.py`:** assert `csd_files` and `system` instead of `datasets["USRSEC"].key_length`.
  - **`test_region_on_abend.py`:** the monkeypatched `_vsam_engine` lambda takes `config` only.
  - **The tn3270 tests** (`tn3270_helpers.served_session`, `test_tn3270_e2e.py`, `test_tn3270_crud_e2e.py`, `test_tn3270_region.py`) and the root DB2 tests take a fixture `carddemo_system(tmp_path) -> Path`. It runs `install(load_declaration(<config/carddemo/data.toml with data_dir pointed at the vendored EBCDIC data>), SystemCatalog(tmp_path / "system"))` and returns the directory, and they pass it to `load_config`. Put the fixture in `cicada/tests/integration/cics/conftest.py`, and a twin in the root `tests/conftest.py`. The two packages' test trees cannot import each other.
  - **`red_dragon_forge/carddemo_db2_cli.py`:** add `--system`.
  - **`dump.py`:** `--system DIR --dsn DSN` replace `--data`, and it reads `SystemCatalog(system).lookup(dsn).path`.

- [ ] **Step 8: Delete the seeding**

Run `git rm cicada/cics/vsam/seed.py cicada/tests/unit/cics/test_vsam_seed.py`. Delete `fct.py` and `write_flat_file` (with `test_vsam_format.py`'s write tests) once `rg 'FctConfig|DatasetConfig|write_flat_file|seed_vsam|seed_records' --glob '!docs/**' --glob '!vendor/**'` prints nothing.

- [ ] **Step 9: Run everything**

Run: `make db2-up`, `. ./bridge-env.sh && . squall/db2/dsn-env.sh && make test-all`
Expected: all pass, with exactly one xfail, the zqxf test. If a CardDemo end-to-end assertion fails on which card or transaction appears first, see Review Focus 1.

- [ ] **Step 10: Commit**

```bash
git add -A cicada red_dragon_forge tests docs/presentation/capture/cics_flow.py uv.lock
git commit -m "feat(cicada): file control on the system catalog — CICS files resolve through the CSD; no seeded copies; CXACAIX is a path over CCXREF (red-dragon-forge-zave)"
git push origin main
```

---

### Task 6: red-dragon — retire the read-only alternate-key driver

**Files (in `~/code/red-dragon`):**
- Modify: `interpreter/cobol/file_drivers.py` (delete `AlternateKeyDriver` and `open_alternate_key_driver`)
- Delete: `tests/unit/cobol/test_alternate_key_driver.py`

- [ ] **Step 1:** Run `rg 'AlternateKeyDriver|open_alternate_key_driver'` in both repos. It must print only the definition and its test.
- [ ] **Step 2:** Delete them. Run `cd ~/code/red-dragon && uv run pytest -q -x`; expect all to pass. Commit with `refactor(cobol): remove the read-only AlternateKeyDriver; paths use AlternateIndexDriver` and push.
- [ ] **Step 3:** Bump the submodule in the forge, run `make test-all` (all pass), and commit with `chore(vendor): bump red-dragon — read-only AlternateKeyDriver removed`. Push.

---

### Task 7: Docs

**Files:**
- Create: `docs/reference/catnip/README.md` (catalog objects; `catalog.json` shape; the declaration format with CardDemo's excerpt; `catnip install`; validation messages; N5's known difference, citing zqxf)
- Create: `docs/records/design/2026-10-14-catnip-catalog-extraction.md` (decisions N1–N12 condensed, with the IBM sources; it states that it supersedes the catalog's placement in the 2026-09-09 package-boundaries record)
- Modify: `docs/README.md` (index catnip), `docs/reference/forge/architecture.md` (package list; line 43's install step), `docs/reference/jackal/architecture.md:153-175` (the catalog now lives in catnip; paths), `docs/reference/jackal/cli.md` (`catalog add` writes catnip's catalog), `docs/reference/cicada/architecture.md:37,146-163` (file control over the catalog), `docs/reference/cicada/tn3270-config.md` (`csd_files`, `--system`; `[datasets]` and `data_dir` removed), `docs/how-to/run-jcl-job.md:34` (`make catnip-install-carddemo`)

- [ ] **Step 1:** Write the pages. Describe what each component covers; give no test counts.
- [ ] **Step 2:** `rg -n 'jackal-install|data_dir|\[datasets\.|jackal\.(labels|system_catalog|dataset)' docs/reference docs/how-to docs/README.md` prints nothing.
- [ ] **Step 3:** Commit with `docs(catnip): reference page, decision record, and the jackal and cicada pages updated (red-dragon-forge-zave)`. Close the bead with `bd close red-dragon-forge-zave --reason "<commits>"`, then `bd export -o issues/issues.jsonl`, stage it in the same commit, and push.

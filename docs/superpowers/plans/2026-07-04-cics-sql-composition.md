# CICS + EXEC SQL Composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `red-dragon-forge`, a repo that composes Cicada's CICS lowering strategy and
Squall's EXEC SQL lowering strategy over RedDragon's `extension_strategies` seam — proven end to
end by running Bank-of-Z's real `INQCUST` program (two `SELECT ... INTO` queries) against a live
Db2 database, with zero changes to Cicada, Squall, or RedDragon.

**Architecture:** A generic `CoprocessorSpec` (strategy factory + source prepass + execution-owner
flag) lets `compile_program()` compose N coprocessors without knowing their names; per-coprocessor
adapter modules (`adapters/cics.py`, `adapters/sql.py`) are the only code that imports Cicada or
Squall internals. `run_program()` is intentionally CICS-aware (the one documented execution-owning
coprocessor today) rather than pretending a generic runner protocol exists.

**Tech Stack:** Python 3.11, uv, pytest, RedDragon's `interpreter.project.cobol_compile.compile_cobol`,
Cicada's `cics` package, Squall's `squall` package, `ibm_db` (real Db2 driver).

## Global Constraints

- No edits to `cicada`, `squall`, or `red-dragon` source — this repo only consumes them.
- `red_dragon_forge/coprocessor.py` and `red_dragon_forge/compile.py` must never import `cics.*` or
  `squall.*` — only the `adapters/` modules may.
- Tests follow the existing family convention: **no skip, no env-fallback** — a missing
  `PROLEAP_BRIDGE_JAR` or Db2 env var is a hard failure (`KeyError`/`os.environ[...]`), never a
  skip or a guessed default.
- Every numeric/byte-length constant that reappears (COMMAREA lengths, field offsets) is a named
  constant, not a bare literal, even where the copybook itself uses literals.
- `uv run --no-sync` for all tool invocations once `uv sync` has been run once (mirrors Cicada's
  and Squall's own convention — a plain `uv run` re-resolves and can trigger a slow editable
  rebuild of the vendored `red-dragon`/`cicada`/`squall` wheels).

---

## File Structure

```
red-dragon-forge/
  pyproject.toml
  Makefile
  .gitignore
  vendor/red-dragon/        (submodule)
  vendor/cicada/            (submodule)
  vendor/squall/            (submodule)
  vendor/bank-of-z/         (submodule, added in Task 9)
  red_dragon_forge/
    __init__.py
    coprocessor.py          # CoprocessorSpec — generic, no CICS/SQL imports
    compile.py              # compile_program() — generic, no CICS/SQL imports
    run.py                  # run_program() — intentionally CICS-aware
    adapters/
      __init__.py
      cics.py               # build_cics_spec()
      sql.py                # build_sql_spec()
  tests/
    integration/
      conftest.py                    # bridge_jar fixture
      forge_cobol_helpers.py         # shared parser/copybook-dir helpers
      test_coprocessor.py            # Task 3
      test_compile_program.py        # Task 4
      test_cics_adapter.py           # Task 5
      test_sql_adapter.py            # Task 6
      test_run_program.py            # Task 7
      test_cics_sql_composition.py   # Task 8 (synthetic combined proof)
      test_inqcust_e2e.py            # Task 10 (real Bank-of-Z program, real Db2)
      db2_env.sh                     # Task 9 (Db2 DSN sourcing, mirrors squall's db2/dsn-env.sh)
```

All tests live under `tests/integration/` (not `tests/unit/`) because every one of them, even
Task 3's `CoprocessorSpec` test, exercises the real ProLeap bridge JAR — there is no meaningful
"pure unit" layer here that doesn't touch the COBOL compile pipeline.

---

### Task 1: Repo scaffolding + RedDragon submodule

**Files:**
- Create: `pyproject.toml`
- Create: `Makefile`
- Create: `.gitignore`
- Create: `red_dragon_forge/__init__.py` (empty)

**Interfaces:**
- Produces: an importable `interpreter` package (from the vendored RedDragon), a `red_dragon_forge`
  package placeholder for later tasks.

- [ ] **Step 1: Add the RedDragon submodule, pinned to the actual latest commit on `main`**

Cicada's `vendor/red-dragon` is currently pinned to `3697011bb5a6d35ebe498c6b8caca899432fc0e3`;
Squall's is pinned to `c78b0c42b742f248954a535bfa4279941172cd58` (newer — Cicada's commit is an
ancestor of it). Neither is actually current: RedDragon's real `origin/main` tip is
`cbed0e62f0ae7f37175f8e7b2abf18f6ccc86b6d` (2026-07-03), newer than both. Pin to that tip rather
than either sibling's stale pin — re-run `git fetch origin main && git rev-parse origin/main` in
`vendor/red-dragon` right before this step in case a newer commit has landed since this plan was
written, and use whatever that resolves to instead of the SHA below if it differs.

```bash
git submodule add git@github.com:avishek-sen-gupta/red-dragon.git vendor/red-dragon
cd vendor/red-dragon
git fetch origin main
git checkout $(git rev-parse origin/main)
cd ../..
git add vendor/red-dragon
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.env
uv.lock
.pytest_cache/
.mypy_cache/
.pyright/
.ruff_cache/
```

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "red-dragon-forge"
version = "0.1.0"
description = "Composition layer for RedDragon COBOL coprocessor runtimes (CICS + EXEC SQL + more)"
readme = "README.md"
requires-python = ">=3.11,<4.0"
dependencies = [
    "red-dragon",
]

[tool.uv.sources]
red-dragon = { path = "vendor/red-dragon", editable = true }

[tool.hatch.build.targets.wheel]
packages = ["red_dragon_forge"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "black>=26.1.0",
    "pyright>=1.1.408",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.black]
line-length = 88
target-version = ["py311"]
```

(`cicada`/`squall` dependencies are added in Task 2, once their submodules exist — `uv sync` would
fail on a path dependency that doesn't exist on disk yet.)

- [ ] **Step 4: Write `Makefile`**

```makefile
# red-dragon-forge local development tasks.
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar

PYTEST = uv run --no-sync python -m pytest

.PHONY: help setup jar jar-force python test fmt

help:
	@echo "make setup     - init submodules + build bridge JAR + uv sync"
	@echo "make jar       - build ProLeap bridge JAR (skipped if already built)"
	@echo "make jar-force - force-rebuild ProLeap bridge JAR"
	@echo "make python    - uv sync"
	@echo "make test      - full test suite (needs jar)"
	@echo "make fmt       - black-format the codebase"

setup:
	git submodule update --init --recursive
	$(MAKE) jar
	$(MAKE) python

$(PROLEAP_BRIDGE_JAR):
	cd vendor/red-dragon/proleap-bridge && ./build.sh

jar: $(PROLEAP_BRIDGE_JAR)

jar-force:
	cd vendor/red-dragon/proleap-bridge && ./build.sh

python:
	uv sync

test: jar
	PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) $(PYTEST) tests/ $(PYTEST_ARGS)

fmt:
	uv run --no-sync python -m black red_dragon_forge tests
```

- [ ] **Step 5: Create the empty package and sync**

```bash
mkdir -p red_dragon_forge
touch red_dragon_forge/__init__.py
uv sync
```

- [ ] **Step 6: Verify RedDragon imports and build the bridge JAR**

```bash
make jar
uv run --no-sync python -c "from interpreter.project.cobol_compile import compile_cobol; print('ok')"
```

Expected: prints `ok` with no import errors. `make jar` may take several minutes (Maven build) the
first time.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml Makefile .gitignore red_dragon_forge/__init__.py
git commit -m "Scaffold red-dragon-forge; vendor RedDragon at squall's newer pin"
```

---

### Task 2: Cicada + Squall submodules, dependency wiring, compatibility smoke test

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: importable `cics` (Cicada) and `squall` packages, confirmed compatible with the
  RedDragon commit pinned in Task 1.

- [ ] **Step 1: Add Cicada as a submodule**

Cicada now has a real GitHub remote (confirmed during Task 2 execution — the plan's original "no
remote, use a local path" premise is stale):

```bash
git submodule add git@github.com:avishek-sen-gupta/cicada.git vendor/cicada
```

- [ ] **Step 2: Add Squall as a submodule**

```bash
git submodule add git@github.com:avishek-sen-gupta/squall.git vendor/squall
```

- [ ] **Step 3: Update `pyproject.toml` — do NOT declare cicada/squall as uv path dependencies**

**This step supersedes the plan's original approach**, which declared `cicada`/`squall` as
`[project.dependencies]` with `[tool.uv.sources]` path overrides, matching Task 1's pattern for
`red-dragon`. That fails: `uv sync` errors with
`Requirements contain conflicting URLs for package red-dragon` — Cicada's own `pyproject.toml`
declares `red-dragon = {path="vendor/red-dragon"}` relative to *its own* root, and Squall's
declares the same relative to *its* root; these are two different physical directories (pinned at
different commits at the time this was discovered), and uv's resolver treats them as a genuine
same-package/conflicting-source conflict — this is NOT fixed by pinning both to the same commit
(the paths are still different directories). A `[tool.uv.workspace] exclude=[...]` on this
project's own `pyproject.toml` was tried and does **not** avoid the conflict either — uv still
reads Cicada's/Squall's own `[tool.uv.sources]` when resolving them as path dependencies at all,
workspace membership notwithstanding.

**The fix, confirmed working:** don't ask uv's resolver to reconcile Cicada's/Squall's own declared
dependencies at all. Declare their actual (small) transitive dependency lists directly in this
project instead, and install Cicada/Squall themselves as editable with `--no-deps`, outside the
normal `uv sync` resolution — a standard, well-known workaround for "two sibling projects each
vendor an unpublished shared dependency, consumed together by a third."

```toml
[project]
name = "red-dragon-forge"
version = "0.1.0"
description = "Composition layer for RedDragon COBOL coprocessor runtimes (CICS + EXEC SQL + more)"
readme = "README.md"
requires-python = ">=3.11,<4.0"
dependencies = [
    "red-dragon",
    "pyyaml>=6.0",
    "sortedcontainers>=2.4.0",
    "lark>=1.3.1",
    "antlr4-python3-runtime>=4.13,<4.14",
]

[project.optional-dependencies]
db2 = ["ibm-db>=3.2.0"]

[tool.uv.sources]
red-dragon = { path = "vendor/red-dragon", editable = true }

[tool.hatch.build.targets.wheel]
packages = ["red_dragon_forge"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "black>=26.1.0",
    "pyright>=1.1.408",
    "ibm-db>=3.2.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.black]
line-length = 88
target-version = ["py311"]
```

`pyyaml`/`sortedcontainers`/`antlr4-python3-runtime` mirror Cicada's own `[project.dependencies]`
(`lark` and `red-dragon` are already covered — `lark` is also Squall's only non-red-dragon runtime
dependency, so no separate addition needed for Squall). If Cicada's or Squall's own dependency list
changes in the future, this list needs a matching manual update — a small, explicit duplication
cost, not a hidden one.

- [ ] **Step 3b: Sync, then install Cicada and Squall editable with `--no-deps`**

```bash
uv sync
uv pip install -e vendor/cicada --no-deps
uv pip install -e vendor/squall --no-deps
```

Expected: `uv sync` succeeds cleanly (no conflict — it never has to resolve Cicada's/Squall's own
`red-dragon` source at all now), and both `--no-deps` installs succeed. Add these two `uv pip
install` lines to the `Makefile`'s `python` target (Task 1's Makefile) now, so `make python`/
`make setup` performs the full sequence in one command going forward:

```makefile
python:
	uv sync
	uv pip install -e vendor/cicada --no-deps
	uv pip install -e vendor/squall --no-deps
```

- [ ] **Step 3c: Verify both packages import**

```bash
uv run --no-sync python -c "from cics.strategy import CicsLoweringStrategy; print('cics ok')"
uv run --no-sync python -c "from squall.strategy import SqlLoweringStrategy; print('squall ok')"
```

Expected: both print their `ok` line with no import errors.

- [ ] **Step 4: Compatibility smoke test — run Cicada's own unit suite against the latest pinned RedDragon**

This is the concrete check for the version-mismatch risk found during planning (Cicada was tested
against an older RedDragon commit than the one this repo now vendors).

```bash
cd vendor/cicada
uv run --no-sync python -m pytest tests/unit/ -x -q
cd ../..
```

Expected: all pass. **If this fails**, the newer RedDragon commit broke something Cicada's own
`interpreter.cobol.*` usage relies on — stop and investigate before continuing to Task 3; do not
proceed with a broken compatibility baseline.

- [ ] **Step 5: Run Squall's own unit suite against the same pin, for the same reason**

```bash
cd vendor/squall
uv run --no-sync python -m pytest tests/unit/ -x -q
cd ../..
```

Expected: all pass. Same rationale as Step 4, for Squall's side of the pin gap.

- [ ] **Step 6: Add a "doctor" script that fails loudly when the three RedDragon pins drift apart**

Git submodule pins are inherently **per-repo, independently-committed pointers** — there is no
native git mechanism for multiple sibling repos to share one *live* pointer (declaring
`branch = main` in `.gitmodules`, which Cicada and Squall already do, only affects what
`git submodule update --remote` would fetch if someone explicitly runs it; it does not keep the
actually-committed SHA in sync, which is exactly how Cicada's and Squall's pins silently drifted
apart in the first place). The practical fix is a checked convention, not a structural guarantee:
this script makes drift immediately visible instead of silently accumulating again.

```bash
mkdir -p scripts
```

```python
# scripts/check_red_dragon_pin.py
"""Fail loudly if this repo's vendored RedDragon commit doesn't match the one
vendored inside vendor/cicada or vendor/squall (their own nested submodule
checkouts). This does NOT modify cicada or squall — it only reports drift; a
human decides whether/how to re-pin those repos (see the plan's Task 2 for why
this repo doesn't reach into siblings and bump their pins itself).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_CHECKOUTS = {
    "red-dragon-forge (this repo)": _ROOT / "vendor" / "red-dragon",
    "cicada": _ROOT / "vendor" / "cicada" / "vendor" / "red-dragon",
    "squall": _ROOT / "vendor" / "squall" / "vendor" / "red-dragon",
}


def _head_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    shas = {name: _head_sha(path) for name, path in _CHECKOUTS.items()}
    unique = set(shas.values())
    for name, sha in shas.items():
        print(f"{name}: {sha}")
    if len(unique) == 1:
        print("OK: all three RedDragon pins match.")
        return 0
    print(
        "DRIFT: RedDragon pins disagree across repos. Re-pin the stale ones "
        "(in their own repos, with their own commits) to the newest SHA above.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Run it and confirm it correctly reports today's known drift**

```bash
uv run --no-sync python scripts/check_red_dragon_pin.py
echo "exit code: $?"
```

Expected: prints three different SHAs (this repo's `cbed0e62...`, Cicada's `3697011b...`, Squall's
`c78b0c42...`) and exits 1 — this confirms the script actually detects the real, currently-existing
drift rather than trivially passing. This is the test for this script (no separate pytest file — it's
a standalone maintenance check, run manually/in CI, not part of the pytest suite).

- [ ] **Step 8: Commit the doctor script**

```bash
git add pyproject.toml scripts/check_red_dragon_pin.py
git commit -m "Add cicada + squall submodules/dependencies + a RedDragon-pin drift check"
```

- [ ] **Step 9: Bump Cicada's and Squall's own RedDragon pins to match, eliminating today's drift**

The user has explicitly asked for this (not a default this plan would otherwise take on its own —
bumping a sibling repo's submodule pin is a real change to that repo). These commits are made
**directly in `vendor/cicada` and `vendor/squall`**, which are this repo's own submodule checkouts
of those repos (real, independent git repositories on disk, each with their own history) — the
commits land in Cicada's and Squall's own git history, staying local until the user chooses to push
them from within those repos themselves.

```bash
cd vendor/cicada/vendor/red-dragon
git fetch origin main
git checkout cbed0e62f0ae7f37175f8e7b2abf18f6ccc86b6d
cd ../..
git add vendor/red-dragon
git commit -m "Bump vendor/red-dragon to cbed0e62 (align with squall + red-dragon-forge)"
cd ../..
```

```bash
cd vendor/squall/vendor/red-dragon
git fetch origin main
git checkout cbed0e62f0ae7f37175f8e7b2abf18f6ccc86b6d
cd ../..
git add vendor/red-dragon
git commit -m "Bump vendor/red-dragon to cbed0e62 (align with cicada + red-dragon-forge)"
cd ../..
```

- [ ] **Step 10: Re-run both sibling unit suites against the bumped pin (this supersedes Steps 4-5's already-passing runs, but re-run to be certain the actual checked-out commit — not just the dependency resolution — is the bumped one)**

```bash
cd vendor/cicada && uv run --no-sync python -m pytest tests/unit/ -x -q && cd ../..
cd vendor/squall && uv run --no-sync python -m pytest tests/unit/ -x -q && cd ../..
```

Expected: both pass, exactly as in Steps 4-5.

- [ ] **Step 11: Re-run the doctor script to confirm the drift is now resolved**

```bash
uv run --no-sync python scripts/check_red_dragon_pin.py
echo "exit code: $?"
```

Expected: prints the same SHA three times and `OK: all three RedDragon pins match.`, exit code 0.

- [ ] **Step 12: Update this repo's own `vendor/cicada` and `vendor/squall` submodule gitlinks to point at the just-created bump commits**

Steps 9-10 committed inside the *nested* checkouts; this repo's own submodule gitlinks (what
`vendor/cicada`/`vendor/squall` point to as a whole) must be updated to reference those new commits,
or a fresh clone of `red-dragon-forge` would check out the pre-bump state.

```bash
git add vendor/cicada vendor/squall
git commit -m "Point at cicada/squall commits with the aligned RedDragon pin"
```

---

### Task 3: `CoprocessorSpec` — the generic composition seam

**Files:**
- Create: `red_dragon_forge/coprocessor.py`
- Test: `tests/integration/test_coprocessor.py`

**Interfaces:**
- Produces:
  - `CoprocessorSpec` (frozen dataclass): `name: str`, `make_strategy: Callable[[], RedDragonExtensionLoweringStrategy]`,
    `source_prepass: Callable[[str], str] = <identity>`, `owns_execution: bool = False`,
    `cics_text_parser: Any | None = None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_coprocessor.py
from __future__ import annotations

from red_dragon_forge.coprocessor import CoprocessorSpec


def test_default_source_prepass_is_identity():
    spec = CoprocessorSpec(name="noop", make_strategy=lambda: object())
    assert spec.source_prepass("       IDENTIFICATION DIVISION.") == (
        "       IDENTIFICATION DIVISION."
    )


def test_defaults_are_non_execution_owning_with_no_cics_text_parser():
    spec = CoprocessorSpec(name="noop", make_strategy=lambda: object())
    assert spec.owns_execution is False
    assert spec.cics_text_parser is None


def test_spec_is_frozen():
    import dataclasses

    spec = CoprocessorSpec(name="noop", make_strategy=lambda: object())
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "renamed"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --no-sync python -m pytest tests/integration/test_coprocessor.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'red_dragon_forge.coprocessor'`. (Also
add `import pytest` to the top of the test file before running — omitted above only in the
walkthrough, not in the file you write.)

- [ ] **Step 3: Write `red_dragon_forge/coprocessor.py`**

```python
"""CoprocessorSpec — the generic seam for composing RedDragon COBOL coprocessor
lowering strategies (CICS, EXEC SQL, and others later).

This module and compile.py must never import cics.* or squall.* — only the
adapters/ package is allowed to know which coprocessors exist by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from interpreter.cobol.red_dragon_extension_strategy import (
    RedDragonExtensionLoweringStrategy,
)


def _identity(source: str) -> str:
    return source


@dataclass(frozen=True)
class CoprocessorSpec:
    """One coprocessor's contribution to a composed COBOL program.

    ``make_strategy`` is a zero-arg closure built by a per-coprocessor adapter
    (e.g. ``adapters.cics.build_cics_spec``), already bound to whatever runtime
    state that coprocessor needs. ``source_prepass`` runs at the source-text
    layer, before ProLeap parses the program.

    A coprocessor whose strategy construction depends on state its own prepass
    computes (e.g. Squall's dclgen field metadata) closes over a private
    mutable one-element list shared between ``source_prepass`` and
    ``make_strategy`` — the same holder-cell idiom Cicada's own
    CicsLoweringStrategy already uses for ``context_holder``/``result_holder``.
    ``compile_program`` guarantees every spec's ``source_prepass`` runs before
    ANY spec's ``make_strategy`` is called, so that holder is always populated
    in time.

    ``owns_execution`` marks the (at most one) coprocessor that imposes
    execution semantics on the compiled program (CICS's dispatcher/SUSPEND) —
    see ``run_program`` in ``run.py``.

    ``cics_text_parser`` threads RedDragon's ``compile_cobol(cics_text_parser=...)``
    argument through without this module knowing what a "CICS text parser" is;
    only the CICS adapter ever sets it.
    """

    name: str
    make_strategy: Callable[[], RedDragonExtensionLoweringStrategy]
    source_prepass: Callable[[str], str] = _identity
    owns_execution: bool = False
    cics_text_parser: Any | None = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run --no-sync python -m pytest tests/integration/test_coprocessor.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add red_dragon_forge/coprocessor.py tests/integration/test_coprocessor.py
git commit -m "Add CoprocessorSpec — generic coprocessor composition seam"
```

---

### Task 4: `compile_program()` — generic compile-time composition

**Files:**
- Create: `red_dragon_forge/compile.py`
- Test: `tests/integration/test_compile_program.py`

**Interfaces:**
- Consumes: `CoprocessorSpec` (Task 3).
- Produces: `compile_program(source: bytes, parser: Any, specs: Sequence[CoprocessorSpec], *, program_source_dir: Path | None = None, extra_subprogram_sources: dict[str, bytes] | None = None) -> tuple[Any, LinkedProgram]`.

This task proves the generic composition mechanism (prepass ordering, strategy list assembly,
`cics_text_parser` selection) using **two fake specs** — no real CICS or SQL strategy is needed to
prove `compile_program` itself is correct; that keeps this test fast and isolates what's actually
being tested (the composition logic, not Cicada's or Squall's lowering).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_compile_program.py
from __future__ import annotations

import os

import pytest

from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner

from red_dragon_forge.compile import compile_program
from red_dragon_forge.coprocessor import CoprocessorSpec


@pytest.fixture
def bridge_jar() -> str:
    return os.environ["PROLEAP_BRIDGE_JAR"]


_TRIVIAL_PROGRAM = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRIVIAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FIELD PIC X(10).
       PROCEDURE DIVISION.
           MOVE 'HELLO' TO WS-FIELD.
           STOP RUN.
"""


def test_every_specs_prepass_runs_before_any_make_strategy(bridge_jar):
    call_order = []

    def prepass_a(source: str) -> str:
        call_order.append("prepass_a")
        return source

    def prepass_b(source: str) -> str:
        call_order.append("prepass_b")
        return source

    def make_strategy_a():
        call_order.append("make_strategy_a")
        return _FakeStrategy()

    def make_strategy_b():
        call_order.append("make_strategy_b")
        return _FakeStrategy()

    specs = [
        CoprocessorSpec(name="a", make_strategy=make_strategy_a, source_prepass=prepass_a),
        CoprocessorSpec(name="b", make_strategy=make_strategy_b, source_prepass=prepass_b),
    ]
    parser = ProLeapCobolParser(RealSubprocessRunner(), bridge_jar)

    compile_program(_TRIVIAL_PROGRAM, parser, specs)

    assert call_order == [
        "prepass_a",
        "prepass_b",
        "make_strategy_a",
        "make_strategy_b",
    ]


def test_at_most_one_cics_text_parser_allowed(bridge_jar):
    def sentinel_parser(text: str):
        return text

    specs = [
        CoprocessorSpec(
            name="a", make_strategy=_FakeStrategy, cics_text_parser=sentinel_parser
        ),
        CoprocessorSpec(
            name="b", make_strategy=_FakeStrategy, cics_text_parser=sentinel_parser
        ),
    ]
    parser = ProLeapCobolParser(RealSubprocessRunner(), bridge_jar)

    with pytest.raises(AssertionError):
        compile_program(_TRIVIAL_PROGRAM, parser, specs)


class _FakeStrategy:
    """A minimal RedDragonExtensionLoweringStrategy that handles nothing —
    proves compile_program's plumbing without needing real CICS/SQL lowering."""

    def handles(self, stmt) -> bool:
        return False

    def preprocess_program_dict(self, data: dict) -> dict:
        return data

    def on_procedure_entry(self, ctx, materialised) -> None:
        pass

    def lower(self, ctx, stmt, materialised) -> None:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --no-sync python -m pytest tests/integration/test_compile_program.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'red_dragon_forge.compile'`.

- [ ] **Step 3: Write `red_dragon_forge/compile.py`**

```python
"""compile_program() — generic compile-time composition of CoprocessorSpecs.

This module must never import cics.* or squall.* — only the adapters/ package
is allowed to know which coprocessors exist by name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from interpreter.project.cobol_compile import compile_cobol
from interpreter.project.types import LinkedProgram

from red_dragon_forge.coprocessor import CoprocessorSpec


def compile_program(
    source: bytes,
    parser: Any,
    specs: Sequence[CoprocessorSpec],
    *,
    program_source_dir: Path | None = None,
    extra_subprogram_sources: dict[str, bytes] | None = None,
) -> tuple[Any, LinkedProgram]:
    """Compile ``source`` with every spec's prepass and strategy composed.

    Every spec's ``source_prepass`` runs, in order, before ANY spec's
    ``make_strategy`` is called — a spec whose strategy construction depends on
    state its own prepass populates (e.g. Squall's dclgen field metadata)
    relies on this ordering (see CoprocessorSpec's docstring).

    At most one spec may supply a ``cics_text_parser`` — RedDragon's
    ``compile_cobol`` accepts only one.
    """
    text = source.decode("utf-8")
    for spec in specs:
        text = spec.source_prepass(text)

    strategies = [spec.make_strategy() for spec in specs]

    cics_text_parsers = [s.cics_text_parser for s in specs if s.cics_text_parser is not None]
    assert len(cics_text_parsers) <= 1, (
        f"at most one CoprocessorSpec may supply a cics_text_parser, got "
        f"{len(cics_text_parsers)}"
    )

    return compile_cobol(
        text.encode("utf-8"),
        parser=parser,
        extension_strategies=strategies,
        cics_text_parser=cics_text_parsers[0] if cics_text_parsers else None,
        program_source_dir=program_source_dir,
        extra_subprogram_sources=extra_subprogram_sources,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run --no-sync python -m pytest tests/integration/test_compile_program.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add red_dragon_forge/compile.py tests/integration/test_compile_program.py
git commit -m "Add compile_program — generic multi-coprocessor compilation"
```

---

### Task 5: CICS adapter (`build_cics_spec`)

**Files:**
- Create: `red_dragon_forge/adapters/__init__.py` (empty)
- Create: `red_dragon_forge/adapters/cics.py`
- Create: `tests/integration/conftest.py`
- Test: `tests/integration/test_cics_adapter.py`

**Interfaces:**
- Consumes: `CoprocessorSpec` (Task 3), `compile_program` (Task 4).
- Produces: `build_cics_spec(context_holder: list, result_holder: list | None = None, program_cache: dict | None = None, vsam_engine: Any = None, screen_queue: Any = None, input_queue: Any = None, **kwargs: Any) -> CoprocessorSpec`.

- [ ] **Step 1: Write `tests/integration/conftest.py`**

```python
"""Shared fixtures for red-dragon-forge integration tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def bridge_jar() -> str:
    """The ProLeap bridge JAR path — required, no default, no skip."""
    return os.environ["PROLEAP_BRIDGE_JAR"]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/test_cics_adapter.py
from __future__ import annotations

import queue

from cics.dispatcher import run_cics
from cics.types import CicsContext, DispatchKind

from red_dragon_forge.adapters.cics import build_cics_spec
from red_dragon_forge.compile import compile_program

_CICS_ONLY_PROGRAM = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSONLY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FIELD PIC X(10).
       PROCEDURE DIVISION.
           MOVE 'HELLO' TO WS-FIELD.
           EXEC CICS RETURN
           END-EXEC.
"""


def test_cics_only_spec_compiles_and_returns(bridge_jar):
    from interpreter.cobol.cobol_parser import ProLeapCobolParser
    from interpreter.cobol.subprocess_runner import RealSubprocessRunner

    context_holder = [None]
    result_holder = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    parser = ProLeapCobolParser(RealSubprocessRunner(), bridge_jar)

    _frontend, linked = compile_program(_CICS_ONLY_PROGRAM, parser, [spec])

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    result = run_cics(
        linked,
        CicsContext(transid="CICO", commarea=b"", eibaid="\x7d"),
        screen_q,
        input_q,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=10_000,
    )

    assert result.kind == DispatchKind.RETURN
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run --no-sync python -m pytest tests/integration/test_cics_adapter.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'red_dragon_forge.adapters'`.

- [ ] **Step 4: Write `red_dragon_forge/adapters/__init__.py`** (empty file)

- [ ] **Step 5: Write `red_dragon_forge/adapters/cics.py`**

```python
"""Adapter wrapping Cicada's CicsLoweringStrategy as a CoprocessorSpec.

This is the ONLY module in red_dragon_forge (besides run.py) allowed to import
cics.*.
"""

from __future__ import annotations

from typing import Any

from cics.preprocessor import apply_cics_prepass
from cics.strategy import CicsLoweringStrategy
from cics.cics_visitor import parse_exec_cics_text

from red_dragon_forge.coprocessor import CoprocessorSpec


def build_cics_spec(
    context_holder: list,
    result_holder: list | None = None,
    program_cache: dict | None = None,
    vsam_engine: Any = None,
    screen_queue: Any = None,
    input_queue: Any = None,
    **kwargs: Any,
) -> CoprocessorSpec:
    """Build the EXEC CICS CoprocessorSpec.

    ``context_holder``/``result_holder``/``program_cache`` are the same
    mutable cells CicsLoweringStrategy already uses internally (Cicada's own
    convention) — pass the SAME dicts/lists across multiple compile_program()
    calls for programs that LINK to each other within one region.
    """

    def _make_strategy() -> CicsLoweringStrategy:
        return CicsLoweringStrategy(
            context_holder=context_holder,
            result_holder=result_holder,
            program_cache=program_cache,
            vsam_engine=vsam_engine,
            screen_queue=screen_queue,
            input_queue=input_queue,
            **kwargs,
        )

    return CoprocessorSpec(
        name="cics",
        make_strategy=_make_strategy,
        source_prepass=apply_cics_prepass,
        owns_execution=True,
        cics_text_parser=parse_exec_cics_text,
    )
```

- [ ] **Step 6: Run test to verify it passes**

```bash
uv run --no-sync python -m pytest tests/integration/test_cics_adapter.py -v
```

Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add red_dragon_forge/adapters/__init__.py red_dragon_forge/adapters/cics.py \
        tests/integration/conftest.py tests/integration/test_cics_adapter.py
git commit -m "Add CICS adapter — build_cics_spec"
```

---

### Task 6: SQL adapter (`build_sql_spec`)

**Files:**
- Create: `red_dragon_forge/adapters/sql.py`
- Create: `tests/integration/forge_cobol_helpers.py`
- Test: `tests/integration/test_sql_adapter.py`

**Interfaces:**
- Consumes: `CoprocessorSpec` (Task 3), `compile_program` (Task 4).
- Produces: `build_sql_spec(connections: Mapping[str, SqlBackend], copybook_dirs: Sequence[Path] = ()) -> CoprocessorSpec`.
- Produces: `forge_cobol_helpers.squall_copybooks_dir() -> Path`, `forge_cobol_helpers.make_parser(bridge_jar: str, copybook_dirs: list[Path]) -> ProLeapCobolParser`.

Squall's own `SqlLoweringStrategy` needs `field_meta`, which only exists **after** `apply_sql_prepass`
runs — this is the case `CoprocessorSpec`'s holder-cell pattern exists for.

- [ ] **Step 1: Write `tests/integration/forge_cobol_helpers.py`**

```python
"""Shared parser-construction helpers for red-dragon-forge integration tests.

Squall's own copybooks directory (SQLCA.cpy, DCLGEN records) must always be on
the parser's copybook search path whenever a SQL spec is in play — mirrors
Squall's own make_cobol_parser helper (tests/integration/squall_cobol_helpers.py).
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner


def squall_copybooks_dir() -> Path:
    """Return the filesystem path to squall's bundled copybooks (SQLCA, DCLGEN records)."""
    ref = importlib.resources.files("squall.copybooks")
    return Path(str(ref))


def make_parser(bridge_jar: str, copybook_dirs: list[Path] | None = None) -> ProLeapCobolParser:
    """Build a ProLeapCobolParser, always including squall's copybooks dir."""
    dirs: list[Path] = [squall_copybooks_dir()]
    if copybook_dirs:
        dirs.extend(copybook_dirs)
    return ProLeapCobolParser(RealSubprocessRunner(), bridge_jar, copybook_dirs=dirs)
```

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/test_sql_adapter.py
from __future__ import annotations

import sqlite3

from interpreter.project.entry_point import EntryPoint
from interpreter.run import run_linked
from interpreter.address import Address
from interpreter.var_name import VarName
from interpreter.vm.vm import VMState, StackFrame
from interpreter.func_name import FuncName
from interpreter import constants as rd_constants

from squall.backends.sqlite import SqliteBackend
from squall.binding import _decode_field

from red_dragon_forge.adapters.sql import build_sql_spec
from red_dragon_forge.compile import compile_program
from tests.integration.forge_cobol_helpers import make_parser

_SQL_ONLY_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLONLY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID  PIC 9(4) VALUE 11.
       01 WS-BAL PIC 9(9).
       01 SQLCODE PIC S9(9).
       PROCEDURE DIVISION.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           EXEC SQL
               SELECT ACCT_BAL
               INTO :WS-BAL
               FROM ACCOUNT
               WHERE ACCT_ID = :WS-ID
           END-EXEC.
           STOP RUN.
"""


def _read_ws_field(vm: VMState, field_name: str):
    ws_var = VarName("__ws_region")
    region = None
    for frame in reversed(vm.call_stack):
        local_vars = getattr(frame, "local_vars", {})
        if ws_var in local_vars:
            addr = Address(str(local_vars[ws_var].value))
            region = vm.region_get(addr)
            break
    assert region is not None, "__ws_region not found in call stack"
    layout = vm.data_layout
    f = layout[field_name]
    off, length = f["offset"], f["length"]
    raw = bytes(region[off : off + length])
    return _decode_field(raw, f)


def test_sql_only_spec_selects_into(bridge_jar):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)")
    conn.execute("INSERT INTO ACCOUNT VALUES (11, 500)")
    conn.commit()
    backend = SqliteBackend(conn)

    spec = build_sql_spec(connections={"SAMPLE": backend})
    parser = make_parser(bridge_jar)

    _frontend, linked = compile_program(_SQL_ONLY_PROGRAM.encode("utf-8"), parser, [spec])

    entry_point = EntryPoint.top_level()
    if linked.func_symbol_table:
        proc_label = next(
            (
                label
                for label in linked.func_symbol_table
                if not str(label).startswith("func_init_params_")
            ),
            None,
        )
        if proc_label is not None:
            entry_point = EntryPoint.function(lambda ref, _l=proc_label: ref.label == _l)

    initial_vm = VMState()
    initial_vm.data_layout = linked.data_layout
    initial_vm.call_stack.append(StackFrame(function_name=FuncName(rd_constants.MAIN_FRAME_NAME)))

    vm = run_linked(linked, entry_point=entry_point, max_steps=2000, initial_vm=initial_vm)

    assert _read_ws_field(vm, "WS-BAL") == 500
    assert _read_ws_field(vm, "SQLCODE") == 0
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run --no-sync python -m pytest tests/integration/test_sql_adapter.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'red_dragon_forge.adapters.sql'`.

- [ ] **Step 4: Write `red_dragon_forge/adapters/sql.py`**

```python
"""Adapter wrapping Squall's SqlLoweringStrategy as a CoprocessorSpec.

This is the ONLY module in red_dragon_forge allowed to import squall.*.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from squall.backend import SqlBackend
from squall.parser.sql_model import FieldMeta
from squall.preprocess import apply_sql_prepass
from squall.strategy import SqlLoweringStrategy

from red_dragon_forge.coprocessor import CoprocessorSpec


def build_sql_spec(
    connections: Mapping[str, SqlBackend],
    copybook_dirs: Sequence[Path] = (),
) -> CoprocessorSpec:
    """Build the EXEC SQL CoprocessorSpec.

    ``source_prepass`` expands EXEC SQL INCLUDE -> COPY and gathers the dclgen
    field metadata into a private holder as a side effect; ``make_strategy``
    reads that holder when called. ``compile_program`` always runs every
    spec's prepass before any spec's make_strategy, so the holder is populated
    in time (see CoprocessorSpec's docstring for why this ordering is required
    for SQL specifically, unlike CICS).
    """
    field_meta_holder: list[Mapping[str, FieldMeta]] = [{}]

    def _prepass(source: str) -> str:
        result = apply_sql_prepass(source, copybook_dirs)
        field_meta_holder[0] = result.field_meta
        return result.source

    def _make_strategy() -> SqlLoweringStrategy:
        return SqlLoweringStrategy(connections, field_meta_holder[0])

    return CoprocessorSpec(
        name="sql",
        make_strategy=_make_strategy,
        source_prepass=_prepass,
        owns_execution=False,
    )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run --no-sync python -m pytest tests/integration/test_sql_adapter.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add red_dragon_forge/adapters/sql.py tests/integration/forge_cobol_helpers.py \
        tests/integration/test_sql_adapter.py
git commit -m "Add SQL adapter — build_sql_spec"
```

---

### Task 7: `run_program()` — execution-owner dispatch

**Files:**
- Create: `red_dragon_forge/run.py`
- Test: `tests/integration/test_run_program.py`

**Interfaces:**
- Consumes: `CoprocessorSpec` (Task 3).
- Produces: `run_program(linked: LinkedProgram, specs: Sequence[CoprocessorSpec], *args: Any, **kwargs: Any) -> Any`.

Per the design doc, this module is **intentionally CICS-aware** — it does not invent a generic
runner protocol, since CICS is the only documented execution-owning coprocessor today.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_run_program.py
from __future__ import annotations

import pytest

from red_dragon_forge.coprocessor import CoprocessorSpec
from red_dragon_forge.run import run_program


def test_raises_when_no_spec_owns_execution():
    specs = [CoprocessorSpec(name="sql", make_strategy=lambda: object(), owns_execution=False)]
    with pytest.raises(NotImplementedError):
        run_program(linked=object(), specs=specs)


def test_raises_when_more_than_one_spec_owns_execution():
    specs = [
        CoprocessorSpec(name="a", make_strategy=lambda: object(), owns_execution=True),
        CoprocessorSpec(name="b", make_strategy=lambda: object(), owns_execution=True),
    ]
    with pytest.raises(AssertionError):
        run_program(linked=object(), specs=specs)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --no-sync python -m pytest tests/integration/test_run_program.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'red_dragon_forge.run'`.

- [ ] **Step 3: Write `red_dragon_forge/run.py`**

```python
"""run_program() — dispatches execution to whichever CoprocessorSpec owns it.

Intentionally CICS-aware (imports cics.dispatcher directly): the design's own
documented asymmetry is that CICS owns execution (dispatcher, SUSPEND/resume)
and SQL is purely synchronous, so there is no generic "runner protocol" to
build here — only a real second execution-owning coprocessor would justify one.
"""

from __future__ import annotations

from typing import Any, Sequence

from cics.dispatcher import run_cics

from red_dragon_forge.coprocessor import CoprocessorSpec


def run_program(
    linked: Any,
    specs: Sequence[CoprocessorSpec],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run a compiled program via whichever spec owns execution.

    Exactly one spec's ``owns_execution`` must be True today (the CICS
    adapter) — ``run_cics(linked, *args, **kwargs)`` is called directly.

    With no execution-owning spec (e.g. a SQL-only composition), there is
    nothing for this repo to add over Squall's own standalone synchronous run
    — raises NotImplementedError rather than guessing at a fallback shape,
    since no such case is in scope for this plan (see the design doc's
    deferred section).
    """
    owners = [s for s in specs if s.owns_execution]
    assert len(owners) <= 1, (
        f"at most one CoprocessorSpec may own execution, got {len(owners)}"
    )
    if not owners:
        raise NotImplementedError(
            "no execution-owning CoprocessorSpec present — a SQL-only "
            "composition should use squall's own standalone run, not "
            "red_dragon_forge.run_program (see design doc §2.3)"
        )
    return run_cics(linked, *args, **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run --no-sync python -m pytest tests/integration/test_run_program.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add red_dragon_forge/run.py tests/integration/test_run_program.py
git commit -m "Add run_program — CICS-aware execution dispatch"
```

---

### Task 8: Combined CICS + SQL synthetic proof

**Files:**
- Test: `tests/integration/test_cics_sql_composition.py`

**Interfaces:**
- Consumes: `build_cics_spec` (Task 5), `build_sql_spec` (Task 6), `compile_program` (Task 4),
  `run_program` (Task 7).

This is the critical de-risking step before tackling the much heavier real Bank-of-Z corpus: one
small hand-written program combining an `EXEC SQL SELECT INTO` with `EXEC CICS ASSIGN` and a bare
`EXEC CICS RETURN`, compiled with **both** specs together, run via `run_program`, asserting both
effects landed.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_cics_sql_composition.py
from __future__ import annotations

import queue
import sqlite3

from cics.types import CicsContext, DispatchKind

from red_dragon_forge.adapters.cics import build_cics_spec
from red_dragon_forge.adapters.sql import build_sql_spec
from red_dragon_forge.compile import compile_program
from red_dragon_forge.run import run_program
from squall.backends.sqlite import SqliteBackend
from tests.integration.forge_cobol_helpers import make_parser

_COMBINED_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMBINED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID       PIC 9(4) VALUE 42.
       01 WS-BAL      PIC 9(9).
       01 SQLCODE     PIC S9(9).
       01 WS-APPLID   PIC X(8).
       PROCEDURE DIVISION.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           EXEC SQL
               SELECT ACCT_BAL
               INTO :WS-BAL
               FROM ACCOUNT
               WHERE ACCT_ID = :WS-ID
           END-EXEC.
           EXEC CICS ASSIGN APPLID(WS-APPLID)
           END-EXEC.
           EXEC CICS RETURN
           END-EXEC.
"""


def test_cics_and_sql_compose_in_one_program(bridge_jar):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)")
    conn.execute("INSERT INTO ACCOUNT VALUES (42, 777)")
    conn.commit()
    backend = SqliteBackend(conn)

    context_holder = [None]
    result_holder = [None]
    cics_spec = build_cics_spec(
        context_holder=context_holder, result_holder=result_holder, applid="FORGEAPP"
    )
    sql_spec = build_sql_spec(connections={"SAMPLE": backend})
    parser = make_parser(bridge_jar)

    _frontend, linked = compile_program(
        _COMBINED_PROGRAM.encode("utf-8"), parser, [cics_spec, sql_spec]
    )

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    result = run_program(
        linked,
        [cics_spec, sql_spec],
        CicsContext(transid="COMB", commarea=b"", eibaid="\x7d"),
        screen_q,
        input_q,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=10_000,
    )

    assert result.kind == DispatchKind.RETURN
```

Note: this test only asserts the `DispatchResult`, not the SQL-fetched `WS-BAL` value directly —
per Task-6's research finding, `run_cics` discards the final VM state for a bare `RETURN`, so
`WS-BAL` isn't independently observable here without the same LINK/`RETURN TRANSID` machinery Task
10 uses. Proving `result.kind == DispatchKind.RETURN` (rather than an ABEND from a lowering/runtime
error) is precisely what de-risks composition itself: if either strategy's lowering or a
`CallFunction`/builtin dispatch conflict existed between CICS and SQL sharing one `EmitContext`,
this program would ABEND or raise during compile/run, not return cleanly.

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --no-sync python -m pytest tests/integration/test_cics_sql_composition.py -v
```

Expected: FAIL — either an import error (if any prior task's module is missing) or a real
composition bug if one exists. Investigate any failure here directly; this test has no reason to
fail if Tasks 3-7 are correct, so a failure here means Tasks 3-7 have a real bug (most likely: the
CICS and SQL strategies' `on_procedure_entry`/lowering interacting in the shared `EmitContext` in a
way neither's isolated test caught).

- [ ] **Step 3: (only if Step 2 failed for a real reason) fix the bug, re-run until green**

There is no "minimal implementation" step here — Tasks 3-7 already provide the implementation. If
this test fails, it means those tasks have a latent defect; fix it in the relevant task's file, do
not add special-casing in the test.

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run --no-sync python -m pytest tests/integration/test_cics_sql_composition.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_cics_sql_composition.py
git commit -m "Prove CICS + SQL compose in one program (synthetic, before Bank-of-Z)"
```

---

### Task 9: Bank-of-Z submodule + Db2 test environment

**Files:**
- Create: `tests/integration/db2_env.sh`
- Modify: `.gitmodules` (via `git submodule add`)

**Interfaces:**
- Produces: `vendor/bank-of-z/src/base/cics/{cobol,bms,copy}` on disk; `SQUALL_DB2_DSN` env var
  sourcing for the test in Task 10 (reusing Squall's own MOJO database — no new container).

- [ ] **Step 1: Add the Bank-of-Z submodule**

```bash
git submodule add https://github.com/IBM/Bank-of-Z.git vendor/bank-of-z
```

- [ ] **Step 2: Verify `INQCUST` is present**

```bash
test -f vendor/bank-of-z/src/base/cics/cobol/INQCUST.cbl && echo "found"
test -f vendor/bank-of-z/src/base/cics/copy/INQCUSTZ.cpy && echo "found"
test -f vendor/bank-of-z/src/base/cics/copy/CUSTDB2.cpy && echo "found"
```

Expected: three `found` lines.

- [ ] **Step 3: Write `tests/integration/db2_env.sh`**

Reuses Squall's own MOJO Db2 container (`squall-db2`, per `squall/docker-compose.yml`) rather than
standing up a second one — this repo's tests run against the SAME container Squall's own Db2
integration tests use, started via `docker compose -f vendor/squall/docker-compose.yml up -d`.

```sh
# Source this (from the repo root) to export SQUALL_DB2_DSN for red-dragon-forge's
# own Db2 integration test. Reuses squall's own MOJO container config; does not
# stand up a second one. POSIX-sh safe; intentionally does not set -e/-u.
[ -f vendor/squall/.env ] && . vendor/squall/.env

: "${DB2_PASSWORD:?DB2_PASSWORD not set (copy vendor/squall/.env.example to vendor/squall/.env)}"
: "${PROLEAP_BRIDGE_JAR:?PROLEAP_BRIDGE_JAR not set}"
_forge_host="${DB2_HOST:-localhost}"
_forge_port="${DB2_PORT:-50000}"

export SQUALL_DB2_DSN="DATABASE=MOJO;HOSTNAME=${_forge_host};PORT=${_forge_port};PROTOCOL=TCPIP;UID=db2inst1;PWD=${DB2_PASSWORD}"
```

- [ ] **Step 4: Start the container and verify connectivity**

```bash
docker compose -f vendor/squall/docker-compose.yml up -d
# Wait for the healthcheck (see squall/docker-compose.yml's healthcheck block —
# can take several minutes on first init).
docker compose -f vendor/squall/docker-compose.yml ps
. tests/integration/db2_env.sh
uv run --no-sync python -c "
import ibm_db, os
conn = ibm_db.connect(os.environ['SQUALL_DB2_DSN'], '', '')
print('connected')
ibm_db.close(conn)
"
```

Expected: prints `connected`.

- [ ] **Step 5: Commit**

```bash
git add .gitmodules vendor/bank-of-z tests/integration/db2_env.sh
git commit -m "Add Bank-of-Z submodule + Db2 test env (reuses squall's MOJO container)"
```

---

### Task 10: `INQCUST` end-to-end proof — real Bank-of-Z program, real Db2

**Files:**
- Test: `tests/integration/test_inqcust_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 3-9.

`INQCUST` is invoked via `EXEC CICS LINK` in real CICS (never as a top-level transaction entry), so
this test follows the exact precedent found during planning
(`cicada/tests/integration/cics/test_link.py::test_link_commarea_written_back`): a small synthetic
`WRAPPER` driver program `LINK`s to the real `INQCUST`, then does
`RETURN TRANSID(...) COMMAREA(...)` so the test can observe the result via
`DispatchResult.commarea` — `run_cics` on a bare top-level `RETURN` does not expose the mutated
COMMAREA (confirmed during planning: `run_cics` discards the final VM state in that case).

`INQCUST`'s COMMAREA layout (`vendor/bank-of-z/src/base/cics/copy/INQCUSTZ.cpy`), relevant fields
in order:

```
03 INQCUST-EYE        PIC X(4).
03 INQCUST-SCODE      PIC X(6).
03 INQCUST-CUSTNO     PIC 9(10).
03 INQCUST-NAME.
   05 INQCUST-TITLE       PIC X(10).
   05 INQCUST-FIRST-NAME  PIC X(50).
   05 INQCUST-LAST-NAME   PIC X(50).
... (dob/phone/address/status/dates/credit-score fields, not needed for this test's assertions)
03 INQCUST-INQ-SUCCESS   PIC X.      -- 'Y' found, 'N' not found
03 INQCUST-INQ-FAIL-CD   PIC X.
03 INQCUST-PCB-POINTER   PIC X(4).   -- IMS-only, unused on the Db2 path
```

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_inqcust_e2e.py
from __future__ import annotations

import os
import queue
from pathlib import Path

import ibm_db

from cics.dispatcher import run_cics
from cics.types import CicsContext, DispatchKind

from squall.backends.db2 import Db2Backend

from red_dragon_forge.adapters.cics import build_cics_spec
from red_dragon_forge.adapters.sql import build_sql_spec
from red_dragon_forge.compile import compile_program
from tests.integration.forge_cobol_helpers import make_parser

_BANK_OF_Z_COPY = Path(__file__).parents[2] / "vendor" / "bank-of-z" / "src" / "base" / "cics" / "copy"
_BANK_OF_Z_COBOL = Path(__file__).parents[2] / "vendor" / "bank-of-z" / "src" / "base" / "cics" / "cobol"

# INQCUSTZ.cpy field widths (see this task's docstring / INQCUSTZ.cpy).
_EYE_LEN = 4
_SCODE_LEN = 6
_CUSTNO_LEN = 10

_SORT_CODE = "123456"
_FOUND_CUSTNO = "0000000001"
_NOT_FOUND_CUSTNO = "0000009999"

# WRAPPER links to INQCUST with a seeded commarea, then hands the (possibly
# mutated) commarea back via RETURN TRANSID so the test can observe it —
# mirrors cicada's own test_link.py::test_link_commarea_written_back, the only
# proven commarea-readback precedent for a bare-RETURN callee (see Task 10's
# header note).
_WRAPPER_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WRAPPER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CA.
           COPY INQCUSTZ.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS LINK PROGRAM('INQCUST')
                     COMMAREA(WS-CA)
                     LENGTH(LENGTH OF WS-CA)
           END-EXEC.
           EXEC CICS RETURN TRANSID('WRAP') COMMAREA(WS-CA)
           END-EXEC.
"""


def _seed_commarea(sort_code: str, custno: str) -> bytes:
    eye = b" " * _EYE_LEN
    scode = sort_code.encode("ascii").ljust(_SCODE_LEN)[:_SCODE_LEN]
    cust = custno.encode("ascii").rjust(_CUSTNO_LEN, b"0")[:_CUSTNO_LEN]
    # The remainder of the commarea (output fields) starts zeroed; INQCUST
    # overwrites what it needs and the WRAPPER hands the whole buffer back.
    return eye + scode + cust


def _inq_success(commarea: bytes) -> str:
    # INQCUST-INQ-SUCCESS sits right after the (fixed, known) input fields plus
    # every output field ahead of it in INQCUSTZ.cpy; simplest robust read here
    # is via the compiled data_layout rather than a hand-counted offset — see
    # Step 2 below, which asserts this the same way the rest of this test does.
    raise NotImplementedError("see read_commarea_field in this test file")


def _make_engine_none():
    return None


def test_inqcust_found_and_not_found(bridge_jar):
    dsn = os.environ["SQUALL_DB2_DSN"]
    conn = ibm_db.connect(dsn, "", "")
    try:
        backend = Db2Backend(conn)

        context_holder = [None]
        result_holder = [None]
        program_cache: dict = {}

        parser = make_parser(bridge_jar, copybook_dirs=[_BANK_OF_Z_COPY])

        # Compile INQCUST (CICS + SQL) and register it in the shared program_cache
        # so WRAPPER's EXEC CICS LINK can find it by name at run time.
        inqcust_cics_spec = build_cics_spec(
            context_holder=context_holder,
            result_holder=result_holder,
            program_cache=program_cache,
        )
        inqcust_sql_spec = build_sql_spec(
            connections={"SAMPLE": backend}, copybook_dirs=[_BANK_OF_Z_COPY]
        )
        inqcust_source = (_BANK_OF_Z_COBOL / "INQCUST.cbl").read_bytes()
        _frontend, inqcust_linked = compile_program(
            inqcust_source, parser, [inqcust_cics_spec, inqcust_sql_spec]
        )
        program_cache["INQCUST"] = inqcust_linked

        # Compile WRAPPER (CICS only — it never touches SQL) sharing the SAME
        # context_holder/result_holder/program_cache.
        wrapper_spec = build_cics_spec(
            context_holder=context_holder,
            result_holder=result_holder,
            program_cache=program_cache,
        )
        wrapper_parser = make_parser(bridge_jar, copybook_dirs=[_BANK_OF_Z_COPY])
        _frontend, wrapper_linked = compile_program(
            _WRAPPER_PROGRAM.encode("utf-8"), wrapper_parser, [wrapper_spec]
        )

        screen_q: queue.Queue = queue.Queue()
        input_q: queue.Queue = queue.Queue()

        # --- Found case ---
        found_commarea = _seed_commarea(_SORT_CODE, _FOUND_CUSTNO)
        found_result = run_cics(
            wrapper_linked,
            CicsContext(transid="WRAP", commarea=found_commarea, eibaid="\x7d"),
            screen_q,
            input_q,
            context_holder=context_holder,
            result_holder=result_holder,
            max_steps=50_000,
        )
        assert found_result.kind == DispatchKind.RETURN_TRANSID
        assert found_result.commarea is not None
        # INQCUST-INQ-SUCCESS is a single byte; its offset in the returned
        # commarea is the layout's own concern, so decode it via the compiled
        # data_layout rather than a hand-counted literal offset.
        success_field = _frontend.data_layout["INQCUST-INQ-SUCCESS"]
        off, length = success_field["offset"], success_field["length"]
        assert found_commarea[off : off + length] != b"Y", (
            "sanity: seeded commarea must NOT already contain 'Y' before the run"
        )
        assert found_result.commarea[off : off + length] == b"Y", (
            f"expected INQCUST-INQ-SUCCESS='Y' for a known customer, "
            f"got {found_result.commarea[off:off+length]!r}"
        )

        # --- Not-found case ---
        not_found_commarea = _seed_commarea(_SORT_CODE, _NOT_FOUND_CUSTNO)
        not_found_result = run_cics(
            wrapper_linked,
            CicsContext(transid="WRAP", commarea=not_found_commarea, eibaid="\x7d"),
            screen_q,
            input_q,
            context_holder=context_holder,
            result_holder=result_holder,
            max_steps=50_000,
        )
        assert not_found_result.kind == DispatchKind.RETURN_TRANSID
        assert not_found_result.commarea is not None
        assert not_found_result.commarea[off : off + length] == b"N", (
            f"expected INQCUST-INQ-SUCCESS='N' for an unknown customer, "
            f"got {not_found_result.commarea[off:off+length]!r}"
        )
    finally:
        ibm_db.close(conn)
```

Note the `_frontend.data_layout["INQCUST-INQ-SUCCESS"]` lookup: this assumes `CobolFrontend`
exposes a `data_layout` attribute keyed by field name with `offset`/`length` — this is the same
shape Task 6's `_read_ws_field` helper already relies on for `linked.data_layout`. **If
`_frontend.data_layout` is empty or doesn't carry this field** (COMMAREA/LINKAGE SECTION fields may
be laid out differently from WORKING-STORAGE fields in RedDragon's data_layout), fall back to
`inqcust_linked.data_layout` (the `LinkedProgram`'s own copy, used successfully in Task 6) instead
of `_frontend.data_layout` — try `inqcust_linked.data_layout` first when writing this step for real,
since Task 6 already proved that attribute works; `_frontend.data_layout` is included above only
because `INQCUST-INQ-SUCCESS` is a LINKAGE SECTION field owned by DFHCOMMAREA, which may or may not
be the same layout table as WORKING-STORAGE. **Verify which one actually contains the field by
printing both and inspecting** before hard-coding the assertion — this is exactly the kind of thing
that must be confirmed empirically against the real compiled program, not assumed from a
specification.

- [ ] **Step 2: Run test to verify it fails, and resolve the data_layout lookup**

```bash
. tests/integration/db2_env.sh
uv run --no-sync python -m pytest tests/integration/test_inqcust_e2e.py -v -s
```

Expected first run: FAIL, likely at the `_frontend.data_layout["INQCUST-INQ-SUCCESS"]` lookup or
earlier at compilation (INQCUST is a large, real program — expect to iterate on `copybook_dirs`
until every `COPY` resolves: `SORTCODE`, `CUSTOMER`, `ABNDINFO`, `INQCUSTZ`, and — via Squall's own
`apply_sql_prepass` INCLUDE-rewriting — `CUSTDB2` and `SQLCA`). Add print statements for
`inqcust_linked.data_layout.keys()` and `_frontend.data_layout.keys()` to find which one actually
contains `INQCUST-INQ-SUCCESS`, fix the test to use the correct one, and remove the now-dead
`_inq_success`/`_make_engine_none` helper stubs from Step 1 (they were left in only as a reminder
that a hand-counted-offset approach was rejected in favor of `data_layout` — delete them once the
real lookup works).

- [ ] **Step 3: Seed the MOJO `CUSTOMER` table with the found-case row**

Before the test can pass, MOJO needs a `CUSTOMER` row matching `_SORT_CODE`/`_FOUND_CUSTNO`. Add a
`setup`/`teardown` (or a `try`/`finally` insert-then-delete, matching
`test_db2_connect_e2e.py`'s `_setup_routed`/`_drop` pattern) at the top of the test:

```python
def _seed_customer(conn) -> None:
    ibm_db.exec_immediate(
        conn,
        "INSERT INTO CUSTOMER (CUSTOMER_SORTCODE, CUSTOMER_NUMBER, CUSTOMER_FIRST_NAME) "
        f"VALUES ('{_SORT_CODE}', '{_FOUND_CUSTNO}', 'TESTFIRST')",
    )
    ibm_db.commit(conn)


def _unseed_customer(conn) -> None:
    ibm_db.exec_immediate(
        conn,
        f"DELETE FROM CUSTOMER WHERE CUSTOMER_SORTCODE = '{_SORT_CODE}' "
        f"AND CUSTOMER_NUMBER = '{_FOUND_CUSTNO}'",
    )
    ibm_db.commit(conn)
```

Call `_seed_customer(conn)` right after `conn = ibm_db.connect(...)` and wrap the body in
`try: ... finally: _unseed_customer(conn); ibm_db.close(conn)`. **If MOJO's `CUSTOMER` table
doesn't exist yet or has a different column set**, inspect it first —
`ibm_db.exec_immediate(conn, "SELECT * FROM CUSTOMER FETCH FIRST 1 ROW ONLY")` — and adjust the
INSERT to match the real schema; do not assume the column names above are exactly right without
checking, since MOJO's actual DDL wasn't inspected during planning (Squall's own tests use `ACCOUNT`
and `ROUTED`, not `CUSTOMER` — this may be the first thing to create `CUSTOMER` in MOJO at all).

- [ ] **Step 4: Run test to verify it passes**

```bash
. tests/integration/db2_env.sh
uv run --no-sync python -m pytest tests/integration/test_inqcust_e2e.py -v -s
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_inqcust_e2e.py
git commit -m "Prove real Bank-of-Z INQCUST runs end-to-end via CICS+SQL composition"
```

---

## Self-Review Notes

- **Spec coverage**: Task 1-2 cover the design's §2.1's submodule/dependency layout and the
  version-mismatch check the design doc flagged as a deferred "doctor-style check" — surfaced here
  concretely since research found the mismatch is real, not hypothetical. Tasks 3-4 cover
  `CoprocessorSpec`/`compile_program` (§2.1/§2.2, invariants #1-#2). Tasks 5-6 cover the adapters
  (§2.1). Task 7 covers §2.3 execution ownership (invariant #3). Task 8 is the de-risking step the
  design doc implied but didn't name explicitly — added because Task 10's real corpus is too heavy
  a first proof of composition itself. Tasks 9-10 cover §3 (Bank-of-Z, INQCUST, real Db2).
- **Placeholder scan**: Task 10 contains explicit "verify empirically, don't assume" instructions
  (the `data_layout` lookup, the `CUSTOMER` schema) rather than a blind literal — this is
  intentional, not a placeholder: real MOJO schema/RedDragon internals were not directly
  inspectable during planning, and pretending certainty here would be worse than flagging exactly
  what to verify and how. Every other task's code is complete and concrete.
- **Type/name consistency**: `CoprocessorSpec`, `compile_program`, `run_program`, `build_cics_spec`,
  `build_sql_spec` are named identically everywhere they're referenced across tasks; `context_holder`/
  `result_holder`/`program_cache` threading matches Cicada's own existing parameter names exactly
  (not renamed).

---

Plan complete and saved to `docs/superpowers/plans/2026-07-04-cics-sql-composition.md`.

# Monorepo Migration (Cicada/Squall/Jackal → red-dragon-forge) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge Cicada, Squall, and Jackal into `red-dragon-forge` as one monorepo — one shared `vendor/red-dragon` submodule, one `uv` workspace/lockfile, one root `Makefile`/`.pre-commit-config.yaml`/`.importlinter`, one Beads DB — while each package stays independently buildable/testable exactly as it is today.

**Architecture:** `git subtree` merges each package in as a top-level sibling directory, preserving full commit history. Each package keeps its own `Makefile`, `pyproject.toml`, `CLAUDE.md`, and test suite unchanged in behavior; only cross-cutting concerns (RedDragon vendoring, dependency locking, pre-commit hooks, import-linter, Beads, CI) get consolidated at the new root.

**Tech Stack:** `git subtree`, `uv` workspaces, GNU Make, `pre-commit`, `import-linter`, `bd` (Beads), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-05-monorepo-migration-design.md` — read it before starting; this plan implements it section by section.

## Global Constraints

- RedDragon stays a separate, un-merged repo (spec's Scope section) — never touch `~/code/red-dragon`, only `vendor/red-dragon` submodule pointers.
- No change to any package's own internal code, tests, or runtime behavior (spec's Non-goals) — every task's verification is "still passes exactly as many tests as before," never "behavior changed."
- One shared `vendor/red-dragon` submodule at the monorepo root; the copies formerly nested inside `cicada/vendor/`, `squall/vendor/`, `jackal/vendor/` are removed, not repointed.
- Package-specific submodules that are NOT RedDragon (`third-party/che-che4z-lsp-for-hlasm-fork`, `third-party/carddemo`, `testbed/db2-samples`) are **not** deduplicated by this migration — they stay nested exactly where each package already has them, just one path segment deeper (e.g. `cicada/third-party/carddemo`).
- One shared `.importlinter` independence contract over `{cics, squall, jackal}` (source packages only, not `tests/`) — see spec's Architectural contracts section for the exact contract text. Each package's own existing contracts (`cics`'s `vsam-bms-independence`/`builtins-no-dispatcher`, `squall`'s `parser-backends-independence`/`vocabulary-leaves`, `jackal`'s `layered-architecture`/`jcl-idcams-independence`/`model-results-are-leaves`) must all keep passing unchanged.
- Static/lint/format pre-commit hooks (`terminology-guard`, `terminology-commit-msg`, `black`, `python-fp-lint`, `pyright`, `import-linter`) stay global (`always_run: true`); test-suite hooks stay per-package and gain `files:` scoping, with `always_run: true` **removed** (not left alongside `files:`) per the spec's critical mechanism note.
- Beads issue IDs are namespace-prefixed per repo (`cicada-*`, `squall-*`, `jackal-*`, `forge-*`) and collision-free; forge's Beads DB already exists (`bd init`, this session) with one issue (`forge-don`) already tracked — import adds to it, does not replace it.
- Old standalone `cicada`/`squall`/`jackal` GitHub repos are left as-is (spec's Old standalone repos / Non-goals) — no archiving, no deletion, no GitHub-side action.

---

### Task 1: Record pre-migration baselines

Every later task's verification compares against these numbers. No code changes in this task.

**Files:**
- Create: `/tmp/monorepo-migration-baseline.md` (scratch notes, not committed — record in your task report instead)

**Interfaces:**
- Produces: the baseline test counts and RedDragon SHA every later task's verification step references.

- [ ] **Step 1: Record each package's current standalone test count**

Run each in its own repo directory:
```bash
cd ~/code/cicada && make test 2>&1 | tail -5
cd ~/code/squall && make test 2>&1 | tail -5
cd ~/code/jackal && make test 2>&1 | tail -5
cd ~/code/red-dragon-forge && make test 2>&1 | tail -5
```
Expected (per the spec's Testing section, confirm these still hold): Cicada 348 passed, Squall 271 passed/1 skipped, Jackal 127 passed, red-dragon-forge 7 passed. Record the actual numbers you see — if they differ from the spec, use your actual numbers as the baseline for later tasks, not the spec's.

- [ ] **Step 2: Record the current RedDragon submodule SHA in each of the four repos**

```bash
for repo in cicada squall jackal red-dragon-forge; do
  echo "$repo: $(git -C ~/code/$repo/vendor/red-dragon rev-parse HEAD)"
done
```
Expected: all four print the **same** SHA (confirmed earlier this session — Cicada and Jackal were both bumped to the same current RedDragon commit; forge and Squall vendor it too). If any differ, note the mismatch in your report — later tasks assume they already match, since re-aligning pins is out of scope for this migration.

- [ ] **Step 3: Record forge's current Beads issue**

```bash
cd ~/code/red-dragon-forge && bd list --status=open
```
Expected: exactly one issue, `forge-don`.

No commit for this task — it's pure fact-gathering. Report the four test counts, the RedDragon SHA, and confirmation of `forge-don` in your task report.

---

### Task 2: Merge Cicada in via `git subtree`

**Files:**
- Create: `cicada/` (entire subtree — full Cicada repo content, preserving history)
- Modify: `.gitmodules` (add Cicada's non-RedDragon submodules under `cicada/`, at their shifted paths)
- Modify: `cicada/Makefile:1` (repoint `PROLEAP_BRIDGE_JAR` one level up)
- Delete: `cicada/vendor/red-dragon` (nested RedDragon submodule — superseded by the shared root one)

**Interfaces:**
- Consumes: nothing from earlier tasks (first subtree merge).
- Produces: `cicada/` directory tree at the monorepo root, `cicada/Makefile`'s `PROLEAP_BRIDGE_JAR` pointing at `$(CURDIR)/../vendor/red-dragon/...`, ready for Task 3 (Squall) to follow the identical pattern.

- [ ] **Step 1: Add Cicada as a git remote and subtree-merge it**

From `~/code/red-dragon-forge`:
```bash
git remote add cicada-origin git@github.com:avishek-sen-gupta/cicada.git
git fetch cicada-origin
git subtree add --prefix=cicada cicada-origin main
```
Expected: a new merge commit; `cicada/` now exists at the repo root with Cicada's full file tree, including `cicada/vendor/red-dragon` (a submodule gitlink) and `cicada/.gitmodules`.

- [ ] **Step 2: Verify Cicada's history came across**

```bash
git log --follow --oneline -- cicada/cics/bootstrap.py | head -5
```
Expected: shows Cicada's own pre-merge commit history for that file (not just the single subtree-merge commit), confirming `--follow` can walk across the old repo boundary.

- [ ] **Step 3: Merge Cicada's non-RedDragon submodules into the root `.gitmodules`, at shifted paths**

Read `cicada/.gitmodules` (now at that path post-merge) and add entries to the **root** `.gitmodules` for everything except `vendor/red-dragon`:
```
[submodule "cicada/third-party/che-che4z-lsp-for-hlasm-fork"]
	path = cicada/third-party/che-che4z-lsp-for-hlasm-fork
	url = git@github.com:avishek-sen-gupta/che-che4z-lsp-for-hlasm.git
	branch = krakatoa-1.22.1
[submodule "cicada/third-party/carddemo"]
	path = cicada/third-party/carddemo
	url = git@github.com:avishek-sen-gupta/aws-mainframe-modernization-carddemo.git
	branch = main
```
Append these two blocks to the root `.gitmodules` (creating it if it doesn't exist yet — check first, since forge already has one with `vendor/red-dragon`/`vendor/cicada`/`vendor/squall`/`vendor/bank-of-z` entries; this task only adds the two new blocks above, it does not touch the existing four).

- [ ] **Step 4: Deregister Cicada's own nested RedDragon submodule**

```bash
git submodule deinit -f cicada/vendor/red-dragon
git rm -f cicada/vendor/red-dragon
rm -rf .git/modules/cicada/vendor/red-dragon
```
Remove the now-stale `[submodule "cicada/vendor/red-dragon"]` block that the merge brought into `cicada/.gitmodules` — delete `cicada/.gitmodules` entirely (its remaining two entries were already re-added to the root `.gitmodules` in Step 3; a per-package `.gitmodules` nested inside a monorepo subdirectory is not consulted by git and would only confuse a future reader).
```bash
git rm -f cicada/.gitmodules
```

- [ ] **Step 5: Register the two carried-over submodules for real**

```bash
git submodule update --init --recursive cicada/third-party/che-che4z-lsp-for-hlasm-fork
git submodule update --init --recursive cicada/third-party/carddemo
```
Expected: both directories populate with content (they were empty gitlink placeholders after the subtree merge, same as `vendor/` showed empty in a plain `ls` before `submodule update --init`).

- [ ] **Step 6: Repoint Cicada's Makefile at the shared root RedDragon**

In `cicada/Makefile`, change:
```makefile
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
```
to:
```makefile
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
```
and the two `$(PROLEAP_BRIDGE_JAR):`/`jar-force:` recipe bodies from:
```makefile
	cd vendor/red-dragon/proleap-bridge && ./build.sh
```
to:
```makefile
	cd ../vendor/red-dragon/proleap-bridge && ./build.sh
```
(three occurrences total: the `$(PROLEAP_BRIDGE_JAR):` rule, `jar-force:`, and the `setup:`/`build:` chain that calls `./build.sh` — check `cicada/build.sh` too, since it also hardcodes `vendor/red-dragon/proleap-bridge`; update it the same way.)

- [ ] **Step 7: Verify Cicada still builds and tests standalone from its new location**

```bash
cd ~/code/red-dragon-forge/cicada && make test 2>&1 | tail -5
```
Expected: same pass count recorded in Task 1 Step 1 for Cicada (348 passed, or your actual baseline).

- [ ] **Step 8: Commit**

```bash
cd ~/code/red-dragon-forge
git add .gitmodules cicada/Makefile cicada/build.sh
git rm -f cicada/.gitmodules 2>/dev/null || true
git commit -m "chore: merge Cicada into the monorepo via git subtree, dedupe vendor/red-dragon"
git remote remove cicada-origin
```

---

### Task 3: Merge Squall in via `git subtree`

Identical pattern to Task 2, applied to Squall. Squall's only non-RedDragon submodule is `testbed/db2-samples`.

**Files:**
- Create: `squall/` (entire subtree)
- Modify: `.gitmodules` (add `squall/testbed/db2-samples`)
- Modify: `squall/Makefile:1` (repoint `PROLEAP_BRIDGE_JAR`)
- Delete: `squall/vendor/red-dragon`, `squall/.gitmodules`

**Interfaces:**
- Consumes: the root `.gitmodules` shape established in Task 2 (append, don't replace).
- Produces: `squall/` at the monorepo root, ready for Task 4 (Jackal).

- [ ] **Step 1: Subtree-merge Squall**

```bash
git remote add squall-origin git@github.com:avishek-sen-gupta/squall.git
git fetch squall-origin
git subtree add --prefix=squall squall-origin main
```

- [ ] **Step 2: Verify history**

```bash
git log --follow --oneline -- squall/squall/strategy.py | head -5
```
Expected: Squall's pre-merge commit history for that file.

- [ ] **Step 3: Add Squall's non-RedDragon submodule to the root `.gitmodules`**

Append:
```
[submodule "squall/testbed/db2-samples"]
	path = squall/testbed/db2-samples
	url = https://github.com/IBM/db2-samples.git
```

- [ ] **Step 4: Deregister Squall's nested RedDragon submodule and its own `.gitmodules`**

```bash
git submodule deinit -f squall/vendor/red-dragon
git rm -f squall/vendor/red-dragon
rm -rf .git/modules/squall/vendor/red-dragon
git rm -f squall/.gitmodules
```

- [ ] **Step 5: Register the carried-over submodule**

```bash
git submodule update --init --recursive squall/testbed/db2-samples
```

- [ ] **Step 6: Repoint Squall's Makefile**

In `squall/Makefile`, change:
```makefile
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
```
to:
```makefile
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
```
and both `cd vendor/red-dragon/proleap-bridge && ./build.sh` recipe lines to `cd ../vendor/red-dragon/proleap-bridge && ./build.sh`. Update `squall/build.sh` the same way if it hardcodes the same path.

- [ ] **Step 7: Verify Squall still builds and tests standalone**

```bash
cd ~/code/red-dragon-forge/squall && make test 2>&1 | tail -5
```
Expected: same pass/skip count as Task 1's Squall baseline (271 passed / 1 skipped, or your actual baseline). Requires `SQUALL_DB2_DSN`/`make db2-up` per Squall's existing test contract — unchanged by this migration.

- [ ] **Step 8: Commit**

```bash
git add .gitmodules squall/Makefile squall/build.sh
git rm -f squall/.gitmodules 2>/dev/null || true
git commit -m "chore: merge Squall into the monorepo via git subtree, dedupe vendor/red-dragon"
git remote remove squall-origin
```

---

### Task 4: Merge Jackal in via `git subtree`

Jackal was never vendored inside red-dragon-forge before (no `vendor/jackal` submodule existed) — this is its first appearance in this repo at all. Same pattern as Tasks 2-3. Jackal's only non-RedDragon submodule is `third-party/carddemo`.

**Files:**
- Create: `jackal/` (entire subtree)
- Modify: `.gitmodules` (add `jackal/third-party/carddemo`)
- Modify: `jackal/Makefile:1` (repoint `PROLEAP_BRIDGE_JAR`; note `JCL_BRIDGE_JAR` stays package-local, unaffected)
- Delete: `jackal/vendor/red-dragon`, `jackal/.gitmodules`

**Interfaces:**
- Consumes: the root `.gitmodules` shape from Tasks 2-3.
- Produces: `jackal/` at the monorepo root, ready for Task 5 (vendor cleanup) which needs all three packages merged first.

- [ ] **Step 1: Subtree-merge Jackal**

```bash
git remote add jackal-origin git@github.com:avishek-sen-gupta/jackal.git
git fetch jackal-origin
git subtree add --prefix=jackal jackal-origin main
```

- [ ] **Step 2: Verify history**

```bash
git log --follow --oneline -- jackal/jackal/cli.py | head -5
```

- [ ] **Step 3: Add Jackal's non-RedDragon submodule to the root `.gitmodules`**

Append:
```
[submodule "jackal/third-party/carddemo"]
	path = jackal/third-party/carddemo
	url = git@github.com:avishek-sen-gupta/aws-mainframe-modernization-carddemo.git
	branch = main
```

- [ ] **Step 4: Deregister Jackal's nested RedDragon submodule and its own `.gitmodules`**

```bash
git submodule deinit -f jackal/vendor/red-dragon
git rm -f jackal/vendor/red-dragon
rm -rf .git/modules/jackal/vendor/red-dragon
git rm -f jackal/.gitmodules
```

- [ ] **Step 5: Register the carried-over submodule**

```bash
git submodule update --init --recursive jackal/third-party/carddemo
```

- [ ] **Step 6: Repoint Jackal's Makefile**

In `jackal/Makefile`, change:
```makefile
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
```
to:
```makefile
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
```
Leave `JCL_BRIDGE_JAR ?= $(CURDIR)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar` untouched — the JCL bridge is Jackal-specific, never shared, per the Global Constraints. Update both `cd vendor/red-dragon/proleap-bridge && ./build.sh` recipe lines (`$(PROLEAP_BRIDGE_JAR):` and `jar-force:`) to `cd ../vendor/red-dragon/proleap-bridge && ./build.sh`. Update `jackal/build.sh` the same way if it hardcodes the path.

- [ ] **Step 7: Verify Jackal still builds and tests standalone**

```bash
cd ~/code/red-dragon-forge/jackal && make test 2>&1 | tail -5
```
Expected: same pass count as Task 1's Jackal baseline (127 passed, or your actual baseline).

- [ ] **Step 8: Commit**

```bash
cd ~/code/red-dragon-forge
git add .gitmodules jackal/Makefile jackal/build.sh
git rm -f jackal/.gitmodules 2>/dev/null || true
git commit -m "chore: merge Jackal into the monorepo via git subtree, dedupe vendor/red-dragon"
git remote remove jackal-origin
```

---

### Task 5: Remove the now-superseded `vendor/cicada`/`vendor/squall` submodules

Before this migration, forge vendored Cicada and Squall as submodules (`vendor/cicada`, `vendor/squall`) to consume their code as dependencies. Now that `cicada/` and `squall/` exist as real subdirectories (Tasks 2-3), those old submodule copies are dead weight.

**Files:**
- Delete: `vendor/cicada/`, `vendor/squall/` (submodule gitlinks)
- Modify: `.gitmodules` (remove their two entries; `vendor/red-dragon` and `vendor/bank-of-z` entries stay)
- Modify: `scripts/check_red_dragon_pin.py` — this script exists specifically to detect pin drift between forge's `vendor/red-dragon` and the nested copies inside `vendor/cicada`/`vendor/squall`; once those nested copies no longer exist (this task) and there's only one `vendor/red-dragon` in the whole monorepo (Tasks 2-4), the script's entire purpose is gone.

**Interfaces:**
- Consumes: `cicada/` and `squall/` directories from Tasks 2-3 (must exist before deleting their old submodule stand-ins, or forge's own code/tests would have nothing to import from during the gap).
- Produces: a `vendor/` containing only `red-dragon` and `bank-of-z`, matching the spec's Repository structure diagram.

- [ ] **Step 1: Deregister and delete the two old submodules**

```bash
git submodule deinit -f vendor/cicada
git submodule deinit -f vendor/squall
git rm -f vendor/cicada
git rm -f vendor/squall
rm -rf .git/modules/vendor/cicada .git/modules/vendor/squall
```

- [ ] **Step 2: Remove their entries from `.gitmodules`**

Delete these two blocks from the root `.gitmodules` (leave `vendor/red-dragon` and `vendor/bank-of-z` untouched):
```
[submodule "vendor/cicada"]
	path = vendor/cicada
	url = git@github.com:avishek-sen-gupta/cicada.git
[submodule "vendor/squall"]
	path = vendor/squall
	url = git@github.com:avishek-sen-gupta/squall.git
```

- [ ] **Step 3: Delete the now-purposeless pin-check script**

```bash
git rm -f scripts/check_red_dragon_pin.py
```
Verify nothing else references it:
```bash
grep -rn "check_red_dragon_pin" --include="*.yml" --include="*.md" --include="Makefile" . 2>/dev/null | grep -v vendor/
```
Expected: no matches (if any turn up — e.g. a CI workflow step or a `make` target — remove that reference too in this same step).

- [ ] **Step 4: Verify `vendor/` now contains exactly two entries**

```bash
ls vendor/
```
Expected: `bank-of-z`, `red-dragon` — nothing else.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove superseded vendor/cicada and vendor/squall submodules, dead pin-check script"
```

---

### Task 6: uv workspace — one root `pyproject.toml`, one lockfile

**Files:**
- Modify: `pyproject.toml` (root) — add `[tool.uv.workspace]`
- Modify: `Makefile` (root) — remove the `--no-deps` editable-install workaround from the `python:` target
- Delete: (implicitly, via `uv sync`) the four independently-resolved lockfiles collapse into one root `uv.lock`

**Interfaces:**
- Consumes: `cicada/pyproject.toml`, `squall/pyproject.toml`, `jackal/pyproject.toml` unchanged (each remains a workspace member — not rewritten), all now present from Tasks 2-4.
- Produces: one root `uv.lock` that Task 7 (root Makefile) and Task 10 (CI) both rely on for `uv sync` to install every package's dependencies in one pass.

- [ ] **Step 1: Add the workspace declaration to the root `pyproject.toml`**

Add this table (anywhere after `[project]`):
```toml
[tool.uv.workspace]
members = ["cicada", "squall", "jackal"]
```
Only `cicada/`, `squall/`, `jackal/` are true workspace *members* — each is a subdirectory with its own `pyproject.toml`. Forge's own package (`red_dragon_forge/`, declared via `[tool.hatch.build.targets.wheel] packages = ["red_dragon_forge"]` already in this same root `pyproject.toml`) is the workspace *root* project itself, not a member — `uv` includes the root automatically and it must not also be listed in `members`.

- [ ] **Step 2: Remove the `--no-deps` workaround from the root Makefile**

In the root `Makefile`, change:
```makefile
python:
	uv sync
	uv pip install -e vendor/cicada --no-deps
	uv pip install -e vendor/squall --no-deps
```
to:
```makefile
python:
	uv sync
```

- [ ] **Step 3: Re-resolve the lockfile**

```bash
cd ~/code/red-dragon-forge && rm -f uv.lock && uv sync
```
Expected: `uv` resolves all four packages' dependencies (including the shared `red-dragon` path dependency) into one `uv.lock` with no conflict errors.

- [ ] **Step 4: Verify each package's own dependency-consuming code still imports cleanly**

```bash
uv run --no-sync python -c "import cics; import squall; import jackal; import red_dragon_forge"
```
Expected: no `ImportError`.

- [ ] **Step 5: Verify forge's own test suite still passes with the new workspace resolution**

```bash
cd ~/code/red-dragon-forge && make test 2>&1 | tail -5
```
Expected: same 7-passed baseline from Task 1 (forge's own suite doesn't depend on the subtree-merged packages' own test suites, only on `build_cics_spec`/`build_sql_spec` imports from `cics`/`squall`).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml Makefile uv.lock
git commit -m "feat: consolidate four separate lockfiles into one uv workspace"
```

---

### Task 7: Root Makefile — shared JAR built once, `test-all` aggregate target

**Files:**
- Modify: `Makefile` (root) — add `jar`/`test-all` targets per the spec's Build tooling section

**Interfaces:**
- Consumes: `cicada/Makefile`, `squall/Makefile`, `jackal/Makefile` each already repointed at `../vendor/red-dragon/...` (Tasks 2-4).
- Produces: `make test-all` from the repo root, the single command CI (Task 10) and any future "build everything" workflow invokes.

- [ ] **Step 1: Add `jar` and `test-all` targets to the root Makefile**

The root `Makefile` already has a `jar`/`jar-force`/`$(PROLEAP_BRIDGE_JAR):` set (from forge's pre-existing `make setup`/`make jar`). Add a new `test-all` target that depends on `jar` first, then invokes each package's own `test`:
```makefile
.PHONY: test-all

test-all: jar
	$(MAKE) -C cicada test
	$(MAKE) -C squall test
	$(MAKE) -C jackal test
	$(MAKE) test
```
Place it near the existing `test:` target. Update the `help:` target's echoed list to mention `test-all`:
```makefile
	@echo "make test-all  - jar once, then run every package's full suite (cicada, squall, jackal, forge)"
```

- [ ] **Step 2: Verify the JAR builds exactly once across a full `test-all` run**

```bash
rm -f vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
make test-all 2>&1 | grep -c "BUILD SUCCESS"
```
Expected: `1` — the Maven build log's "BUILD SUCCESS" line appears exactly once, in the root `jar` prerequisite step, not again inside any of the four `$(MAKE) -C ... test` sub-invocations (each package's own `$(PROLEAP_BRIDGE_JAR):` rule sees the file already exists and is fresh, per GNU Make's file-target-freshness check, and skips its recipe).

- [ ] **Step 3: Verify the full aggregate run passes**

```bash
make test-all 2>&1 | tail -20
```
Expected: all four packages' pass counts match Task 1's baselines, run back-to-back in one invocation.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "feat: add root test-all target, shared JAR built once via Make target-freshness"
```

---

### Task 8: Root `.importlinter` — shared independence contract, existing per-package contracts preserved

**Files:**
- Create: `.importlinter` (root)
- Delete: `cicada/.importlinter`, `squall/.importlinter`, `jackal/.importlinter` (superseded — one root config now covers all of it)

**Interfaces:**
- Consumes: nothing structural from earlier tasks (any point after Tasks 2-4 works; placed here to follow the spec's own section order).
- Produces: the root `.importlinter` Task 9 (pre-commit) points its shared `import-linter` hook at.

- [ ] **Step 1: Write the root `.importlinter`, merging all three packages' existing contracts plus the new cross-package one**

```ini
[importlinter]
root_packages =
    cics
    squall
    jackal

[importlinter:contract:cicada-squall-jackal-independence]
name = Cicada, Squall, and Jackal must not import each other
type = independence
modules =
    cics
    squall
    jackal

[importlinter:contract:vsam-bms-independence]
name = VSAM and BMS subsystems must not import each other
type = independence
modules =
    cics.vsam
    cics.bms

[importlinter:contract:builtins-no-dispatcher]
name = Builtins must not import the dispatcher (avoid circular dependency)
type = forbidden
source_modules =
    cics.builtins
forbidden_modules =
    cics.dispatcher

[importlinter:contract:parser-backends-independence]
name = SQL parser and DB backends must not import each other
type = independence
modules =
    squall.parser
    squall.backends

[importlinter:contract:vocabulary-leaves]
name = backend and parser.sql_model are leaf vocabulary — must not import other squall modules
type = forbidden
source_modules =
    squall.backend
    squall.parser.sql_model
forbidden_modules =
    squall.binding
    squall.builtins
    squall.backends
    squall.parser.parse
    squall.preprocess
    squall.strategy
    squall.dclgen

[importlinter:contract:layered-architecture]
name = Layers: orchestration -> execution -> catalog -> model
type = layers
layers =
    jackal.cli
    jackal.runner
    jackal.cobol_step : jackal.utilities
    jackal.catalog
    jackal.model

[importlinter:contract:jcl-idcams-independence]
name = JCL parser and IDCAMS subsystems must not import each other
type = independence
modules =
    jackal.jcl
    jackal.idcams

[importlinter:contract:model-results-are-leaves]
name = model and results are leaf vocabulary — must not import other jackal modules
type = forbidden
source_modules =
    jackal.model
    jackal.results
forbidden_modules =
    jackal.catalog
    jackal.runner
    jackal.cli
    jackal.cobol_step
    jackal.utilities
    jackal.idcams
    jackal.jcl
```

- [ ] **Step 2: Delete the three now-superseded per-package configs**

```bash
git rm -f cicada/.importlinter squall/.importlinter jackal/.importlinter
```

- [ ] **Step 3: Run the consolidated contract set from the root**

```bash
cd ~/code/red-dragon-forge && uv run --no-sync lint-imports
```
Expected: all 9 contracts (1 new cross-package + 8 pre-existing) pass with no violations. If the new `cicada-squall-jackal-independence` contract fails, it means one of the three packages already imports another directly (a real coupling this migration is meant to surface, not paper over) — stop and report it rather than weakening the contract.

- [ ] **Step 4: Verify each package's own `make lint` (which calls the same `lint-imports`) still works standalone**

```bash
cd ~/code/red-dragon-forge/cicada && make lint
cd ~/code/red-dragon-forge/squall && make lint
cd ~/code/red-dragon-forge/jackal && make lint
```
Expected: `lint-imports` discovers the root `.importlinter` via its standard upward directory search from each package's own directory — since it's a config-file lookup identical to `pyproject.toml`/`pyrightconfig.json` discovery — and all three pass.

- [ ] **Step 5: Commit**

```bash
git add .importlinter
git commit -m "feat: consolidate four import-linter configs into one root .importlinter with a shared cicada/squall/jackal independence contract"
```

---

### Task 9: Consolidated `.pre-commit-config.yaml` and shared `precommit-scripts/`

**Files:**
- Create: `.pre-commit-config.yaml` (root)
- Create: `precommit-scripts/check-terminology`, `precommit-scripts/check-commit-msg`, `precommit-scripts/lib-terminology.sh`, `precommit-scripts/scan-history` (copied byte-identical from any of the three packages — confirmed identical via `diff` across all three)
- Create: `precommit-scripts/run-tests-squall` (renamed from Squall's own `precommit-scripts/run-tests`)
- Create: `pyrightconfig.json` (root) — replaces four separate per-package Pyright configs
- Delete: `cicada/.pre-commit-config.yaml`, `squall/.pre-commit-config.yaml`, `jackal/.pre-commit-config.yaml`, `cicada/precommit-scripts/`, `squall/precommit-scripts/`, `jackal/precommit-scripts/`

**Interfaces:**
- Consumes: the root `.importlinter` from Task 8 (the shared `import-linter` hook entry references it implicitly via `lint-imports`' own config discovery).
- Produces: the one pre-commit hook stack that governs every commit in the monorepo going forward.

- [ ] **Step 1: Copy the shared scripts to a root `precommit-scripts/`**

```bash
mkdir -p precommit-scripts
cp cicada/precommit-scripts/check-terminology precommit-scripts/
cp cicada/precommit-scripts/check-commit-msg precommit-scripts/
cp cicada/precommit-scripts/lib-terminology.sh precommit-scripts/
cp cicada/precommit-scripts/scan-history precommit-scripts/
chmod +x precommit-scripts/check-terminology precommit-scripts/check-commit-msg precommit-scripts/scan-history
cp squall/precommit-scripts/run-tests precommit-scripts/run-tests-squall
chmod +x precommit-scripts/run-tests-squall
```

- [ ] **Step 2: Delete the three packages' own copies**

```bash
git rm -rf cicada/precommit-scripts squall/precommit-scripts jackal/precommit-scripts
git rm -f cicada/.pre-commit-config.yaml squall/.pre-commit-config.yaml jackal/.pre-commit-config.yaml
```

- [ ] **Step 3: Create the root `pyrightconfig.json`, replacing the four separate `[tool.pyright]` blocks**

Cicada and Jackal each have a `[tool.pyright]` block in their own `pyproject.toml` (Jackal's: `include = ["jackal", "tests"]`, `exclude = ["vendor", "**/__pycache__"]`); Squall and forge have none today (relying on Pyright's defaults). Create one root config:
```json
{
  "include": ["cicada/cics", "cicada/bms_copybook_gen", "squall/squall", "jackal/jackal", "red_dragon_forge"],
  "exclude": ["**/vendor", "**/__pycache__", "**/third-party", "**/testbed"]
}
```
Remove the now-redundant `[tool.pyright]` block from `jackal/pyproject.toml` (the one existing per-package Pyright config that would otherwise conflict with the root one).

- [ ] **Step 4: Write the root `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: local
    hooks:
      - id: terminology-guard
        name: Terminology Guard
        entry: precommit-scripts/check-terminology
        language: script
        types: [text]

      - id: terminology-commit-msg
        name: Terminology Guard (commit message)
        entry: precommit-scripts/check-commit-msg
        language: script
        stages: [commit-msg]

      - id: black
        name: Black (auto-fix)
        entry: bash -c 'uv run --no-sync python -m black cicada/cics cicada/tests squall/squall squall/tests jackal/jackal jackal/tests red_dragon_forge tests && git add -u'
        language: system
        pass_filenames: false
        always_run: true

      - id: python-fp-lint
        name: Python FP lint (warnings only)
        entry: bash -c 'uv run --no-sync python -m python_fp_lint check cicada/cics/ squall/squall/ jackal/jackal/ || true'
        language: system
        pass_filenames: false
        always_run: true

      - id: pyright
        name: Pyright type check (warnings only)
        entry: bash -c 'uv run --no-sync pyright || true'
        language: system
        pass_filenames: false
        always_run: true

      - id: import-linter
        name: import-linter architectural contracts
        entry: bash -c 'uv run --no-sync lint-imports'
        language: system
        pass_filenames: false
        always_run: true

      - id: tests-cicada
        name: Cicada full test suite (incl. mandatory CardDemo e2e)
        entry: make -C cicada test PYTEST_ARGS="-x -q"
        language: system
        pass_filenames: false
        files: ^(cicada|vendor/red-dragon)/

      - id: tests-squall
        name: Squall unit test suite
        entry: precommit-scripts/run-tests-squall
        language: script
        pass_filenames: false
        files: ^(squall|vendor/red-dragon)/

      - id: tests-jackal
        name: Jackal full test suite (jackal + COBOL e2e via red-dragon)
        entry: bash -c 'PROLEAP_BRIDGE_JAR="$(git rev-parse --show-toplevel)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar" JCL_BRIDGE_JAR="$(git rev-parse --show-toplevel)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar" uv run --no-sync pytest jackal/tests -x -q'
        language: system
        pass_filenames: false
        files: ^(jackal|vendor/red-dragon)/

      - id: tests-forge
        name: red-dragon-forge test suite
        entry: make test PYTEST_ARGS="-x -q"
        language: system
        pass_filenames: false
        files: ^(red_dragon_forge|cicada|squall|vendor/)/
```
Note `precommit-scripts/run-tests-squall`'s own content (copied in Step 1) is `cd`-relative to Squall's own directory (`pytest tests/unit -x -q`) — since pre-commit hooks run from the repo root by default, update its first line from `cd`-implicit to explicit:
```bash
#!/bin/bash
[ -f squall/.env ] && source squall/.env
cd squall && uv run --no-sync python -m pytest tests/unit -x -q
```

- [ ] **Step 5: Reinstall the hooks and run them**

```bash
pre-commit install --hook-type pre-commit --hook-type commit-msg
pre-commit run --all-files
```
Expected: Terminology Guard, Black, FP lint, Pyright, and import-linter all run once globally; `tests-cicada`/`tests-squall`/`tests-jackal`/`tests-forge` all run too (since `--all-files` bypasses `files:` scoping and runs every hook), each showing its respective baseline pass count from Task 1.

- [ ] **Step 6: Verify `files:` scoping actually skips unaffected packages on a real commit**

```bash
echo "# test comment" >> squall/squall/strategy.py
git add squall/squall/strategy.py
git commit -m "test: verify pre-commit scoping" --dry-run -v 2>&1 | grep -E "tests-(cicada|squall|jackal|forge)"
git checkout -- squall/squall/strategy.py
```
Expected: only `tests-squall` (and possibly `tests-forge`, since its pattern also matches `squall/`) appear as having run; `tests-cicada` and `tests-jackal` are skipped (not listed, or listed as "Skipped" depending on your pre-commit version's dry-run output).

- [ ] **Step 7: Commit**

```bash
git add .pre-commit-config.yaml precommit-scripts pyrightconfig.json jackal/pyproject.toml
git commit -m "feat: consolidate four pre-commit configs into one root config with per-package test scoping"
```

---

### Task 10: Beads — import Cicada/Squall/Jackal issues into forge's existing DB

**Files:**
- Modify: forge's `.beads` DB (via `bd import`, not a file edit)
- Modify: `beads/issues.jsonl` (regenerated export, per this repo's tracked-snapshot convention)
- Delete: `cicada/.beads/`, `squall/.beads/`, `jackal/.beads/` (including each package's own `config.yaml` with its now-defunct `sync.remote`)

**Interfaces:**
- Consumes: `forge-don` already present in forge's DB (confirmed in Task 1 Step 3) — verify it's undisturbed after import.
- Produces: one Beads DB covering all four namespaces (`forge-*`, `cicada-*`, `squall-*`, `jackal-*`), the terminal state of the spec's Beads issue tracker section.

- [ ] **Step 1: Import each package's tracked export into forge's DB**

```bash
cd ~/code/red-dragon-forge
bd import cicada/beads/issues.jsonl
bd import squall/beads/issues.jsonl
bd import jackal/beads/issues.jsonl
```

- [ ] **Step 2: Verify counts and that `forge-don` survived untouched**

```bash
bd list --status=open | wc -l
bd show forge-don
```
Expected: total open+closed count roughly matches the sum of Task 1's per-repo `beads/issues.jsonl` line counts (69 + 15 + 38 + 1 = 123, or your actual baseline numbers) plus/minus any that were already closed; `forge-don`'s title and description are unchanged from when you created it.

- [ ] **Step 3: Delete each package's now-defunct `.beads/` directory**

```bash
git rm -rf cicada/.beads squall/.beads jackal/.beads
```
(These may already be gitignored per each package's own convention — if `git rm` reports nothing tracked, confirm with `ls cicada/.beads` that the directory is genuinely absent from the working tree too, and remove it directly with `rm -rf` if it's an untracked leftover.)

- [ ] **Step 4: Regenerate the tracked export**

```bash
bd export -o beads/issues.jsonl
```

- [ ] **Step 5: Commit**

```bash
git add beads/issues.jsonl
git add -A cicada squall jackal  # picks up the .beads deletions if they were tracked
git commit -m "chore: import Cicada/Squall/Jackal Beads issues into the shared monorepo DB"
```

---

### Task 11: `CLAUDE.md` consolidation and CI

**Files:**
- Modify: `CLAUDE.md` (root) — extract cross-cutting content (Beads integration block, monorepo-wide conventions) already present from `bd init`; leave each package's own nested `CLAUDE.md` untouched
- Create: `.github/workflows/ci.yml` (root) — forge had no CI before this migration; each merged package's own `.github/workflows/ci.yml` becomes redundant duplication once the root one runs all four jobs

**Interfaces:**
- Consumes: `make test-all`'s constituent per-package `make test` targets (Task 7) — CI's four jobs each invoke one package's own `make test`, matching local dev exactly.
- Produces: the final piece of the spec's design — nothing later depends on this task's output.

- [ ] **Step 1: Confirm the root `CLAUDE.md`'s existing Beads block needs no further edits**

`bd init` (run earlier this session) already wrote a Beads integration block into the root `CLAUDE.md`. Read it and confirm it matches the cross-cutting shape described in the spec's CLAUDE.md section (issue-tracking commands, session-close protocol) — no package-specific content should be here. If any package-specific content leaked in, remove it; the package's own nested `CLAUDE.md` is still authoritative for its own conventions.

- [ ] **Step 2: Write the root CI workflow**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  cicada:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: cicada
    steps:
      - uses: actions/checkout@v5
        with:
          submodules: recursive
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
      - uses: astral-sh/setup-uv@v6
      - uses: actions/setup-java@v5
        with:
          distribution: temurin
          java-version: "17"
          cache: maven
      - name: Install build dependencies for hlasm_export
        run: sudo apt-get install -y cmake ninja-build clang libc++-dev libc++abi-dev
      - name: Build all artefacts and run full suite
        run: make setup && make test

  squall:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: squall
    env:
      DB2_PASSWORD: ${{ secrets.DB2_PASSWORD }}
    steps:
      - uses: actions/checkout@v5
        with:
          submodules: recursive
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
      - uses: astral-sh/setup-uv@v6
      - uses: actions/setup-java@v5
        with:
          distribution: temurin
          java-version: "17"
      - name: Build the ProLeap bridge JAR
        run: make jar
      - name: Start DB2
        run: make db2-up
      - name: Run the full test suite
        run: make test

  jackal:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: jackal
    steps:
      - uses: actions/checkout@v5
        with:
          submodules: recursive
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"
      - uses: astral-sh/setup-uv@v6
      - uses: actions/setup-java@v5
        with:
          distribution: temurin
          java-version: "17"
      - name: Build the bridge JARs (ProLeap + JCL)
        run: make jar
      - name: Run the full test suite
        run: make test

  forge:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          submodules: recursive
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
      - uses: astral-sh/setup-uv@v6
      - uses: actions/setup-java@v5
        with:
          distribution: temurin
          java-version: "17"
      - name: Build the shared ProLeap bridge JAR
        run: make jar
      - name: Install Python dependencies
        run: make python
      - name: Run the full test suite
        run: make test
```
All four jobs run unconditionally on every push/PR (no `paths:` filters), per the spec's CI section — this is the deliberate contrast with the `files:`-scoped local pre-commit hooks from Task 9.

- [ ] **Step 3: Delete each package's own now-redundant CI workflow**

```bash
git rm -f cicada/.github/workflows/ci.yml squall/.github/workflows/ci.yml jackal/.github/workflows/ci.yml
```
(GitHub Actions only discovers workflows under the repo root's `.github/workflows/` — a nested `cicada/.github/workflows/ci.yml` inside a monorepo subdirectory is never triggered at all, so leaving it would be dead, misleading config, not a harmless duplicate.)

- [ ] **Step 4: Verify the workflow YAML is syntactically valid**

```bash
cd ~/code/red-dragon-forge
uv run --no-sync python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "valid YAML"
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git rm -rf cicada/.github squall/.github jackal/.github
git commit -m "feat: add root CI workflow covering all four packages, remove redundant per-package workflows"
```

---

### Task 12: Final whole-repo verification

**Files:** none modified — this task only runs verification and updates the spec's Testing section with final confirmed numbers if they've changed.

**Interfaces:**
- Consumes: every prior task's output.
- Produces: the signed-off, mergeable end state.

- [ ] **Step 1: Run the full aggregate suite one more time from a clean state**

```bash
cd ~/code/red-dragon-forge
git submodule update --init --recursive
make test-all 2>&1 | tail -30
```
Expected: Cicada, Squall, Jackal, and forge all report the same pass counts as Task 1's baselines.

- [ ] **Step 2: Run the full pre-commit hook stack once more**

```bash
pre-commit run --all-files
```
Expected: every hook passes (Terminology Guard ×2, Black, FP lint, Pyright, import-linter, all four `tests-*` hooks).

- [ ] **Step 3: Confirm no stray references to the old vendored-submodule layout remain**

```bash
grep -rln "vendor/cicada\|vendor/squall" --include="*.py" --include="*.md" --include="Makefile" --include="*.toml" . 2>/dev/null | grep -v "^\./vendor/\|^\./cicada/vendor\|^\./squall/vendor\|^\./jackal/vendor"
```
Expected: no matches (any hit is a leftover reference this task must fix before considering the migration complete).

- [ ] **Step 4: Confirm `bd doctor` reports a healthy DB**

```bash
bd doctor
```
Expected: no sync/hook problems reported.

- [ ] **Step 5: Final commit if Steps 1-4 required any fixes**

If everything passed clean with no fixes needed in this task, there's nothing to commit — report that in your task summary instead of an empty commit.

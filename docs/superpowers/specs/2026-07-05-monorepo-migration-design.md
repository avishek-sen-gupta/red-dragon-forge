# Monorepo Migration Design: Cicada/Squall/Jackal → red-dragon-forge

## Problem

Cicada, Squall, Jackal, and red-dragon-forge are four independently-cloned
repos, each vendoring RedDragon as its own separate git submodule copy. This
session repeatedly hit the resulting pain:

- **Pin drift.** Jackal's `vendor/red-dragon` was frozen at a commit from
  before the entire generic-dialect-parsers migration — silently stale for
  an era of RedDragon history, discovered only by manual investigation.
  Cicada's own pin also drifted stale mid-session and required a
  since-forgotten manual bump.
- **Duplicated spec-building logic.** `CoprocessorSpec`/`compile_program`
  and each coprocessor's `build_cics_spec`/`build_sql_spec` had to be kept
  in sync by hand across red-dragon-forge and its consumers before being
  hoisted into shared locations — exactly the kind of cross-repo
  duplication a monorepo's shared dependency graph prevents by construction.
- **Manual dependency-resolution workarounds.** red-dragon-forge's own
  `Makefile` needs `uv pip install -e vendor/cicada --no-deps` /
  `--no-deps vendor/squall` specifically to dodge a `uv` resolver conflict
  over the shared `red-dragon` path dependency — a symptom of four separate
  lockfiles all trying to agree on one dependency.
- **Redundant Java builds.** Each of the four repos independently builds
  its own copy of the ProLeap bridge JAR from its own `vendor/red-dragon`
  checkout.

## Scope

RedDragon itself is explicitly **out of scope** — it stays a separate repo,
vendored once. It's a general-purpose multi-language interpreter, not owned
by (or scoped to) the CICS/SQL/JCL coprocessor stack, and folding it in
would couple its release cadence to theirs for no benefit this migration
needs.

## Design

### Repository structure

`red-dragon-forge` becomes the monorepo root. `cicada/`, `squall/`,
`jackal/` merge in as top-level sibling directories to the existing
`red_dragon_forge/` package, via `git subtree` — preserving each package's
full commit history (`git log`/`git blame` on any file continues to work
across the old repo boundary). `vendor/red-dragon` becomes the **single**
shared RedDragon submodule; the copies formerly nested inside each of
`cicada/vendor/`, `squall/vendor/`, `jackal/vendor/` are removed.

```
red-dragon-forge/
  vendor/red-dragon/       # the ONE shared RedDragon submodule
  cicada/                  # full history preserved via git subtree
  squall/                  # full history preserved via git subtree
  jackal/                  # full history preserved via git subtree
  red_dragon_forge/        # unchanged, forge's own composition-layer package
  pyproject.toml           # NEW: uv workspace root
  Makefile                 # NEW: root orchestrator (see Build tooling)
  .importlinter            # NEW: cross-package independence contract
  CLAUDE.md                # trimmed to cross-cutting content only
```

Each merged package keeps its own nested `CLAUDE.md` unchanged.

### Python packaging: uv workspace

One root `pyproject.toml` declares:

```toml
[tool.uv.workspace]
members = ["cicada", "squall", "jackal", "red_dragon_forge"]
```

Each package keeps its own `pyproject.toml` (a workspace member, not
rewritten). One shared `uv.lock` at the root replaces today's four separate
lockfiles, and eliminates the `--no-deps` editable-install workaround
red-dragon-forge's current `Makefile` needs — `uv`'s workspace resolver
handles the shared `red-dragon` path dependency natively once there's one
lockfile instead of four independently-resolved ones.

### Build tooling: independent per-package, de-duplicated when built together

Each package's `Makefile` is otherwise unchanged — `cd cicada && make test`
still works standalone, identically to today. The only change: each
package's `PROLEAP_BRIDGE_JAR` variable resolves one level up, to the
shared root `vendor/red-dragon`, instead of a package-local copy:

```makefile
# cicada/Makefile (squall/Makefile the same in spirit)
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
...
$(PROLEAP_BRIDGE_JAR):
	cd ../vendor/red-dragon/proleap-bridge && ./build.sh
```

A new root-level `Makefile` builds the shared JAR once, as an explicit
prerequisite of an aggregate target — not relying on incidental
first-package-wins ordering, which would race under parallel execution:

```makefile
# red-dragon-forge/Makefile (root)
PROLEAP_BRIDGE_JAR := $(CURDIR)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar

.PHONY: jar test-all

jar: $(PROLEAP_BRIDGE_JAR)

$(PROLEAP_BRIDGE_JAR):
	cd vendor/red-dragon/proleap-bridge && ./build.sh

test-all: jar                # built here, first, guaranteed-once
	$(MAKE) -C cicada test
	$(MAKE) -C squall test
	$(MAKE) -C jackal test
	$(MAKE) test              # forge's own suite
```

Because `test-all` depends on `jar` first, the shared JAR exists on disk
before any of the four `$(MAKE) ...` recipe lines run. Each package's own
`$(PROLEAP_BRIDGE_JAR):` rule still exists (for standalone use) and is
still independently evaluated when invoked via `$(MAKE) -C cicada test` —
but by then the file is already present and fresh, so that rule's recipe is
skipped. This is plain GNU Make file-target-freshness checking (the same
mechanism that keeps a normal C project from recompiling an up-to-date
`.o` file) spanning four separate `make` process invocations that happen
to check the same shared absolute path — no custom coordination or locking
is introduced. Jackal's own `jcl-bridge` JAR (jackal-specific, never
shared across packages) is unaffected by any of this.

### Pre-commit hooks

Cicada, Squall, and Jackal each have their own `.pre-commit-config.yaml` +
`precommit-scripts/`, installed on top of a globally-installed Talisman
hook (`.git/hooks/pre-commit.legacy`, seeded per-machine, not per-repo).
Forge has neither today — only the global Talisman hook applies to it.

The hook *list* is templated/shared across the three
(`terminology-guard`, `terminology-commit-msg`, `black`,
`python-fp-lint`, `pyright`, `import-linter`, `tests`) —
`precommit-scripts/check-terminology`/`check-commit-msg` are byte-identical
across Cicada and Jackal (verified via `diff`). Per-package differences are
confined to which directory Black/FP-lint target, and the test invocation:
Cicada and Jackal run their **full** suite (including gated e2e) on every
local commit; Squall deliberately runs only a fast unit-test subset locally
(`precommit-scripts/run-tests` → `pytest tests/unit -x -q`), presumably
because its integration suite needs a live Db2 container — a real,
deliberate policy difference to preserve, not homogenize.

Since git hooks are repo-root-scoped (no native per-subdirectory hook
support), all four packages' hooks must live in **one** root
`.pre-commit-config.yaml` post-merge. Two different scoping strategies
apply, split by hook cost:

- **Static/lint/format checks stay global**, exactly like today
  (`always_run: true`, no `files:` filter) — Terminology Guard (×2),
  Black, Python FP lint, Pyright, and the new cross-package
  `import-linter` contract. These are fast; running them across all four
  packages' source on every commit costs little. Since they run globally
  now anyway, Black and Python FP lint collapse from "one hook per
  package" into **one combined invocation** listing all four packages'
  paths (less code, matching the earlier per-package build-tooling
  reasoning in spirit) — `python-fp-lint` takes an explicit directory
  argument per repo today, so its combined form lists all four; `pyright`
  takes no path argument at all (it discovers its config from
  `pyproject.toml`/`pyrightconfig.json`), so unifying it requires **one
  root-level `[tool.pyright]` config** (`include = ["cicada", "squall",
  "jackal", "red_dragon_forge"]`) replacing today's four separate
  per-repo configs — a design detail for the implementation plan to spell
  out precisely.
- **Test-suite hooks stay per-package and gain `files:` scoping** — these
  are slow (full suites, JVM bridge calls, live Db2), so a change to
  `squall/` should not also force Cicada's and Jackal's full suites to run
  locally. Each keeps its own hook ID, its own existing test-invocation
  policy (full vs. unit-only), and a `files:` regex gating whether it runs
  at all: `^(cicada|vendor/red-dragon)/` for Cicada, `^(squall|vendor/red-dragon)/`
  for Squall, `^(jackal|vendor/red-dragon)/` for Jackal. Every test hook
  additionally matches `vendor/red-dragon` itself, since a shared RedDragon
  pin bump can affect any package — this is a `files:` regex gate, not
  `always_run`, so it's still skipped for a commit that touches neither
  that package nor the shared submodule.

**Critical mechanism note:** `always_run: true` and `files:` are mutually
exclusive in effect — `always_run: true` bypasses file-matching entirely.
Today's per-repo configs set `always_run: true` on every hook (correct in
a single-package repo, where "unconditional" and "this package changed"
are the same thing). Migrating a hook to per-package `files:` scoping
means **removing** `always_run: true` from it, not just adding `files:`
alongside it — otherwise the flag silently wins and the hook keeps running
on every commit regardless of the filter. `pass_filenames: false` is
unaffected either way; it only controls whether matched paths are passed
as CLI arguments to the entry command, not whether the hook runs at all.

Forge gains its own `tests-forge` hook for the first time (it has none
today), with a **broader** `files:` pattern than the others —
`^(red_dragon_forge|cicada|squall|vendor/)/` — since forge's own suite
exercises Cicada's and Squall's adapters directly (`build_cics_spec`/
`build_sql_spec`); a change to either should re-trigger forge's suite too,
not just a change to `red_dragon_forge/` itself.

Once the root `.pre-commit-config.yaml` and shared
`precommit-scripts/check-terminology`/`check-commit-msg` exist, Cicada's,
Squall's, and Jackal's own now-superseded `.pre-commit-config.yaml` files
are **deleted** (not left behind) as part of the same `git subtree` merge
commit — same "no dead config" principle already applied to their
`.beads/` directories. Package-specific scripts that aren't shared
boilerplate (Squall's own `precommit-scripts/run-tests`) move with their
package rather than being deleted, renamed to make their scope explicit
(`run-tests-squall`) since they now live alongside the root config's other
packages' equivalents.

### Architectural contracts

A root-level `.importlinter` adds **one shared** `independence`-type
contract over `{cics, squall, jackal}` — the same contract *type*
RedDragon's own `.importlinter` already uses for `interpreter.frontends.*`
mutual independence, and (deliberately) the same scope: source packages
only, not their `tests/` directories. This converts today's implicit,
docstring-level convention ("only `adapters/` may import
`cics.*`/`squall.*`", the "no cross-sharing except through injection at the
forge level" invariant this session relied on repeatedly) into something CI
actively checks on every change, rather than something enforced only by the
packages having been physically separate repos.

```
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
```

**Test-directory coverage deferred, not dropped.** `cicada/tests/`,
`squall/tests/`, `jackal/tests/` sit as *siblings* of their package's
source directory today, not nested inside it — so `squall.tests.*` isn't a
real dotted import path the way `squall.*` is, and can't join the same
contract as-is without either per-package contracts (rejected — one shared
contract is a hard requirement here) or physically relocating each `tests/`
dir one level deeper into its own package (e.g. `squall/tests/` →
`squall/squall/tests/`) so it becomes a true subpackage. That relocation is
a real, if mechanical, one-time move (touches CI paths, coverage config,
anything hardcoding `tests/`) and is out of scope for this migration.
Tracked as a follow-up: `forge-don`.

### CI

Each package keeps its own test job (invoking its own `make test`), run in
parallel — normal per-package wall-clock is unaffected. Unlike the local
pre-commit hooks (deliberately `files:`-scoped to skip unaffected
packages, for fast local iteration), CI runs **all four jobs
unconditionally on every push/PR regardless of what changed** — that's the
whole point of moving to CI as the backstop: a RedDragon vendor pin bump
can no longer merge without all three coprocessor packages' suites passing
in the *same* pipeline run, closing the exact silent-drift gap that let
jackal's pin go stale for so long. Local scoping optimizes for fast
iteration; CI optimizes for never merging a silent cross-package break —
the two are complementary, not in tension.

### Beads issue tracker

red-dragon-forge already has its own Beads DB (`bd init`, run this session,
prefix `forge-`), backed by its remote
`git@github.com:avishek-sen-gupta/red-dragon-forge.git`, and already tracks
its first issue (`forge-don`, the deferred test-directory-nesting
follow-up from the Architectural contracts section above). Issue IDs
across the three merging source repos are already namespace-prefixed
(`cicada-*`, `squall-*`, `jackal-*` — verified directly against each
repo's `beads/issues.jsonl`) and collision-free against `forge-*`, so
importing all three of `cicada/beads/issues.jsonl`,
`squall/beads/issues.jsonl`, `jackal/beads/issues.jsonl` into forge's
already-existing DB via `bd import` adds to it without touching
`forge-don` or any other pre-existing forge issue. `bd` operates per-repo, and once
`cicada/`, `squall/`, `jackal/` are plain subdirectories of one repo, there
is exactly one `.beads/` going forward — the root's. Each merged package's
own `.beads/` directory (including its `config.yaml` with its now-defunct
`sync.remote` pointing at that package's own standalone repo) is deleted
entirely as part of the same `git subtree` merge commit, not repointed —
there is no scenario where a subdirectory of a monorepo needs its own
independent Beads DB. RedDragon's own Beads DB and issue history are
untouched — it remains its own separate project with its own tracker,
consistent with it staying a separate repo.

### CLAUDE.md

No merge. Each package keeps its own `CLAUDE.md` nested at its own
subdirectory root, unchanged. Only genuinely cross-cutting content (the
Beads integration block, monorepo-wide conventions) moves to the new root
`CLAUDE.md`; each package's own project-specific content stays exactly
where it is today, just one path segment deeper.

### Old standalone repos

`cicada`, `squall`, and `jackal`'s existing GitHub repos are left as-is —
not archived, not deleted. They simply stop being the active development
location once the `git subtree` merges land; no GitHub-side action is
taken on them as part of this migration.

## Non-goals

- RedDragon does not move, is not restructured, and its own Beads DB is
  untouched.
- No change to any package's own internal code, tests, or behavior — this
  is a repository/tooling structure migration, not a refactor.
- No archiving/deletion of the old standalone repos (deferred, if ever
  wanted, to a separate follow-up decision).

## Testing

After migration: each package's own full test suite (Cicada 348, Squall
271/1-skip, Jackal 127, red-dragon-forge 7) must pass both standalone
(`cd cicada && make test`) and via the root `make test-all`.
`scripts/check_red_dragon_pin.py`-equivalent verification becomes
unnecessary for this repo set specifically, since there is now structurally
only one `vendor/red-dragon` to drift from at all.

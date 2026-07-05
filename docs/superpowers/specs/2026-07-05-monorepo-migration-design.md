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

### Architectural contracts

A root-level `.importlinter` adds an `independence`-type contract over
`{cics, squall, jackal}` — the same contract *type* RedDragon's own
`.importlinter` already uses for `interpreter.frontends.*` mutual
independence. This converts today's implicit, docstring-level convention
("only `adapters/` may import `cics.*`/`squall.*`", the "no cross-sharing
except through injection at the forge level" invariant this session relied
on repeatedly) into something CI actively checks on every change, rather
than something enforced only by the packages having been physically
separate repos.

### CI

Each package keeps its own test job (invoking its own `make test`), run in
parallel — normal per-package wall-clock is unaffected. The behavior
change: a RedDragon vendor pin bump can no longer merge without all three
coprocessor packages' suites passing in the *same* CI pipeline run, closing
the exact silent-drift gap that let jackal's pin go stale for so long.

### Beads issue tracker

red-dragon-forge gets its own Beads DB for the first time (`bd init` — it
has none today), backed by its new remote
`git@github.com:avishek-sen-gupta/red-dragon-forge.git` (created and
pushed this session). Issue IDs across the four source repos are already
namespace-prefixed (`red-dragon-*`, `cicada-*`, `squall-*`, `jackal-*` —
verified directly against each repo's `beads/issues.jsonl`), so importing
all three of `cicada/beads/issues.jsonl`, `squall/beads/issues.jsonl`,
`jackal/beads/issues.jsonl` into forge's new DB via `bd import` is
collision-free at the ID level. `bd` operates per-repo, and once
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

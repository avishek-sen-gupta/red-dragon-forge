## Workflow — red-dragon-forge

Bindings and overrides for `workflow.md` and `lang/python/workflow.md`. Where this file
disagrees with either, this file wins.

### Build

Only the root has a Makefile; `cicada`, `squall`, `jackal` and `cobble` deliberately have none.

```bash
make setup     # init submodules + build hlasm_export + rebuild ProLeap and JCL bridge JARs + uv sync
make jar       # both bridge JARs; skipped if already built (jar-force rebuilds)
make python    # uv sync --all-packages, then Playwright's Chromium (cobble's page tests drive it)
make fmt       # Black over BLACK_PATHS
make hlasm     # the native hlasm_export binary alone (needs cmake, ninja, a C++ toolchain)
```

### Verification gate

This replaces the generic gate in `lang/python/workflow.md` — that one names no root `tests/`
runner that works here, and drops `import-linter`.

```bash
make fmt                                    # Black, scoped to BLACK_PATHS
uv run pyright                              # strict, zero errors
uv run lint-imports                         # .importlinter package-boundary contracts
pre-commit run python-fp-lint-check --hook-stage manual --all-files
make test                                   # root composition suite (needs the JARs)
make test-all                               # every package's suite; before anything cross-cutting
```

Two invocations worth getting right:

- **`make fmt`, not `black .`** — Black is scoped to `BLACK_PATHS`, which excludes `vendor/` and
  the generated ANTLR grammar. A bare `black .` reformats both.
- **python-fp-lint by hook, not by hand.** The `python-fp-lint` hook lints *staged blobs*; the
  `python-fp-lint-check` variant above lints the working tree and is the only on-demand form.
  Both read `fp.json`, which carries the exclusion list, so a manual run honours what the commit
  gate honours.

`make test` alone is not the gate for a change that touches a runtime. Use `make test-all`,
which builds the JARs once and then runs cicada, squall, jackal, cobble and the root suite.

Running a package's suite by hand, from that package's directory:

```bash
. ./bridge-env.sh        # exports both bridge JAR paths; from the repo root
cd cicada && uv run --no-sync python -m pytest
```

Three environment facts that cause confusing failures:

- **`bridge-env.sh` is required** for cicada, squall, jackal and the root suite. `cobble` is
  run **without** it, which is why `make test-all` does not source it there: its acceptance
  tests skip when the JAR is absent and the rest never start a JVM. Sourcing it turns those
  acceptance tests on — they take minutes rather than seconds, and some are currently failing
  for reasons that predate this note, so a green `cd cobble && pytest` is not evidence about
  them either way. Two of cobble's *stages* start a JVM, `cobble-parse-corpus` and
  `cobble-expand-corpus`; every stage after the parse reads the one ASG cache that stage wrote.
- **Db2-backed tests need a running Db2**: `make db2-up`, then source `squall/db2/dsn-env.sh`
  for `SQUALL_DB2_DSN`. Keep the container running between runs; the first init is slow.
- **`--no-sync`** on `uv run` is deliberate in the hooks and Makefile — it keeps a test run from
  silently re-resolving the workspace.

### Package boundaries

The three runtimes must not import each other. Only `red_dragon_forge/` and `cobble/` may
import more than one, and `cobble` is held to the static surface: it must not reach into any
runtime, and nothing may import it. The contract is `.importlinter`, checked by
`uv run lint-imports`, and it is the enforcement — this paragraph is the rationale.

`cicada`, `squall` and `jackal` stay independent at the import level and are built and set up
only from the forge root. `vendor/red-dragon` is never modified here; interpreter changes go
upstream, and interpreter issues are filed in red-dragon's own beads DB
(`bd -C <red-dragon clone> create …`), not the forge's.

jackal parses JCL and IDCAMS by grammar, never by regex: a new JCL surface feature is a grammar
production plus a transformer case, not a string scan.

### Issue tracking — beads, manual-export model

Not beads' Dolt sync. `.beads/` is **fully gitignored** (config, hooks, the Dolt working DB —
all local, per-machine state); `issues/issues.jsonl` is the **tracked** git source of truth.

`bd` refreshes that file itself (`export.auto: true`, `export.path: ../issues/issues.jsonl`,
throttled to 60s), so expect it to go dirty at unpredictable moments while you work — that is
the exporter, not a bug.

**Staging stays yours.** `export.git-add` is false, and this is a deliberate manual step, *not*
a git hook: a hook regenerating a tracked file mid-commit fights pre-commit's stash/restore.
Before committing anything that touches issues:

```bash
bd export -o issues/issues.jsonl   # force a write, ignoring the throttle
git add issues/issues.jsonl
```

On a fresh clone, rebuild the local DB with the opt-out flags. Plain `bd init` repoints
`core.hooksPath` at its own directory — silently orphaning `.git/hooks` and every pre-commit
hook — rewrites `AGENTS.md`/`CLAUDE.md`, and adds `.agents/`, `.codex/`, `.cursor/`:

```bash
bd init --prefix red-dragon-forge --non-interactive --quiet --skip-hooks --skip-agents --role maintainer
bd import issues/issues.jsonl
bd config set export.auto true      # one at a time: batched bd calls contend on .beads.gate.lock
bd config set export.path "../issues/issues.jsonl"
bd config set export.git-add false
bd config set import.auto false
```

Use `bd` for task tracking. Do not commit, push, or run remote sync unless asked; at handoff,
report changed files, validation run, and the commands you would have run.

### The commit hooks are the gate

`.pre-commit-config.yaml` runs, blocking: python-fp-lint, Black (auto-fix and re-stage),
Pyright, import-linter, the test suites (cicada, squall and jackal on their own changes; the
root suite, after a Db2 restart, on root and runtime changes; cobble's on changes to `cobble/` or
the `cicada/`, `squall/` and `vendor/` code it reads, never the root suite for a cobble-only
change), the terminology guard on both the diff
and the commit message, and Talisman.

**`--no-verify` is never used** unless the user explicitly instructs it. When a hook fails: fix
the code, fix the test, or rewrite the commit message. A timeout in an e2e suite is an
infrastructure problem to report, not a reason to skip every gate including the terminology and
talisman checks.

### Documentation

- **No test counts in living documentation.** Never state a concrete count ("348 tests",
  "271 passed / 1 skipped") in a README, package doc, or architecture/design overview. They go
  stale the instant a test is added and mislead readers — describe what a suite *covers*.
  Point-in-time "Expected: N passed" steps inside `docs/superpowers/plans/` are execution
  records, not living claims, and are exempt.
- **Write concisely without dropping information.** Docs and issue text are short because they
  are dense, never because they are vague. Cutting a fact is not concision.

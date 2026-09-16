# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** this repo uses beads' **manual-export** model, NOT Dolt remote sync — `.beads/` (the local Dolt working DB) is fully gitignored, and `issues/issues.jsonl` is the tracked git source of truth, regenerated with `bd export -o issues/issues.jsonl` and staged before committing (there is no `bd dolt push`). See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for the underlying sync concepts this repo deliberately opts out of.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

**Issue graph is version-controlled (manual-export model, not beads' Dolt sync).** `.beads/`
(Dolt working DB) is **fully gitignored** (not just partially, unlike some sibling packages'
older convention — `config.yaml`/hooks/etc. are all local, per-machine state here);
`issues/issues.jsonl` is the **tracked** git source of truth. **Whenever a change touches
issues, regenerate and stage the snapshot BEFORE committing** — a deliberate manual step, NOT
a git hook:
```bash
bd export -o issues/issues.jsonl && git add issues/issues.jsonl
```
On a fresh clone, `bd import issues/issues.jsonl` rebuilds the local DB.


## Build & Test

The root `Makefile` orchestrates the whole workspace (see `README.md` for details):

```bash
make setup     # init submodules + build hlasm_export + the ProLeap + JCL bridge JARs + uv sync --all-packages
make jar       # build both bridge JARs (ProLeap + JCL); skipped if already built
make python    # uv sync --all-packages
make test      # root composition-layer + integration suite (needs the JARs)
make test-all  # build JARs once, then run every package's suite (cicada, squall, jackal, cobble, forge)
```

Each package is also independently buildable/testable from its own directory (`cd cicada && make test`,
`cd cobble && uv run pytest`, etc.). `make setup` also builds the native `hlasm_export` binary
(`make hlasm` alone; needs cmake/ninja/a C++ toolchain). `. ./bridge-env.sh` exports both bridge JAR paths.
Db2-backed tests need `SQUALL_DB2_DSN` and a running Db2 (`cd squall && make db2-up`).

## Architecture Overview

A `uv` workspace layering four runtimes on top of the vendored
RedDragon interpreter (`vendor/red-dragon`, never modified here):

- `cicada/` — CICS runtime (pseudo-conversational dispatch, VSAM KSDS, BMS).
- `squall/` — EXEC SQL / Db2 coprocessor runtime.
- `jackal/` — JCL/batch execution engine.
- `red_dragon_forge/` — composition layer; assembles multiple coprocessor extensions into one
  compiled COBOL program via a generic `CoprocessorSpec` seam.
- `cobble/` — corpus onboarding and whole-system knowledge-graph extraction (analysis only);
  runs its pipeline from `cobble/` as `uv run cobble-parse-corpus --config …` then
  `uv run cobble-build --config …` (after `. ../bridge-env.sh`); cobble has no Makefile. The
  parse is the only stage that starts a JVM; every stage after it reads the one ASG cache it
  wrote. Configs are TOML.

Cicada, Squall, and Jackal were merged in via `git subtree` (history preserved) and stay
independently buildable — they must not import each other.

## Conventions & Patterns

- **Package independence** is enforced by the root `.importlinter` contract: the three runtimes
  must not import each other, and only `red_dragon_forge/` and `cobble/` may import more than
  one. Cobble is further held to the static surface — it must not reach into any runtime, and
  nothing may import it. Run `uv run lint-imports` to check.
- **Formatting**: Black (line length 88); `make fmt` at the root, or per package.
- **Comments are a smell.** Reaching for a comment means the code did not say it — rename,
  extract, or restructure until it does. Comments that survive earn it by carrying what code
  cannot: an external constraint, a non-obvious "why", a reference to an issue or standard.
- **Decouple.** Prefer a named seam over a flag threaded through a call chain, and a value
  object over a tuple whose meaning lives in the caller's head.
- **Write concisely, without dropping information.** Documentation and issue text should be
  short because it is dense, never because it is vague. Cutting a fact is not concision.
- **Answer in 5–6 lines, 10 at the outside.** Explanations to a human are subject to the same
  rule as documentation: dense, not padded.
- **No test counts in docs.** Never state concrete test counts (e.g. "348 tests",
  "271 passed / 1 skipped") in living documentation — READMEs, package docs,
  architecture/design overviews. They go stale the instant a test is added or removed and
  mislead readers; describe what a suite *covers*, not how many tests it has. (Point-in-time
  "Expected: N passed" step instructions inside `docs/**/plans/` TDD plans are execution
  records, not living claims, and are exempt.)
- **Issue tracking**: Beads with the manual-export model described above — regenerate and stage
  `issues/issues.jsonl` before committing anything that touches issues.
- **`--no-verify` is never used** unless explicitly instructed by the user. Pre-commit hooks
  exist to catch real problems (terminology leaks, broken tests, talisman violations). When
  hooks fail: fix the code, fix the test, or rewrite the commit message — never bypass the
  hooks. A timeout in an e2e suite is an infrastructure problem to report, not a reason to
  skip all gates including the terminology and talisman checks.

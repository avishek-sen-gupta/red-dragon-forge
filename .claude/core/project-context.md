## Project Context

**jackal** is a JCL execution/orchestration layer: it parses JCL, sequences job
steps, resolves DD statements to datasets, and runs each `EXEC PGM` step (COBOL
load modules and emulated utilities) against the red-dragon VM + file engine.

- **Language:** Python 3.13+ (main codebase), Markdown (docs)
- **Package manager:** uv (matches the squall sibling)
- **Test framework:** pytest
- **Formatter:** Black
- **Issue tracker:** Beads (`bd`)
- **red-dragon:** consumed as a git submodule at `vendor/red-dragon`; jackal runs
  COBOL via its `run()` / VM + `CobolIOProvider` file engine. Bump the submodule
  to pick up engine fixes.
- **Specs (immutable):** `docs/superpowers/specs/` and `docs/superpowers/plans/` —
  never modify these. Newer specs supersede older ones by convention.

## Task Tracking

Use `bd` (Beads) for ALL task tracking. Do NOT use markdown TODO lists.

1. File an issue before starting work: `bd create "title" --description="..." -t bug|feature|task -p 0-4`
   - **Exhaustive details required.** Include what is wrong or missing, where it
     manifests, and any known constraints.
2. Claim it: `bd update <id> --claim`
3. When done: `bd close <id> --reason "..."`

## External Dependencies

- `vendor/red-dragon` submodule. Its COBOL frontend requires JDK 17+ and the
  ProLeap bridge JAR (`PROLEAP_BRIDGE_JAR`).
- The real-batch corpus (deferred milestone) lives in an external checkout
  referenced by env var — never committed, never named in tracked artifacts.

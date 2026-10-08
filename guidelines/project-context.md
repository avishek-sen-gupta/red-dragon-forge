## Project Context

- **Language:** Python 3.13+ — the effective workspace floor, set by `jackal`. Individual
  members declare lower minimums (root and `squall`/`cobble` 3.11, `cicada` 3.10); `uv sync
  --all-packages` resolves against the strictest. Java 17+ for the two bridge JARs.
- **Purpose:** Monorepo for RedDragon's COBOL coprocessor runtimes — CICS (`cicada`),
  EXEC SQL/Db2 (`squall`), JCL/batch (`jackal`) — the composition layer that assembles them
  into one compiled program (`red_dragon_forge`), and the static analyser that reads the same
  corpora without running them (`cobble`).
- **Package manager:** `uv`, one workspace; members are `cicada`, `squall`, `jackal`, `cobble`,
  with `red_dragon_forge` at the root. `vendor/red-dragon` is an editable path source. The
  Java bridges are built with Maven, not uv.
- **Test framework:** `pytest`. The root suite is `tests/`; each package is tested from its own
  directory. The root suite and cicada/squall/jackal need `. ./bridge-env.sh` sourced first;
  `cobble` does not. See `project/workflow.md` for the gate.
- **Formatter:** Black, line length 88, `target-version = py311`. `make fmt` at the root.
- **Architecture:** see `docs/reference/forge/architecture.md` (the packages and the
  `CoprocessorSpec` seam at `interpreter.project.coprocessor_compile`) and the per-package pages
  under `docs/reference/`. Boundary rationale: `docs/records/design/2026-09-09-package-boundaries.md`.
  Do not restate any of it here — a second copy drifts.
- **Docs:** everything for people is under `docs/`, indexed from `docs/README.md`.
- **Specs (immutable):** `docs/superpowers/specs/` and `docs/records/` — dated design records and
  analyses, never edited after the fact. `docs/superpowers/plans/` holds dated TDD execution
  records and is equally point-in-time. `vendor/red-dragon` is a submodule and is never modified
  from here; changes to the interpreter go upstream.

## External Dependencies

- `uv` (packaging), `pytest`, Black, Pyright (strict; `pyrightconfig.json` excludes `vendor`,
  `__pycache__`, third-party, testbeds and the generated ANTLR grammar under
  `cicada/cics/cics_grammar/`)
- [python-fp-lint](https://github.com/avishek-sen-gupta/python-fp-lint) — the functional-style
  gate; rules in `.python-fp-lint/`, project rule set in `fp.json`
- `import-linter` — architectural contracts in `.importlinter`; run with `uv run lint-imports`
- Talisman (secret scan) and `betterleaks` via `precommit-scripts/check-terminology`
  (terminology guard, on both the diff and the commit message)
- JDK + Maven — the ProLeap bridge JAR (built in `vendor/red-dragon`) and jackal's JCL bridge
  JAR. `. ./bridge-env.sh` exports both paths.
- cmake, ninja, a C++ toolchain — the native `hlasm_export` binary (`make hlasm`)
- Docker — Db2 for squall's and the composition layer's Db2-backed tests (`make db2-up`,
  then source `squall/db2/dsn-env.sh` for `SQUALL_DB2_DSN`)
- `bd` (beads) — issue tracking; `ast-grep` and `ripgrep` on PATH

## Related Projects

- [red-dragon](https://github.com/avishek-sen-gupta/red-dragon) — the interpreter every runtime
  extends. Vendored at `vendor/red-dragon`; the `CoprocessorSpec` seam lives there.
- [python-fp-lint](https://github.com/avishek-sen-gupta/python-fp-lint) — the executable half of
  these guidelines. See `lang/python/workflow.md`.
- `agent-guidelines-templates` — upstream source of every other file in `guidelines/`. Changes
  that are not specific to this repo belong there.
- Vendored corpora, read-only: `vendor/carddemo`, `vendor/bank-of-z`,
  `squall/testbed/db2-samples`, `cicada/third-party/che-che4z-lsp-for-hlasm-fork`.

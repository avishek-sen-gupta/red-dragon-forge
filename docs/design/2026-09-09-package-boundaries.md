# red-dragon-forge: Package Boundaries — Decision Record

**Date:** 2026-09-09
**Status:** in force; enforced by [`.importlinter`](../../.importlinter) in pre-commit and CI.
**Supersedes nothing** — this records boundaries established across the subtree merges
([`2026-07-05-monorepo-migration-design.md`](../superpowers/specs/2026-07-05-monorepo-migration-design.md))
and the cobble consolidation, previously stated only in the root README.

---

## Layout

```
red-dragon-forge/
  vendor/red-dragon/       # the ONE shared RedDragon submodule
  cicada/                  # CICS runtime, full history preserved via git subtree
  squall/                  # EXEC SQL runtime, full history preserved via git subtree
  jackal/                  # JCL/batch runtime, full history preserved via git subtree
  cobble/                  # corpus onboarding + knowledge-graph extraction, via git subtree
  red_dragon_forge/        # composition-layer package (this repo's own code)
  tests/                   # root composition + integration suites
  pyproject.toml           # uv workspace root (members: cicada, squall, jackal, cobble)
  Makefile                 # root orchestrator — builds the shared JARs once, runs all suites
  .importlinter            # cross-package independence contract
  .pre-commit-config.yaml  # consolidated hooks (static checks global, test suites per-package)
```

Cicada, Squall, Jackal, and Cobble were originally separate repos, merged in via `git subtree`
with full commit history preserved — `git log --follow -m` on any file inside them still walks
back across the merge boundary. Each keeps its own `CLAUDE.md`, `Makefile`, `pyproject.toml`,
and test suite, and remains fully independently buildable and testable: merging them didn't
couple their release cadences or make them depend on each other.

## The boundaries

A shared root [`.importlinter`](../../.importlinter) contract enforces them; run
`uv run lint-imports` to check.

- **The three runtimes must not import each other.** Cicada, Squall, and Jackal are peers.
  EXEC SQL is a coprocessor extension, not a CICS facility, and JCL orchestrates programs
  without knowing what coprocessors they carry — so none of the three needs the others, and a
  contract keeps it that way rather than trusting review.
- **Only `red_dragon_forge/` and `cobble/` may import from more than one of them.** The
  composition layer's whole purpose is to assemble several coprocessor extensions into one
  program, and cobble reads corpora that mix all three dialects. Everything else stays single-
  package.
- **Cobble is held to the static surface by three further contracts:** it must not import the
  interpreter, nor any runtime (cicada's dispatcher/VSAM/BMS/strategy, jackal's
  runner/catalog/IDCAMS, squall beyond `statements`), and nothing in the workspace may import
  it. Cobble parses and walks the ASG; it never lowers to IR and never executes. Keeping it off
  the interpreter is what makes it VM-free, and keeping it un-imported is what makes that
  cheap to prove.

Import-linter enforces prohibitions, not permissions, so only the forbidden lists are
machine-checked. The *allowed* static surface — `cobol_asg.*`, `cobol_memory`,
`cics.{cics_parser,cics_visitor,cics_grammar,csd_parse,statements,bms}`, `bms_copybook_gen`,
`jackal.{model,dsn,value_parts,tso,jcl.*}` and `squall.statements` — is stated in
`.importlinter`'s own comments because it is what a future extraction of a lean core would
have to contain. Keeping the two in step is a review obligation, not an automated one.

## History

Whole-system graph extraction once lived here as a `knowledge_graph/` package, with per-runtime
extractors inside Cicada and Jackal. It was deleted ahead of folding cobble in — cobble was a
VM-free successor, not a lagging copy, so the stack arrived with cobble rather than being merged
into its own ancestor, and has since grown the field-level byte dataflow work. See
[`2026-09-01-delete-stale-graph-stack-design.md`](../superpowers/specs/2026-09-01-delete-stale-graph-stack-design.md).

# Reverse engineering a legacy system: the deterministic half

A recorded video, about an hour, for people new to reverse engineering. Design:
`docs/superpowers/specs/2026-10-28-reverse-engineering-video-design.md`.

**The one idea:** let deterministic tools establish the facts about the code (its syntax tree,
control flow, data flow, how fields cluster), and have the LLM interpret those facts rather than
guess from raw source.

The example system is CardDemo, a COBOL/CICS/batch credit-card application.

## The frozen run

Every segment reads one artifact run, built once before recording:

```bash
make carddemo-all
```

```bash
RUN=cobble/out-carddemo-20261030-0432-rebuild-all   # the directory the run printed; update it after a rebuild
```

All commands below use `$RUN` relative to the repo root unless they `cd cobble`, where it is
`${RUN#cobble/}`. Rebuild and update this one line if cobble changes before recording.

## Segments

| # | file | what | target length |
|---|---|---|---|
| 1 | [01-opening.md](01-opening.md) | the problem: legacy code nobody fully understands | 5 min |
| 2 | [02-pipeline.md](02-pipeline.md) | the pipeline, stage by stage, with explainers | 30 min |
| 3 | [03-runtime.md](03-runtime.md) | the app really runs; tests assert on its data | 8 min |
| 4 | [04-interpretation.md](04-interpretation.md) | an agent answers questions from the artifacts | 12 min |
| 5 | [05-close.md](05-close.md) | back to the one idea | 3 min |

## Prerequisites

- `make setup` once: submodules, `hlasm_export`, both bridge JARs, `uv sync`.
- `. ./bridge-env.sh` in every shell that parses or runs COBOL.
- For the Db2 headless test: `make db2-up`, then `. squall/db2/dsn-env.sh`.
- For the CardDemo screen clip: `c3270` and `vhs` on `PATH`.
- For segment 4: Claude Code in this repo, after `make skills` copies the `cobble-artifacts`
  skill from `cobble/skills/` into `.claude/skills/`.

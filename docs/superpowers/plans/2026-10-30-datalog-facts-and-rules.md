# Datalog Facts and Rule Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cobble-experimental-datalog-facts` writes a cobble run as Soufflé facts plus their schema, and a tracked library of generic rules answers questions a machine writes against them.

**Architecture:** Two writer-side facts the experiment had to guess or parse become artifact fields (CFG `entry`, access `node`). A new `cobble/cobble/experimental/datalog/` package holds one definition per relation (name, typed columns, rows from a typed reader of one artifact) that writes both `<relation>.facts` and `schema.dl`. Generic rules ship in `experimental/datalog/rules/` and take their target from facts the question states.

**Tech Stack:** Python 3.13, Pydantic v2, frozen dataclasses, Soufflé 2.5 (optional, tests skip without it), pytest.

**Spec:** `docs/superpowers/specs/cobble/2026-10-30-datalog-facts-and-rules-design.md`

## Global Constraints

- Relations and column types exactly as the experiment's `cobble/out-datalog-20261029-souffle/rules/schema.dl` (42 relations), including its encoding: `yes`/`no` booleans, `-` for an absent PERFORM resume/range end, tabs/newlines in text replaced by spaces, rows de-duplicated and sorted, origin and sink as typed `kind`/`name` columns.
- No guessed fact; no string parsing of structure the run holds; every artifact read through a Pydantic model; extents through `extent_text.byte_range`.
- A missing input artifact fails the command, naming the file.
- Soufflé optional: rule tests `pytest.mark.skipif(shutil.which("souffle") is None, ...)`.
- Repo rules: frozen dataclasses, one class per file, no `None` defaults, no comments beyond a one-line module/class header, Pyright strict, python-fp-lint, no relative imports. Never reference external codebases (CardDemo is fine). One hooked commit at the end; never `--no-verify`; never run pre-commit by hand. Run targeted `uv run --no-sync python -m pytest <paths>` from `cobble/`, without `bridge-env.sh`.
- The CardDemo-specific question files stay untracked in `cobble/out-datalog-20261029-souffle/`.

## Review Focus

1. A program whose first paragraph has an incoming edge (a loop back to it): `entry` is still that paragraph's label.
2. An external program: `entry` is `%EXTERNAL#label`.
3. A run missing one artifact (e.g. no `aggregates/unified.jsonl`): the command exits non-zero naming it, writing nothing partial.
4. A text column containing a tab or newline (a literal, a predicate text): the facts line keeps its column count.
5. `slot_edge` with no alignments: `slot_align` has no rows for it, and the byte rules treat it as whole-field.

---

### Task 1: CFG entry and access node as artifact fields

**Files:**
- Modify: `cobble/cobble/dataflow/srccfg/cfg.py` (`Cfg.entry: str`, required; `external_cfg` sets `EXTERNAL_ENTRY.id`), `build.py` (`entry=label_id(order[0].name)`), `bundle.py`, `dataflow.py:978`, `rows/program_row.py` (`entry: str`, required), `rows/cfg_row.py` (`program_row(program, entry, external)`), `reach/walk.py:46`.
- Modify: `cobble/cobble/dataflow/fields/access.py` (`AccessRow.node: str`), `access_report.py` (writes `"node"`).
- Docs: `docs/reference/cobble/srccfg.md` (the program row's `entry`), the accesses row in its doc.
- Tests: `cobble/tests/dataflow/srccfg/` (build: first paragraph's label, also when a later GO TO loops back to it; external: `%EXTERNAL#label`; bundle round trip keeps `entry`), access test (row carries `node` equal to the CFG node id). Every `Cfg(` in tests passes `entry`.

- [ ] Step 1: write the tests; run `uv run --no-sync python -m pytest tests/dataflow/srccfg tests/dataflow/fields -q` — FAIL.
- [ ] Step 2: implement; same command — PASS.

### Task 2: Typed readers for the artifacts that lack one

**Files:** a Pydantic line model beside the writer of each, one class per file, for: `extents.jsonl` (all columns `field_decl` needs: names, records, paths, levels, pics, usages, occurs, origins, values, redefines, extents — extend `experimental/partition/extent_row.py` or add `dataflow/fields/extent_line.py`), `accesses/*.jsonl`, `depgraph/edges.jsonl`, `fixpoint/aliases.jsonl` (reuse `LinkRow` if it fits), `combine/targets.jsonl` (reuse `TargetSite` if it fits). Already typed: knowledge graph (`knowledge_graph.graph_file.read_graph_rows`), CFG rows (`CFG_ROWS`), `MemberCounts`, `ReachingRow`, `SinkRow`, `FlowAttrs`, `LinkRow`, jumps (`jumps.rows`), partition `NodeLine`/`EdgeLine`, `UnifiedLine`.
- Test: each new model validates a line from the writer's own output (write then read in the same test).

- [ ] Step 1: tests; FAIL. Step 2: models; PASS.

### Task 3: The facts command

**Files:**
- Create: `cobble/cobble/experimental/datalog/` — a column type enum (`SYMBOL`, `NUMBER`), a `Column`, a `Relation` (name, columns), one module per artifact family yielding `(Relation, rows)` from its typed reader, a writer (facts files + `schema.dl`, rows de-duplicated and sorted, text cleaned of tabs/newlines), `facts_cli.py` (`--run`, `--out`).
- Modify: `cobble/pyproject.toml` (script `cobble-experimental-datalog-facts = "cobble.experimental.datalog.facts_cli:main"`; package data for `rules/*.dl`), `.importlinter` if experimental packages are listed.
- Test: `cobble/tests/experimental/datalog/test_facts.py` — a small run directory built by the existing fixtures (or hand-written lines for each artifact) gives exact rows for representative relations (`cfg_entry`, `cfg_perform` with `-`, `fp_flow` with typed origin, `origin`, `slot_align`, `access`), `schema.dl` declares every written relation with its arity and types; a missing artifact raises naming it; a text column with a tab keeps the column count.

- [ ] Step 1: tests; FAIL. Step 2: implement; PASS.
- [ ] Step 3: on `cobble/out-carddemo-20261030-0308-rebuild-all` (after Task 6's rebuild, a new run), every relation's rows equal the experiment exporter's on the same run (`python3 cobble/out-datalog-20261029-souffle/export.py <run> <tmp>`), except `cfg_entry`/`access` which must equal too since the fields now carry what was guessed/parsed.

### Task 4: The rule library

**Files:** `cobble/cobble/experimental/datalog/rules/{reach,guards,programs,bytes,writers,guard_reads,gaps}.dl`, each `#include "schema.dl"` (resolved with `souffle --include-dir <facts dir>`), lifted from the experiment's `base.dl`, `guards.dl`, `credit.dl`, `claims.dl` with every CardDemo name replaced by a question relation: `site(p, n)`, `target_slot(slot)`, `target_bytes(slot, start, end)`. Guard against double inclusion (`#pragma once` or include guards).
- Test: `cobble/tests/experimental/datalog/test_rules.py` (skip without Soufflé) — hand-written facts per behaviour: a PERFORM returns to its caller and its range end does not fall through; a guard on every path vs one on only some; a setter (new bytes from a FILE origin) vs a write-back; a byte walk through an aligned edge keeps offsets and through an unaligned edge takes the whole field; a transaction runs a program two XCTLs away; a gap for an unsettled program.

- [ ] Step 1: tests; FAIL. Step 2: rules; PASS.
- [ ] Step 3 (untracked verification): rewrite the experiment's `credit.dl`, `signon.dl`, `menu.dl`, `claims.dl` to include the library and state their targets; run on the new facts; every result CSV and the four proofs in `results/proofs/` match the current ones.

### Task 5: Docs and skill

- Create `docs/reference/cobble/datalog.md`: the command, every relation with its columns and source artifact, the library files and the question relations each reads, how a question is run (`souffle --include-dir <facts> -F <facts> -D <out> question.dl`). Link from `docs/README.md` and the cobble reference index.
- `cobble/skills/cobble-artifacts/SKILL.md`: the `datalog/` facts directory; `make skills`.

### Task 6: Rebuild step, rebuild, commit

- [ ] `tools/rebuild-all.sh`: a step after the aggregates: `run cobble-experimental-datalog-facts --run "$OUT" --out "$OUT/datalog"`.
- [ ] `make carddemo-all`; Task 3 Step 3 and Task 4 Step 3 against the new run; update `RUN=` in `docs/presentation/video/README.md`.
- [ ] Stage only this plan's files (`git diff --cached --name-only`), then one commit: `feat(cobble): Datalog facts of a run, and a generic rule library`.

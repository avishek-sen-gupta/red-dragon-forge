# Dynamic CICS Operands (red-dragon-forge-gra) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Resolve a dynamic `TRANSID`, `MAP`, `MAPSET` or `FILE` operand the way Unit 1 resolved `PROGRAM`, and delete `cics/verb_source_asg.py::_resolve_operand`.

**Architecture:** Unit 1 built the machinery — a value lattice, a `targets.jsonl` artifact, and a three-way edge rule (proven / candidate / explicitly unresolved). This plan generalises it from one operand role to five, driven by a single `(verb, role)` table rather than copied per family.

**Issue:** `red-dragon-forge-gra`. The design it reuses is described in `docs/superpowers/specs/2026-09-30-cobble-dynamic-call-resolution-design.md` §4.5–§4.7 (untracked on the author's machine).

**Worktree:** branched from `origin/main` at `50a144d`. Rebase onto `9bbe3d0` (or later) before Task 1 — this is not a no-op. Since `50a144d`, `fixpoint/build_corpus.py` gained parallel workers, per-member resumable output and completion-order submission; `fields/side_tables.py` gained named row identities and a `program` in `defs` rows; `build_graph.py` gained `--dynamic-call-targets` and lost the config's `out_dir`. Re-read those files before planning edits against them.

## Global Constraints

- Frozen dataclasses. No `Any`, no bare `object`, no unparameterised generics. The Pyright gate is PER-FILE: ~761 pre-existing repo errors are out of scope, zero in files you touch.
- Docstrings are expected; inline `#` comments are prohibited except a one-line header above a module constant.
- No mutating `for` loops. `Sequence`/`Mapping` from `collections.abc`. Concrete equality assertions, never a containment check where a value was available.
- Read JSONL through `fixpoint/rows.py` helpers only — never `json.loads`.
- **Never source `bridge-env.sh`** for the cobble suite: it switches on acceptance tests that already fail for unrelated reasons. Run a suite ONCE, in the foreground. Do not background a suite and wait.
- `make fmt` from the repo root, never `black .`. `uv run lint-imports`. Never `--no-verify`.
- Do not touch `.talismanrc` — reword if flagged. The scanner matches short ordinary English fragments inside identifiers and prose, so false positives are routine and rewording is the documented remedy.
- No `__init__.py` under `tests/`.
- `python-fp-lint`: `C901` ceiling 3, `PLR0915` ceiling 10 statements, no reassignment across branches.
- **The graph is ONE tagged file.** `cobble/reference/graph.jsonl` holds 1280 rows — 448 tagged `node`, 832 tagged `edge`. Verify with `uv run --no-sync cobble-compare --graph <path>`; `cobble-build` writes it via `--output`. Node identity is `(kind, id)` and edge identity is `(source, source_kind, target, target_kind, kind)`, unchanged from the two-file era, so the review discipline still applies.
- **The reference includes the dynamic-target edges, so `cobble-build` must be given the fixpoint's table.** Since `d912d2a` the build no longer finds `targets.jsonl` by convention: without `--dynamic-call-targets <fixpoint out-dir>/targets.jsonl` the diff against the reference is 89 rows, not empty. Every gate in this plan is:
  ```bash
  uv run --no-sync cobble-dataflow-fixpoint --asg-dir out-parsed --out-dir out-fields \
    --extents out-fields/extents-input.jsonl --all --force
  uv run --no-sync cobble-build --config config/carddemo.toml --output out/carddemo.jsonl \
    --dynamic-call-targets out-fields/targets.jsonl
  uv run --no-sync cobble-compare --graph out/carddemo.jsonl
  ```
- **The fixpoint resumes from `<out-dir>/members/` and reuses what it finds** (`ca99a61`). A member directory written before a task changed what the fixpoint emits is stale, and nothing detects that. Give `--force` to every fixpoint run in this plan, as the gate above does. Add fields to `MemberCounts` only with defaults, never rename or remove one: `counts.json` is validated with `extra="forbid"`, and a corpus run in progress elsewhere resumes from directories written by the current schema.
- **Worktree prerequisites**, none of which a fresh worktree inherits — all five are in place, and a future resume must redo them:
  1. `git submodule update --init vendor/red-dragon vendor/carddemo`
  2. `uv sync --all-packages`
  3. `cobble/out-parsed` — 29 ASG members, copied from the main checkout rather than re-parsed (parsing needs the ProLeap JAR and takes minutes)
  4. `cobble/out-fields/extents-input.jsonl` — about 108 MB, regenerate with `cobble-extents --asg-dir out-parsed --out out-fields/extents-input.jsonl` (no JVM). The fixpoint reads it with `--extents` and no longer writes an `extents.jsonl` of its own (`cea1864`).
  5. **The bridge JARs, symlinked from the main checkout.** Without them `test_fields_synthetic.py` and `test_fields_trace.py` skip on `no bridge JAR at vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar`, costing ~40 tests that LOOK fine in the summary. Symlink both bridges rather than running `make jar`.
  6. **A whole-corpus fixpoint run**, for the `targets.jsonl` the build gate needs — the first command of the gate above. About 10 s on CardDemo with four workers.

## Review Focus

1. **A composed id with two dynamic halves.** A `BMS_MAP` node's id is `MAPSET.MAP`. Both operands dynamic means a cross product — 11 × 11 is 121 candidates from one site. Task 5 must cap it and record the cap as a reason, not emit 121 edges.
2. **A verb that maps many-to-one.** Eight file verbs collapse onto five edge kinds. A `(verb, role)` table must reject a verb it has no row for rather than defaulting to something.
3. **Promotion must still require empty reasons.** Five roles multiply the chances of a one-candidate-with-a-reason site being published as proven. Task 2 keeps that as one condition, not one per role.
4. **Removing `_resolve_operand` must not drop a literal.** It resolves literals too. After deletion, literal operands must resolve exactly as now — the reference graph is the check.
5. **A dynamic operand with no `targets.jsonl`.** The not-attempted fallback covers XCTL/LINK only. Five roles need it generalised or deliberately scoped, and stated either way.
6. **Two operands at one CFG node.** `targets.jsonl` rows are deduped on `target_identity(caller, node)` in `side_tables.py`. A SEND MAP node has a MAP and a MAPSET operand, and a READ node can have a FILE operand beside others: with the identity unchanged, the second row at a node is silently dropped — the defect `59cd4c5` fixed for `defs`. The identity must include the role (Task 1).
7. **Every corpus pays a full fixpoint re-run.** Tasks 3–5 move resolution into the fixpoint, so its output changes for every member with a dynamic operand: any existing fixpoint output, including a resumable corpus run, has to be regenerated with `--force`. Minutes on CardDemo; hours on a corpus of thousands of members, even after `0e4eeeb` and `9bbe3d0`.

## What this is actually worth — measured, not estimated

Counted over the 29-member CardDemo cache, every `ExecCicsStatement` operand of interest, literal versus data name:

| verb / option | literal | **data name** |
|---|---|---|
| `RETURN TRANSID` | 0 | **20** |
| `READ DATASET` | 0 | 14 |
| `READPREV` / `STARTBR` / `READ FILE` | 0 | 6 each |
| `READNEXT DATASET` | 0 | 5 |
| `ENDBR` / `REWRITE` / `WRITE` / `DELETE` | 0 | ~15 |
| `SEND MAP` — `MAP`, `MAPSET` | 15 | 5 each |
| `RECEIVE MAP` — `MAP`, `MAPSET` | 12 | 5 each |
| `INQUIRE PROGRAM` | 0 | 1 |
| | | **122 total** |

The reference graph holds only ONE fabricated node because `_resolve_operand`'s `VALUE` lookup only *fails* for a field with no `VALUE` clause. The other 121 operands are `LIT-ACCTFILENAME`, `WS-USRSEC-FILE`, `LIT-CARD-FILE` and the like — fields that DO carry one, which the old code resolves correctly by accident, exactly as it did for `WS-ABEND-PGM` before Unit 1. So the graph looks cleanest where it is least verified: 122 edge targets taken from a declaration, with nothing checking whether a later `MOVE` invalidated it. `RETURN TRANSID` is 20 of 20 dynamic, so the whole transaction-flow half of the graph rests on that accident.

`INQUIRE PROGRAM` with a data name is a verb no current table maps, so it contributes no edge at all today — out of scope here, worth its own issue.

## Baseline to hold

The gate in Global Constraints — fixpoint with `--force`, build with `--dynamic-call-targets`, compare — is EMPTY DIFF through Tasks 1–2, against a reference of 1280 rows (448 `node`, 832 `edge`).

Tasks 3–5 will move it **substantially**: 122 operands stop being resolved from declarations and start being resolved from dataflow, so expect candidate edges in volume and some targets to change. Each task states its expected delta BEFORE regenerating anything.

Suites, measured on this branch after the single-graph-file change landed:
- `tests/cics/` + `tests/knowledge_graph/` + `tests/test_compare.py` + `tests/test_build_graph.py` — **129 green**
- `tests/dataflow/` — **13 skipped**, all expected: twelve want an srccfg acceptance config and one wants a closure config, and neither exists for this corpus. State how many tests ran, as arithmetic against the previous run, never as a bare number — three times in the preceding unit a suite covered less while still reporting green.

### Task 6 uses a diff classifier, not a reading

Unit 1 reviewed its reference delta line by line because it was four nodes and 63 edges. A 122-operand change is too large for that. One tagged file with unchanged identity semantics makes the better instrument cheap: read `reference/graph.jsonl` and the regenerated file, group every added and removed row by `(type, kind)`, and assert each group's size against a stated expectation. A group nobody predicted is the defect — same rule as Unit 1, enforced by arithmetic rather than by eye.

---

### Task 1: Carry an operand role, with PROGRAM as one of five

No behaviour change. `DynamicSite`, `ResolvedTarget` and the `targets.jsonl` row gain a `role` naming what the operand denotes — a typed enum (`PROGRAM`, `TRANSID`, `MAP`, `MAPSET`, `FILE`) serialised by value, following `UnresolvedReason`'s precedent. Every existing row reads `role: "PROGRAM"`.

`target_identity` gains the role: `(caller, node, role)`. Without it, the second dynamic operand at one CFG node is deduped away (Review Focus 6). The build's `_covered_sites` matches sites on `(caller, operand name)`; check it still matches each site to its own row once a node can hold several.

Gate: the Global Constraints gate EMPTY DIFF, both suites unmoved. One test asserts a round-tripped row carries its role; another writes two rows at one node with different roles and asserts both survive the writer.

### Task 2: Generalise the three-way rule over a (verb, role) table

Add the nine candidate `EdgeKind` members — the variants of `READS`, `WRITES`, `UPDATES`, `DELETES`, `ENDS_BROWSE`, `RETURN_TRANSID`, `START_TRANSID`, `SENDS_MAP`, `RECEIVES_MAP` — and ONE table mapping `(verb, role)` to `(NodeKind, ordinary EdgeKind, candidate EdgeKind)`, replacing `_ORDINARY` and `_CANDIDATE`. Generalise `DYNAMIC_TARGET`'s docstring from "a dynamic CALL/XCTL/LINK site" to any dynamic reference, with the role in `attrs`.

Promotion stays exactly one condition: one candidate AND empty reasons. Only PROGRAM rows exist yet, so `cobble-compare --graph` stays EMPTY DIFF.

### Task 3: Resolve a dynamic TRANSID

`_return_verb` and `_start_verb` stop calling `_resolve_operand`; the operand is carried unresolved and resolved from the settled state. Candidates become `TRANSACTION` nodes.

**Measure the expected graph delta and state it before regenerating anything.** Count how many `TRANSID` operands in the corpus are data names, and what each resolves to.

### Task 4: Resolve a dynamic FILE

`_file_verb` likewise, with `CICS_FILE` nodes. Eight verbs, five edge kinds. The table must reject an unmapped verb rather than defaulting. Measure and state the expected delta first.

### Task 5: Resolve a dynamic MAP and MAPSET, including the composed id

The hard one. Rules to implement and test, each with a concrete assertion:

- both operands literal: behaves exactly as today;
- one dynamic: candidates composed against the literal half;
- both dynamic: the cross product, **capped**, with the cap recorded as a reason rather than silently truncated.

Reuse `values.py`'s `MAX_VALUES` and `OVER_BUDGET` rather than inventing a second budget. `CCARD-NEXT-MAPSET.CCARD-NEXT-MAP` is the real both-dynamic case in the corpus.

### Task 6: Delete `_resolve_operand`, regenerate the reference, update the docs

`_resolve_operand`, `_field_value` and `_static_value` go. Literal operands must resolve exactly as before.

Regenerate `cobble/reference/graph.jsonl` and review the delta with the classifier described above, not line by line: group every added and removed row by `(type, kind)` and assert each group's size against the expectation Tasks 3–5 stated. The removed rows must include the fabricated `BMS_MAP` node `CCARD-NEXT-MAPSET.CCARD-NEXT-MAP` and the edges pointing at it; every added row must be a candidate edge, a newly resolved one, or a node they introduce. **A group nobody predicted is a defect in Tasks 3–5, not a new baseline** — once committed, `tests/test_compare.py` enforces it. Regenerate the reference with the gate's own commands, `--dynamic-call-targets` included, or it bakes in a graph without the dynamic-target edges.

Update `cobble/README.md`'s dynamic-target section to cover all five roles, and the stage table if a row changes. No test counts in living documentation.

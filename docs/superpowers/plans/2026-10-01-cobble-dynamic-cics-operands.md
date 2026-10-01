# Dynamic CICS Operands (red-dragon-forge-gra) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Resolve a dynamic `TRANSID`, `MAP`, `MAPSET` or `FILE` operand the way Unit 1 resolved `PROGRAM`, and delete `cics/verb_source_asg.py::_resolve_operand`.

**Architecture:** Unit 1 built the machinery — a value lattice, a `targets.jsonl` artifact, and a three-way edge rule (proven / candidate / explicitly unresolved). This plan generalises it from one operand role to five, driven by a single `(verb, role)` table rather than copied per family.

**Issue:** `red-dragon-forge-gra`. The design it reuses is described in `docs/superpowers/specs/2026-09-30-cobble-dynamic-call-resolution-design.md` §4.5–§4.7 (untracked on the author's machine).

**Worktree:** branched from `origin/main` at `50a144d`, so it lacks `05d64af`, a beads-only commit. Reconcile at merge; no code impact.

## Global Constraints

- Frozen dataclasses. No `Any`, no bare `object`, no unparameterised generics. The Pyright gate is PER-FILE: ~761 pre-existing repo errors are out of scope, zero in files you touch.
- Docstrings are expected; inline `#` comments are prohibited except a one-line header above a module constant.
- No mutating `for` loops. `Sequence`/`Mapping` from `collections.abc`. Concrete equality assertions, never a containment check where a value was available.
- Read JSONL through `fixpoint/rows.py` helpers only — never `json.loads`.
- **Never source `bridge-env.sh`** for the cobble suite: it switches on acceptance tests that already fail for unrelated reasons. Run a suite ONCE, in the foreground. Do not background a suite and wait.
- `make fmt` from the repo root, never `black .`. `uv run lint-imports`. Never `--no-verify`.
- Do not touch `.talismanrc` — reword if flagged (it matches the bare substrings "key" and "pass").
- No `__init__.py` under `tests/`.
- `python-fp-lint`: `C901` ceiling 3, `PLR0915` ceiling 10 statements, no reassignment across branches.
- Worktree prerequisites are already in place: submodules, `.venv`, `cobble/out-parsed` (29 members), `cobble/out-fields/extents.jsonl` (108 MB).

## Review Focus

1. **A composed id with two dynamic halves.** A `BMS_MAP` node's id is `MAPSET.MAP`. Both operands dynamic means a cross product — 11 × 11 is 121 candidates from one site. Task 5 must cap it and record the cap as a reason, not emit 121 edges.
2. **A verb that maps many-to-one.** Eight file verbs collapse onto five edge kinds. A `(verb, role)` table must reject a verb it has no row for rather than defaulting to something.
3. **Promotion must still require empty reasons.** Five roles multiply the chances of a one-candidate-with-a-reason site being published as proven. Task 2 keeps that as one condition, not one per role.
4. **Removing `_resolve_operand` must not drop a literal.** It resolves literals too. After deletion, literal operands must resolve exactly as now — the reference graph is the check.
5. **A dynamic operand with no `targets.jsonl`.** The not-attempted fallback covers XCTL/LINK only. Five roles need it generalised or deliberately scoped, and stated either way.

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

`cobble-compare` is EMPTY DIFF at 448 nodes / 832 edges through Tasks 1–2. Tasks 3–5 will move it **substantially** — 122 operands stop being resolved from declarations and start being resolved from dataflow, so expect candidate edges in volume and some targets to change. Each task states its expected delta BEFORE regenerating anything, and Task 6 does the row-by-row review. Suites: `tests/dataflow/` 899 passed / 13 skipped; `tests/cics/` + `tests/knowledge_graph/` 94 passed.

---

### Task 1: Carry an operand role, with PROGRAM as one of five

No behaviour change. `DynamicSite`, `ResolvedTarget` and the `targets.jsonl` row gain a `role` naming what the operand denotes — a typed enum (`PROGRAM`, `TRANSID`, `MAP`, `MAPSET`, `FILE`) serialised by value, following `UnresolvedReason`'s precedent. Every existing row reads `role: "PROGRAM"`.

Gate: `cobble-compare` EMPTY DIFF, both suites unmoved. A test asserts a round-tripped row carries its role.

### Task 2: Generalise the three-way rule over a (verb, role) table

Add the nine candidate `EdgeKind` members — the variants of `READS`, `WRITES`, `UPDATES`, `DELETES`, `ENDS_BROWSE`, `RETURN_TRANSID`, `START_TRANSID`, `SENDS_MAP`, `RECEIVES_MAP` — and ONE table mapping `(verb, role)` to `(NodeKind, ordinary EdgeKind, candidate EdgeKind)`, replacing `_ORDINARY` and `_CANDIDATE`. Generalise `DYNAMIC_TARGET`'s docstring from "a dynamic CALL/XCTL/LINK site" to any dynamic reference, with the role in `attrs`.

Promotion stays exactly one condition: one candidate AND empty reasons. Only PROGRAM rows exist yet, so `cobble-compare` stays EMPTY DIFF.

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

Regenerate `cobble/reference/` with the row-by-row review Unit 1 used: every removed line must be the fabricated `BMS_MAP` node `CCARD-NEXT-MAPSET.CCARD-NEXT-MAP` or an edge pointing at it; every added line a candidate edge or a newly-resolved one. **An unexplained line is a defect in Tasks 3–5, not a new baseline** — once committed, `tests/test_compare.py` enforces it.

Update `cobble/README.md`'s dynamic-target section to cover all five roles, and the stage table if a row changes. No test counts in living documentation.

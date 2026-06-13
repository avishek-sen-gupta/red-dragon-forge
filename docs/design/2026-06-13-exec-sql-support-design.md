# EXEC SQL Support for RedDragon COBOL — Design

**Date:** 2026-06-13
**Status:** Approved (architecture); slice 1 not yet implemented
**Repo:** `squall` (this repo) — a peer of `cicada`

---

## 1. Motivation

Real CICS business logic — and most production COBOL — embeds SQL via
`EXEC SQL … END-EXEC`. The AWS **CBSA** banking sample (our richest available CICS+LINK
corpus) is **Db2-backed**: its business programs cannot run today because the pipeline
drops EXEC SQL entirely. Supporting EXEC SQL unlocks CBSA and gives RedDragon a second
major COBOL capability alongside CICS.

This document defines a standalone EXEC SQL coprocessor runtime — **Squall** — and the
minimal RedDragon seam it plugs into.

---

## 2. Where EXEC SQL sits (the taxonomy)

EXEC SQL is **not** part of the COBOL language, and **not** a CICS facility. It is a
**coprocessor extension** — handled historically by the Db2 precompiler, which rewrites
each `EXEC SQL … END-EXEC` into `CALL 'DSNHLI'` plus host-variable marshaling, *before*
the COBOL compiler runs.

| Tier | What | Home |
|---|---|---|
| 1. Core COBOL | `MOVE`, `PERFORM`, `COMPUTE`, `CALL`, divisions, file verbs | RedDragon core |
| 2. Coprocessor extensions | `EXEC CICS`, **`EXEC SQL`**, `EXEC DLI` | RedDragon EXEC seam + a per-coprocessor package |
| 3. Services | CICS TM, **Db2**, IMS | runtime (cicada / **squall**) |

EXEC SQL is in tier 2, the **same slot as EXEC CICS** — a peer, not a child.

### 2.1 SQL imposes no execution semantics (the key contrast with CICS)

CICS *owns execution*: pseudo-conversational dispatch, conversational RECEIVE that
**suspends** the program, XCTL/LINK logical levels, the terminal wait. That is why cicada
has a region/dispatcher and why RedDragon gained a `SUSPEND` primitive.

EXEC SQL has **none** of this. Every statement is a **synchronous call**: marshal host
vars → params, execute, marshal results back, set `SQLCODE`, fall through. Identical
control-flow shape to `CALL 'SUBPROG' USING …`. Consequences:

- No region, no dispatcher, no suspend/resume, no logical-level stack.
- Squall touches the `SUSPEND` primitive **not at all**.
- **Cursors** are the only stateful part — `OPEN`/`FETCH`/`CLOSE` — but cursor state is
  just a handle held in the runtime; `FETCH` is a plain synchronous call and the COBOL
  program drives the loop itself (`PERFORM UNTIL SQLCODE = 100`). No control inversion.
- The one seam where CICS and SQL meet is **CICS-DB2 SYNCPOINT** unit-of-work
  coordination — and even there CICS drives; SQL merely exposes commit/rollback. Deferred.

**Squall is therefore passive**: lowering strategy + binding engine + builtins + backend,
with **no runtime driver**. It is asymmetric with cicada (which has a driver); the
work table below has no "region" row.

---

## 3. Target SQL surface (from CBSA)

Static embedded SQL, no dynamic SQL / stored procedures:

```
SELECT … INTO          INSERT / UPDATE / DELETE       COMMIT / ROLLBACK
cursors: DECLARE / OPEN / FETCH / CLOSE               SQLCODE / SQLCA
host variables (:VAR)  EXEC SQL INCLUDE (SQLCA, DCLGEN copybooks)
```

(CBSA histogram: INCLUDE×26, INSERT×10, SELECT×8, UPDATE×6, DELETE×4, COMMIT×3,
DECLARE/OPEN/CLOSE×2, FETCH×2; `INTO` and `SQLCODE` used pervasively.)

---

## 4. The two embedded surfaces (why the binding engine is generic)

Embedded SQL has two distinct surfaces, and only one of them touches COBOL:

- **The embedded envelope** — `:host-var` references, the `INTO :v1,:v2` target list,
  `SQLCODE`/`SQLCA`. Standard across every DB; the *only* thing that touches COBOL.
  **This is all the binding engine handles.**
- **The query** — `SELECT … FROM … WHERE …`, DML, cursor bodies. **Opaque text** to the
  binding engine; handed to the backend, which alone knows the dialect.

So the binding engine does purely lexical, dialect-free work:

1. find `:host-var` tokens and their roles (input params vs `INTO` outputs);
2. strip the embedded-only bits (`INTO :v1,:v2`) and substitute `:VAR` with the backend's
   placeholder → a plain query + an ordered param/result map;
3. at runtime, marshal COBOL field bytes ↔ param values (via `data_layout`/WS region,
   exactly as the CICS builtins do), map result columns back to the `INTO` fields, set
   `SQLCODE`/`SQLCA`.

Backend contract:

```python
class SqlBackend(Protocol):
    def execute(self, sql: str, params: list) -> SqlResult: ...   # rows, rowcount, sqlcode
    # backend owns: placeholder style (? / :name), dialect, transactions, cursors
```

`SqliteBackend` is the first impl. The binding engine is unit-testable against a **fake
backend**; the SQLite backend is testable on its own. Swapping DBs or patching
DB2→SQLite dialect deltas stays entirely inside the backend.

---

## 5. The RedDragon seam (already mostly the right shape)

### 5.1 ProLeap already preprocesses EXEC blocks correctly

ProLeap is a two-stage pipeline. Its **preprocessor** (`CobolPreprocessor`) recognizes
`EXEC SQL` / `EXEC CICS` **alongside `COPY`/`REPLACE`** (`triggers = {copy, exec sql,
exec cics, …}`) and re-emits each block as **tagged marker lines** (`*>EXECSQL`). The
**main COBOL grammar** only ever sees those opaque tags
(`EXECSQLLINE : EXECSQLTAG WS …; execSqlStatement : EXECSQLLINE+`) — it **does not parse
SQL**; it slurps the tagged text and hangs an `ExecSqlStatement` node carrying the raw
body. The grammar's only footprint is a **positional opaque placeholder** — legitimate
and necessary (the real compiler likewise sees a `CALL 'DSNHLI'` where the EXEC was).

**No parser re-architecture is warranted.** Recognition already lives in the preprocessor,
where it belongs.

### 5.2 What RedDragon must add

The frontend's current EXEC hook is **CICS-shaped** — a single injected
`exec_cics_strategy: ExecCicsStrategy` (`cobol_frontend.py`). Generalize it:

1. **bridge** `serializeExecSql` — serialize the existing `ExecSqlStatement` opaque text
   (peer of `serializeExecCics`). *(JAR rebuild; Java.)*
2. an **`ExecSqlStatement`** node in the Python frontend's `cobol_statements`
   (peer of `ExecCicsStatement`).
3. a generic **`RedDragonExtensionLoweringStrategy`** protocol (collapse the
   identically-shaped `ExecCicsStrategy` into it: `preprocess_program_dict` /
   `on_procedure_entry` / `lower(stmt)`), and a strategy **registry** keyed by EXEC kind
   (`Mapping[ExecKind, RedDragonExtensionLoweringStrategy]`) replacing the single hook.
4. **frontend dispatch**: on an opaque EXEC placeholder of kind *K*, dispatch to the
   strategy registered for *K* (catch-all warns if none).

All of this is **tier-2 frontend plumbing** — no `vm/**`, `ir.py`, `run.py`, etc. — so it
stays inside the "no RedDragon core edits" invariant. The strategy *implementations* carry
no SQL/CICS semantics in RedDragon; they are injected by the application.

---

## 6. Composition & repository strategy

```
   squall  ───depends on──▶  RedDragon     (RedDragonExtensionLoweringStrategy protocol, EmitContext, IR, data_layout)
   cicada  ───depends on──▶  RedDragon
   cicada  ───depends on──▶  squall        (only when composing CICS + Db2)
```

Acyclic. No `squall → cicada` edge (Squall needs nothing from the CICS runtime).

- **Standalone:** a runner/entrypoint *in squall* builds `CobolFrontend` with
  `{SQL: SqlLoweringStrategy}` injected → plain COBOL VM + SQL, zero CICS.
- **Composed (CBSA):** cicada submodules squall; its bootstrap builds the registry
  `{CICS: CicsLoweringStrategy, SQL: SqlLoweringStrategy}` and injects both. The two
  strategies never reference each other; the registry dispatches by EXEC kind.
- **Single RedDragon pin:** in a composed environment both repos submodule RedDragon —
  keep them pinned to one RedDragon commit; do not let two divergent checkouts coexist.

---

## 7. Preprocessing — two layers (future work, not slice 1)

1. **Source-text layer (inside ProLeap):** COPY/REPLACE expansion + EXEC tagging, already
   one unified pass. **`EXEC SQL INCLUDE → COPY`** belongs here — the included
   SQLCA/DCLGEN fields must exist as source before parsing, since host-var references
   resolve against them. SQL needs no other source-level preprocessing.
2. **Bridge-dict layer (Python, post-bridge, pre-ASG):** today a single hook
   (`cobol_frontend.py:178`, used by CICS for DFHRESP/DFHEIBLK). With the registry this
   becomes a **pipeline** — compose every registered strategy's `preprocess_program_dict`
   in a defined order: `reduce(lambda d, s: s.preprocess_program_dict(d), strategies, d)`.
   CICS and SQL touch disjoint parts of the dict, so chaining is safe.

SQL has **no analog** to CICS's *hidden* injections (DFHEIBLK auto-prologue, DFHRESP/
DFHVALUE translation) — so it needs none of those prepasses. Its only source injection
(`INCLUDE`) is explicit and COPY-shaped. Hence "simpler preprocessor story."

---

## 8. Slices (incremental, TDD)

| # | Scope | Proves |
|---|---|---|
| **1** | `SELECT … INTO :v FROM t WHERE c = :v` against one seeded table; host-var bind; `SQLCODE` 0 / +100 | bridge → registry/dispatch → lower → bind → execute → bind-back → SQLCODE, end-to-end |
| 2 | `INSERT` / `UPDATE` / `DELETE`; `SQLCODE` + rowcount | input-only host-var marshaling, DML |
| 3 | Cursors: `DECLARE` / `OPEN` / `FETCH` / `CLOSE`; program-driven fetch loop | runtime-held cursor state, multi-row |
| 4 | `COMMIT` / `ROLLBACK` | transaction state via backend |
| 5 | `EXEC SQL INCLUDE → COPY`; SQLCA/DCLGEN copybooks | source-layer preprocessing |
| 6 | dict-layer **preprocessor pipeline**; run a real CBSA Db2 program under cicada+squall | dual-coprocessor composition |

**Slice 1 needs neither preprocessor pipeline nor INCLUDE** — explicit host vars + a small
hand-written SQLCA, single strategy.

### Slice-1 work breakdown

| Layer | Work |
|---|---|
| RedDragon bridge | `serializeExecSql` (serialize `ExecSqlStatement` opaque text) |
| RedDragon frontend | generic `RedDragonExtensionLoweringStrategy` protocol; registry (single entry); `ExecSqlStatement` node; dispatch |
| squall | `parser.py` (host-var extract / INTO strip); `binding.py` (generic engine); `backend.py` (protocol); `backends/sqlite.py`; `builtins/` (`__exec_sql`); `strategy.py` (lower SELECT INTO) |
| tests | unit: binding engine vs fake backend; integration: real VM + SQLite, one tiny COBOL program + seeded table |

---

## 9. Testing approach

- **Binding engine** unit-tested against a **fake backend** — proves the generic layer
  (host-var extraction, INTO mapping, marshaling, SQLCODE) in isolation, no DB.
- **SqliteBackend** unit-tested directly (query in → rows/sqlcode out).
- **Integration** exercises real VM execution end-to-end against SQLite.
- TDD throughout: failing test → implement → green.

---

## 10. Invariants

1. No edits to RedDragon's core engine (`interpreter/vm/**`, `ir.py`, `run.py`,
   `executor.py`, `cfg.py`); SQL reaches the VM only via `CallFunction` builtins.
2. No `squall → cicada` dependency; `squall/` does not import `cics` and vice-versa.
3. The binding engine is dialect/backend-agnostic; dialect + placeholder style live only
   in the backend.

---

## 11. Deferred / out of scope

- CICS-DB2 SYNCPOINT unit-of-work coordination (CICS-driven; integration seam).
- Dynamic SQL, `SQLDA`, stored procedures (not in CBSA).
- DB2→SQLite dialect deltas beyond what CBSA's surface needs (handled incrementally,
  inside the backend, as real programs surface them).
- Generalizing whether RedDragon's strategy registry should later subsume other EXEC
  kinds beyond CICS/SQL/SQLIMS.

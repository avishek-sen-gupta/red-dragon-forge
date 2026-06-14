# EXEC SQL Support for RedDragon COBOL — Design

**Date:** 2026-06-13 (updated 2026-06-14)
**Status:** RedDragon seam **SHIPPED** (RedDragon `main` `ab598905`). Squall runtime design settled & validated; build not started.
**Repo:** `squall` (this repo) — a peer of `cicada`

---

## 1. Motivation

Real CICS business logic — and most production COBOL — embeds SQL via `EXEC SQL … END-EXEC`.
The AWS **CBSA** banking sample (our richest CICS+LINK corpus) is **Db2-backed**: its business
programs can't run today because the pipeline dropped EXEC SQL entirely. Supporting EXEC SQL
unlocks CBSA and gives RedDragon a second major COBOL capability alongside CICS.

This document defines a standalone EXEC SQL coprocessor runtime — **Squall** — and the RedDragon
seam it plugs into (now shipped).

---

## 2. Where EXEC SQL sits (the taxonomy)

EXEC SQL is **not** part of the COBOL language, and **not** a CICS facility. It's a **coprocessor
extension** — handled historically by the Db2 precompiler, which rewrites each `EXEC SQL … END-EXEC`
into `CALL 'DSNHLI'` + host-variable marshaling *before* the COBOL compiler runs.

| Tier | What | Home |
|---|---|---|
| 1. Core COBOL | `MOVE`, `PERFORM`, `COMPUTE`, `CALL`, divisions, file verbs | RedDragon core |
| 2. Coprocessor extensions | `EXEC CICS`, **`EXEC SQL`**, `EXEC DLI` | RedDragon EXEC seam + a per-coprocessor package |
| 3. Services | CICS TM, **Db2**, IMS | runtime (cicada / **squall**) |

EXEC SQL is tier 2 — the **same slot as EXEC CICS**, a peer not a child.

### 2.1 SQL imposes no execution semantics (the contrast with CICS)

CICS *owns execution* (pseudo-conversational dispatch, conversational RECEIVE that **suspends**,
XCTL/LINK levels) — hence cicada's region/dispatcher and RedDragon's `SUSPEND` primitive. EXEC SQL
has **none** of it: every statement is a **synchronous call** — marshal host vars → params, execute,
marshal back, set `SQLCODE`, fall through. So:

- No region, no dispatcher, no suspend/resume, no logical-level stack; squall never touches `SUSPEND`.
- **Cursors** are the only stateful part (`OPEN`/`FETCH`/`CLOSE`), but cursor state is a handle held
  in the backend; `FETCH` is synchronous and the COBOL program drives the loop. No control inversion.
- CICS↔SQL meet only at **CICS-DB2 SYNCPOINT** unit-of-work coordination — CICS drives, SQL just
  exposes commit/rollback. Deferred.

**Squall is passive**: parser + lowering strategy + binding engine + builtins + backend, with **no
runtime driver**. Asymmetric with cicada.

---

## 3. Target surface

**CBSA core** (slice targets): `SELECT … INTO`, `INSERT`/`UPDATE`/`DELETE`, cursors
(`DECLARE`/`OPEN`/`FETCH`/`CLOSE`), `COMMIT`/`ROLLBACK`, host variables `:VAR` (+ indicators),
`EXEC SQL INCLUDE` (SQLCA + DCLGEN copybooks). (Histogram: INCLUDE×26, INSERT×10, SELECT×8, UPDATE×6,
DELETE×4, COMMIT×3, cursors, FETCH; `INTO`/`SQLCODE` pervasive.)

**Full EXEC SQL *directive* surface** ≈ **30 constructs** (the precompiler's surface): cursors +
`ALLOCATE CURSOR`; host-var I/O clauses `SELECT/FETCH/VALUES … INTO`, `OPEN … USING`, `WHERE CURRENT
OF`; dynamic SQL `PREPARE`/`EXECUTE`/`EXECUTE IMMEDIATE`/`DESCRIBE`; transactions `COMMIT`/`ROLLBACK`/
`SAVEPOINT`/`RELEASE`; connection `CONNECT`/`SET CONNECTION`/`DISCONNECT`; errors `WHENEVER`/`GET
DIAGNOSTICS`/`SIGNAL`; declarations/inclusion `INCLUDE`/`DECLARE TABLE`/`DECLARE STATEMENT`/`DECLARE
VARIABLE`/`BEGIN|END DECLARE SECTION`; locators `FREE`/`HOLD`/`ASSOCIATE`; `CALL`; `SET`. **The
grammar parses all ~30; lowering implements the CBSA subset first** (an unimplemented directive must
fail at *lowering*, never at *parsing*). Plain SQL (`SELECT`/DML bodies + DDL/admin) is **not** a
directive — it's opaque text that goes to the DB.

---

## 4. The two surfaces, and how host vars are *surfaced*

Embedded SQL has two surfaces, and the boundary is the whole design:

- **The embedded *directive* surface** — cursor verbs, `INTO`/`USING` clauses, host-var refs +
  indicators, `WHERE CURRENT OF`, `INCLUDE`, `WHENEVER`, … This is the precompiler's job (→ `DSNHLI`);
  no DB understands it. **We must parse it.**
- **The SQL *body*** — `SELECT … FROM … WHERE …`, the interiors of DML. **Opaque** to us; host-var-
  substituted and handed to the backend, which alone knows the dialect.

The catch: **host variables are interwoven through the body** (`WHERE acct_id = :WS-ID`, `VALUES (:a)`,
`SET c = :v`), so "directive vs body" is not a clean *text* split. It is, however, a clean **lexer +
grammar** split:

1. **The lexer surfaces host vars — safely, not by regex.** A string/comment/identifier-aware lexer
   tokenizes the whole statement, so a real host var is a `COLON · NAME` token adjacency, while a
   `:foo` inside `'…'` or a `-- …` comment is sealed inside a single `STRING`/`COMMENT` token and
   never becomes `COLON NAME`. (Hyphenated COBOL names like `:HV-ACCOUNT-ID` lex as one identifier.)
   This is precisely why a regex over raw text is wrong and a lexer is required.
2. **The directive grammar assigns site + role.** The lexer finds host-var *tokens*; only the parser
   knows a host var is *under an `INTO` node* vs *in the body*. The grammar parses the directive
   skeleton and treats the SQL body as an **opaque token run that surfaces `host_var` nodes**.
3. **Role (input vs output) = which clause captured the node** — and that mapping is **embedded-SQL
   semantics**, not something the grammar invents:
   - `INTO` (and `FETCH … INTO`, `VALUES … INTO`, `DESCRIBE … INTO`) → **output** (receivers).
   - everywhere else — `WHERE`/`VALUES`/`SET`/select-list/`USING` → **input** (bind params), in
     left-to-right source order.
   - **Exception: `CALL`** — `IN`/`OUT`/`INOUT` lives in the procedure signature, not the syntax or
     the grammar; needs external metadata. Not in CBSA → deferred.

So: **lexer = safe surfacing of host-var tokens; directive grammar = structure + role.** Neither alone
suffices (regex-over-text is unsafe; lexer-only can't assign role). The binding engine then does the
*typed* read/write (§6).

---

## 5. The parser

**A lean Lark directive grammar** (Earley + dynamic lexer), pure-Python, MIT: ~30 directive rules +
an opaque host-var-surfacing `body` rule + a `generic` opaque fallback for DDL/admin. It parses the
full directive surface; lowering implements a subset.

**Validated (2026-06-14 probe).** A ~15-rule Lark prototype correctly handled the three genuinely hard
cases, which are the whole risk:
- **`INTO` overloading** — `SELECT … INTO :hv` (directive output) vs `INSERT INTO t …` (SQL keyword);
- **string-sealed colons** — `WHERE x = 'has :colon'` does not surface `:colon`;
- **`CURRENT OF` vs `CURRENT DATE`** — `SET x = CURRENT DATE WHERE CURRENT OF c` keeps the former in
  the body and parses the latter as the directive.
Role read straight off the capturing clause. The mechanism is proven; scaling to all ~30 is mechanical.

### 5.1 Tool survey (why bespoke, and what we reuse)

- **sqlglot** — *rejected for this layer.* No DB2 dialect; and it **silently mis-parses** hyphenated
  host vars (`:WS-ID` → placeholder `:WS` then `- ID`), errors on indicators, and can't parse
  `INTO`/cursors/`CURRENT OF`. It's a *query-dialect* tool, the wrong layer.
- **IBM `db2-sqlglot-plugin`** — adds a real DB2 *query* dialect to sqlglot, but query-dialect only
  (no host vars/INTO/cursors); early-stage. **Reserved** for optional DB2→SQLite *dialect translation
  behind the backend*, on already-cleaned, host-var-free query text — not for the embedded surface.
- **che4z `Db2SqlExecParser.g4`** (Eclipse/Broadcom, **EPL-2.0**, ANTLR4) — the real **embedded** DB2
  SQL grammar (~500 rules; parses directive **and** full body). A spike (ANTLR→Python) parsed **14/14**
  real CBSA statements clean, hyphenated host vars and all. We use it as the **authoritative
  reference** for the directive surface **and a test oracle** (diff our extraction vs its full parse) —
  **not a runtime dependency**: it parses the entire body (heavier than we need + EPL + ANTLR), and its
  *lean* sibling `Db2SqlParser` is 100% opaque (`sqlCode : ~END_EXEC*`, no host-var extraction). Neither
  che4z grammar is the *directive-with-opaque-body* granularity we want — that's ours to write. (EPL/
  ANTLR are acceptable as reference/oracle; the existing che4z/HLASM dependency in cicada's BMS pipeline
  is precedent.)

### 5.2 Position in the pipeline

**After ProLeap.** ProLeap (host-language parser) tags + extracts each `EXEC SQL` block as opaque text
(`ExecSqlStatement.text`, verbatim envelope) via the bridge; squall's Lark grammar parses **that text**,
at **lowering time** (compile-time, once per statement — the result is baked into the emitted IR; the
runtime builtin never re-parses). Two parsers in sequence, each on its own language. Mirrors the real
precompiler (host scan locates EXEC SQL; SQL parser parses each block).

---

## 6. Binding engine + COBOL↔SQL types

**The COBOL field's PIC *is* the type contract** — that's what DCLGEN (the standard DB2 utility)
guarantees: it generates the host-var `01` record so each column's PIC matches its SQL type:

| DB2 type | COBOL PIC |
|---|---|
| `SMALLINT`/`INTEGER`/`BIGINT` | `PIC S9(4)/S9(9)/S9(18) COMP` (binary) |
| `DECIMAL(p,s)`/`NUMERIC` | `PIC S9(p-s)V9(s) COMP-3` (packed decimal) |
| `CHAR(n)` | `PIC X(n)` |
| `VARCHAR(n)` | group `49 LEN COMP, 49 TEXT X(n)` |
| `DATE`/`TIME`/`TIMESTAMP` | `PIC X(10)/X(8)/X(26)` |
| nullable column | + indicator `PIC S9(4) COMP` |

So the binding engine needs **no runtime type table** — it decodes/encodes each host-var field by its
`data_layout` **category + scale** (→ Python `int`/`Decimal`/`str`), and the matching SQL column type is
whatever the DB has (DCLGEN made them agree). **Codec families:** `ZONED_DECIMAL`, `COMP-3` (scaled →
`Decimal`), `BINARY` (COMP), `ALPHANUMERIC` (CHAR), `VARCHAR` (49-group), indicators.

**Direction of work (role from the parser):**
- **Outputs** = the `INTO` receivers (ordered). Result column[i] → receiver[i], positionally. A receiver
  may be a scalar list *or* a **host structure** (a DCLGEN `01` group) — the grammar gives the target
  name; `data_layout` flattens a group to its elementary fields; columns map onto them in order.
- **Inputs** = body/`USING` host vars (ordered, source order) → bind params.

**The DB driver does the value binding — we never string-interpolate.** We rewrite each host-var token
span → the backend's placeholder (sanitized — `:WS-ID` isn't a legal DBAPI param name) and pass the
decoded Python values; `sqlite3` binds them. (`sqlite3` doesn't bind `Decimal` natively → a small
adapter.) **NULL/indicators:** `:VAR:IND` rides on the host-var node — input: "send NULL"; output:
"receive NULL flag"; a NULL fetched with no indicator → `SQLCODE -305`.

**WS region access:** via `__ws_region` — a **RedDragon-general** local var bound at every program's
procedure entry (`lower_program_init`), not a CICS invention. Squall replicates the ~6-line lookup
(`vm.region_get` + `vm.data_layout`) locally; it does **not** import cicada.

---

## 7. Backend

```python
@dataclass(frozen=True)
class SqlResult: rows: list[tuple]; rowcount: int; sqlcode: int   # 0 / +100 / negative

class SqlBackend(Protocol):
    def execute(self, sql: str, params: list) -> SqlResult: ...
    # cursors are first-class EXEC SQL, so the protocol carries them from the start:
    def open_cursor(self, name: str, sql: str, params: list) -> None: ...
    def fetch(self, name: str) -> SqlResult: ...
    def close(self, name: str) -> None: ...
```

`SqliteBackend` is the first impl — it owns the placeholder style, transactions, cursor handles, and
the **DB2→SQLite dialect**. Dialect deltas (`FETCH FIRST`→`LIMIT`, special registers, `WHERE CURRENT
OF`) are handled here: hand-roll the few CBSA needs, or later run sqlglot + the IBM DB2 plugin on the
*cleaned, host-var-free* query text — entirely behind this seam.

---

## 8. The RedDragon seam — SHIPPED (`main ab598905`)

Done and merged (no further RedDragon work needed for slice 1):
- `ExecSqlStatement` opaque node — carries the raw `EXEC SQL … END-EXEC` text **verbatim** (no string
  surgery; squall parses it).
- bridge `serializeExecSql` (verbatim passthrough, peer of `serializeExecCics`).
- generic `RedDragonExtensionLoweringStrategy` protocol (`handles`/`preprocess_program_dict`/
  `on_procedure_entry`/`lower`) + an `extension_strategies` **array** on `CobolFrontend`, dispatch
  routed by `handles()`. CICS migrated onto the array (cicada `handles()` + bootstrap). Empty array =
  no extension processing. All tier-2 frontend plumbing; no `vm/**`/`ir.py` edits.

Squall plugs in by injecting `extension_strategies=[SqlLoweringStrategy(backend)]` (or `[cics, sql]`).

---

## 9. Composition & repository

```
squall ─▶ RedDragon (RedDragonExtensionLoweringStrategy, EmitContext, IR, data_layout)
cicada ─▶ RedDragon
cicada ─▶ squall      (only when composing CICS + Db2)
```
Acyclic; no `squall → cicada` edge. Standalone: squall builds `CobolFrontend(parser,
extension_strategies=[SqlLoweringStrategy])` — plain COBOL VM + SQL, zero CICS. Composed (CBSA):
cicada submodules squall and injects `[cics, sql]`. Both repos pin **one** RedDragon commit.

---

## 10. Preprocessing

- **Squall's own preprocessing is essential / in-core (not a follow-up).** `EXEC SQL INCLUDE → COPY`
  brings in **SQLCA** (real `SQLCODE`/`SQLSTATE`) and **DCLGEN** copybooks (the typed host-var `01`
  records the binding engine reads). It runs at the **source-text layer**, before ProLeap, because the
  included fields must exist before host-var references resolve. → an early slice.
- **The unified, config-driven preprocessor *pipeline* is a deliberate follow-up** (sequenced *after*
  squall-standalone is proven): a framework where each coprocessor declares its preprocessing steps and
  **config** composes them — CICS (`inject_dfheiblk` source-pass + `DFHRESP` dict-pass) **and** squall
  (`INCLUDE → COPY` + SQLCA) — across the source **and** dict layers. The `extension_strategies`
  `preprocess_program_dict` chain is the seed; the declarative two-layer pipeline is the generalization.

---

## 11. Slices (incremental, TDD)

The **parser** (full ~30-directive Lark grammar + che4z oracle) underpins everything → built first
(slice 0). Then:

| # | Scope | Proves |
|---|---|---|
| **0** | Full directive Lark grammar + lexer; test matrix (per-directive + CBSA samples) vs che4z oracle | the parser, complete on the directive surface |
| **1** | `SELECT … INTO` against one seeded SQLite table; host-var bind; `SQLCODE` 0/+100 (hand-declared SQLCODE) | lower → bind (zoned/int) → execute → bind-back → SQLCODE, end-to-end |
| **2** | `EXEC SQL INCLUDE → COPY`; **SQLCA + DCLGEN** typed host-var records (`COMP-3` etc.) | squall's source-layer preprocessing; the real typed codec |
| **3** | `INSERT`/`UPDATE`/`DELETE`; rowcount | input-only marshaling, DML, driver param binding |
| **4** | Cursors: `DECLARE`/`OPEN`/`FETCH`/`CLOSE`; program-driven loop | backend cursor surface, multi-row, role across statements |
| **5** | `COMMIT`/`ROLLBACK` | transaction state via backend |
| **6** | A real CBSA Db2 program **standalone** (squall only) | the whole vertical on real code |

**Follow-up (after standalone proof):** the declarative CICS+squall preprocessor pipeline (§10) + run a
CBSA CICS+Db2 program under cicada+squall.

### Slice-1 work breakdown (seam already shipped)
| Layer | Work |
|---|---|
| squall | `parser.py` (Lark directive grammar — SELECT INTO subset live, rest parse-only); `binding.py` (role-by-clause, zoned/int codec, `__ws_region`); `backend.py` (`SqlBackend`+cursor surface) + `backends/sqlite.py`; `builtins/exec_sql.py` (`__exec_sql`); `strategy.py` (`SqlLoweringStrategy`) |
| tests | unit: parser matrix vs che4z oracle; binding vs fake backend; sqlite backend direct. integration: real VM + SQLite, one COBOL program (`bridge_jar` fixture) |

---

## 12. Invariants

1. No edits to RedDragon core (`interpreter/vm/**`, `ir.py`, `run.py`, `executor.py`, `cfg.py`); SQL
   reaches the VM only via `CallFunction` builtins.
2. No `squall → cicada` dependency; `squall/` does not import `cics` and vice-versa.
3. Binding engine is dialect/backend-agnostic; dialect + placeholder style live only in the backend.
4. **No regex / string-surgery for SQL parsing** — a string/comment-aware **lexer** + the directive
   **grammar** only. Host vars surface as `COLON NAME` token adjacencies, never via text search.
5. Tests follow the `bridge_jar` fixture pattern (required `PROLEAP_BRIDGE_JAR`, no skip/default).

---

## 13. Deferred / out of scope

- **Dynamic SQL** (`PREPARE`/`EXECUTE`/`DESCRIBE`) and **`CALL`** — the grammar *parses* them; lowering
  is deferred (CALL also needs proc-signature metadata for IN/OUT/INOUT — absent from the syntax).
- **DB2→SQLite dialect translation** beyond CBSA's deltas — incremental, inside the backend (optionally
  sqlglot + IBM DB2 plugin on cleaned query text).
- **CICS-DB2 SYNCPOINT** unit-of-work coordination (CICS-driven seam).
- **The declarative CICS+squall preprocessor pipeline** (§10) — follow-up after standalone proof.

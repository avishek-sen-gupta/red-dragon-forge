# Squall — Directive Grammar + SELECT INTO Vertical (slices 0–1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use `- [ ]` checkboxes.

**Goal:** A working `squall` package that (a) parses the **full EXEC SQL directive surface** with a lean Lark grammar (validated against che4z as an oracle), and (b) executes `SELECT … INTO` **end-to-end** through RedDragon + SQLite, binding host variables and setting `SQLCODE`.

**Architecture (settled — see `../design/2026-06-13-exec-sql-support-design.md`):** The RedDragon seam is **shipped** (`main ab598905`): opaque `ExecSqlStatement`, bridge `serializeExecSql`, `extension_strategies` array. Squall is passive: **parser** (lexer surfaces host vars string-safely; lean directive grammar with opaque host-var-surfacing bodies; role by capturing clause) → **binding engine** (DCLGEN-typed codec via `data_layout`/`__ws_region`) → **`SqlBackend`** (`execute` + cursor surface) / **`SqliteBackend`** → **`__exec_sql` builtin** → **`SqlLoweringStrategy`** on the seam. No runtime driver, no `SUSPEND`.

**Tech stack:** Python 3 (uv), **Lark** (directive grammar), `antlr4-python3-runtime` (che4z oracle, tests only), stdlib `sqlite3`, pytest. Depends on RedDragon (`interpreter.*`) via `vendor/red-dragon` submodule. Integration needs the ProLeap JAR via `PROLEAP_BRIDGE_JAR`.

**Repo:** `~/code/squall` (docs-only today). Work on a branch.

**Invariants:** no `squall → cicada` import; no RedDragon `vm/**`/`ir.py` edits; **no regex/string-surgery for SQL** — lexer + grammar only; tests use the `bridge_jar` fixture (required env, no skip/default).

**Core tenets (every task):** **TDD** — failing test first, watch it fail, minimal pass. **FP** — pure functions over data (parser, extraction, codec, rewrite take values in → values out, no side effects); effects only at the edges (VM region via `binding.py`; DB via `SqlBackend`); enforced by `python_fp_lint`. **Immutability** — frozen dataclasses for all value types (`ParsedSql`, `SqlResult`, …), tuples over lists, never mutate inputs/shared state.

**Scope note:** this plan covers **slice 0** (the full directive parser) + **slice 1** (the SELECT INTO vertical). The grammar **parses all ~30 directives**; only `SELECT … INTO` is *lowered* here — other directives parse fine and raise a clear "not lowered yet" at lowering. Slices 2+ (INCLUDE/SQLCA/DCLGEN, DML, cursors, txns, real CBSA) are follow-up plans.

---

## File structure

```
squall/
  __init__.py
  parser/
    __init__.py
    grammar.lark        # lexer terminals + ~30 directive rules + opaque body
    parse.py            # parse_exec_sql(text) -> ParsedSql (kind, in_vars, out_vars, cursor, query)
  binding.py            # read_params / write_outputs / write_sqlcode (data_layout + __ws_region)
  backend.py            # SqlBackend protocol (execute + open_cursor/fetch/close) + SqlResult
  backends/
    __init__.py
    sqlite.py           # SqliteBackend
  builtins/
    __init__.py
    exec_sql.py         # make_exec_sql_builtin(backend) -> __exec_sql
  strategy.py           # SqlLoweringStrategy (RedDragonExtensionLoweringStrategy)
tests/
  unit/   test_lexer.py, test_grammar_matrix.py, test_che4z_oracle.py, test_parse.py,
          test_sqlite_backend.py, test_binding.py, test_exec_sql_builtin.py, test_strategy.py
  integration/  conftest.py (bridge_jar) + test_select_into_e2e.py
  oracle/   (vendored adapted che4z Db2SqlExec*.g4 + generated Python parser; EPL — see LICENSE note)
pyproject.toml
vendor/red-dragon   (submodule @ ab598905)
```

**Tests:** unit `uv run python -m pytest tests/unit -q`; integration `PROLEAP_BRIDGE_JAR=$HOME/code/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run python -m pytest tests/integration -q`.

---

## Task 0: Scaffold

- [ ] **Submodule:** `git submodule add git@github.com:avishek-sen-gupta/red-dragon.git vendor/red-dragon && git -C vendor/red-dragon checkout ab598905`.
- [ ] **`pyproject.toml`** (uv): deps `lark>=1.1`; dev-deps `pytest>=8`, `black`, `pyright`, `python-fp-lint` (available transitively via the editable RedDragon dep; pin if needed), `antlr4-python3-runtime==4.13.2`; RedDragon as editable path dep (confirm its dist name via `grep '^name' vendor/red-dragon/pyproject.toml`; if not installable, use `pythonpath=[".","vendor/red-dragon"]`). `[tool.pytest.ini_options] pythonpath=["."]`.
- [ ] **Pre-commit** (`.pre-commit-config.yaml`, mirroring RedDragon/cicada): `black` (auto-fix), **`python_fp_lint check squall/`** (the FP tenet), `pyright` (warnings), and the unit test suite. This enforces the FP + immutability tenets mechanically.
- [ ] **Skeleton:** create the `squall/` packages above (empty `__init__.py`), `tests/{unit,integration,oracle}/`.
- [ ] **Verify RedDragon import:** `uv run python -c "from interpreter.cobol.cobol_statements import ExecSqlStatement; print(ExecSqlStatement)"`.
- [ ] **Commit** `chore: scaffold squall (lark + vendor/red-dragon submodule)`.

---

## Task 1: The lexer (string/comment/identifier-aware terminals)

The lexer is the safety layer — host vars surface as `COLON NAME` adjacencies; colons inside strings/comments must NOT.

**Files:** `squall/parser/grammar.lark` (terminals section); `tests/unit/test_lexer.py`.

- [ ] **Step 1 — failing test.** `tests/unit/test_lexer.py`: load the grammar (start rule `generic` for now), assert that for `WHERE x = 'has :colon' AND y = :HV-ID` the only surfaced host var is `HV-ID`; that `-- :cmt` and `/* :c */` surface none; that `:HV-ACCOUNT-ID` is one host var (hyphens); that `:V:IND` surfaces value+indicator. (Use a helper that runs the Lark parser and collects `host_var` nodes.)
- [ ] **Step 2 — run, FAIL.**
- [ ] **Step 3 — implement** the terminals + `host_var`/`generic`/`body` rules from the **proven probe** (Earley + dynamic lexer):
  - `STRING: /'([^']|'')*'/`, line/block comments `%ignore`d, `COLON`, `COMMA`/`LP`/`RP`/`DOT`, `NAME: /[A-Za-z_][A-Za-z0-9_]*(-[A-Za-z0-9_]+)*/`, `NUM`, `OTHER: /[=<>!+\-*\/%|&^~@?]/`.
  - `host_var: COLON NAME (COLON NAME)?` ; `body: _atom*` ; `_atom: host_var | _word | STRING | COMMA | LP | RP | DOT | OTHER | <clause keywords>` ; `_word: NAME | NUM | <statement keywords>` (so keywords are consumable inside opaque bodies).
- [ ] **Step 4 — run, PASS. Step 5 — commit** `feat(parser): string/comment/host-var-aware lexer`.

---

## Task 2: The directive grammar (all ~30, opaque bodies)

Extend to the full directive surface. **Parse all; the grammar must not choke** on any directive even though we only lower `SELECT INTO`.

**Files:** `squall/parser/grammar.lark`; `tests/unit/test_grammar_matrix.py`.

- [ ] **Step 1 — failing test matrix.** `tests/unit/test_grammar_matrix.py`: a table of **one statement per directive** (synthetic, DB2 syntax, drawn from che4z's rule reference) **plus the real CBSA samples**, asserting each parses without error and dispatches to the expected `kind`. Cover: `select_into`, `insert`, `update[ cur_of]`, `delete[ cur_of]`, `merge`, `values_into`, `declare_cursor`, `open[ using]`, `fetch into`, `close`, `commit`, `rollback`, `savepoint`, `release`, `connect`, `prepare`, `execute[ using|into]`, `execute_immediate`, `describe into`, `whenever`, `get_diagnostics`, `signal`, `include`, `declare_table`, `declare_statement`, `declare_variable`, `begin/end declare section`, `free`/`hold`/`associate` locators, `call`, `set`, `lock`, and a `generic` DDL fallback (`CREATE TABLE …`). Include the three proven hard cases (INTO-overload, string colon, `CURRENT OF` vs `CURRENT DATE`).
- [ ] **Step 2 — run, FAIL.**
- [ ] **Step 3 — implement** the ~30 rules, each `KEYWORD … (clauses) … body?`, reusing the opaque-body mechanism. Pure directives (no SQL body) are explicit small rules; DML carries `body`/`cur_of`/`into`; DDL/admin fall to `generic`. The proven probe is the seed — extend rule by rule until the matrix is green. **This is iterative**; the matrix is the contract.
- [ ] **Step 4 — run, PASS (all matrix rows). Step 5 — commit** `feat(parser): full EXEC SQL directive grammar`.

---

## Task 3: che4z oracle cross-check

Vendor che4z's adapted grammar + generated Python parser and cross-validate our extraction against its full parse.

**Files:** `tests/oracle/` (the spike's adapted `gen_Db2SqlExec*.g4` + ANTLR-generated `*.py`, with an `EPL-LICENSE` note); `tests/unit/test_che4z_oracle.py`.

- [ ] **Step 1 — bring the oracle in.** Copy the spike's adapted grammars + generated Python parser (from `/tmp/che4z_sql/gen` during the spike, regenerated reproducibly) into `tests/oracle/`, with the ANTLR generate command recorded in a README and the EPL-2.0 header preserved.
- [ ] **Step 2 — write the cross-check.** `tests/unit/test_che4z_oracle.py`: for every statement in the Task-2 matrix that che4z covers, parse it with che4z, extract its host-var tokens + INTO targets from che4z's tree, and assert our `parse_exec_sql` (Task 4) yields the **same** host-var sets and INTO targets. (Marks divergences as failures — the oracle catches grammar gaps.)
- [ ] **Step 3 — green; commit** `test(parser): che4z oracle cross-check (EPL grammar, test-only)`.

---

## Task 4: `parse_exec_sql` — the extraction API

**Files:** `squall/parser/parse.py`; `tests/unit/test_parse.py`.

`parse_exec_sql(text) -> ParsedSql(kind, in_vars, out_vars, cursor, query)`:
- strip the `EXEC SQL`/`END-EXEC` envelope (fixed delimiters);
- walk the tree: `out_vars` = `host_var` nodes under `into`; `in_vars` = host_var nodes elsewhere, in order; `cursor` = the cursor name for cursor statements; `query` = the body with host-var spans → `?` and the `into` clause removed (span-keyed rewrite).

- [ ] **Step 1 — failing tests** (real shapes): `SELECT acct_bal INTO :WS-BAL FROM account WHERE acct_id = :WS-ID` → `kind=SELECT_INTO, out_vars=["WS-BAL"], in_vars=["WS-ID"], query="SELECT acct_bal FROM account WHERE acct_id = ?"`; `UPDATE … SET x=:V WHERE k=:N` → `in_vars=["V","N"]` (source order), `query` with two `?`; `FETCH FROM C INTO :A,:B` → `kind=FETCH, cursor="C", out_vars=["A","B"], query=None`; the string-colon case yields no spurious host var.
- [ ] **Step 2–4 — FAIL → implement (tree walk + span rewrite) → PASS. Step 5 — commit** `feat(parser): parse_exec_sql extraction (host vars, role, clean query)`.

---

## Task 5: `SqlBackend` protocol + `SqlResult`

**Files:** `squall/backend.py`; `tests/unit/test_sqlite_backend.py` (shared).

- [ ] **Step 1 — failing test:** `SqlResult(rows, rowcount, sqlcode)` fields; a fake with `execute` + `open_cursor`/`fetch`/`close` satisfies `SqlBackend` (`@runtime_checkable`).
- [ ] **Step 2–4 —** implement `backend.py` (the §7 protocol + frozen `SqlResult`). PASS. **Commit** `feat(squall): SqlBackend protocol + cursor surface`.

---

## Task 6: `SqliteBackend`

**Files:** `squall/backends/sqlite.py`; `tests/unit/test_sqlite_backend.py` (append).

- [ ] **Step 1 — failing tests** over a seeded `:memory:` db: `execute("SELECT bal FROM acct WHERE id=?",[11])` → rows + `sqlcode 0`; no-row → `sqlcode 100`; bad SQL → `sqlcode < 0`; cursor: `open_cursor("c","SELECT id FROM acct ORDER BY id",[])` then `fetch("c")` twice yields successive rows then `sqlcode 100`; `close("c")`.
- [ ] **Step 2–4 —** implement (`cur.description is not None` ⇒ SELECT; commit on DML; cursors held in a dict keyed by name). PASS. **Commit** `feat(squall): SqliteBackend (execute + cursors)`.

---

## Task 7: Binding engine

**Files:** `squall/binding.py`; `tests/unit/test_binding.py`. Slice-1 codec = `ZONED_DECIMAL`/numeric + alphanumeric (COMP-3/VARCHAR land in slice 2 with DCLGEN).

- [ ] **Step 1 — failing test:** build a minimal `VMState` with a WS region + `data_layout` for `WS-ID`,`WS-BAL`,`SQLCODE` + the `__ws_region` local var (mirror cicada `tests/unit/cics/test_screen_builtins.py`'s construction — read it in `vendor/red-dragon`? no — it's in cicada; **replicate** the helper locally). Assert `read_params(vm,["WS-ID"])==[11]`; after `write_outputs(vm,["WS-BAL"],(500,))` WS-BAL decodes to 500; after `write_sqlcode(vm,100)` SQLCODE reads 100.
- [ ] **Step 2–4 —** implement: locate WS region via `__ws_region` (call-stack walk → `vm.region_get`); `vm.data_layout.get(name)` → offset/length/category; zoned/int decode+encode (no IR — runtime byte ops). PASS. **Commit** `feat(squall): binding engine (field<->param, SQLCODE)`.

---

## Task 8: `__exec_sql` builtin

**Files:** `squall/builtins/exec_sql.py`; `tests/unit/test_exec_sql_builtin.py`.

`make_exec_sql_builtin(backend)` → `__exec_sql(args, vm)`: `args` = (query, in_var_names, out_var_names) as `Const` values; `params=read_params(vm,in)`; `r=backend.execute(query,params)`; if rows `write_outputs(vm,out,r.rows[0])`; `write_sqlcode(vm,r.sqlcode)`; `BuiltinResult(None)`.

- [ ] **Step 1 — failing test** with a fake backend + the minimal VM (Task 7): assert INTO field set + SQLCODE written. **Step 2–4 — FAIL → implement → PASS. Commit** `feat(squall): __exec_sql builtin`.

---

## Task 9: `SqlLoweringStrategy`

**Files:** `squall/strategy.py`; `tests/unit/test_strategy.py`. Implements `interpreter.cobol.red_dragon_extension_strategy.RedDragonExtensionLoweringStrategy`.

- `__init__(backend)`: register `__exec_sql` into `Builtins.TABLE` (mirror cicada `cics/strategy.py`).
- `handles(stmt)`: `isinstance(stmt, ExecSqlStatement)`. `preprocess_program_dict`: identity. `on_procedure_entry`: no-op.
- `lower(ctx, stmt, materialised)`: `p = parse_exec_sql(stmt.text)`; **if `p.kind != SELECT_INTO`: raise `NotImplementedError(f"EXEC SQL {p.kind} not lowered yet")`** (parse-all/lower-subset); else emit `Const`s for `p.query`, `p.in_vars`, `p.out_vars` + `CallFunction(FuncName("__exec_sql"), …)`.

- [ ] **Step 1 — failing test:** fake ctx (capture `emit_inst`) or real `EmitContext`; `lower(ExecSqlStatement(text="EXEC SQL SELECT acct_bal INTO :WS-BAL FROM account WHERE acct_id = :WS-ID END-EXEC"), …)` emits a `CallFunction` to `__exec_sql` with Const args `("SELECT acct_bal FROM account WHERE acct_id = ?", ["WS-ID"], ["WS-BAL"])`; `handles()` true for ExecSqlStatement / false otherwise; a non-SELECT statement raises `NotImplementedError`.
- [ ] **Step 2–4 — FAIL → implement → PASS. Commit** `feat(squall): SqlLoweringStrategy on the extension seam`.

---

## Task 10: Integration — SELECT INTO end-to-end

**Files:** `tests/integration/conftest.py` (the `bridge_jar` fixture — required `PROLEAP_BRIDGE_JAR`, no skip/default); `tests/integration/test_select_into_e2e.py`.

- [ ] **Step 1 — failing test.** Real JAR parser (`ProLeapCobolParser(RealSubprocessRunner(), bridge_jar)`); seeded `:memory:` SQLite (`ACCOUNT(ACCT_ID, ACCT_BAL)` = `(11, 500)`); `frontend = CobolFrontend(parser, extension_strategies=[SqlLoweringStrategy(SqliteBackend(conn))])`. COBOL program: `01 WS-ID PIC 9(4) VALUE 11.`, `01 WS-BAL PIC 9(9) VALUE 0.`, `01 SQLCODE PIC S9(9) VALUE 0.`, body `EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID END-EXEC. STOP RUN.` Lower → run → assert `WS-BAL` decodes to `500`, `SQLCODE` is `0`. (Mirror cicada integration for the run + region-read; thread `bridge_jar`.)
- [ ] **Step 2 — FAIL.** **Step 3 — wire** whatever the real run surfaces (entry point, WS-region var, SQLCODE field). No fallbacks — declare `SQLCODE` in the program. **Step 4 — PASS. Step 5 — commit** `test(squall): SELECT INTO end-to-end on SQLite`.

---

## Task 11: Wrap-up

- [ ] Full unit suite green; integration green with `PROLEAP_BRIDGE_JAR` exported. `uv run python -m black .`.
- [ ] Commit/push the branch. Note follow-up plans: **slice 2** (INCLUDE→COPY + SQLCA + DCLGEN typed codec — COMP-3/VARCHAR), then DML, cursors, txns, real CBSA standalone; and the **declarative CICS+squall preprocessor pipeline** after standalone proof.

---

## Self-review

**Coverage vs design:** parser (lexer + full directive grammar + oracle) → Tasks 1–4; binding/types (slice-1 codec) → Task 7; backend incl. cursors → Tasks 5–6; builtin/strategy on the shipped seam → Tasks 8–9; INCLUDE/DCLGEN/COMP-3 → slice 2 (deferred, noted); end-to-end → Task 10. Seam = already shipped (no RedDragon tasks).

**No-regex check:** all host-var surfacing is lexer/grammar (Task 1 tests the string/comment seal); Task 9 forbids string surgery; `parse_exec_sql` rewrites by parse-tree spans.

**Parse-all / lower-subset:** Task 2 parses all ~30; Task 9 lowers only `SELECT_INTO` and raises `NotImplementedError` otherwise — so unimplemented directives fail at lowering, never at parsing (per the directive-coverage decision).

**Risks:** (1) the full directive grammar (Task 2) is iterative — the test matrix + che4z oracle are the contract; (2) WS-region/field codec reuse (Task 7) is replicated locally from RedDragon's `data_layout`, never imported from cicada; (3) `Builtins.TABLE` register + `SQLCODE` field presence (Tasks 9–10) confirmed against `vendor/red-dragon` + cicada's pattern during execution.

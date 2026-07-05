# EXEC SQL Slice 2 Implementation Plan — INCLUDE→COPY preprocessing + typed codec

> **For agentic workers:** execute task-by-task with TDD. Steps use `- [ ]`.

**Goal:** squall's source-layer preprocessing (`EXEC SQL INCLUDE → COPY`, shipping SQLCA + DCLGEN
copybooks) and the real typed binding codec (`COMP-3`, binary `COMP`, `VARCHAR` 49-group, indicators).

**Architecture:** A pure `apply_sql_prepass(source: str) -> str` that mirrors cicada's
`apply_cics_prepass` shape (text→text), run before ProLeap so the parser inlines copybooks. squall ships
a `copybooks/` dir (SQLCA + a test DCLGEN record) wired into the parser's `copybook_dirs`. `binding.py`
gains codec families decoded/encoded by `data_layout` category + scale. The combined cicada+squall
pipeline stays a deferred follow-up; we only keep the prepass shape homogeneous.

**Tenets:** TDD, FP (pure functions; effects at edges), immutability (frozen types). **No regex on SQL.**

---

## Contract alignment (settled)

- squall's source pre-pass is `apply_sql_prepass(source: str) -> str` — identical *shape* to cicada's
  `apply_cics_prepass(source: str) -> str`. Both are pure text→text, so a future composite pipeline can
  chain `[apply_cics_prepass, apply_sql_prepass, …]`.
- Copybook dirs: squall ships its own `copybooks/` and supplies it to the parser in squall's own compile
  path (same way cicada supplies the DFHEIBLK dir separately). Bundling *(transform + copybook_dirs)*
  into one shared `SourcePreprocessor` object is deferred to when the combined pipeline is built.

## No-regex discipline for INCLUDE→COPY

The prepass must locate `EXEC SQL … END-EXEC` blocks in raw COBOL **by their fixed delimiters only**
(same fixed-keyword strip already used in `parse.py:_strip_envelope`), then hand each extracted block to
the existing `parse_exec_sql` to classify it. Only blocks whose `kind == "include"` are rewritten to
`COPY <name>.`; every other block is left byte-for-byte untouched. No regex parses SQL content.

---

### Task 1: `apply_sql_prepass` — INCLUDE→COPY (source layer)

**Files:** Create `squall/preprocess.py`; Test `tests/unit/test_preprocess.py`.

- [ ] **Step 1 — failing test.** `apply_sql_prepass` turns an INCLUDE directive into a COPY statement
  and leaves other EXEC SQL blocks and ordinary COBOL untouched:

```python
from squall.preprocess import apply_sql_prepass

def test_include_becomes_copy():
    src = "       EXEC SQL INCLUDE SQLCA END-EXEC.\n"
    assert apply_sql_prepass(src).strip() == "COPY SQLCA."

def test_non_include_exec_sql_untouched():
    src = "       EXEC SQL SELECT A INTO :X FROM T END-EXEC.\n"
    assert apply_sql_prepass(src) == src   # SELECT is not rewritten

def test_plain_cobol_untouched():
    src = "       MOVE 1 TO WS-X.\n"
    assert apply_sql_prepass(src) == src
```

- [ ] **Step 2 — run, expect fail** (`apply_sql_prepass` undefined).
- [ ] **Step 3 — implement.** Scan `source` for `EXEC SQL … END-EXEC` blocks using the FIXED delimiters
  (case-insensitive `EXEC SQL` open, `END-EXEC` close — reuse the same fixed-keyword approach as
  `parse.py`, NOT a SQL regex). For each block, call `parse_exec_sql(block)`; if `kind == "include"`,
  replace the block span with `COPY <cursor-or-name>.` preserving the COBOL area-A indentation of the
  original block's first line; otherwise leave the span unchanged. Return the rebuilt source. Pure
  function. (The `include` rule is `INCLUDE NAME`; the parsed name is on the tree — extend
  `parse_exec_sql`/`ParsedSql` if needed to expose the INCLUDE target name, e.g. reuse the `cursor`
  field or add an `include_name`; pick one and note it.)
- [ ] **Step 4 — run, expect pass.**
- [ ] **Step 5 — edge tests + commit.** Multiple INCLUDEs in one program; an INCLUDE with lowercase
  keywords; an INCLUDE whose name is a DCLGEN record. Commit
  `feat(preprocess): apply_sql_prepass — EXEC SQL INCLUDE → COPY (fixed-delimiter, parser-classified)`.

---

### Task 2: Ship copybooks (SQLCA + a test DCLGEN record)

**Files:** Create `squall/copybooks/SQLCA.cpy`, `squall/copybooks/ACCTREC.cpy`; Test
`tests/unit/test_copybooks.py`.

- [ ] **Step 1 — SQLCA.cpy.** The standard IBM SQLCA `01 SQLCA.` group: `05 SQLCAID PIC X(8)`,
  `05 SQLCABC PIC S9(9) COMP`, `05 SQLCODE PIC S9(9) COMP`, `05 SQLERRM` (VARCHAR group `49 SQLERRML
  PIC S9(4) COMP`, `49 SQLERRMC PIC X(70)`), `05 SQLERRP PIC X(8)`, `05 SQLERRD OCCURS 6 PIC S9(9) COMP`,
  `05 SQLWARN` (10 × `PIC X`), `05 SQLSTATE PIC X(5)`. Area-A/B columns valid for ProLeap.
- [ ] **Step 2 — ACCTREC.cpy** (a minimal DCLGEN-style record proving the typed codec):
  `01 ACCT-REC.` with `05 ACCT-ID PIC S9(9) COMP`, `05 ACCT-BAL PIC S9(7)V9(2) COMP-3`,
  `05 ACCT-NAME` VARCHAR group (`49 ACCT-NAME-LEN PIC S9(4) COMP`, `49 ACCT-NAME-TEXT PIC X(20)`).
- [ ] **Step 3 — test.** Resolve the dir via `importlib.resources.files("squall.copybooks")`; assert
  both `.cpy` files exist and contain `SQLCODE` / `ACCT-BAL` respectively. Commit
  `feat(copybooks): ship SQLCA + ACCTREC DCLGEN copybooks for INCLUDE expansion`.

---

### Task 3: Typed codec — COMP-3, binary COMP, VARCHAR group, indicators

**Files:** Modify `squall/binding.py`; Test `tests/unit/test_codec_typed.py`.

Use RedDragon as the encoding reference (`interpreter/cobol/binary.py` for COMP big-endian two's
complement; `interpreter/cobol/cobol_types.py` `CobolDataCategory` = `COMP3`/`BINARY`/`ZONED_DECIMAL`/
`ALPHANUMERIC` + byte sizes). Decode/encode is selected by the field's `data_layout` `category` (+ scale
for COMP-3). Keep helpers pure.

- [ ] **Step 1 — COMP-3 (packed BCD).** `_comp3_decode(bytes, scale) -> Decimal` (two nibbles/byte,
  last low nibble = sign `0x0D` negative else positive; insert the decimal point per `scale`) and
  `_comp3_encode(Decimal, total_digits, scale) -> bytes`. Tests: round-trip `Decimal("12345.67")`,
  `Decimal("-0.01")`, zero, across digit counts; assert the sign nibble matches RedDragon's
  `ByteConstants`.
- [ ] **Step 2 — binary COMP.** `_binary_decode(bytes) -> int` / `_binary_encode(int, length) -> bytes`
  (big-endian two's complement; 2/4/8-byte sizes per digit count). Prefer delegating to RedDragon's
  `interpreter/cobol/binary.py` if it exposes plain functions; else replicate. Tests: round-trip
  positive/negative/zero at 2/4/8 bytes.
- [ ] **Step 3 — VARCHAR 49-group.** A VARCHAR receiver is a group of `LEN` (binary COMP) + `TEXT`
  (PIC X). Decode → `str` of the first `LEN` chars; encode `str` → set `LEN` + left-justified text.
  The group is surfaced as two elementary fields in `data_layout`; add helpers keyed off the group's
  child layout. Tests: round-trip `"ALICE"` in a `LEN+X(20)` group; empty string.
- [ ] **Step 4 — indicators.** Extend `read_params`/`write_outputs` to honor a host var's `indicator`:
  on output, a NULL column writes `-1` to the indicator field (binary COMP) and leaves the data field;
  a non-NULL writes `0`. On input, an indicator `< 0` sends SQL `NULL` (param = `None`). A NULL fetched
  into a receiver with **no** indicator → `SQLCODE -305` (set via `write_sqlcode`). Tests cover each.
- [ ] **Step 5 — dispatch + sqlite Decimal adapter.** Route `_decode_field`/`_encode_field` by category
  (`ZONED_DECIMAL`/`COMP3`/`BINARY`/`ALPHANUMERIC`/VARCHAR-group). Register a `sqlite3` adapter so
  `Decimal` binds (the backend, at its edge). Commit
  `feat(binding): typed codec — COMP-3 (Decimal), binary COMP, VARCHAR group, indicators`.

---

### Task 4: Wire copybook dirs into squall's compile path + parser construction

**Files:** Modify `tests/integration/squall_cobol_helpers.py` (and any squall compile entry); Test via
Task 5.

- [ ] Construct `ProLeapCobolParser(runner, jar, copybook_dirs=[<squall/copybooks abs path>])` and run
  `apply_sql_prepass(source)` before `frontend.lower(...)` in squall's compile helper. Keep the prepass
  call explicit at the boundary (mirror cicada's bootstrap docstring contract: caller pre-passes once).

---

### Task 5: e2e — INCLUDE SQLCA + DCLGEN record + typed SELECT INTO

**Files:** Create `tests/integration/test_include_dclgen_e2e.py`. Requires `PROLEAP_BRIDGE_JAR`
(build-product JAR). Real `CobolFrontend` + `VMState`, no fakes.

- [ ] A COBOL program that `EXEC SQL INCLUDE SQLCA END-EXEC` (→ COPY SQLCA, providing the real binary
  `SQLCODE`) and `EXEC SQL INCLUDE ACCTREC END-EXEC` (the DCLGEN host record), then
  `EXEC SQL SELECT ACCT_ID, ACCT_BAL, ACCT_NAME INTO :ACCT-ID, :ACCT-BAL, :ACCT-NAME FROM ACCOUNT
  WHERE ACCT_ID = :WS-ID END-EXEC`. Seed SQLite `ACCOUNT(ACCT_ID INTEGER, ACCT_BAL NUMERIC, ACCT_NAME
  TEXT)` with `(11, 1234.56, 'ALICE')`.
- [ ] Assert post-run working storage: `ACCT-BAL` decodes (COMP-3) to `Decimal("1234.56")`, `ACCT-NAME`
  (VARCHAR group) to `"ALICE"`, `ACCT-ID` (binary COMP) to `11`, and the SQLCA `SQLCODE` (binary COMP)
  to `0`. A no-row case → `SQLCODE 100`. Commit
  `test(integration): INCLUDE SQLCA + DCLGEN typed SELECT INTO e2e`.

---

### Task 6: Wrap-up

- [ ] Full suite green (`PROLEAP_BRIDGE_JAR=…/target/proleap-bridge-0.1.0-shaded.jar uv run pytest tests/`).
- [ ] Update design doc §11 slices table: mark slice 2 done. Note any deferrals (e.g. real DCLGEN
  generation vs hand-shipped copybooks; `SQLERRD`/`SQLWARN` unused).
- [ ] `.talismanrc` entries for any new SQL-bearing test files (`ignore_detectors: [filecontent]`).

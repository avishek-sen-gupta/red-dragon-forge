# CardDemo Db2 Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve CardDemo's two Db2 screens — admin `5` "Transaction Type List/Update" (`COTRTLIC`, transid `CTLI`) and admin `6` "Transaction Type Maintenance" (`COTRTUPC`, `CTTU`) — correctly: headless first, then over the TN3270 wire, with writes proven committed through a live Db2.

**Architecture:** A shared fixed-format COBOL line module becomes the only way any prepass rewrites source, so a rewrite cannot push the identification area into the code area. squall derives DCLGEN field metadata structurally instead of requiring its own JSON sidecars, recovers `DECLARE CURSOR` from WORKING-STORAGE, and learns about CICS commit boundaries through named hooks. `red_dragon_forge` composes the CICS and SQL coprocessor specs, because the import-linter contract forbids `cics` from importing `squall`.

**Tech Stack:** Python 3.13, `uv`, pytest, `ibm_db` + live Db2 (LUW), ProLeap COBOL bridge (Java, hard-wired FIXED format), red-dragon's `CoprocessorSpec` seam, `s3270` for the wire test.

**Spec:** `docs/superpowers/specs/2026-09-18-carddemo-db2-tn3270-design.md` — the composition design there is still sound and unchanged. Its "Status" block records the earlier attempt. The behavioural specification for both programs, and the layer surveys this plan is built on, were written to `.superpowers/sdd/db2-epic/` (gitignored scratch); their durable conclusions are recorded on epic `forge-o4q`.

**Epic:** `forge-o4q`. Children: `forge-kgd`, `forge-yuo`, `forge-qhi`, `forge-9kx`, `forge-pkw`, `forge-2xy`, `forge-9ow`.

## Global Constraints

- `cics` must never import `squall`, and `squall` must never import `cics`. Contract `cicada-squall-jackal-independence` in `.importlinter`; verify with `uv run --no-sync lint-imports`.
- **Column preservation is non-negotiable.** Any rewrite of fixed-format source must leave columns 73-80 at columns 73-80. A rewrite may never drag the identification area into the code area, and may never silently push code past column 72.
- Pyright and python-fp-lint are **blocking** pre-commit hooks. New code must pass both. When touching existing code carrying violations, fix them; the `fp.json` exclusion is for code that genuinely must mutate and is the exception, not the rule.
- Never use `--no-verify`.
- Always invoke tools as `uv run --no-sync`.
- Source `. ./bridge-env.sh` from the forge root; add `. ./carddemo-env.sh` for CardDemo paths and `. tests/integration/db2_env.sh` for `SQUALL_DB2_DSN`.
- Db2 tests **skip** when `SQUALL_DB2_DSN` is unset.
- **Committed-state assertions must read through a separate connection** from the one the program under test uses. Asserting through the program's own `Db2Backend` cannot distinguish committed from uncommitted, so a suite built the obvious way passes on every unit-of-work defect in Task 6.
- Headless driving stays first-class (`cics-headless-first-class`): every behaviour is asserted headlessly before any wire test asserts it.
- **Fix defects upstream, where they are. Do not patch downstream.** If the
  ProLeap bridge or its grammar is the wrong shape, change the bridge or the
  grammar — do not build a compensating workaround in squall or cicada. A second
  parser re-deriving what the first one silently discarded is a workaround, not a
  fix, and this repo already carries one dead example of that mistake
  (`dclgen_copybooks`, superseded once the real bug was found).
- RedDragon changes go in `~/code/red-dragon`, never in `vendor/red-dragon`, and
  reach this repo as a submodule bump. That is a different workflow — Maven build,
  a commit and push in that repo, its own issue tracker, then `make jar-force` and
  a submodule bump here — so say so in the handoff when a task takes it.
- CardDemo source is never modified. Eight defects in the vendored programs are to be **reproduced, not fixed** (Task 12).
- Issue changes require `bd export -o issues/issues.jsonl && git add issues/issues.jsonl` before committing.

---

## Why this plan looks the way it does

Four investigations established that the earlier attempt's four "different" blockers were substantially **one** defect wearing four masks. Our own prepasses rewrote fixed-format source without respecting its columns:

`COTRTUPC.cbl:286` is `028600      EXEC SQL INCLUDE DCLTRTYP END-EXEC                          02860000`. squall rewrote the span to `COPY DCLTRTYP.` — 20 characters shorter — so `02860000` slid from column 73 to column 47, inside Area B. ProLeap correctly keeps columns 12-72 as content, so the grammar then saw a bare `02860000` between two `01` groups. Because `dataDescriptionEntryFormat1` may begin with an `INTEGERLITERAL`, ANTLR's error recovery consumed to the next `DOT_FS` and **ate the following `01` as well** — silently, exit 0, no diagnostic. That is how `CARDDEMO-COMMAREA` vanished.

The input was never at fault. The vendored files are valid fixed-format COBOL, and the bridge handles columns 73-80 correctly on its own (`CobolLineReaderImpl` captures the comment area, `CobolLineWriterImpl` never emits it). Every corruption was introduced by us.

Hence Task 1: make a column-breaking rewrite **inexpressible** rather than merely absent.

---

## File Structure

| File | Responsibility |
|---|---|
| `squall/squall/fixed_format.py` | **New.** The four positional zones of a fixed-format line, and the only sanctioned way to rewrite one. |
| `squall/squall/exec_sql_scan.py` | **Modify.** Scan code areas; retire the sequence-number regex. |
| `squall/squall/preprocess.py` | **Modify.** Rewrite spans through the module; collect cursor plans. |
| `squall/squall/dclgen_meta.py` | **New.** Derive `field_meta` structurally from level-49 groups. |
| `squall/squall/strategy.py` | **Modify.** Populate `field_meta` in `preprocess_program_dict`; register the new hooks. |
| `squall/squall/binding.py` | **Modify.** Accept derived metadata; write `SQLERRM`. |
| `squall/squall/backends/db2.py` | **Modify.** Kind-keyed `+100` on zero-row DML; error boundary on `open_cursor`. |
| `squall/squall/builtins/exec_sql.py` | **Modify.** Syncpoint and rollback handlers; cursor registration. |
| `cicada/cics/preprocessor.py` | **Modify.** Ask the line for its code area. |
| `cicada/cics/strategy.py` | **Modify.** Emit `__cics_syncpoint_hook` / `__cics_rollback_hook`; suppress task-end inside a LINK. |
| `cicada/cics/tn3270/config.py` | **Modify.** Plural `source_dirs`/`bms_dirs`, plus `copybook_exts`. |
| `cicada/cics/tn3270/region.py` | **Modify.** `extra_specs` seam; multi-dir resolution. |
| `red_dragon_forge/carddemo_db2_schema.py` | **New.** Schema and seed for the transaction-type tables. |
| `red_dragon_forge/carddemo_db2_region.py` | **New.** The one place the CICS and SQL specs meet. |
| `cicada/config/carddemo-db2-tn3270.toml` | **New.** Region spanning both CardDemo source trees. |
| `tests/integration/conftest.py` | **Modify.** Db2 fixtures, including the separate assertion connection. |
| `tests/integration/test_carddemo_db2_*.py` | **New.** Compile gate, headless CRUD, wire. |

---

### Task 1: The fixed-format line module

The foundation. Everything else assumes a rewrite cannot break columns.

**Files:**
- Create: `squall/squall/fixed_format.py`
- Test: `squall/tests/unit/test_fixed_format.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) class FixedLine` with `sequence: str`, `indicator: str`, `code: str`, `identification: str`, and `raw: str`.
  - `parse_line(raw: str) -> FixedLine`
  - `render(line: FixedLine) -> str`
  - `with_code(line: FixedLine, code: str) -> FixedLine` — raises `CodeAreaOverflow` if `code` exceeds the code area width.
  - `replace_span(lines: Sequence[FixedLine], start: int, end: int, code: str) -> tuple[FixedLine, ...]` — puts `code` on line `start`, empties the code area of lines `start+1..end`, preserves every line's own sequence and identification fields.
  - `class CodeAreaOverflow(ValueError)`

- [ ] **Step 1: Write the failing tests**

```python
_NUMBERED = (
    "028600      EXEC SQL INCLUDE DCLTRTYP END-EXEC                          02860000"
)
_PLAIN = "           MOVE A TO B."


def test_parses_the_four_zones():
    line = parse_line(_NUMBERED)

    assert line.sequence == "028600"
    assert line.indicator == " "
    assert line.code.strip() == "EXEC SQL INCLUDE DCLTRTYP END-EXEC"
    assert line.identification == "02860000"


def test_render_round_trips_exactly():
    assert render(parse_line(_NUMBERED)) == _NUMBERED
    assert render(parse_line(_PLAIN)) == _PLAIN


def test_a_line_with_no_identification_area_does_not_gain_one():
    """Most CardDemo programs have no sequence area at all. Rewriting must not
    manufacture zones by padding every line out to 80 columns."""
    line = parse_line(_PLAIN)

    assert line.identification == ""
    assert render(with_code(line, "MOVE C TO D.")) == "           MOVE C TO D."


def test_shortening_a_rewrite_keeps_the_identification_area_at_column_73():
    """The whole point. COPY DCLTRTYP. is 20 chars shorter than what it
    replaces; 02860000 must not move."""
    rewritten = render(with_code(parse_line(_NUMBERED), "     COPY DCLTRTYP."))

    assert rewritten[72:80] == "02860000"
    assert rewritten[6] == " "
    assert "COPY DCLTRTYP." in rewritten[7:72]


def test_code_that_overflows_the_area_raises_rather_than_truncating():
    with pytest.raises(CodeAreaOverflow):
        with_code(parse_line(_NUMBERED), "X" * 70)


def test_replace_span_empties_later_lines_but_keeps_their_own_fields():
    raw = [
        "028600      EXEC SQL                                                    02860000",
        "028700      INCLUDE SQLCA                                               02870000",
        "028800      END-EXEC                                                    02880000",
    ]
    lines = [parse_line(r) for r in raw]

    out = replace_span(lines, 0, 2, "     COPY SQLCA.")

    assert len(out) == 3
    assert render(out[0])[72:80] == "02860000"
    assert render(out[1])[72:80] == "02870000"
    assert render(out[2])[72:80] == "02880000"
    assert "COPY SQLCA." in render(out[0])
    assert render(out[1])[7:72].strip() == ""
    assert render(out[2])[7:72].strip() == ""
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd ~/code/red-dragon-forge/squall && . ../bridge-env.sh
uv run --no-sync pytest tests/unit/test_fixed_format.py -x -q
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Zones are positional, 1-indexed as COBOL numbers them: sequence = cols 1-6, indicator = col 7, code = cols 8-72, identification = cols 73-80. In Python slices that is `[0:6]`, `[6:7]`, `[7:72]`, `[72:80]`.

A line shorter than 73 characters has an empty `identification`; a line shorter than 7 has an empty `indicator`. `render` must reproduce the original exactly for any line it parsed — so it pads the code area to 65 characters **only when** there is an identification field to keep in place, and otherwise right-strips.

The module's docstring must state that the ProLeap bridge is hard-wired to FIXED format (`proleap-bridge/.../Main.java:86` passes no `-format`), which is what makes this positional model correct for this stack.

Keep it fp-lint clean.

- [ ] **Step 4: Add the ANTLR regression test**

The hazard this module exists to prevent is silent, so pin it. `red-dragon`'s own tracker carries the general form; here, assert our module cannot produce it:

```python
def test_rewriting_never_leaves_a_stray_token_in_the_code_area():
    """A bare sequence-shaped token in Area B makes ANTLR's error recovery eat
    the FOLLOWING 01 group, silently and with exit 0. This is what corrupted
    CARDDEMO-COMMAREA. No rewrite may produce it."""
    line = parse_line(_NUMBERED)

    rewritten = render(with_code(line, "     COPY DCLTRTYP."))

    assert "02860000" not in rewritten[7:72]
```

- [ ] **Step 5: Run and commit**

```bash
uv run --no-sync pytest tests/unit/test_fixed_format.py -x -q
git add squall/squall/fixed_format.py squall/tests/unit/test_fixed_format.py
git commit -m "feat(squall): a fixed-format line model that rewrites only the code area"
```

---

### Task 2: Migrate squall's scan and prepass onto the module

**Files:**
- Modify: `squall/squall/exec_sql_scan.py`
- Modify: `squall/squall/preprocess.py`
- Test: `squall/tests/unit/test_exec_sql_scan.py`, `squall/tests/unit/test_preprocess.py`

**Interfaces:**
- Consumes: Task 1's `parse_line`, `replace_span`, `with_code`, `FixedLine`.
- Produces: `apply_sql_prepass(source, copybook_dirs) -> PrepassResult` unchanged in signature, now column-preserving. `find_exec_sql_spans` matches against code areas.

- [ ] **Step 1: Write the failing test that pins the real bug**

```python
def test_include_rewrite_preserves_the_identification_area():
    """The defect that corrupted CARDDEMO-COMMAREA: the rewrite was 20 chars
    shorter, so 02860000 slid from column 73 into Area B."""
    source = (
        "028600      EXEC SQL INCLUDE DCLTRTYP END-EXEC                          02860000\n"
    )

    result = apply_sql_prepass(source, copybook_dirs=[])

    line = result.source.splitlines()[0]
    assert line[72:80] == "02860000"
    assert "COPY DCLTRTYP." in line[7:72]
    assert "02860000" not in line[7:72]
```

- [ ] **Step 2: Add the real-file test**

```python
def test_real_cotrtupc_prepass_leaves_no_sequence_token_in_any_code_area(carddemo_home):
    db2 = carddemo_home / "app-transaction-type-db2"
    source = (db2 / "cbl" / "COTRTUPC.cbl").read_text(encoding="latin-1")

    result = apply_sql_prepass(source, copybook_dirs=[db2 / "dcl"])

    for number, line in enumerate(result.source.splitlines(), start=1):
        assert not re.fullmatch(r"\s*\d{8}\s*", line[7:72]), f"line {number}"
```

`carddemo_home` is an existing fixture in `tests/integration/conftest.py`; if squall's unit suite cannot reach it, resolve the path from `CARDDEMO_HOME` locally and skip when unset.

- [ ] **Step 3: Run to verify both fail**

```bash
cd ~/code/red-dragon-forge/squall && . ../bridge-env.sh
uv run --no-sync pytest tests/unit/test_preprocess.py -x -q
```

- [ ] **Step 4: Rewrite the scan to work on code areas**

`find_exec_sql_spans` currently matches `_EXEC_SQL_OPEN` against raw source with a `(?:\d{6})?` prefix. Replace that model: parse the source into `FixedLine`s once, and match against the joined **code areas**. The sequence-number alternation disappears entirely — there are no sequence digits in a code area by construction.

Delete `_SEQ_NUM_LINE` and the `(?:\d{6})?` prefix. Both existed only to cope with what the module now makes impossible.

Keep `find_exec_sql_spans` iterative — the `fp.json` exclusion for this module stands, and its `exclude_why` should be updated to say the scan is now over `FixedLine`s.

- [ ] **Step 5: Rewrite span replacement through `replace_span`**

`_rewrite_block` returns `f"{indent}COPY {include_name}."`. It must instead hand the code text to `replace_span`, which owns padding and the later lines' fields.

- [ ] **Step 6: Run the squall unit suite**

```bash
uv run --no-sync pytest tests/unit -x -q
```

Expected: all pass. The 12 `test_backend.py[db2]` errors require a live Db2 — if `SQUALL_DB2_DSN` is set they should now pass; if unset they error, which is pre-existing.

- [ ] **Step 7: Commit**

```bash
git add squall/squall/exec_sql_scan.py squall/squall/preprocess.py squall/tests/unit/
git commit -m "fix(squall): rewrite EXEC SQL spans without disturbing the identification area"
```

---

### Task 3: Migrate cicada's prepass onto the module

`cicada/cics/preprocessor.py:92-97` does `line.strip().upper().split()` and compares `tokens[0]` to `"WORKING-STORAGE"`. For `003700 WORKING-STORAGE SECTION.` that token is `003700`, so `DFHEIBLK` and `DFHHANDLE` are **never injected into any sequence-numbered source**. `COTRTLIC` hard-fails on `DFHEIBLK`; `COTRTUPC` degrades to four `unresolvable field reference 'EIBAID'` sentinels.

Every working CardDemo program happens to have no sequence numbers, which is why this was invisible.

`cics` may not import `squall`, so it cannot use Task 1's module directly. See the Ruling below.

**Files:**
- Modify: `cicada/cics/preprocessor.py`
- Test: `cicada/tests/unit/cics/test_preprocessor.py`

**Interfaces:**
- Consumes: nothing from squall (see Ruling).
- Produces: `apply_cics_prepass` unchanged in signature, now correct for sequence-numbered source.

**Ruling for the implementer:** do NOT import squall's module, and do NOT duplicate the whole model. cicada's need is narrow — it inspects a line's code area and inserts whole new lines; it never rewrites within a line. Add a small private helper in `cicada/cics/preprocessor.py` that returns a line's code area (cols 8-72), used by `_is_ws_section`. If a second cicada site ever needs the full model, that is the moment to ask whether the module belongs in red-dragon's `interpreter/` where both packages may import it — raise it then, do not pre-empt it now.

- [ ] **Step 1: Write the failing tests**

```python
def test_working_storage_is_found_in_sequence_numbered_source():
    """003700 WORKING-STORAGE SECTION. — the sequence number is not a token."""
    source = (
        "003600 DATA DIVISION.                                                   00360000\n"
        "003700 WORKING-STORAGE SECTION.                                         00370000\n"
        "003800 01 WS-FOO PIC X.                                                 00380000\n"
    )

    result = apply_cics_prepass(source)

    assert "COPY DFHEIBLK." in result


def test_working_storage_is_still_found_without_sequence_numbers():
    source = " DATA DIVISION.\n WORKING-STORAGE SECTION.\n 01 WS-FOO PIC X.\n"

    assert "COPY DFHEIBLK." in apply_cics_prepass(source)


def test_injection_does_not_disturb_the_identification_area():
    source = "003700 WORKING-STORAGE SECTION.                                         00370000\n"

    result = apply_cics_prepass(source)

    ws_line = next(l for l in result.splitlines() if "WORKING-STORAGE" in l)
    assert ws_line[72:80] == "00370000"
```

Check `apply_cics_prepass`'s real signature before writing these — it may take more than `source`.

- [ ] **Step 2: Run to verify the first fails**

```bash
cd ~/code/red-dragon-forge/cicada && . ../bridge-env.sh
uv run --no-sync pytest tests/unit/cics/test_preprocessor.py -x -q
```

Expected: the sequence-numbered test FAILS, the unnumbered one PASSES.

- [ ] **Step 3: Fix `_is_ws_section`**

Inspect the code area rather than the whole line. Injection already inserts whole new lines (`_inject_after_ws_section`), so nothing else needs to change.

- [ ] **Step 4: Run the full cicada suite and commit**

```bash
uv run --no-sync pytest -x -q
git add cicada/cics/preprocessor.py cicada/tests/unit/cics/test_preprocessor.py
git commit -m "fix(cicada): find WORKING-STORAGE in sequence-numbered source"
```

Expected: all pass — the existing CardDemo programs have no sequence numbers, so they exercise the unchanged path.

---

### Task 4: The compile gate

Prove both programs compile with the specs composed, on a clean tree. **If this fails, stop the plan and report** — Tasks 5 onward assume it.

**Files:**
- Create: `tests/integration/test_carddemo_db2_compile.py`

**Interfaces:**
- Consumes: Tasks 1-3. `squall.coprocessor.build_sql_spec(connections, copybook_dirs=(), initial_connector=NullDbConnector(), *, tolerant=False)`; `cics.coprocessor.build_cics_spec(context_holder, result_holder=None, program_cache=None, ...)`; `interpreter.project.coprocessor_compile.compile_program(source, parser, specs, *, program_source_dirs=(), tolerant=False) -> tuple[Any, LinkedProgram]`.
- Produces: the verified recipe — copybook dirs, `copybook_exts`, `tolerant` — that Tasks 9-11 reuse.

- [ ] **Step 1: Write the test**

Compile both `COTRTUPC` and `COTRTLIC` against an in-memory `SqliteBackend` (compilation never touches a database, so this must not require Db2). Construct the parser directly — `make_parser` takes no `copybook_exts`:

```python
COPYBOOK_EXTS = ["", "cpy", "CPY", "cob", "cbl", "copy", "COPY", "dcl"]
```

`-copybook-ext` **replaces** the bridge's default list rather than extending it, so every extension must be restated. Copybook dirs: the Db2 tree's `cpy`, `cpy-bms`, `dcl`, then `carddemo_home/cpy`, `cpy-bms`, plus squall's and cicada's own `copybooks` directories. `tolerant=True` — CardDemo's hand-written copybooks have no dclgen sidecars.

Do **not** use `stage_sanitised_copybooks`. Raw `.dcl` members parse correctly once Task 2 stops corrupting columns; a test asserting that is the point.

- [ ] **Step 2: Run it**

```bash
cd ~/code/red-dragon-forge && . ./bridge-env.sh && . ./carddemo-env.sh
uv run --no-sync pytest tests/integration/test_carddemo_db2_compile.py -x -q
```

Expected: PASS, with `COTRTUPC` yielding `CARDDEMO-COMMAREA`, `SQLCA`, `DCLTRANSACTION-TYPE` and `DCLTRANSACTION-TYPE-CATEGORY` among its fields. Assert on those four names explicitly — their absence is the signature of the column bug returning.

If it fails, record which of these occurred and stop: copybook resolution; COBOL syntax; lowering (name the field); something else.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_carddemo_db2_compile.py
git commit -m "test(forge): prove both CardDemo Db2 programs compile composed"
```

---

### Task 5: Derive `field_meta` from the level-49 group

`forge-yuo`. squall's VARCHAR codec is correct but unreachable: `binding.py:590,628` gate the 49-group path on `field_meta[name]["category"] == "VARCHAR"`, and `field_meta` is populated only from `<NAME>.json` sidecars that only squall's own generator writes. Measured on the real layout: reading `:DCL-TR-DESCRIPTION` gives `'\x00\x97PURCHASE'`; writing `'CASH ADVANCE'` sets `LEN = -15423` and `TEXT = 'SH ADVANCE'`. `TR_DESCRIPTION` is the only editable column on either screen.

**Files:**
- Create: `squall/squall/dclgen_meta.py`
- Modify: `squall/squall/strategy.py`, `squall/squall/binding.py`
- Test: `squall/tests/unit/test_dclgen_meta.py`, plus a binding round-trip test

**Interfaces:**
- Consumes: the raw bridge JSON that `SqlLoweringStrategy.preprocess_program_dict` (`strategy.py:120`, today a no-op) already receives, carrying `level`, `picture` and `usage` per field.
- Produces: `derive_field_meta(program: Mapping) -> Mapping[str, FieldMeta]` — recognises the DCLGEN VARCHAR shape (a group whose children are a `49` `PIC S9(4) COMP` length followed by a `49` `PIC X(n)` text) and emits `category="VARCHAR"` metadata for it.

- [ ] **Step 1: Write the failing test on the real shape**

```python
_DCLGEN_VARCHAR = {
    "name": "DCL-TR-DESCRIPTION",
    "level": 10,
    "children": [
        {"name": "DCL-TR-DESCRIPTION-LEN", "level": 49, "picture": "S9(4)", "usage": "COMP"},
        {"name": "DCL-TR-DESCRIPTION-TEXT", "level": 49, "picture": "X(50)"},
    ],
}


def test_a_level_49_group_is_recognised_as_varchar():
    meta = derive_field_meta({"data_fields": [_DCLGEN_VARCHAR]})

    assert meta["DCL-TR-DESCRIPTION"]["category"] == "VARCHAR"
    assert meta["DCL-TR-DESCRIPTION"]["length"] == 50


def test_a_plain_group_is_not_varchar():
    plain = {
        "name": "SOME-GROUP",
        "level": 10,
        "children": [{"name": "A", "level": 15, "picture": "X(4)"}],
    }

    assert "SOME-GROUP" not in derive_field_meta({"data_fields": [plain]})
```

Read the actual bridge JSON before finalising these fixtures — dump it for `COTRTUPC` and shape the test to what the bridge really emits, including the real key names for children, level, picture and usage. Do not invent the schema.

- [ ] **Step 2: Add the round-trip test that proves the defect is gone**

```python
def test_varchar_host_variable_round_trips_exactly():
    """Without derived metadata this wrote LEN = -15423 and TEXT = 'SH ADVANCE'."""
    region = _region_with_dclgen_layout()

    write_host_var(region, "DCL-TR-DESCRIPTION", "CASH ADVANCE")

    assert read_host_var(region, "DCL-TR-DESCRIPTION") == "CASH ADVANCE"
```

Build it from the helpers the existing binding tests use; do not invent a new harness.

- [ ] **Step 3: Run to verify they fail, then implement**

`preprocess_program_dict` populates the metadata holder. **`field_meta` is currently an immutable `MappingProxyType`** — see the Ruling.

**Ruling for the implementer:** derived metadata and sidecar metadata must merge, with the **sidecar winning** on conflict, because a sidecar is an explicit statement and derivation is an inference. Replace the holder's contents with a new merged mapping rather than mutating the proxy in place; keep the public value immutable. If that proves impossible without a signature change, report rather than loosening the type.

- [ ] **Step 4: Run the squall suite and commit**

```bash
cd ~/code/red-dragon-forge/squall && . ../bridge-env.sh
uv run --no-sync pytest tests/unit -x -q
git add squall/squall/dclgen_meta.py squall/squall/strategy.py squall/squall/binding.py squall/tests/unit/
git commit -m "feat(squall): derive DCLGEN VARCHAR metadata from the level-49 group"
```

---

### Task 6: CICS commit boundaries reach squall

`EXEC CICS SYNCPOINT` lowers to `__cics_syncpoint` (`cics/strategy.py:131`, `:999`), a pure no-op that never touches SQL. `RETURN`/`RETURN TRANSID` emit `__cics_task_end_hook` (`:1363`) which squall registers (`squall/strategy.py:111`) as `_reset_session` = commit + close cursors (`builtins/exec_sql.py:243`). **`XCTL` emits nothing** (`:1373`), and an **abend emits nothing at all**.

`COTRTUPC` syncpoints at 1557, 1606 and 1637 (after UPDATE/INSERT/DELETE) and at 453, immediately before `XCTL` at 457. `COTRTLIC` syncpoints at 616 (before an XCTL), 1856 and 1909. There is **no `SYNCPOINT ROLLBACK` in either program**.

Each DML site is followed by a `RETURN TRANSID` in the same task, so the happy path does commit today — but only after the screen has claimed success, and the PF3 paths leave the unit of work open across the XCTL into `COADM01C`.

Also found: `make_link_builtin` saves and restores `result_holder` across a LINK but **not** the hook, so a LINKed program's `RETURN` commits its caller's unit of work and closes its cursors mid-task.

**Files:**
- Modify: `cicada/cics/strategy.py`, `squall/squall/strategy.py`, `squall/squall/builtins/exec_sql.py`
- Test: `cicada/tests/unit/cics/test_task_end_hook.py`, a squall registration test, and an integration test in Task 11

**Interfaces:**
- Produces: `__cics_syncpoint_hook` and `__cics_rollback_hook`, emitted by cicada and registered by squall under the same name convention as `__cics_task_end_hook`. `cics` gains no import of `squall`.

- [ ] **Step 1: Write the cicada-side failing tests**

```python
def test_syncpoint_emits_the_syncpoint_hook():
    ir = lower_program("EXEC CICS SYNCPOINT END-EXEC")

    assert _calls(ir, "__cics_syncpoint_hook")


def test_xctl_does_not_emit_the_task_end_hook():
    """Unchanged behaviour, pinned: the task continues in the new program."""
    ir = lower_program("EXEC CICS XCTL PROGRAM('OTHER') END-EXEC")

    assert not _calls(ir, "__cics_task_end_hook")


def test_a_linked_program_return_does_not_fire_the_task_end_hook():
    """A LINKed program's RETURN must not commit its caller's unit of work."""
    ...
```

Follow the existing style in `test_task_end_hook.py` — it already asserts the XCTL behaviour at line 100, so extend rather than reinvent.

- [ ] **Step 2: Write the squall-side test**

Assert `register_default` wires both new names, and that the syncpoint handler commits **without** closing cursors while the task-end handler closes them. Getting that distinction wrong breaks COTRTLIC's paging.

**Ruling for the implementer:** `SYNCPOINT` commits and does **not** close cursors. Real CICS closes non-`WITH HOLD` cursors at syncpoint, but COTRTLIC opens, fetches and closes every cursor inside a single paragraph within one task, so no cursor is ever open across one of its syncpoints. Closing them would be more faithful and equally harmless today; not closing them is simpler and cannot break the observed programs. Record this in the code comment with that reasoning, so a future WITH-HOLD program is a deliberate revisit rather than a surprise.

- [ ] **Step 3: Implement**

Register `__cics_syncpoint_hook` → commit; `__cics_rollback_hook` → rollback + close cursors. Lower `EXEC CICS SYNCPOINT` to the new hook. Lower `EXEC CICS SYNCPOINT ROLLBACK` to the rollback hook (currently unregistered and therefore a loud abend, `forge-1zu.15`).

Suppress the task-end hook for a `RETURN` executing inside a LINK — mirror how `make_link_builtin` already saves and restores `result_holder`.

Abend paths: the dispatcher-level abends (`PGMI`, `TRNI`, `AZCT`) are raised in Python, not IR, so they cannot emit a hook. **Ruling:** `build_cics_spec` gains an optional `on_abend: Callable[[], None] = _noop`, which `red_dragon_forge`'s composition supplies as the rollback callable in Task 10. cicada therefore never names squall, and a CICS-only region keeps its current behaviour exactly.

- [ ] **Step 4: Run both suites, verify the contract, commit**

```bash
cd ~/code/red-dragon-forge && uv run --no-sync lint-imports
cd cicada && . ../bridge-env.sh && uv run --no-sync pytest -x -q
cd ../squall && uv run --no-sync pytest tests/unit -x -q
git commit -m "feat(cicada,squall): carry CICS commit boundaries to the SQL runtime"
```

---

### Task 7: Recover `DECLARE CURSOR` from WORKING-STORAGE

`forge-qhi`. `DataFieldSerializer.serializeEntries` (`proleap-bridge/.../DataFieldSerializer.java:52-65`) covers only `DataDescriptionEntryGroup` and `...Rename`; an `EXEC_SQL` data-description entry falls off the end of the `instanceof` chain — no error, no JSON node. ProLeap *does* build the node and populate its text. Parsing the real `COTRTLIC` yields **11 `EXEC_SQL` nodes and zero `DECLARE`s**, so `ctx.cursors` stays empty and `OPEN` returns SQLCODE −1. Admin option 5 cannot work.

**Ruling: fix this squall-side, not in the bridge.** squall's prepass already finds and parses every `EXEC SQL` span in the raw source, including those in WORKING-STORAGE. Have it collect `DECLARE_CURSOR` plans and hand them over through the existing holder pattern, then empty their code area exactly as a real precompiler does. This needs no Java change, no submodule bump, and keeps the plan inside one repo. If it proves impossible, stop and report — the bridge change is the fallback, and it belongs in `~/code/red-dragon`.

**Files:**
- Modify: `squall/squall/preprocess.py`, `squall/squall/strategy.py`, `squall/squall/builtins/exec_sql.py`
- Test: `squall/tests/unit/test_preprocess.py`, plus a cursor open/fetch test

- [ ] **Step 1: Write the failing test**

```python
def test_a_declare_cursor_in_working_storage_is_collected():
    source = (
        "033800      EXEC SQL                                                    03380000\n"
        "033900           DECLARE C-TR-TYPE-FORWARD CURSOR FOR                   03390000\n"
        "034000               SELECT TR_TYPE FROM CARDDEMO.TRANSACTION_TYPE      03400000\n"
        "034100      END-EXEC                                                    03410000\n"
    )

    result = apply_sql_prepass(source, copybook_dirs=[])

    assert "C-TR-TYPE-FORWARD" in result.cursors
    assert result.source.splitlines()[0][72:80] == "03380000"
    assert "DECLARE" not in result.source
```

- [ ] **Step 2: Add the runtime test**

`OPEN` on a cursor declared in WORKING-STORAGE must return SQLCODE 0, not −1. Use a SQLite backend so this stays a unit test.

- [ ] **Step 3: Implement, run, commit**

`PrepassResult` gains a `cursors` field. Registration happens at compile time through the holder `make_strategy` already reads.

Also in scope, both small and both live-verified: `open_cursor` **raises** on a DB error instead of returning a SQLCODE the way `execute` does; and `FETCH` on an unknown cursor returns `+100` rather than `−501`.

---

### Task 8: SQLCODE fidelity

Three defects that make the runtime lie rather than fail.

**Files:**
- Modify: `squall/squall/backends/db2.py`, `squall/squall/binding.py`
- Test: `squall/tests/unit/test_backend.py`, a binding test

- [ ] **Step 1: Zero-row DML must return +100** (`forge-pkw`)

Live-verified: `rowcount=0, sqlcode=0`. `COTRTUPC:1558` branches `WHEN SQLCODE = +100` into `9700-INSERT-RECORD`, so the "add a new transaction type" path is **dead** — a no-op update reports success and inserts nothing.

**The fix must be kind-keyed**: `CREATE` returns `rowcount=-1`, so a blanket "rowcount 0 means +100" is wrong. Only `UPDATE`, `DELETE` and `INSERT` map zero rows to `+100`.

- [ ] **Step 2: Populate `SQLERRM`**

`binding.py:674` is the sole SQLCA writer and writes only SQLCODE. `COTRTUPC` STRINGs `SQLERRM OF SQLCA` into user-visible messages at lines 1504, 1574, 1614, 1645, 1646 and 1658 — all blank today.

**Ruling:** write the driver's message text, right-padded into the `SQLERRM` `PIC X(70)` VARCHAR shape. Real Db2 fills it with tokens, not prose, but the programs only ever display it, so prose is strictly more useful to an operator and nothing branches on its content. Note in the comment that this diverges from Db2 deliberately.

Verified as **not needed**: SQLSTATE, SQLERRD and SQLWARN — neither program reads any of them.

- [ ] **Step 3: Fix `_varchar_decode`'s rstrip**

It right-strips a value whose `LEN` already delimits it, so a legitimately trailing space is lost. Pin with a test using a description that ends in a space.

- [ ] **Step 4: Run and commit**

---

### Task 9: Region config and the composition seam

**Files:**
- Modify: `cicada/cics/tn3270/config.py`, `cicada/cics/tn3270/region.py`, `cicada/config/*.toml`
- Test: `cicada/tests/unit/cics/test_tn3270_config.py`, `cicada/tests/integration/cics/test_tn3270_region.py`

- [ ] **Step 1: Plural directories and `copybook_exts`**

`RegionConfig.source_dir` → `source_dirs: tuple[Path, ...]`; `bms_dir` → `bms_dirs`; add `copybook_exts: tuple[str, ...]`, optional and empty by default so the bridge's own defaults apply and the existing CICS-only config is untouched. Resolution is first-hit-wins across the ordered tuple, raising a named `ConfigError` listing the directories searched when a declared program is in none of them.

Update every TOML under `cicada/config/` and every caller; `grep -rn "source_dir\b\|bms_dir\b"` across `cicada`, `red_dragon_forge` and `tests` must come back clean outside `docs/`.

- [ ] **Step 2: `extra_specs`**

```python
def build_region(
    config: RegionConfig,
    bridge_jar: str,
    work_dir: Path,
    extra_specs: Sequence[CoprocessorSpec] = (),
) -> ServedRegion
```

`_compiled` moves off `compile_cics_program` onto `compile_program`, passing `[cics_spec, *extra_specs]` and taking `[1]` of its `(frontend, linked)` return. The default empty tuple keeps every existing caller, the `cicada-tn3270` script and the whole wire suite unchanged.

Test the seam with a local stand-in spec whose `source_prepass` records that it ran — cicada cannot import squall, so it must not be tested with squall's spec.

- [ ] **Step 3: `lint-imports`, full cicada suite, commit**

The existing wire tests build regions from these configs and are the real proof this refactor preserves behaviour.

---

### Task 10: Schema, seed, and the composed region

**Files:**
- Create: `red_dragon_forge/carddemo_db2_schema.py`, `red_dragon_forge/carddemo_db2_region.py`, `cicada/config/carddemo-db2-tn3270.toml`
- Modify: `tests/integration/conftest.py`
- Test: `tests/integration/test_carddemo_db2_schema.py`

- [ ] **Step 1: Schema and seed**

Execute the two table DDL files verbatim — `ddl/TRNTYPE.ddl`, `ddl/TRNTYCAT.ddl` — so the schema cannot drift from what the programs expect. Drop in FK order (category first). Create the `CARDDEMO` schema if absent.

**Ruling: skip `XTRNTYPE.ddl` and `XTRNTYCAT.ddl`.** Both fail on Db2 LUW with SQL0104N — `ERASE NO`/`CLOSE NO` are z/OS-only — and the primary keys already create equivalent unique indexes, so nothing is lost. Record that in a comment, citing the SQL code, so it reads as a decision rather than an omission.

Seed the 7 transaction types and 18 categories with parameterised inserts, taking the values from `ctl/DB2LTTYP.ctl` and `ctl/DB2LTCAT.ctl` but not executing those files (licence-header comments and a trailing `COMMIT;` would need hand-rolled SQL splitting). Preserve the vendored misspelling `REVERAL`. Parents before children. **Commit.**

- [ ] **Step 2: Fixtures**

Add to `tests/integration/conftest.py`:
- `db2_dsn` — skips when `SQUALL_DB2_DSN` is unset
- `db2_admin_conn` — a separate **autocommit-on** connection for DDL and seeding
- `db2_probe_conn` — **the load-bearing one.** A third connection used only for assertions. Asserting through the program's own `Db2Backend` cannot distinguish committed from uncommitted, so without this the suite passes on every Task 6 defect.
- `carddemo_db2_schema` — applies Step 1 and yields

Seeding must be committed **before** `Db2Backend` is constructed: its `__init__` (`backends/db2.py:59`) sets `SQL_AUTOCOMMIT_OFF`.

- [ ] **Step 3: The composed region**

`red_dragon_forge/carddemo_db2_region.py` exposing:

```python
def build_db2_region(
    config: RegionConfig, bridge_jar: str, work_dir: Path, dsn: str
) -> tuple[ServedRegion, Connection]
```

It opens the connection, builds `build_sql_spec(connections={"CARDDEMO": Db2Backend(conn)}, copybook_dirs=..., initial_connector=NamedDbConnector("CARDDEMO"), tolerant=True)`, supplies Task 6's `on_abend` rollback callable to `build_cics_spec`, and calls `build_region(..., extra_specs=(sql_spec,))`. It returns the connection so a caller can close it.

This is the only place both runtimes meet. `uv run --no-sync lint-imports` is the gate.

- [ ] **Step 4: The config**

`cicada/config/carddemo-db2-tn3270.toml`: both source trees in `source_dirs`, both BMS trees in `bms_dirs`, the Db2 tree's `cpy`/`cpy-bms`/`dcl` added to `copybook_dirs`, `copybook_exts` restating the bridge's full default list plus `dcl`, and two transactions — `CTTU = "COTRTUPC"` and `CTLI = "COTRTLIC"`, both verified against `csd/CRDDEMOD.csd` and each program's own `LIT-THISTRANID`.

---

### Task 11: Admin 6 and admin 5, headless

The acceptance criteria. Every assertion about committed state goes through `db2_probe_conn`.

**Files:**
- Create: `tests/integration/test_carddemo_db2_headless.py`

**The padding contract for every assertion:** both programs set `DCL-TR-DESCRIPTION-LEN` to `FUNCTION LENGTH` of a `PIC X(50)` field (`COTRTUPC.cbl:1541-1542`, `COTRTLIC.cbl:1843-1844`) — always 50. So assert `RTRIM(TR_DESCRIPTION) = '<text>'` **and** `LENGTH(TR_DESCRIPTION) = 50`. Seed rows loaded by SQL are unpadded, so the length change is itself a useful assertion.

- [ ] **Step 1: Admin 6 — update**

Sign on `ADMIN001`/`PASSWORD`, option `06`, `TRTYPCD='3'` + ENTER (the program normalises it to `03` at 834-842, then SELECTs at 1475-1482 → `CREDIT`). Overtype the description with `CREDIT BALANCE`, ENTER — expect `Changes validated.Press F5 to save` and **no SQL**. Then F5: UPDATE at 1544-1548, SQLCODE 0, SYNCPOINT at 1557.

Assert through `db2_probe_conn`: `TR_TYPE='03'` has `RTRIM(TR_DESCRIPTION)='CREDIT BALANCE'` and `LENGTH(...)=50`.

- [ ] **Step 2: Admin 6 — the commit boundary**

The test that proves Task 6. After F5 but **before** the task's `RETURN`, the row must already be visible on `db2_probe_conn`. Structure this so the assertion happens between the syncpoint and task end — if the driver cannot interleave, assert instead that `COMMIT` reached the backend before the SEND MAP, using a spy.

- [ ] **Step 3: Admin 6 — insert and the `-532` delete**

Type `08` + ENTER → SELECT returns `+100`; F5 → add mode; description `TEST TYPE`; ENTER then F5 → UPDATE returns `+100` → INSERT at 1597-1602 → SYNCPOINT at 1606. Table goes 7 → 8 rows.

Then `03` + F4/F4 → DELETE → **`-532`** (every seed type has child categories, `ON DELETE RESTRICT`), and the table is unchanged at 8 rows. This exercises a real Db2 SQLCODE the program handles explicitly.

- [ ] **Step 4: Admin 5 — list, page, filter, update**

Option `05` → one page, `PAGENO=1`, rows `01`-`07`. Row 5 select `U`, description `REFUND PROCESSED`, ENTER (highlight plus `Update HIGHLIGHTED row. Press F10 to save`, no DML), then **F10**: UPDATE at 1846-1850, SYNCPOINT at 1856. Assert `05` → `REFUND PROCESSED`, length 50.

Filter `03` → `COUNT(1)` at 1803-1814 returns 1, one row shown. Filter `AB` → `TYPE CODE FILTER,IF SUPPLIED MUST BE A 2 DIGIT NUMBER`, no SQL issued.

F7 on page 1 → `No previous pages to display`. F8 needs **two** presses to reach `No more pages to display` — the first only sets `CA-LAST-PAGE-SHOWN` (1546-1549). Pin that as written; it is the program's behaviour, not a bug to fix.

- [ ] **Step 5: Run the whole forge suite and commit**

```bash
cd ~/code/red-dragon-forge
. ./bridge-env.sh && . ./carddemo-env.sh && . tests/integration/db2_env.sh
make test
```

---

### Task 12: Reproduce CardDemo's own defects; document; close out

**Files:**
- Modify: `tests/integration/test_carddemo_db2_headless.py`, `cicada/README.md`, `issues/issues.jsonl`

- [ ] **Step 1: Pin the source defects as characterisation tests**

These are CardDemo bugs. We reproduce them so a future change that "fixes" one is caught as a behaviour change. Never edit `vendor/carddemo`.

The two worth a test each: `COTRTLIC`'s backward-fetch path has **no `+100` branch** (1761-1790), so exhausting it reports a Db2 error rather than the top of the list; and `9300`'s `WHEN OTHER` does not set `CA-DELETE-REQUESTED`, so a non-`-532` delete failure is reported to the operator as **success**. Add a module comment listing the other six from the behavioural spec.

- [ ] **Step 2: Document how to run it**

`cicada/README.md`: move admin `5` and `6` into the working-options table marked as needing Db2, and give the command sequence — `make db2-up`, `. ./carddemo-env.sh`, `. tests/integration/db2_env.sh`, then the server. State that the transaction-type tables are created and seeded at startup, so a restart resets them. No test counts.

- [ ] **Step 3: Close the epic's children and re-scope what remains**

Close `forge-kgd`, `forge-yuo`, `forge-qhi`, `forge-pkw`, `forge-9kx`. Then:

- **`forge-2xy` stays open and becomes the blocker for serving both screens in one region.** Verified: `compile_program` calls `make_strategy()` per program, each `SqlLoweringStrategy.__init__` builds a fresh `_plans` list and overwrites `__exec_sql` globally, so with equal-length pools **program A silently executes program B's SQL against A's host variables**. Two programs of differing length give `IndexError`. This plan serves both transids from one config, so Task 11 will hit it.

  The root cause is a scope mismatch: the **address space** (statement indices) is per-program, but the **resolver** (the `__exec_sql` builtin name) is per-process, so two programs mint the same addresses and one resolver arbitrates. The same mistake shows up in state as well as addressing — only the last-registered program's cursor set is closed at task end, so in a region serving both screens COTRTLIC's two cursors leak.

  **Ruling: implement the two scopes separately, because they are genuinely different, and squall's own docstrings already name them.** `connector.py:9` describes the attachment facility establishing *the thread*; `coprocessor.py:37` describes it handing *a plan-bound program* a live thread. The implementation collapsed both into one process-global registration, contradicting that design.

  | Thing | Scope | Why |
  |---|---|---|
  | statement addresses | **per program** | a Db2 package's statement numbers are local to it — a precompiled program gets its own plan |
  | cursor set, commit boundary, SQLCA | **per task** | they belong to the Db2 thread, which under CICS is the task |

  So: the call site carries program identity alongside the statement index, and the session state (cursors, UOW) hangs off the task rather than off the registration.

  Do **not** implement per-program cursor state. Cursors belong to the thread: real Db2 closes every non-`WITH HOLD` cursor on the thread at commit regardless of which program opened it, and a task that `XCTL`s from A to B keeps the same thread throughout. Per-program cursor state breaks when A opens a cursor, `XCTL`s to B, and B syncpoints — nobody closes it. CardDemo will not catch that (COTRTLIC opens, fetches and closes inside one paragraph and never carries a cursor across an `XCTL`), which is precisely why the model must be chosen deliberately rather than from what the corpus happens to exercise.

  Do not work around any of this by serving one program per region: the symptom disappears while the region stays silently wrong for whoever adds a second SQL program later.
- **`forge-9ow`** — `stage_sanitised_copybooks` now has no purpose: Task 4 proves raw `.dcl` parses. Leave the module in place per the owner's decision, and update the bead to say it is superseded rather than merely uncalled.
- **File new:** no DSNTIAC stub exists and `CALL` by data-name is unsupported, so `COTRTLIC`'s only error-reporting path is silently empty (`CALL LIT-DSNTIAC USING DFHEIBLK, DFHCOMMAREA, SQLCA, ...`). Not on the happy path; needed before error handling can be trusted.
- **File new:** a real-corpus regression fixture. Every defect in this plan existed because squall's and the bridge's fixtures were generated by our own tooling and had never met a real IBM artefact. Without a fixture built from vendored source, the next real program surfaces the same class again.

- [ ] **Step 4: Export, stage, commit**

```bash
bd export -o issues/issues.jsonl && git add issues/issues.jsonl
```

---

## Notes for the executor

**Task ordering is not arbitrary.** Tasks 1-3 make the column bug class unreachable; Task 4 proves it; Tasks 5-8 fix silent wrongness inside squall; Tasks 9-10 build the composition; Tasks 11-12 prove and document it. Task 4 is a gate — if it fails, stop.

**CORRECTION 2026-09-21: `forge-6jj` was never fixed and is still OPEN (P1).** This line originally claimed it was, which is wrong and misled a later session into reporting a known bug as a regression. An unknown-program XCTL still crashes the driver: `RuntimeError: step() called on a region that has terminated`, confirmed on the wire (it drops the connection and takes the server down with it). Main option `09` is the reachable route on both servers; admin `5`/`6` on the plain CICS-only one.

**The Db2 harness.** `squall-db2` on host port **15000**, not `db2server` on 50000 — that one is unrelated and its `db2inst1` password expired 2026-09-12. `squall/.env` pins `DB2_PORT=15000`. `forge-zka` records that the instance dies while the container stays up; the remedy is `make db2-restart`.

**Talisman** will flag some of these files. Findings on this work have been uniformly false positives ("key", "PASSWORD", hex-like strings). Add a `.talismanrc` checksum entry only when every finding on that file is confirmed a false positive, and list every entry added in the handoff. Use the checksum talisman itself prints — it is not a plain sha256 of the file.

**Two things no survey could settle**, both to be answered by execution during Task 11 rather than assumed: whether the syncpoint ordering is observable through the driver (Step 2 has a fallback), and whether `_last_sqlcode()` reading a driver global causes a stale code to surface — it was observed returning `-204` after a *successful* UPDATE. If the latter bites, it is a real defect and deserves its own bead.

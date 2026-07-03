# red-dragon-forge: Composing CICS + EXEC SQL Coprocessors — Design

**Date:** 2026-07-04
**Status:** design approved; implementation not yet started.
**Repo:** `red-dragon-forge` (this repo) — depends on `cicada`, `squall`, and `red-dragon`; none of
those repos gain any awareness of this one or of each other.

---

## 1. Motivation

Real CICS business logic embeds SQL (`EXEC SQL … END-EXEC`) alongside CICS verbs in the same
program. Two peer runtimes already exist over RedDragon's COBOL frontend:

- **Cicada** — the CICS runtime (dispatcher, VSAM, BMS, `CicsLoweringStrategy`).
- **Squall** — the EXEC SQL coprocessor runtime (`SqlLoweringStrategy`, Db2/SQLite backends).

Both plug into RedDragon's `RedDragonExtensionLoweringStrategy` seam (a `CobolFrontend`-level
array: `handles()`-routed dispatch, with `preprocess_program_dict` already looped across every
element of that array). Squall's own design doc anticipated composing the two — but neither
Cicada nor Squall should have to know about the other, or about any other coprocessor either. This
document defines a **third, generic composition layer** that assembles N coprocessors (today:
CICS + SQL; extensible to more later, e.g. EXEC DLI/IMS) without modifying any ingredient repo.

**Why not do this inside Cicada?** Squall's Db2 backend needs a live Db2 test container to prove
anything real; Cicada's own integration suite today needs no database at all (VSAM is in-process).
Folding SQL composition into Cicada would make every Cicada contributor's test run hard-require a
Db2 container — a real, permanent cost to a repo whose current scope is CICS+VSAM+BMS only. Adding
`squall` to Cicada's `pyproject.toml` would also create a permanent dependency edge for all Cicada
users, not just the ones exercising SQL. Keeping the composition in its own repo mirrors a pattern
already used one level down: RedDragon's core stays free of CICS concerns; CICS concerns live one
level up in Cicada. The same logic says: keep Cicada free of SQL/Db2-container concerns, and put
the composed proof one level up again, in `red-dragon-forge`.

**Why not hardcode "CICS + SQL" as the only combination?** The point of this repo is to stay a
place to *bring more coprocessors later* (a future EXEC DLI/IMS strategy is a plausible next
addition — Bank-of-Z conveniently ships an IMS variant of several programs). So the composition
core must be generic over "a list of coprocessor specs," not aware of CICS or SQL by name.

---

## 2. Architecture

```
red-dragon ◀── cicada        (unchanged — no new awareness)
red-dragon ◀── squall        (unchanged — no new awareness)
red-dragon ◀── cicada ◀── red-dragon-forge
                squall ◀── red-dragon-forge
                bank-of-z ◀── red-dragon-forge   (submodule lives here, not in cicada)
```

Acyclic. `cicada` and `squall` are consumed as ordinary path dependencies (git submodules,
editable installs — same convention as `cicada`'s own `vendor/red-dragon`); neither is modified.

### 2.1 `CoprocessorSpec` — the generic extensibility seam

```python
@dataclass(frozen=True)
class CoprocessorSpec:
    name: str
    make_strategy: Callable[[], RedDragonExtensionLoweringStrategy]  # zero-arg; closes over its own config
    source_prepass: Callable[[str], str] = lambda s: s
    owns_execution: bool = False
```

Each ingredient gets a small **adapter module living in this repo** (not in cicada/squall
themselves) that builds a `CoprocessorSpec`:

- `adapters/cics.py` — `build_cics_spec(vsam_engine, screen_queue, input_queue, ...) -> CoprocessorSpec`,
  wrapping `cicada`'s `CicsLoweringStrategy` + `apply_cics_prepass`, `owns_execution=True` (per
  Squall's own design doc: CICS is the only one of the two that imposes execution semantics —
  pseudo-conversational dispatch, `SUSPEND`/resume — SQL is purely synchronous).
- `adapters/sql.py` — `build_sql_spec(connections, field_meta) -> CoprocessorSpec`, wrapping
  `squall`'s `SqlLoweringStrategy` + `apply_sql_prepass`, `owns_execution=False`.

Adding a third coprocessor later means adding one more adapter module — the composition core below
never changes.

### 2.2 `compile_program` — generic compile-time composition

```python
def compile_program(source: bytes, parser, specs: Sequence[CoprocessorSpec], **compile_kwargs):
    strategies = [s.make_strategy() for s in specs]
    prepass = functools.reduce(
        lambda f, g: lambda src: g(f(src)), (s.source_prepass for s in specs), lambda src: src
    )
    return compile_cobol(
        source, parser=parser, extension_strategies=strategies, source_transform=prepass,
        cics_text_parser=parse_exec_cics_text, **compile_kwargs,
    )
```

Calls RedDragon's `compile_cobol` directly (already generic over `extension_strategies`) rather
than reusing Cicada's `compile_cics_program`, which hardcodes a single strategy. This is the one
deliberate, small duplication in this design: `compile_program` mirrors the shape of
`compile_cics_program` (~15 lines), trading a little drift risk (if Cicada's compile orchestration
changes shape later) for zero coupling — Cicada never has to grow a parameter to accommodate this
repo.

### 2.3 Running the compiled program

Execution ownership is genuinely asymmetric (documented in Squall's own design: CICS drives,
SQL/EXEC-DLI-if-ever-added are passive/synchronous), so this repo does not invent a generic
"runner protocol." It picks the (at most one) `owns_execution` spec and hands the compiled
`LinkedProgram` to that owner's existing runner, unmodified:

- With a CICS spec present: reuse Cicada's `run_cics` / `_run_dispatcher_with_runner` /
  `CicsContext` / VSAM engine / screen-input channel protocols exactly as they exist today.
- With no execution-owning spec (SQL-only composition, or a future non-CICS one): a plain
  synchronous VM run — the same "squall standalone" mode Squall already supports on its own.

`_run_dispatcher_with_runner` is a leading-underscore ("private by convention") Cicada helper;
reusing it here is an accepted minor wart rather than a reason to change Cicada's public surface
for this alone. If it becomes annoying, renaming it to public in Cicada is a trivial, isolated
follow-up — not required for this design to work.

---

## 3. First proof target: Bank-of-Z `INQCUST`

- **Submodule**: `vendor/bank-of-z` → `IBM/Bank-of-Z` (the actively-maintained successor to the
  now-archived `cicsdev/cics-banking-sample-application-cbsa`, which its own README points to).
  Only `src/base/cics/{cobol,bms,copy}` is relevant; its IMS/batch/frontend material is ignored for
  this first proof (a future IMS coprocessor could revisit it).
- **Program**: `INQCUST` (`vendor/bank-of-z/src/base/cics/cobol/INQCUST.cbl`) — COMMAREA-driven
  (invoked via `EXEC CICS LINK`, no BMS screen), doing two `SELECT … INTO` queries against
  `CUSTOMER`: a keyed lookup (sort code + customer number) and an
  `ORDER BY CUSTOMER_NUMBER DESC FETCH FIRST 1 ROW ONLY` max-lookup. No cursors, no DML — squarely
  within Squall's already-implemented slice 1/2 (`SELECT INTO`, host-var bind, `INCLUDE`
  SQLCA/DCLGEN, `SQLCODE`).
- **Backend**: Squall's real `Db2Backend` against the existing MOJO/MOJO2 test containers (reusing
  Squall's own docker-compose test infra rather than duplicating it).
- **Test**: an integration test (mirroring Squall's own `bridge_jar` fixture convention) that
  builds `specs=[cics_spec, sql_spec]`, compiles `INQCUST` via `compile_program`, `LINK`s into it
  with a seeded MOJO customer row, and asserts the returned COMMAREA matches (found case) and
  matches low-values for an unknown customer number (not-found case).

### 3.1 Dependency pinning

`red-dragon-forge` is the "root" project depending on both `cicada` and `squall`, each of which
independently vendors its own `vendor/red-dragon`. This repo owns its own `vendor/red-dragon`
submodule and a `[tool.uv.sources] red-dragon = {path=..., editable=true}` override so both
`cicada`'s and `squall`'s transitive `red-dragon` dependency resolve to **one** shared checkout.
All three pins (this repo's, cicada's, squall's) must track the same RedDragon commit — worth a
`doctor`-style check later, not a blocker for this first proof.

---

## 4. Explicitly deferred / out of scope

- **DML-backed programs** (`CREACC`, `XFRFUN`, `UPDACC`, `DELACC`, `DELCUS`, `UPDCUST`) — need
  Squall slice 3 (`INSERT`/`UPDATE`/`DELETE`), not yet built.
- **Cursor-backed programs** (`INQACC`, `INQACCCU`) — need Squall slice 4
  (`DECLARE`/`OPEN`/`FETCH`/`CLOSE`), not yet built.
- **A concrete third coprocessor** (e.g. EXEC DLI/IMS) — the `CoprocessorSpec` abstraction is
  shaped to make adding one straightforward later, but nothing IMS-specific is built now (no
  concrete need for it yet).
- **Bank-of-Z's IMS/batch/frontend material** — entirely out of scope for this proof.
- **CICS-DB2 SYNCPOINT** unit-of-work coordination — deferred per Squall's own design doc.
- Renaming Cicada's `_run_dispatcher_with_runner` to a public name — optional follow-up, not
  required.

---

## 5. Invariants

1. No changes to `cicada`, `squall`, or `red-dragon` — this repo is the only one that knows all
   three exist together.
2. `compile_program` and `CoprocessorSpec` never hardcode "CICS" or "SQL" by name in the core
   composition logic — only the adapter modules do.
3. Exactly one `owns_execution` spec is supported per composed run (reflecting the real, documented
   asymmetry between CICS and SQL) — not a generic multi-driver abstraction, since nothing today
   needs more than one execution owner.
4. Follows the ingredient repos' own engineering tenets where they apply here: TDD, no
   regex/string-surgery for parsing (none of that lives in this repo — parsing stays inside
   Squall/RedDragon), immutable value types for `CoprocessorSpec`.

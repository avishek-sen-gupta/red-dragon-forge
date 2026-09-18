# Serving the Db2 CardDemo screens over TN3270 — design

**Status:** attempted, stopped at Task 1's feasibility gate

Implementation reached the plan's feasibility gate (compiling `COTRTUPC` with
CICS+SQL specs composed) and failed it four times. Three failures were real
squall bugs, fixed and merged on this branch:
- `d0264d8a` + `1fe86146` — `EXEC SQL` was undetectable in fixed-format source
  carrying sequence numbers in columns 1-6.
- `8164a6f3` — the IBM DCLGEN `DECLARE TABLE` preamble reaches ProLeap through
  `COPY` and its grammar rejects it inside a DATA DIVISION.
- `145e59d1` — that strip could delete a real `DECLARE ... CURSOR`.

Two follow-ups are open, NOT fixes that landed: `forge-kgd` (the scan still
misses the trailing cols-73-80 sequence field) and `forge-9ow`
(`stage_sanitised_copybooks` has no production caller). The same gate run also
disproved `forge-525` (see below).

The fourth is a ProLeap copybook-substitution defect, filed as `red-dragon-9hhu`
in red-dragon's own tracker — this is the current blocker. The rest of this
plan (`forge-9kx`) never ran. **Do not re-run this plan without first checking
`red-dragon-9hhu`'s status.**

**Scope:** CardDemo admin menu option `6` (Transaction Type Maintenance, `COTRTUPC`),
headless first, then over the 3270 wire.

## Problem

CardDemo's admin menu offers six options. `COADM02Y.cpy` raises
`CDEMO-ADMIN-OPT-COUNT` from 4 to 6 to admit two Db2 options — admin `5`
"Transaction Type List/Update" (`COTRTLIC`) and admin `6` "Transaction Type
Maintenance" (`COTRTUPC`) — but the shipped TN3270 config serves neither.

The cause is not missing source. Both programs ship, in a *separate* tree,
`vendor/carddemo/app/app-transaction-type-db2/`, which
`cicada/config/carddemo-tn3270.toml` does not point at. Pointing at it is not
sufficient either: `cics/tn3270/region.py`'s `build_region` composes only
`build_cics_spec`, so a program containing `EXEC SQL` has nothing to lower it.
Compiling `COTRTUPC` under the region today fails with
`ValueError: Unknown COBOL statement type: 'EXEC_SQL'`.

`COTRTUPC` is worth the work: it does full CRUD against one table —
`SELECT` (COTRTUPC.cbl:1480), `UPDATE` (:1545), `INSERT` (:1598) and
`DELETE` (:1628), all on `CARDDEMO.TRANSACTION_TYPE`. Transid `CTTU`,
mapset `COTRTUP`, program `COTRTUPC`.

Admin `5` is **out of scope** for this plan. `COTRTLIC` was once believed to
fail parsing outright (`syntax error in line 2899:7 extraneous input
'YYYY-STORE-PFKEY'`), tracked as `forge-525` — that probe ran with the CICS
spec alone, so `EXEC SQL INCLUDE` was never expanded. `forge-525` is now
**closed, disproven**: with the SQL spec composed, `COTRTLIC` parses fine (see
below). Admin `5` is still not served — nobody has built it — but not because
of a parser defect.

## Constraint that shapes everything

The import-linter contract `cicada-squall-jackal-independence` (`.importlinter`)
forbids `cics` from importing `squall`. `build_region` therefore cannot build a
SQL spec itself, and no config key may make it do so dynamically — a runtime
import is the dependency the contract forbids, merely hidden from the linter.

Only `red_dragon_forge/` may import both runtimes. The composed region is
assembled there.

## Design

### 1. Cicada accepts specs it cannot name

`cics/tn3270/region.py`:

```python
def build_region(
    config: RegionConfig,
    bridge_jar: str,
    work_dir: Path,
    extra_specs: Sequence[CoprocessorSpec] = (),
) -> ServedRegion
```

`CoprocessorSpec` is red-dragon's
(`vendor/red-dragon/interpreter/project/coprocessor_compile.py:34`), so cicada
depends only on the interpreter it already depends on. `_compiled` moves off
cicada's single-spec `compile_cics_program` (`cics/bootstrap.py:39`) onto
red-dragon's `compile_program(source, parser, specs, *, program_source_dirs)`
(`coprocessor_compile.py:84`), passing `[cics_spec, *extra_specs]`.

The default empty tuple keeps every existing caller — including the
`cicada-tn3270` console script and the whole wire test suite — unchanged.

The SQL spec applies to **all** programs in the region, not a declared subset.
No config knob: the existing cicada suite is what proves squall's
`source_prepass` and dialect parser leave SQL-free programs alone. If they do
not, that surfaces immediately rather than hiding behind a flag.

### 2. The config spans two source trees

`cics/tn3270/config.py`'s `RegionConfig` is a frozen dataclass; two fields
become plural, because the Db2 programs and the `COTRTUP` map live in a
different tree from the rest of CardDemo:

- `source_dir: Path` → `source_dirs: tuple[Path, ...]`
- `bms_dir: Path` → `bms_dirs: tuple[Path, ...]`

Resolution is first-hit-wins across the ordered tuple, raising a named error if
a declared program is in none of them. All dirs are passed as
`program_source_dirs` so a `CALL` resolves across trees.

`_parser` gains two copybook directories alongside `CICS_COPYBOOKS`: squall's
own (`squall/squall/copybooks`, for `SQLCA`), and the Db2 tree's `dcl/`, where
CardDemo's hand-written DCLGEN copybooks `DCLTRTYP.dcl` and `DCLTRCAT.dcl`
live. `dcl/` is supplied through `build_sql_spec`'s `copybook_dirs`, so the
forge module passes it in one place, not two.

`COTRTUPC` includes those copybooks with `EXEC SQL INCLUDE DCLTRTYP END-EXEC`,
a SQL INCLUDE rather than a COBOL `COPY`. Squall's prepass rewrites that to
`COPY DCLTRTYP.` (`squall/squall/preprocess.py:125`), leaving ProLeap to
resolve it — and ProLeap does not search `.dcl` by default. Its default list is
`["", "cpy", "CPY", "cob", "cbl", "copy", "COPY"]`
(`proleap-bridge/.../Main.java:50-51`), and `-copybook-ext` **replaces** that
list rather than extending it.

`RegionConfig` therefore gains `copybook_exts: tuple[str, ...]`, optional and
empty by default so the CICS-only region is untouched. The Db2 config restates
the whole default list plus `dcl`. No file is renamed and no red-dragon change
is needed: `ProLeapCobolParser.__init__` already accepts `copybook_exts`
(`vendor/red-dragon/cobol_asg/cobol_parser.py:57`).

This also disproves `COTRTLIC`'s presumed parse bug (`forge-525`, now closed).
That probe ran with the CICS spec alone, so the `EXEC SQL INCLUDE` was never
expanded and the copybooks were never inlined; with the SQL spec composed
`COTRTLIC` parses fine.

A dclgen `.json` sidecar (`preprocess.py:130`) is absent for these hand-written
copybooks, so field metadata resolves to `{}` — which is what
`build_sql_spec(..., tolerant=True)` exists for.

Note squall's own `dclgen` is **not** used and must not be: its `generate()`
reads a live SQLite connection via `PRAGMA table_info`, is not Db2-aware, and
raises `NotImplementedError` on VARCHAR — which `TR_DESCRIPTION VARCHAR(50)`
would trip immediately.

### 3. Forge composes the two runtimes

`red_dragon_forge/carddemo_db2_region.py` is the single place both runtimes
meet — forge's package is otherwise just `run.py`. It exposes
`build_db2_region(config, bridge_jar, work_dir, dsn) -> tuple[ServedRegion, Connection]`,
which opens the connection, seeds, builds the SQL spec, and delegates to
cicada. It returns the connection alongside the region because a test must
assert against the database the program wrote to, and must close it:

```python
backend = Db2Backend(ibm_db.connect(os.environ["SQUALL_DB2_DSN"], "", ""))
sql_spec = build_sql_spec(
    connections={"CARDDEMO": backend},
    copybook_dirs=[db2_tree / "dcl"],
    initial_connector=NamedDbConnector("CARDDEMO"),
)
region = build_region(config, bridge_jar, work_dir, extra_specs=(sql_spec,))
```

`initial_connector` models the CICS Db2 attachment facility: the program never
issues `EXEC SQL CONNECT`, exactly as `tests/integration/test_inqcust_e2e.py`
already does for Bank-of-Z's `INQCUST`, which is the working precedent for this
whole composition.

`squall/squall/coprocessor.py:20` is the spec builder; `owns_execution=False`,
so the CICS spec remains the one execution owner.

### 4. Schema and seed

A test helper, run before `Db2Backend` is constructed:

1. Executes the four vendored `.ddl` files verbatim — `TRNTYPE.ddl`,
   `TRNTYCAT.ddl`, `XTRNTYPE.ddl`, `XTRNTYCAT.ddl` — each a single clean
   statement, preceded by a tolerated `DROP`. Reading them rather than
   restating them is what keeps the schema from drifting from the programs.
2. Inserts the 25 seed rows (7 transaction types, 18 categories) with
   parameterised `INSERT`s, taking the values from `ctl/DB2LTTYP.ctl` and
   `ctl/DB2LTCAT.ctl` but not executing those files — they carry a 14-line
   `/* */` licence header and a trailing `COMMIT;`, and hand-rolled
   comment-stripping and semicolon-splitting is not worth 25 rows.
3. **Commits.**

Both tables are created even though `COTRTUPC` queries only
`TRANSACTION_TYPE`, because `TRANSACTION_TYPE_CATEGORY` carries a foreign key
onto it.

The commit ordering is mandatory, not stylistic: `Db2Backend.__init__`
(`squall/squall/backends/db2.py:59`) sets `SQL_AUTOCOMMIT_OFF` the moment it is
constructed, so anything seeded afterwards on that connection is invisible
until the program under test commits.

### 5. Tests, in two stages

**Headless first** — the primary and permanent path, per the standing
`cics-headless-first-class` rule. Sign on as `ADMIN001`, select admin `6`,
assert the `COTRTUP` map renders, then drive fetch → update → re-fetch,
asserting against the table through the live `Db2Backend` the way the existing
VSAM CRUD tests assert through `region.vsam_engine`.

**Then the wire**, through `s3270`, reusing `served_session` from
`cicada/tests/integration/cics/tn3270_helpers.py`. The wire test is added only
once the headless one is green; it proves the adapter, not the behaviour.

Both **skip when `SQUALL_DB2_DSN` is unset**. This is a deliberate divergence
from squall's own convention, where `squall/tests/integration/test_db2_*` fail
loud with no Db2 — recorded here so the inconsistency is a decision rather than
an oversight. It keeps CI green without a Db2 service; the cost is that a
regression in this path is invisible until someone runs it with Db2 up.

## Dependencies

`forge-6jj` (P1) should land first. An XCTL to an uncompiled program abends
`PGMI` internally but hands the driver a result still marked `XCTL`, so it
steps a terminated region and raises `RuntimeError` instead of painting the
abend. A part-wired Db2 region hits that path constantly, and debugging
through a crash is materially harder than through an abend on screen.

## Out of scope

- Admin `5` / `COTRTLIC` — not attempted; not blocked on a parser defect
  (`forge-525`, disproven and closed). Composing it is `forge-9kx`.
- `COBTUPDT.cbl`, the batch counterpart, which belongs to jackal.
- The `DB2ENTRY`/`DB2TRAN` CSD definitions in `csd/CRDDEMOD.csd`: cicada takes
  transid→program mappings from its own TOML, and the Db2 attachment is
  modelled by `initial_connector`.

## Success criteria

1. Selecting admin `6` from the CardDemo admin menu renders the
   Transaction Type Maintenance screen instead of abending.
2. A headless test updates a transaction type and proves the change through
   the live Db2 connection.
3. The same flow works from `s3270` over the wire.
4. `uv run lint-imports` still passes — in particular, `cics` does not import
   `squall`.
5. The existing cicada suite passes unchanged, proving the SQL spec is inert
   for the 16 SQL-free programs.

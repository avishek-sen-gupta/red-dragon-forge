# catnip: the System Catalog as Its Own Component — Design

**Date:** 2026-10-14
**Issue:** red-dragon-forge-zave (blocks red-dragon-forge-jr5, the prebuilt-program runner)
**Deferred:** red-dragon-forge-zqxf (AIX duplicate order), red-dragon-forge-shdi (IDCAMS AIX/PATH/BLDINDEX), red-dragon-forge-y6gk (region/job sharing and locking)

## Problem

On z/OS the catalog and the datasets it labels belong to the system. Batch jobs and CICS
regions use the same catalog and the same VSAM clusters. CardDemo's `CLOSEFIL`/`OPENFIL`
jobs depend on this: they close a file in CICS, update it in batch, then reopen it.

In the forge the catalog is split in two:

- **jackal** owns `SystemCatalog`: labels (`SequentialLabel`, `KsdsLabel`) in
  `catalog.json`, and dataset bytes under `datasets/<DSN>`.
- **cicada** has its own VSAM store. Each region start copies seed `.PS` files into a
  temporary `vsam/<NAME>.dat`. Record lengths and key positions are written by hand in
  the region TOML (`[datasets.NAME]`). An alternate index is a separate copy of the base
  data with a different key offset.

The split has four consequences:

- A record written by a job never reaches a region.
- A region forgets its writes when it restarts.
- cicada accepts unlabelled datasets, which contradicts decision D5 of
  `docs/records/design/2026-10-11-jackal-dataset-decisions.md`.
- A write through CCXREF is not visible through CXACAIX, because each has its own copy of
  `CARDXREF`.

Both sides already store keyed data the same way, through red-dragon's `IndexedDriver`:
fixed-length records, sorted by key, in one flat file. The duplication is in the metadata
and the stores, not in the engine.

## Goal

The catalog and the dataset store it owns become one workspace package, **catnip**, which
jackal and cicada both depend on. A region opens cataloged datasets in place. Setting up
data takes one declarative step, with no setup JCL. Every failure caused by the
configuration names the dataset, the declared value and the value the program needed,
because an agent iterating on the configuration has to be able to find the line to change.

## Decisions

**N1. catnip is a new workspace member.** It cannot live in `red_dragon_forge`, because the
composition layer imports the runtimes and they cannot import it back. It cannot live in
red-dragon either, which knows nothing of z/OS. catnip depends only on red-dragon (its file
drivers). jackal and cicada import catnip. Two import-linter contracts enforce the
boundary:

- catnip imports none of cicada, squall, jackal or `red_dragon_forge`;
- cobble's `cobble-no-runtime` contract also forbids catnip.

**N2. What moves into catnip, and what stays.** These move from jackal unchanged:
`labels`, `dataset` (`Dataset`, which opens the right driver for a label), `system_catalog`
(`SystemCatalog`, `NotCataloged`), `gdg`, `catalog_stores` and `variable_records`
(`VariableRecordDriver`, the RDW codec).

These stay where they are:

- **in jackal:** the per-job view (`DatasetCatalog`: temporary and passed datasets,
  referbacks), DCB merging (`dcb_label`), allocation, FD checks (`record_format`,
  `cobol_files`) and the IDCAMS executor, which is a client of the catalog;
- **in cicada:** file control and its browse cursors.

Both runtimes reach the bytes through the same drivers. What differs is the
program-facing API: COBOL file verbs in jackal, the CICS file API in cicada.

**N3. Catalog objects.** catnip catalogs five kinds of object:

- **sequential datasets** (`SequentialLabel`);
- **clusters** (`KsdsLabel`);
- **alternate indexes:** a DSN, its base cluster's DSN, an alternate key position, and
  whether duplicate keys are allowed;
- **paths:** a DSN naming one AIX, and the thing programs open;
- **GDG bases.**

An AIX and a path have no bytes of their own. `catalog.json` keeps its current shape and
gains AIX and path entries. Removing a cluster removes its AIXs and paths, matching what
z/OS does when a base cluster is deleted. jackal's existing `DELETE` relies on this.

**N4. Reading and writing through a path.**

- A path reads its base cluster in alternate-key order.
- A write, rewrite or delete through a path changes the base cluster, since z/OS allows
  updates through a path.
- A read that finds more records with the same alternate key reports it: COBOL file
  status 02, or CICS `DUPKEY` (RESP 15).
- A write that would repeat a key in a unique AIX is rejected: status 22, or CICS
  `DUPREC`.

The order is computed when the path is opened: records sorted by alternate key, with
duplicates in primary-key order. Nothing is stored, so the order is always current, as
`UPGRADE` promises.

**N5. Known difference from z/OS, deferred (red-dragon-forge-zqxf).** z/OS returns
duplicate alternate keys "in the order in which they were placed in the file", and a
random read returns "the first record written" in a run of duplicates (IBM Enterprise
COBOL, ALTERNATE RECORD KEY clause). N4 agrees with that for data loaded at install. It
differs for records written afterwards, or whose alternate key is rewritten afterwards.

Fixing it means storing each AIX as an index maintained on every write. The user deferred
that on 2026-10-14. Once this work lands, a test pins the z/OS order and is marked
`xfail`, citing zqxf.

**N6. The alternate-key driver belongs to red-dragon.** Alternate record keys are standard
COBOL: `ALTERNATE RECORD KEY ... WITH DUPLICATES`, and `START`/`READ ... KEY IS`. z/OS only
implements them as an AIX plus a path. red-dragon gains a driver over a fixed-length base
file ordered by any key position. It supports:

- point reads, `START`, and reading next and previous;
- writes, rewrites and deletes that update the base file;
- the duplicate-key conditions in N4. `AccessCondition` gains the "more duplicates
  follow" condition.

It replaces the read-only `AlternateKeyDriver` and `open_alternate_key_driver`, which
cicada's engine is the only user of. catnip opens a path as "the base cluster's file,
ordered by this AIX's key". The change is made in `~/code/red-dragon`, then the
submodule is bumped.

**N7. A region works on cataloged datasets in place.**

- A CICS file maps to a DSN through the CSD's `DEFINE FILE(...) DSNAME(...)`, which
  cicada's existing CSD parser reads.
- The label (record length and key position) comes from the catalog. The bytes are the
  catalog's own.
- A new system directory starts empty, and installing copies the seed files into it, so
  a new directory always starts clean. An existing directory keeps what earlier jobs and
  regions wrote. Seed files are never written to.
- A CICS file whose DSN is not cataloged, or is neither a cluster nor a path, stops the
  region at startup. The message names the file and the DSN.

**N8. Setup is declarative: `catnip install <data.toml> --system DIR`.** Running a
codebase's own IDCAMS JCL is not the setup path, and is parked in red-dragon-forge-shdi.
The declaration:

```toml
data_dir = "${FORGE_ROOT}/vendor/carddemo/app/data/EBCDIC"

[[sequential]]
dsn   = "AWS.M2.CARDDEMO.DALYTRAN.PS"
from  = "AWS.M2.CARDDEMO.DALYTRAN.PS"
recfm = "FB"
lrecl = 350

[[ksds]]
dsn        = "AWS.M2.CARDDEMO.CARDXREF.VSAM.KSDS"
from       = "AWS.M2.CARDDEMO.CARDXREF.PS"
lrecl      = 50
key_offset = 0
key_length = 16

[[ksds.aix]]
dsn        = "AWS.M2.CARDDEMO.CARDXREF.VSAM.AIX"
path       = "AWS.M2.CARDDEMO.CARDXREF.VSAM.AIX.PATH"
key_offset = 25
key_length = 11
unique     = false
```

- `from` paths are relative to `data_dir`, and `${VAR}` is expanded.
- A KSDS without `from` is cataloged empty.
- `[[gdg]]` declares a GDG base. CardDemo's data needs none at install.
- The file is parsed into typed models as it is read.
- Install validates the whole declaration before writing anything. It stops at the first
  failure and names the dataset and the field. It rejects:
  - a seed file whose size is not a whole number of records;
  - a primary or alternate key that does not fit inside the record;
  - a KSDS seed with a repeated primary key;
  - a unique AIX over repeated alternate keys;
  - a DSN declared twice;
  - a `from` file that does not exist.
- It then copies each seed in, sorts every KSDS by primary key, and catalogs the AIXs and
  paths.
- The declaration may be written by hand or drafted by a coding agent that iterates over
  it while running the programs. catnip contains no generator.

**N9. CardDemo's declaration is the forge's own: `config/carddemo/data.toml`.** It carries
what `red_dragon_forge/carddemo_jackal_install.py` lists today (the sequential files
labelled from CardDemo's README), plus the clusters, AIXs and paths that CardDemo's IDCAMS
JCL defines. It replaces that module and `make jackal-install`. CardDemo ships no
TRANSACT seed. The region TOML loads it from `DALYTRAN.PS`, which has the same layout, and
the declaration keeps that choice and states it.

**N10. Config-caused failures name both sides.**

- **jackal:** an FD that conflicts with a label already sets status 39. It also logs the
  DSN, the declared value and the FD's value.
- **cicada:** `LENGERR` or `NOTFND` caused by the declared shape logs the CICS file, its
  DSN, the declared record length and key position, and the program's `LENGTH` and
  `RIDFLD` sizes.

These are logged rather than raised, because a COBOL program may handle the condition
itself.

**N11. The region configuration.** In the region TOML, `[datasets.*]` and `data_dir` are
replaced by `system = "DIR"` and `csd_files = [...]`.

The following are removed:

- `DatasetConfig`'s record length and key fields;
- `cics/vsam/seed.py`, and the seeding half of `cics/vsam/format.py`;
- the per-start `work_dir/vsam` copies;
- the alternate-index copies.

`cics/vsam/dump.py` decodes a cataloged DSN instead of a `.dat` file. jr5's `env.toml`
inherits this shape.

**N12. Out of scope.**

- A region and a job using one system directory at the same time
  (red-dragon-forge-y6gk). Neither locks anything, which is no worse than today.
- Variable-length KSDS records: CardDemo's CSD says `RECORDFORMAT(V)`, but its data is
  fixed length.
- ESDS and RRDS clusters.

## Order of work

Each unit can be committed on its own and keeps every suite green.

1. **red-dragon: the alternate-key driver** (N6), with its unit tests upstream, then a
   submodule bump. The old `AlternateKeyDriver` stays until unit 5 has moved cicada off
   it. A red-dragon commit then removes it, followed by a final bump.
2. **catnip, moved without changes** (N1, N2): the workspace member, its `pyproject.toml`,
   the import-linter contracts, and jackal importing from catnip. jackal's catalog tests
   move with their modules. Behaviour does not change.
3. **AIXs and paths** (N3, N4): catalog entries, the `catalog.json` format, opening a
   path, and removing a cluster removing its AIXs and paths.
4. **`catnip install`** (N8, N9): parsing, validation, loading,
   `config/carddemo/data.toml`, and removing `carddemo_jackal_install.py` and
   `make jackal-install`. Root and jackal tests that install CardDemo switch to the
   declaration.
5. **cicada on catnip** (N7, N10, N11): file control through the catalog and the CSD;
   the region TOMLs changed; `cobol_harness/vsam.py` and every VSAM and CardDemo
   end-to-end test installing into its own `tmp_path` system directory; seeding removed.
   The CardDemo end-to-end suite is the regression gate. This unit also adds the test
   that a record written through CCXREF is read back through CXACAIX, and N5's `xfail`
   test.
6. **Docs:**
   - a catnip reference page (the declaration format, the catalog objects, install);
   - updates to the jackal and cicada architecture and configuration pages, and
     `docs/README.md`;
   - a decision record for the extraction, which supersedes the 2026-09-09
     package-boundaries record's placement of the catalog. That record is immutable.

## Testing

Every unit has unit tests (no I/O beyond `tmp_path`) and integration tests that assert
concrete records and catalog contents. These are the behaviours that must be covered:

- **The driver:**
  - reading and browsing by alternate key in both directions;
  - duplicates reported as in N4;
  - writes through an alternate key landing in the base file;
  - rejecting a repeated key in a unique key position.
- **catnip:**
  - AIX and path entries surviving a reopen of the system directory;
  - removing a cluster removing its AIXs and paths;
  - opening a path returning base records in N4's order.
- **Install:**
  - each validation rejection, naming its dataset and field;
  - a valid declaration producing the expected catalog and sorted bytes;
  - a second install into a new directory being identical.
- **cicada:**
  - CCXREF to CXACAIX visibility;
  - a region starting against an uncataloged DSN stopping, with the file and the DSN
    named;
  - a region restart keeping its writes;
  - the CardDemo end-to-end suite, unchanged in what it asserts.
- **N5:** the `xfail` test, citing red-dragon-forge-zqxf.

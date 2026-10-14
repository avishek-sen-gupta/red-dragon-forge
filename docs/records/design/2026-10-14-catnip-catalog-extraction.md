# catnip: The System Catalog as Its Own Component — Decision Record

**Date:** 2026-10-14
**Status:** accepted; implemented except where a decision says otherwise (red-dragon-forge-zave)
**Issues:** red-dragon-forge-zave (blocks red-dragon-forge-jr5, the prebuilt-program runner);
deferred: red-dragon-forge-zqxf (AIX duplicate order), red-dragon-forge-shdi (IDCAMS
AIX/PATH/BLDINDEX), red-dragon-forge-y6gk (region/job sharing and locking),
red-dragon-forge-b82q (jackal's status-39 logging, N10)
**Supersedes:** in [the 2026-09-09 package-boundaries record](2026-09-09-package-boundaries.md),
its list of workspace members and the catalog's implied placement in jackal ("jackal's
runner/catalog/IDCAMS"). That record's boundaries otherwise stand.

On z/OS the catalog and the datasets it labels belong to the system, and batch jobs and CICS
regions share them. CardDemo's `CLOSEFIL`/`OPENFIL` jobs depend on this: they close a file in
CICS, update it in batch, then reopen it. The forge had two stores. jackal owned the catalog;
cicada copied seed files into a temporary directory at every region start, took record lengths
and key positions from its region TOML, and kept each alternate index as a separate copy of the
base data. A record written by a job never reached a region, a region forgot its writes on
restart, cicada accepted unlabelled datasets against D5 of
[the 2026-10-11 dataset record](2026-10-11-jackal-dataset-decisions.md), and a write through one
CICS file was not visible through its alternate index. This record moves the catalog into its
own package and puts both runtimes on it. The design is
[the catnip spec](../../superpowers/specs/2026-10-14-catnip-system-catalog-design.md); the
reference is [catnip](../../reference/catnip/README.md).

## Sources

| Key | Document |
|---|---|
| COBOL | IBM Enterprise COBOL for z/OS Language Reference — the ALTERNATE RECORD KEY clause |
| CICS | IBM CICS Transaction Server for z/OS 5.5, Application Programming Reference — EXEC CICS DELETE, condition DUPKEY, RESP2 140 |
| CD | `vendor/carddemo`: `README.md`, "Upload Sample Data"; the IDCAMS JCL under `app/jcl`; `app/csd/CARDDEMO.CSD` |

## Decisions

**N1. catnip is a workspace member of its own.** It cannot live in `red_dragon_forge`, which
imports the runtimes and so cannot be imported by them. It cannot live in red-dragon, which knows
nothing of z/OS. catnip depends only on red-dragon (its file drivers); jackal and cicada import
it. `.importlinter` forbids catnip from importing cicada, squall, jackal, cobble or
`red_dragon_forge`, and adds catnip to cobble's forbidden runtimes. The three runtimes still
must not import each other; catnip is not a runtime.

**N2. What moved, and what stayed.** Moved from jackal unchanged: `labels`, `dataset`,
`system_catalog` (`SystemCatalog`, `NotCataloged`), `gdg`, `catalog_stores` and
`variable_records`. Stayed in jackal: the per-job view (`DatasetCatalog`), DCB merging,
allocation, the FD check at `OPEN`, and the IDCAMS executor, a client of the catalog. Stayed in
cicada: file control and its browse cursors. Both runtimes reach the bytes through the same
drivers; only the program-facing API differs.

**N3. Five kinds of catalog object.** Sequential datasets, clusters (KSDS), alternate indexes
(a DSN, its base cluster's DSN, an alternate key position, and whether keys are unique), paths
(a DSN naming one AIX, which is what programs open), and GDG bases. An AIX and a path have no
bytes. `catalog.json` keeps its shape and gains `aixs` and `paths`. Removing a cluster removes
its AIXs and their paths, as deleting a base cluster does on z/OS; jackal's IDCAMS `DELETE`
relies on it. No IBM text is quoted here for that rule.

**N4. Reading and writing through a path.** A path reads its base cluster in alternate-key
order; duplicates come in primary-key order. The order is computed when the path is opened and
nothing is stored, so it is always current, as `UPGRADE` promises. A write, rewrite or delete
through a path changes the base cluster. A read that finds more records with the same alternate
key reports it: COBOL file status `02`, CICS `DUPKEY` (RESP 15). A `DELETE` through a non-unique
path deletes the first record of the run and reports `DUPKEY` when more follow (CICS, DELETE,
DUPKEY RESP2 140). A write that would repeat a key in a unique AIX is rejected: status `22`, or
CICS `DUPREC`. RESP 15 is the value cicada already used for `DUPKEY`; IBM's EIBRESP table could
not be fetched to confirm it.

**N5. Known difference from z/OS, deferred (red-dragon-forge-zqxf).** z/OS returns duplicate
alternate keys "in the order in which they were placed in the file", and a random read returns
"the first record written" in a run of duplicates (COBOL). N4 agrees for data loaded at install
and differs for records written afterwards, or whose alternate key is rewritten afterwards.
Fixing it means storing each AIX as an index maintained on every write; the user deferred that on
2026-10-14. A cicada test pins the z/OS order and is marked `xfail`, citing zqxf.

**N6. The alternate-key driver belongs to red-dragon.** Alternate record keys are standard COBOL
(`ALTERNATE RECORD KEY ... WITH DUPLICATES`, `START`/`READ ... KEY IS`); z/OS implements them as
an AIX and a path. red-dragon's `AlternateIndexDriver` reads a fixed-length base file sorted by
its primary key in the order of any key position: point reads, `START`, read next and previous,
and writes, rewrites and deletes that update the base file, with N4's duplicate conditions.
`AccessCondition` gained `DUPLICATES_FOLLOW`. It replaced the read-only `AlternateKeyDriver`,
which red-dragon then removed. catnip opens a path as "the base cluster's file, ordered by this
AIX's key".

**N7. A region works on cataloged datasets in place.** A CICS file maps to a DSN through the
CSD's `DEFINE FILE(...) DSNAME(...)`. The label comes from the catalog and the bytes are the
catalog's own, so writes survive a restart and a job sees them. A CICS file whose DSN is not
cataloged, or is neither a cluster nor a path, stops the region at startup with a message naming
the file and the DSN. A new system directory starts empty; installing copies seeds into it, and
seeds are never written to.

**N8. Setup is declarative: `catnip install <declaration> --system DIR`.** Running a codebase's
own IDCAMS JCL is not the setup path (red-dragon-forge-shdi). The declaration lists
`[[sequential]]`, `[[ksds]]` with nested `[[ksds.aix]]`, and `[[gdg]]`; `from` paths are relative
to `data_dir`, with `${VAR}` expanded, and a KSDS without `from` is cataloged empty. It is parsed
into typed models as it is read. Install validates the whole declaration before writing anything
and stops at the first failure, naming the dataset and the field. It rejects a seed that is not a
whole number of records, a key that does not fit the record, a repeated primary key, a unique AIX
over repeated alternate keys, a DSN declared twice, and a missing `from` file. It then copies each
seed in, sorts each KSDS by primary key, and catalogs the AIXs and paths. A declaration is
written by hand or drafted by a coding agent; catnip has no generator.

**N9. CardDemo's declaration is the forge's own: `config/carddemo/data.toml`.** It carries the
sequential files labelled from CardDemo's README, and the clusters, AIXs and paths CardDemo's
IDCAMS JCL defines (CD). It replaced `red_dragon_forge/carddemo_jackal_install.py` and
`make jackal-install`; `make catnip-install-carddemo SYSTEM=DIR` installs it. CardDemo ships no
TRANSACT seed; TRANSACT is loaded from `DALYTRAN.PS`, which has the same layout, as the region
TOML did before, and the declaration states it.

**N10. A failure caused by the configuration names both sides, in the log.** In cicada, a
`NOTFND` whose program key length differs from the declared key length logs the CICS file, its
DSN, the declared key length and offset, and the program's key length; a `WRITE` or `REWRITE`
whose record differs from the declared record length logs the file, the DSN and both lengths.
These are logged rather than raised, because a COBOL program may handle the condition itself.
jackal's half, logging the DSN and both values when an FD's conflict with a label sets status
39, is not implemented (red-dragon-forge-b82q).

**N11. The region configuration.** The region TOML's `[datasets.*]` tables and `data_dir` are
gone; `[paths]` gains `csd_files`. The system directory is passed as `--system DIR` on
`cicada-tn3270` and `carddemo-db2-cli` rather than as a TOML key, so one region TOML serves any
system directory. cicada's seeding module, the per-start VSAM copies and the alternate-index
copies are removed. The VSAM dump tool takes `--system DIR --dsn DSN` instead of a `.dat` file.
jr5's `env.toml` inherits this shape.

**N12. Out of scope.** A region and a job using one system directory at the same time: neither
locks anything (red-dragon-forge-y6gk). Variable-length KSDS records: CardDemo's CSD says
`RECORDFORMAT(V)`, but its data is fixed length. ESDS and RRDS clusters.

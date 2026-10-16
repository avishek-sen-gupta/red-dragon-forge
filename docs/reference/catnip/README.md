# catnip

catnip is the system catalog: the datasets a mainframe's batch jobs and CICS regions share, and
the record the system keeps of them. jackal and cicada both depend on it. A job and a region
pointed at the same system directory read and write the same datasets, and what one writes,
the other reads. The decisions and their IBM sources are in
[the extraction decision record](../../records/design/2026-10-14-catnip-catalog-extraction.md).

catnip requires Python 3.13. It depends on `pydantic` and `red-dragon` (its file drivers) only.
`.importlinter` forbids it from importing cicada, squall, jackal, cobble or `red_dragon_forge`,
and forbids cobble from importing it.

## The system directory

A system directory stands in for a mainframe's disks and catalog. It holds:

- `catalog.json`: every catalog entry;
- `datasets/<DSN>`: each dataset's bytes, one file per dataset.

`SystemCatalog(DIR)` opens a directory, creating it if absent, and writes `catalog.json` after
every change. A directory keeps what earlier jobs and regions wrote. Nothing locks it: a job and
a region must not use one directory at the same time (red-dragon-forge-y6gk).

## Catalog objects

| Object | Holds | Bytes |
|---|---|---|
| Sequential dataset | RECFM (`F`, `FB`, `V`, `VB`) and LRECL | its own file |
| KSDS (cluster) | LRECL, key offset and key length; records fixed length, sorted by primary key | its own file |
| Pending dataset | nothing yet: a dataset a job created, labelled at its first `OPEN OUTPUT` | its own file |
| Alternate index (AIX) | its base cluster's DSN, an alternate key offset and length, and whether keys are unique | none |
| Path | the DSN of one AIX; this is the name a program opens | none |
| GDG base | `LIMIT`, `EMPTY`/`NOEMPTY`, `SCRATCH`/`NOSCRATCH`, `FIFO`/`LIFO`, its active generations | none |

Every open reads the label: it chooses the driver and gives the record length. A path opens its
base cluster's file through red-dragon's `AlternateIndexDriver`:

- Reads come in alternate-key order. Records with equal alternate keys come in primary-key
  order.
- A read that finds more records with the same alternate key reports it: COBOL file status
  `02`, CICS `DUPKEY` (RESP 15). A `DELETE` through a non-unique path deletes the first record of
  the run and reports `DUPKEY` when more follow.
- A write, rewrite or delete through a path changes the base cluster. One that would repeat a key
  in a unique AIX is rejected: file status `22`, CICS `DUPREC` (RESP 14).
- The order is computed when the path is opened. Nothing is stored, so it is always current.
- A path cannot be opened for `OUTPUT`. z/OS loads a cluster only once unless it is reusable, and
  a cluster with an AIX cannot be reusable, so `OUTPUT` through a path would reload a loaded base
  cluster. `Dataset.opened` raises `CatalogError`:
  `PATH: OPEN OUTPUT through a path would reload its base cluster BASE`.

Removing a cluster removes its AIXs and their paths. Removing an AIX removes its paths.

**Known difference from z/OS** (red-dragon-forge-zqxf). z/OS returns duplicate alternate keys in
the order they were written to the file. catnip returns them in primary-key order. The two agree
for data loaded by `catnip install`, and differ for records written afterwards, or whose
alternate key is rewritten afterwards. A cicada test pins the z/OS order and is marked `xfail`.

### `catalog.json`

```json
{
  "entries": [
    {"dsn": "A.SEQ", "label": {"kind": "sequential", "recfm": "FB", "lrecl": 80}},
    {"dsn": "A.KSDS", "label": {"kind": "ksds", "lrecl": 50, "key_offset": 0, "key_length": 16}},
    {"dsn": "A.NEW", "label": {"kind": "pending"}}
  ],
  "gdgs": [
    {"name": "A.HIST", "limit": 5, "empty": "NOEMPTY", "scratch": "NOSCRATCH",
     "order": "LIFO", "generations": [1, 2]}
  ],
  "aixs": [
    {"dsn": "A.AIX", "base": "A.KSDS", "key_offset": 25, "key_length": 11, "unique": false}
  ],
  "paths": [
    {"dsn": "A.PATH", "aix": "A.AIX"}
  ]
}
```

`gdgs`, `aixs` and `paths` may be absent. Key offsets count from 0. The file is read into typed
models; an unknown field is an error.

## `catnip install`

```bash
uv run --no-sync catnip install DECLARATION --system DIR
```

Installs a data declaration into the system directory `DIR`. Install into a new directory to
start clean. Installing again into the same directory replaces the declared datasets with their
seeds and leaves every other dataset as it is. Seed files are only read.

Install validates the whole declaration before writing anything, and stops at the first
failure with exit status 1. It then:

1. copies each sequential seed in, labelled as declared;
2. writes each KSDS sorted by its primary key, or empty without `from`;
3. catalogs each AIX and its path;
4. catalogs each GDG base, with no generations.

It logs `installed <DSN>` for each dataset, AIX, path and GDG base.

For CardDemo:

```bash
uv run catnip install config/carddemo/data.toml --system DIR
```

`data_dir` is resolved against the declaration's own directory.

### The declaration

A TOML file, read into typed models. An unknown key is an error.

```toml
data_dir = "../../vendor/carddemo/app/data/EBCDIC"

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

| Table | Keys |
|---|---|
| top level | `data_dir`: the directory `from` paths are relative to; relative to the declaration's own directory |
| `[[sequential]]` | `dsn`, `from`, `recfm` (`F`, `FB`, `V`, `VB`), `lrecl`; all required |
| `[[ksds]]` | `dsn`, `lrecl`, `key_offset`, `key_length`; `from` optional (without it the cluster is cataloged empty) |
| `[[ksds.aix]]` | `dsn`, `path` (the path's DSN), `key_offset`, `key_length`, `unique`; all required. Belongs to the `[[ksds]]` above it |
| `[[gdg]]` | `name`, `limit`, `empty` (`EMPTY`/`NOEMPTY`), `scratch` (`SCRATCH`/`NOSCRATCH`), `order` (`FIFO`/`LIFO`); all required |

A declaration may be written by hand or drafted by a coding agent that iterates on it while
running the programs. catnip has no generator.

`config/carddemo/data.toml` is CardDemo's. It carries the sequential files labelled as CardDemo's
README declares them, and the clusters, AIXs and paths CardDemo's IDCAMS JCL defines. CardDemo
ships no TRANSACT seed, so TRANSACT is loaded from `DALYTRAN.PS`, which has the same layout; the
declaration says so. It declares no GDG.

### Validation messages

Each message names the dataset and the declaration field to change.

| Rejected | Message |
|---|---|
| A `from` file that does not exist | `DSN: from: FILE does not exist` |
| A seed whose size is not a whole number of records | `DSN: from: FILE holds N bytes, not a whole number of L-byte records` |
| A primary or alternate key that does not fit inside the record | `DSN: key_offset: key O+K overruns the L-byte record` |
| A KSDS seed with a repeated primary key | `DSN: from: primary key b'…' repeats` |
| A unique AIX over repeated alternate keys | `AIX: unique: alternate key b'…' repeats` |
| A DSN declared twice, across datasets, AIXs, paths and GDG bases | `DSN: dsn: declared twice` |
| A TOML syntax error | `FILE: <the TOML parser's message, with line and column>` |
| A missing or unknown key, a wrong value type, `lrecl`, `key_length` or `limit` below 1, or a key offset below 0 | `[[SECTION]] NAME: FIELD: <pydantic's message>`, for example `[[ksds.aix]] A.AIX: key_offset: Input should be greater than or equal to 0` |

`SECTION` is `sequential`, `ksds`, `ksds.aix` or `gdg`. `NAME` is the entry's `dsn` (`name` for a
GDG base), or `entry N` (counting from 1) when that did not parse. These shape errors are found
while the file is read, so nothing is written.

## What uses it

- **jackal** opens a job's datasets through the catalog. Its per-job view (temporary and passed
  datasets, referbacks), DCB merging, allocation, the COBOL `OPEN` check against the label, and
  IDCAMS stay in jackal. A COBOL program reads and writes a cluster through a path by naming the
  path's DSN on its DD. `jackal catalog add` catalogs one sequential dataset by hand. See
  [jackal's architecture](../jackal/architecture.md#datasets-and-the-catalog).
- **cicada** resolves each CICS file to a cataloged cluster or path through the CSD's
  `DSNAME`. See [cicada's architecture](../cicada/architecture.md#vsam).

IDCAMS `DEFINE AIX`, `DEFINE PATH` and `BLDINDEX` are not implemented; AIXs and paths come from
a declaration (red-dragon-forge-shdi). ESDS and RRDS clusters, and variable-length KSDS records,
are not supported.

## Package layout

| Path | Contents |
|---|---|
| `catnip/catnip/system_catalog.py` | `SystemCatalog`, `NotCataloged`, the `catalog.json` format |
| `catnip/catnip/labels.py` | `SequentialLabel`, `KsdsLabel`, `LabelPending`, `PathView` |
| `catnip/catnip/dataset.py` | `Dataset`: a DSN, its file and its label, opened by its label |
| `catnip/catnip/alternate_index.py`, `catalog_path.py` | `AlternateIndex`, `CatalogPath` |
| `catnip/catnip/gdg.py` | `GdgBase` and relative-generation arithmetic |
| `catnip/catnip/variable_records.py` | RECFM=V/VB records on disk, each behind its record descriptor word |
| `catnip/catnip/catalog_stores.py` | the catalog's in-place lookup table |
| `catnip/catnip/system_catalog_removal.py` | removing a dataset from the catalog |
| `catnip/catnip/catalog_error.py` | `CatalogError`: a catalog request its contents cannot satisfy |
| `catnip/catnip/declaration_error.py` | `DeclarationError`: a declaration fault, naming the dataset and field |
| `catnip/catnip/declaration.py`, `install.py`, `cli.py` | the declaration, `install`, and the `catnip` command |
| `catnip/tests/unit/` | unit tests. Installing CardDemo's declaration is tested in the root suite |

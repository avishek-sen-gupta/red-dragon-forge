# jackal CLI

The `jackal` command is `jackal.cli:main`, declared in `jackal/pyproject.toml`. Run it from
the repo root as `uv run --no-sync jackal`. `python -m jackal` does not work: the package has
no `__main__`.

## `jackal catalog add`

```
jackal catalog add DSN --system DIR --file PATH --recfm {F,FB,V,VB} --lrecl N
```

Copies `PATH` into the system directory `DIR` as dataset `DSN`, cataloged in catnip's system
catalog with the given label (a sequential dataset). This is the mainframe's upload: jobs only
ever read the system's copy. A dataset is brought in once; later runs against the same `DIR`
find it. To load many datasets, clusters, alternate indexes and paths at once, use
`catnip install` ([catnip](../catnip/README.md#catnip-install)); a CICS region pointed at `DIR`
sees the clusters and paths it installs.

## `jackal run`

```
jackal run JCL --system DIR [--source-dir DIR] [--copybook-dir DIR] [--proclib DIR]...
           [--link PGM ...]
```

Parses `JCL`, runs every step against the system directory, and prints one line per step:

```
STEP05: RC=0
```

The exit status is 0 if the job completed with every return code 0, and 1 otherwise (a nonzero
return code, an abend or a failed allocation). A job that refers to a PROC, step or DD that does
not resolve is not run: the command prints `jackal: <reference>` and exits with 1. Argument errors
exit with 2.

| Argument | Default | Meaning |
|---|---|---|
| `JCL` | required | Path to the JCL file. |
| `--source-dir DIR` | `$CARDDEMO_HOME/app/cbl` | Directory of COBOL sources. `PGM=X` loads `DIR/X.cbl`; a program that is neither there nor a utility is stubbed with RC 0 and a warning. |
| `--system DIR` | required | The system directory: catnip's `catalog.json` and the cataloged datasets' bytes. Created if absent. |
| `--copybook-dir DIR` | `$CARDDEMO_HOME/app/cpy` | Copybook directory for COBOL steps. |
| `--proclib DIR` | `$CARDDEMO_HOME/app/proc` | Directory of cataloged procedures: `EXEC P` expands `DIR/P.prc`. Repeat the flag to search several directories in order. With neither the flag nor `CARDDEMO_HOME`, only in-stream PROCs expand. |
| `--link PGM ...` | none | Programs a CALL by data-name may reach. Each `PGM` is loaded from `--source-dir` and compiled into every COBOL step. A name with no source there is an argument error. |

`--source-dir` and `--copybook-dir` come from their flag, else from `CARDDEMO_HOME`. If neither is given the command
fails before parsing:

```
jackal: error: --source-dir is required: supply the flag or set $CARDDEMO_HOME
```

A run changes the system directory in place, as a job changes a mainframe's catalog: datasets
it catalogs stay for later runs, and datasets it deletes are gone. A DSN not in the catalog is
not found; the CLI then stands in an empty dataset, with a warning, and catalogs it like any
dataset the job creates. Temporary datasets, in-stream cards and sinks live in a scratch
directory that is removed when the command exits.

Each COBOL program may run 500,000 interpreter steps. One that has not ended by then abends
`S322`.

## Environment

| Variable | Required | Use |
|---|---|---|
| `JCL_BRIDGE_JAR` | yes | Path to the JCL bridge JAR. Parsing fails if unset. |
| `PROLEAP_BRIDGE_JAR` | for COBOL steps | Path to the ProLeap COBOL bridge JAR. |
| `CARDDEMO_HOME` | unless all three directory flags are given | Root of a CardDemo checkout, such as `vendor/carddemo`. The defaults above are relative to it. |

`. ./bridge-env.sh` from the repo root exports both JAR paths.

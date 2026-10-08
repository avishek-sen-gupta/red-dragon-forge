# jackal CLI

The `jackal` command is `jackal.cli:main`, declared in `jackal/pyproject.toml`. Run it from
the repo root as `uv run --no-sync jackal`. `python -m jackal` does not work: the package has
no `__main__`.

## `jackal run`

```
jackal run JCL [--source-dir DIR] [--data-dir DIR] [--copybook-dir DIR] [--dataset DSN=PATH ...]
```

Parses `JCL`, runs every step, and prints one line per step:

```
STEP05: RC=0 ran=True
```

`ran=False` means the step was bypassed. The exit status is 0 if every step returned 0, and 1
otherwise. Argument errors exit with 2.

| Argument | Default | Meaning |
|---|---|---|
| `JCL` | required | Path to the JCL file. |
| `--source-dir DIR` | `$CARDDEMO_HOME/app/cbl` | Directory of COBOL sources. `PGM=X` loads `DIR/X.cbl`. |
| `--data-dir DIR` | `$CARDDEMO_HOME/app/data/EBCDIC` | Where an `OLD`, `SHR` or `MOD` DSN not in the catalog is looked up, as `DIR/<DSN>`. |
| `--copybook-dir DIR` | `$CARDDEMO_HOME/app/cpy` | Copybook directory for COBOL steps. |
| `--dataset DSN=PATH` | none | Seeds the catalog with a DSN bound to a file. Repeatable. |

Each directory comes from its flag, else from `CARDDEMO_HOME`. If neither is given the command
fails before parsing:

```
jackal: error: --source-dir is required: supply the flag or set $CARDDEMO_HOME
```

The run uses a fresh temporary working directory and catalog. Datasets the job creates there
are deleted when the command exits, so a job that reads another job's output cannot get it from
an earlier `jackal run`.

The CLI does not expand cataloged procedures: it passes no proclib directories to `JobRunner`.

## Environment

| Variable | Required | Use |
|---|---|---|
| `JCL_BRIDGE_JAR` | yes | Path to the JCL bridge JAR. Parsing fails if unset. |
| `PROLEAP_BRIDGE_JAR` | for COBOL steps | Path to the ProLeap COBOL bridge JAR. |
| `CARDDEMO_HOME` | unless all three directory flags are given | Root of a CardDemo checkout, such as `vendor/carddemo`. The defaults above are relative to it. |

`. ./bridge-env.sh` from the repo root exports both JAR paths.

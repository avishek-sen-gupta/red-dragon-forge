# Jackal

**Jackal** is the JCL-processing package for the [RedDragon](../vendor/red-dragon/README.md)
multi-language COBOL interpreter. It parses real mainframe JCL through the vendored ANTLR
**mapa** grammar (behind a Java "jcl-bridge"), models the job's DDs and datasets
(`dsn.py`, `model.py`), extracts the dataset and `FILE-CONTROL` knowledge graph
(`jcl_graph.py`, `cobol_file_graph.py`), and executes batch job steps end-to-end through
RedDragon — sequencing steps with `COND=` bypass and referback/temp DSN threading
(`runner.py`), running COBOL steps on the VM (`cobol_step.py`) and IDCAMS / IEFBR14 utility
steps (`idcams/`, `utilities.py`). The reference workload is the Apache-licensed
`aws-mainframe-carddemo` batch tier.

RedDragon is an editable path dependency at the forge-root `../vendor/red-dragon`, so its
source can be read and modified in place.

---

## Setup

**Prerequisites:** Python ≥ 3.10, [uv](https://docs.astral.sh/uv/), JDK 17+ and Maven (for the
ProLeap COBOL and JCL bridges).

```bash
git clone --recurse-submodules <repo>
cd jackal

make jar        # builds both Java bridges: the ProLeap COBOL bridge + the ANTLR jcl-bridge
                # (mtime-gated — use `make jar-force` after a red-dragon bump or grammar change)
uv sync         # Python deps (installs red-dragon from vendor/ in editable mode)
```

Export the environment variables the runner and test suite expect:

```bash
export PROLEAP_BRIDGE_JAR="$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
export JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"
export CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"
```

Always invoke `uv run` with `--no-sync` — red-dragon is an editable path dependency, and a
plain `uv run` rebuilds its large editable wheel whenever the submodule changed. Run a bare
`uv sync` once after cloning or after changing dependencies. See `CLAUDE.md` for the full
build/commit conventions.

---

## Running a job

```bash
uv run --no-sync python -m jackal run <job.jcl> \
    --source-dir <cbl> --data-dir <EBCDIC> --copybook-dir <cpy> \
    --dataset DSN=/path/to/file
```

The `--source-dir` / `--data-dir` / `--copybook-dir` flags default to `app/cbl`,
`app/data/EBCDIC`, and `app/cpy` under `$CARDDEMO_HOME` when omitted; `--dataset` (repeatable)
seeds the catalog with concrete `DSN=path` bindings. Each step prints its return code.

---

## Pointers

- Roadmap: [`docs/jcl-execution-roadmap.md`](docs/jcl-execution-roadmap.md) — what jackal needs
  to run useful batch programs end-to-end, layer by layer.
- Philosophy: [`PHILOSOPHY.md`](PHILOSOPHY.md)
- JCL grammar provenance: [`jcl-bridge/PROVENANCE.md`](jcl-bridge/PROVENANCE.md)
- Agent instructions: [`CLAUDE.md`](CLAUDE.md)
- License: MIT — [`LICENSE.md`](LICENSE.md)
</content>
</invoke>

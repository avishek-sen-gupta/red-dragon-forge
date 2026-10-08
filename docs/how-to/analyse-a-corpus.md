# Analyse a corpus with cobble

Runs cobble over CardDemo (`vendor/carddemo`): pre-flight checks, parse, field dataflow,
knowledge graph, and one program's control-flow closure. Every command runs from the repo
root. Every output lands under `cobble/out-carddemo/`, which git ignores.

For another corpus, change the paths in the two config files. Every flag is in
[the cobble reference](../reference/cobble/config.md).

## Prerequisites

- `make setup` has run (see [setup](setup.md)). It builds both bridge JARs and `hlasm_export`.
- Graphviz (`dot`, `sfdp`) is on `PATH` for the WebGL pages and the DOT renders.
- The bridge JAR paths are exported in this shell:

```bash
. ./bridge-env.sh
```

Expected: no output. A `warning: ... not built` line means `make setup` has not finished.

## Steps

1. Write the corpus config. It is `cobble/config/carddemo.toml` with every path made
   relative to the repo root and the generated directories moved under `cobble/out-carddemo/`.

   ```bash
   mkdir -p cobble/out-carddemo
   cat > cobble/out-carddemo/carddemo.toml <<'EOF'
   [corpus]
   cobol_dir = "vendor/carddemo/app/cbl"
   cobol_globs = ["*.cbl"]
   jcl_dir = "vendor/carddemo/app/jcl"
   jcl_globs = ["*.jcl", "*.JCL"]
   proclib_dirs = ["vendor/carddemo/app/proc"]
   csd_files = ["vendor/carddemo/app/csd/CARDDEMO.CSD"]
   copybook_dirs = [
     "cobble/out-carddemo/sym",
     "vendor/carddemo/app/cpy",
     "vendor/carddemo/app/cpy-bms",
     "cobble/cics-copybooks",
   ]
   asg_dir = "cobble/out-carddemo/parsed"

   [bms]
   bms_dir = "vendor/carddemo/app/bms"
   macros_dir = "cobble/bms-macros"
   sym_dir = "cobble/out-carddemo/sym"
   EOF
   ```

   Expected: the file exists.

2. Write the srccfg config, from `cobble/config/srccfg.example.toml`.

   ```bash
   cat > cobble/out-carddemo/srccfg.toml <<'EOF'
   [srccfg]
   asg_dir = "cobble/out-carddemo/parsed"
   out_dir = "cobble/out-carddemo/srccfg"
   EOF
   ```

   Expected: the file exists.

3. Generate the BMS symbolic copybooks.

   ```bash
   uv run --no-sync cobble-sym --config cobble/out-carddemo/carddemo.toml
   ```

   Expected: the last line reads `generated <n> symbolic copybooks -> cobble/out-carddemo/sym`.

4. Run the pre-flight diagnoses.

   ```bash
   uv run --no-sync diagnose-copybooks --config cobble/out-carddemo/carddemo.toml \
     --output cobble/out-carddemo/missing-copybooks.json
   uv run --no-sync diagnose-cobol --config cobble/out-carddemo/carddemo.toml \
     --output cobble/out-carddemo/unparseable-cobol.json
   uv run --no-sync diagnose-jcl --config cobble/out-carddemo/carddemo.toml \
     --output cobble/out-carddemo/unparseable-jcl.json
   ```

   Expected: `No missing copybooks.`, then `0 failed` from each of the other two.

5. Parse the corpus into the ASG cache.

   ```bash
   uv run --no-sync cobble-parse-corpus --config cobble/out-carddemo/carddemo.toml
   ```

   Expected: one `<member>.json` per program in `cobble/out-carddemo/parsed/`, and no `.fail`
   files.

6. Write the extents table.

   ```bash
   uv run --no-sync cobble-extents --asg-dir cobble/out-carddemo/parsed \
     --out cobble/out-carddemo/fixpoint/extents.jsonl
   ```

   Expected: `extents: wrote cobble/out-carddemo/fixpoint/extents.jsonl (0 skipped)`.

7. Run the fixpoint over every member.

   ```bash
   uv run --no-sync cobble-dataflow-fixpoint --asg-dir cobble/out-carddemo/parsed \
     --out-dir cobble/out-carddemo/fixpoint \
     --extents cobble/out-carddemo/fixpoint/extents.jsonl --all \
     > cobble/out-carddemo/fixpoint-summary.json
   ```

   Expected: exit status 0. `fixpoint/` holds `graph.jsonl`, `defs.jsonl`, `aliases.jsonl`,
   `targets.jsonl`, `jumps.jsonl` and `members/`. The summary has `"skipped": 0` and
   `"unsettled": 0`.

8. Link the per-program results across programs.

   ```bash
   uv run --no-sync cobble-dataflow-combine --config cobble/out-carddemo/carddemo.toml \
     --fixpoint-dir cobble/out-carddemo/fixpoint \
     --out-dir cobble/out-carddemo/combined --all
   ```

   Expected: `cobble/out-carddemo/combined/targets.jsonl` and `links.jsonl`, and a last line
   `combine: <n> rounds, <n> discovered edges`.

9. Build the knowledge graph and compare it with the reference.

   ```bash
   uv run --no-sync cobble-build --config cobble/out-carddemo/carddemo.toml \
     --output cobble/out-carddemo/graph/carddemo.jsonl \
     --dynamic-call-targets cobble/out-carddemo/combined/targets.jsonl
   uv run --no-sync cobble-compare --graph cobble/out-carddemo/graph/carddemo.jsonl
   ```

   Expected: the build reports one failure, `CICS program COCRDSEC: not found in cobol_globs
   matches` (the CSD defines a program CardDemo ships no source for). The compare ends with
   `RESULT: EMPTY DIFF`.

10. Render the graph.

    ```bash
    uv run --no-sync cobble-render --graph cobble/out-carddemo/graph/carddemo.jsonl
    uv run --no-sync cobble-render-webgl --graph cobble/out-carddemo/graph/carddemo.jsonl
    ```

    Expected: `carddemo.html` and `carddemo-webgl.html` beside the graph file. Open either in a
    browser.

11. Build one program's control-flow closure and draw it.

    ```bash
    uv run --no-sync cobble-srccfg-build COSGN00C --config cobble/out-carddemo/srccfg.toml \
      --dynamic-call-targets cobble/out-carddemo/combined/targets.jsonl \
      --output cobble/out-carddemo/srccfg/COSGN00C-closure.jsonl
    uv run --no-sync cobble-srccfg-webgl --cfg cobble/out-carddemo/srccfg/COSGN00C-closure.jsonl \
      --output cobble/out-carddemo/srccfg/COSGN00C-closure.html
    ```

    Expected: `COSGN00C-closure.html` in `cobble/out-carddemo/srccfg/`.

12. Ask the fixpoint a question.

    ```bash
    uv run --no-sync cobble-dataflow-fixpoint-query writers CDEMO-FROM-PROGRAM \
      --fixpoint-dir cobble/out-carddemo/fixpoint \
      --extents cobble/out-carddemo/fixpoint/extents.jsonl
    ```

    Expected: one block per program declaring `CDEMO-FROM-PROGRAM`, each with its declared
    extent and a `writers (<n>):` list.

## Clean up

```bash
rm -rf cobble/out-carddemo
```

## Troubleshooting

- `diagnose-cobol` reports a `NullPointerException` for every member: a `copybook_dirs`
  entry does not exist. Run step 3 first.
- `cobble-parse-corpus` refuses to start naming a copybook directory: same cause.
- `PROLEAP_BRIDGE_JAR not set` or `KeyError: 'JCL_BRIDGE_JAR'`: source `bridge-env.sh` in this
  shell.
- `hlasm_export not built`: run `make hlasm`.
- After a bridge change, parse into an empty `asg_dir`. The parse skips members it has
  already cached.

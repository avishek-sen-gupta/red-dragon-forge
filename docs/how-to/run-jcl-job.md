# Run a JCL job

Runs a CardDemo batch job through jackal. Flags are in
[../reference/jackal/cli.md](../reference/jackal/cli.md).

## Prerequisites

- `make setup` has completed at the repo root. See [setup.md](setup.md).
- The `vendor/carddemo` submodule is checked out.

## Steps

1. Export the bridge JAR paths.

   ```bash
   . ./bridge-env.sh
   ```

   Expected: no output. A `warning: … not built` line means `make setup` has not built that JAR.

2. Point jackal at the CardDemo checkout.

   ```bash
   export CARDDEMO_HOME="$PWD/vendor/carddemo"
   ```

   Expected: no output.

3. Bring the job's input into a system directory, with the label CardDemo's README gives it
   (FB, 300). This is the mainframe's upload step; it is done once per system directory.

   ```bash
   uv run --no-sync jackal catalog add AWS.M2.CARDDEMO.ACCTDATA.PS --system /tmp/jackal-system \
     --file vendor/carddemo/app/data/EBCDIC/AWS.M2.CARDDEMO.ACCTDATA.PS --recfm FB --lrecl 300
   ```

   Expected: no output, exit status 0.

4. Run `ACCTFILE.jcl`. It deletes, defines and loads the account VSAM KSDS with IDCAMS.

   ```bash
   uv run --no-sync jackal run vendor/carddemo/app/jcl/ACCTFILE.jcl --system /tmp/jackal-system
   ```

   Expected, with exit status 0:

   ```
   STEP05: RC=0
   STEP10: RC=0
   STEP15: RC=0
   ```

## Troubleshooting

- `--source-dir is required`: `CARDDEMO_HOME` is unset. Repeat step 2, or pass
  `--source-dir` and `--copybook-dir`.
- A step ends `allocation failed (DD …: DATASET_NOT_FOUND)`, or a warning says an empty dataset
  stood in for one: the dataset is not in the system directory. Add it with
  `jackal catalog add`, as in step 3.
- `KeyError: 'JCL_BRIDGE_JAR'`: step 1 was not run in this shell.
- `No module named jackal.__main__`: use `uv run --no-sync jackal`, not `python -m jackal`.

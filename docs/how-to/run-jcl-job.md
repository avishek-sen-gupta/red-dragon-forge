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

3. Run `ACCTFILE.jcl`. It deletes, defines and loads the account VSAM KSDS with IDCAMS.

   ```bash
   uv run --no-sync jackal run vendor/carddemo/app/jcl/ACCTFILE.jcl
   ```

   Expected, with exit status 0:

   ```
   STEP05: RC=0 ran=True
   STEP10: RC=0 ran=True
   STEP15: RC=0 ran=True
   ```

## Troubleshooting

- `--source-dir is required`: `CARDDEMO_HOME` is unset. Repeat step 2, or pass
  `--source-dir`, `--data-dir` and `--copybook-dir`.
- `KeyError: 'JCL_BRIDGE_JAR'`: step 1 was not run in this shell.
- `No module named jackal.__main__`: use `uv run --no-sync jackal`, not `python -m jackal`.

# Db2

squall's Db2 tests, the root composition suite and the Db2 CardDemo server use one Db2
container, `squall-db2`, defined in `squall/docker-compose.yml`.

## Prerequisites

- Docker, with a VM of at least 6 GiB. The image is amd64-only and runs emulated on Apple
  Silicon.
- `make setup` done.

## Start Db2

1. Create `squall/.env` and set a password.

   ```bash
   cp squall/.env.example squall/.env
   ```

   Edit `squall/.env` and set `DB2_PASSWORD`. Never commit `.env`.

2. Start the container and wait until it is healthy.

   ```bash
   make db2-up
   ```

   Prints `DB2 healthy.`. The first start initialises the database and takes several minutes.
   Later starts return at once.

3. Check that the instance answers queries.

   ```bash
   make db2-status
   ```

   Prints `Db2 UP -- …` and exits 0. Exit 1 means down, exit 2 means the DSN is unset.

4. Seed CardDemo's schema. Needed only for the Db2 CardDemo server.

   ```bash
   make db2-seed
   ```

   This drops and recreates the tables. Run it again whenever you want the data reset.

## Use Db2 from a shell

squall's DSNs come from `squall/db2/dsn-env.sh`, which reads `squall/.env`.

```bash
. ./bridge-env.sh
export SQUALL_DIR=squall
. squall/db2/dsn-env.sh
```

This exports `SQUALL_DB2_DSN` (database `MOJO`) and `SQUALL_DB2_DSN2` (database `MOJO2`).

## Lifecycle

| Command | Effect |
|---|---|
| `make db2-up` | Start the container and wait until healthy. Idempotent. |
| `make db2-status` | Connect and query; report whether the CardDemo schema is seeded. |
| `make db2-seed` | Drop, recreate and seed CardDemo's schema. |
| `make db2-restart` | Restart the instance inside the running container. Revives a killed instance. |
| `make db2-stop` | Stop the container. Keeps the container and its volume. |
| `make db2-clean` | Remove the container and its volume. The next `db2-up` re-initialises. |

Keep the container running between test runs. `make db2-stop` followed by `make db2-up` repeats
part of the initialisation.

## Troubleshooting: tests fail with `SQL30081N`

The container reports healthy while the Db2 process inside it has been killed for lack of
memory. A local connect reports `SQL1032N`.

1. Confirm it was the out-of-memory killer.

   ```bash
   docker exec squall-db2 dmesg | grep -i oom
   ```

   A line naming `db2sysc` with `global_oom` confirms it: the VM ran out, so a per-container
   memory limit does not help.

2. Revive the instance.

   ```bash
   make db2-restart
   ```

   Prints `TCP listener up.`.

3. If it recurs, give the VM at least 6 GiB and cap Db2's instance memory at 2 GiB. A 1 GiB cap refuses connections (SQL1643C, SQL10003C) under the parallel suites.

   ```bash
   colima stop && colima start --cpu 4 --memory 6     # Docker Desktop: Settings → Resources
   docker exec squall-db2 bash -lc "su - db2inst1 -c 'db2 update dbm cfg using INSTANCE_MEMORY 524288'"
   make db2-restart
   ```

   A freshly initialised volume already has the cap (`squall/db2/custom-init` sets it). Check
   with:

   ```bash
   docker exec squall-db2 bash -lc "su - db2inst1 -c 'db2 get dbm cfg'" | grep INSTANCE_MEMORY
   ```

The cap bounds shared memory only, so a long-running instance can still be killed. The
pre-commit hook runs `make db2-restart` before the root suite for this reason. Tracked as
`forge-zka`.

# Run the tests

Prerequisite: [Set up a fresh clone](setup.md).

## Everything

1. Start Db2. squall's suite and the root suite need it. See [Db2](db2.md).

   ```bash
   make db2-up
   ```

2. Run every suite: cicada, squall, catnip, litter, jackal, cobble, then the root composition suite.

   ```bash
   make test-all
   ```

## One suite

Run from the repo root. Each line is self-contained.

| Suite | Needs | Command |
|---|---|---|
| cicada | JARs | `. ./bridge-env.sh && (cd cicada && uv run --no-sync python -m pytest)` |
| squall | JARs, Db2 | `. ./bridge-env.sh && (cd squall && . db2/dsn-env.sh && uv run --no-sync python -m pytest)` |
| catnip | nothing | `(cd catnip && uv run --no-sync python -m pytest)` |
| litter | JARs | `. ./bridge-env.sh && (cd litter && uv run --no-sync python -m pytest)` |
| jackal | JARs | `. ./bridge-env.sh && (cd jackal && uv run --no-sync python -m pytest)` |
| cobble | nothing | `(cd cobble && uv run --no-sync python -m pytest)` |
| root (composition) | JARs, Db2 | `make test` |

Pass extra pytest arguments to the root suite with `make test PYTEST_ARGS="-k name"`.

Tests that need Db2 fail, not skip, when it is not running. Sourcing `bridge-env.sh` before
cobble's suite turns on its acceptance tests, which start a JVM and run much longer.

## Without Db2

CI runs this way; Db2-backed tests run only locally.

- squall: its Db2 tests are marked `db2`. Deselect them with
  `. ./bridge-env.sh && (cd squall && uv run --no-sync python -m pytest -m "not db2")`.
- root: with `SQUALL_DB2_DSN` unset, the `db2_dsn` fixture skips every Db2 test. Run
  `. ./bridge-env.sh && uv run --no-sync python -m pytest tests/`, not `make test`, which exports
  the DSN.

## Before committing

The pre-commit hook runs these. Run them by hand to see failures early.

```bash
make fmt
uv run pyright
uv run lint-imports
pre-commit run python-fp-lint-check --hook-stage manual --all-files
make test-all
```

Always use `uv run --no-sync`. A plain `uv run` re-resolves the workspace and rebuilds the
red-dragon editable wheel. After changing dependencies, run `make python` once.

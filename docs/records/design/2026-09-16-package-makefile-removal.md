# cicada, squall, jackal: Remove Per-Package Makefiles

**Date:** 2026-09-16
**Status:** implemented

---

## Goal

Same shape cobble now has: the forge root builds everything, and a package is tested with
`uv run pytest` after `. ./bridge-env.sh`. `cicada/`, `squall/` and `jackal/` lose their
`Makefile` and `build.sh`.

## Why

Each package kept the Makefile it had as a standalone repository. Every target is one of:

- **A copy of root setup** — `setup`, `build`/`build.sh`, `jar`, `jar-force`, `hlasm`,
  `hlasm-force`, `python`. All three already build from `../vendor/red-dragon`, so none is
  buildable outside forge anyway.
- **An env wrapper around pytest** — `test`, `test-unit`, `test-one`: `PROLEAP_BRIDGE_JAR`
  (all), `JCL_BRIDGE_JAR` (jackal), `CARDDEMO_HOME` (cicada, jackal), `db2/dsn-env.sh`
  (squall).
- **A `uv run` wrapper** — `fmt`, `lint`.
- **Real work** — squall's `db2-up`/`db2-restart`/`db2-stop`/`db2-clean`, which manage the
  Db2 container and wait on its health check.

---

## 1 — Root `Makefile` takes the Db2 targets

`db2-up`, `db2-restart`, `db2-stop`, `db2-clean` move verbatim, with `docker compose` given
`-f squall/docker-compose.yml`. The compose project directory stays `squall/`, so the project
name, the `squall-db2` container and its named volume are unchanged — an existing container is
reused, not re-initialised. The comments on why the container must stay up move with them.

`fmt` grows to CI's Black scope (every package's source and tests), replacing the per-package
`fmt` targets.

## 2 — `CARDDEMO_HOME` defaults in jackal's tests

cicada's `tests/integration/cics/conftest.py` already falls back to `vendor/carddemo/app`.
jackal's `carddemo_home` fixture skips instead; it gets the same fallback, so its CardDemo e2e
runs under a bare `uv run pytest` rather than silently skipping. `CARDDEMO_HOME` stays an
override; `bridge-env.sh` does not grow a third variable.

## 3 — Delete the package Makefiles and build scripts

`cicada/Makefile`, `cicada/build.sh`, `squall/Makefile`, `squall/build.sh`, `jackal/Makefile`,
`jackal/build.sh`.

## 4 — Callers

| Caller | Now | Becomes |
|---|---|---|
| root `test-all` | `$(MAKE) -C cicada\|squall\|jackal test` | `. ./bridge-env.sh`, then `cd <pkg> && $(PYTEST)`; squall's line also sources `db2/dsn-env.sh` |
| CI `cicada` | proleap `./build.sh`, `uv sync`, `make test` in `cicada/` | root `make jar`, `make python`; `. ./bridge-env.sh && cd cicada && uv run --no-sync python -m pytest` |
| CI `squall` | `make jar/python/db2-up/test` in `squall/` | root `make jar`, `make python`, `make db2-up`; source `bridge-env.sh` + `squall/db2/dsn-env.sh`, pytest in `squall/` |
| CI `jackal` | `make jar/python/test` in `jackal/` | root `make jar`, `make python`; source `bridge-env.sh`, pytest in `jackal/` |
| CI `forge` | `make db2-up` in `squall/` | root `make db2-up` |
| pre-commit cicada hook | `make -C cicada test PYTEST_ARGS="-x -q"` | `bash -c '. ./bridge-env.sh && cd cicada && uv run --no-sync python -m pytest -x -q'` |
| pre-commit jackal hook | inline JAR paths | sources `bridge-env.sh` |
| `precommit-scripts/run-tests-squall` | computes the JAR path | sources `bridge-env.sh` |

The CI hlasm step and each job's Python version are unchanged.

## 5 — Docs

Every `make <target>` run from a package directory becomes the root target or its `uv run`
command: `cicada/`, `squall/`, `jackal/` `README.md` and `CLAUDE.md`; root `README.md` and
`CLAUDE.md`; `docs/db2-container-memory.md` (`cd squall && make db2-*` → root
`make db2-*`). The replacements for `test-unit` (`uv run pytest tests/unit`) and cicada's
`test-one` (`uv run pytest -p no:xdist --override-ini=addopts= <path>`) are documented where
those targets were. Point-in-time records (`docs/presentation/artifacts/**/FACTS.md`,
`docs/**/plans/`) keep their commands.

Root `CLAUDE.md`'s rule that the runtimes "stay independently buildable" is reworded: they stay
independent **at the import level** (enforced by `.importlinter`) and are **built and set up
only from the forge root**.

## 6 — Presentation capture scripts

`docs/presentation/capture/jcl.sh` sources `bridge-env.sh` instead of computing both JAR paths
itself (its `CARDDEMO_HOME` default stays), and its missing-JAR hint says `make setup` at the
forge root. `db2_inqcust_capture.py`'s run instructions likewise source `bridge-env.sh` and the
root `make db2-up`.

Every capture script is run before this work is committed — including `cobble.sh` and
`srccfg.sh`, which the cobble consolidation (`26e5b759`) edited without running. They regenerate
tracked files under `docs/presentation/artifacts/`; a run is judged by its exit status and by a
diff limited to expected churn (timings, capture dates). Unexpected artifact changes are
investigated, not committed; expected churn is reverted rather than committed as part of this
change.

---

## Verification

```bash
make setup
make db2-up                                     # reuses the existing squall-db2 container
. ./bridge-env.sh
(cd cicada && uv run --no-sync python -m pytest)
(cd jackal && uv run --no-sync python -m pytest)       # CardDemo e2e runs, not skips, with no CARDDEMO_HOME
(cd squall && . db2/dsn-env.sh && uv run --no-sync python -m pytest)
make test-all
ls cicada/Makefile squall/Makefile jackal/Makefile cicada/build.sh squall/build.sh jackal/build.sh   # none exist
```

Before committing, from the root, each exits 0 with only expected churn under
`docs/presentation/artifacts/` (then `git restore docs/presentation/artifacts`):

```bash
bash docs/presentation/capture/cobble.sh
bash docs/presentation/capture/srccfg.sh
bash docs/presentation/capture/jcl.sh
uv run --no-sync python docs/presentation/capture/cics_flow.py
. ./bridge-env.sh && SQUALL_DIR=squall . squall/db2/dsn-env.sh && uv run --no-sync python docs/presentation/capture/db2_inqcust_capture.py
```

A commit touching each package clears every pre-commit hook; CI's `cicada`, `squall`, `jackal` and
`forge` jobs stay green.

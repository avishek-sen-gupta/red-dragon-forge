# squall DB2 Test Infrastructure (local + CI) — Design

**Status:** Designed (2026-06-27). Brainstormed. Awaiting user review. Repo: squall.

## What this builds (plain terms)
A tracked, reproducible way to stand up the DB2 that squall's integration tests require —
for both a fresh local checkout and CI — so the full suite (including the live-Db2 tests) runs
green deterministically, with **no committed credentials** and **no dependency on a third-party
image**. Today this is undocumented tribal knowledge: the `db2community` container must be
manually started (`db2start`) and DSN env vars set by hand — which just cost a long debugging
detour because DB2 was simply not running.

## Driver (why now)
squall's `tests/integration/test_db2_*.py` (and the `[db2]`-parametrized `tests/unit/
test_backend.py`) are **"require live Db2, no skip, fail loud" by design**. Nothing tracked in
the repo provisions that Db2. A clean checkout — or CI — cannot run the suite green without
out-of-band manual setup. This blocks reliable CI and onboarding.

## Key findings (from investigation)
- **The tests self-provision their schema.** Each db2 test `CREATE`/`DROP`s its own tables
  (EMPLOYEE, STAFF, ROUTED) per-test. "SAMPLE" in the tests is a *logical* connection-registry
  name mapping to a MOJO connection — **not** a real database. So the only real-DB2
  requirement is the **databases MOJO + MOJO2 existing** + a reachable, started instance. No
  table seeding needed.
- **The official IBM image pulls anonymously.** `icr.io/db2_community/db2` (e.g. tag
  `11.5.9.0`) `docker manifest inspect`s with no auth — verified. So we depend on **IBM's
  official, pinnable image**, not the third-party `anilmahadev/db2community` mirror. No
  private copy / private registry needed.
- **`privileged: true` is required** — DB2 community won't run without it. Consequence for CI:
  GitHub Actions `services:` containers can't easily run privileged, so CI **runs
  docker-compose in a workflow step** (which can set `privileged: true`), not a service block.
- The IBM image supports a **`/var/custom`** post-init hook (scripts run once after instance
  setup) and `DBNAME` (auto-creates one database) — the documented way to create MOJO + MOJO2.

## Components

### 1. `docker-compose.yml` (committed)
A single `db2` service:
- `image: icr.io/db2_community/db2:11.5.9.0` (official, pinned — not `:latest`).
- `privileged: true`.
- `ports: ["${DB2_PORT:-50000}:50000"]`.
- `environment:` `LICENSE=accept`, `DB2INSTANCE=db2inst1`, `DB2INST1_PASSWORD=${DB2_PASSWORD}`
  (**from the environment — never hardcoded**), `DBNAME=MOJO` (auto-creates the first DB).
- `volumes:` the `/var/custom` init script (read-only) + a **named volume** for `/database`
  (so local restarts skip first-init; DBs persist).
- `healthcheck:` polls real readiness — `su - db2inst1 -c "db2 connect to MOJO"` returning 0 —
  so `make`/CI wait deterministically instead of racing the slow startup.

### 2. `db2/custom-init/01-create-databases.sh` (committed → `/var/custom`)
Idempotent post-init script: create **MOJO2** if absent (`db2 list db directory` check, else
`db2 create database MOJO2`); MOJO comes from `DBNAME`. Runs once on first init via the IBM
image's documented hook. No table seeding — tests own their schema.

### 3. Credentials — single source, never committed
The DB2 password is **self-chosen** (we set it), so it lives in exactly one place per
environment and is derived everywhere else:
- **`docker-compose.yml`** uses `${DB2_PASSWORD}` — no hardcoded value.
- **`.env.example`** (committed) — required vars with **placeholders** only:
  `DB2_PASSWORD=changeme`, `DB2_PORT=50000`, plus a note that `PROLEAP_BRIDGE_JAR` is needed.
  No real secret. (`.gitignore` already has `.env` / `.env.*` / `!.env.example`.)
- **`.env`** (gitignored) — the real local value; created once via `cp .env.example .env`.
- **`db2/dsn-env.sh`** (committed) — sources `.env` and **constructs** the DSNs from
  `$DB2_PASSWORD`, exporting `SQUALL_DB2_DSN` / `SQUALL_DB2_DSN2` (and asserting
  `PROLEAP_BRIDGE_JAR`). The DSN *shape* is committed; the password is not. So no committed
  file ever contains the password.
- **CI** — `DB2_PASSWORD` comes from a **GitHub Actions secret** (`secrets.DB2_PASSWORD`); the
  workflow exports it and the same compose + `dsn-env.sh` consume it. Nothing secret in git.

### 4. `Makefile` targets
- `db2-up` — `docker compose up -d db2` then block until the healthcheck reports healthy.
  Idempotent: a fast no-op when already healthy (keep the container running between runs).
- `db2-stop` — `docker compose stop db2` (keep the container + volume; prefer leaving it up
  since re-up still re-runs DB2's configure phase). Removes nothing.
- `db2-clean` — `docker compose down -v` (remove the container AND volume; next up re-inits).
- `test` (existing, extend) — source `db2/dsn-env.sh`, then run the full suite. Document that
  `make db2-up` must have been run (or make `test` depend on it).

### 5. `.github/workflows/ci.yml` (committed)
On push / PR:
1. Checkout.
2. Set up Python + `uv`; build (or restore-cache) the ProLeap bridge JAR (`make jar`).
3. Create `.env` from the `DB2_PASSWORD` secret (or export it directly).
4. `docker compose up -d db2`; wait for the healthcheck healthy (bounded timeout — DB2
   first-init is several minutes).
5. Source `db2/dsn-env.sh`; run the full suite (`uv run --no-sync python -m pytest -q`).
- Runs compose-in-a-step so `privileged: true` works (vs a `services:` block which can't).

### 6. README / docs
A short "Running the tests" section: `cp .env.example .env` (set a password) → `make db2-up`
→ `make test`. Plus the operational note: the IBM image's first init is slow (minutes; ~20 min
under Apple-Silicon emulation) — pay it ONCE and **leave the container running**; `db2-up` is a
fast no-op when it's already healthy. Do not `down` between runs (forces a re-init).

## Sequencing — local proven before CI committed (hard gate)
Implementation is two phases with a **validation gate** between them:
- **Phase 1 — local infra, validated, then committed.** Build components 1–4 + 6
  (docker-compose, `/var/custom` init, `.env.example`, `db2/dsn-env.sh`, Makefile targets,
  README). Then **actually stand it up**: real `icr.io` pull, real DB2 first-init, MOJO/MOJO2
  created by the init hook, and the **full squall suite green via the NEW compose stack** (not
  the pre-existing manually-started `db2server` container). Only commit Phase 1 once that is
  demonstrably green.
- **Phase 2 — CI workflow (component 5), separate, gated on Phase 1.** The `.github/workflows/
  ci.yml` is authored and committed **only after** Phase 1 is proven working locally. Per the
  user: do not commit the pipeline changes to GitHub until local is validated.

## Validation findings (2026-06-27 — from actually standing it up)
The live stand-up confirmed the functional design (MOJO/MOJO2 created by the `/var/custom`
hook, healthcheck → healthy) and surfaced three hard facts that shape the fast-start story:
1. **A `docker commit`/`export` snapshot is impossible.** The official image declares
   `VOLUME /database` (and `/hadr`), so the entire instance + databases live on a volume —
   which commit/export exclude by definition. Every commit-based "baked" image came up with the
   db2inst1 user but an empty `/database`. **Pre-baking via commit is ruled out**, not deferred.
2. **The "previous setup" marker is the db2inst1 user in the container's `/etc/passwd`**
   (`getent passwd db2inst1`), NOT data on the `/database` volume. Consequence: `compose down`
   removes the container → loses the user → forces a full re-init on the next `up`, even though
   the named volume persists the data. Only keeping the **same container** avoids re-init.
3. **The slowness is dominated by amd64 emulation on Apple Silicon** (DB2 is x86-only): first
   init ~20 min emulated vs ~3–5 min on native amd64. CI (GitHub Actions = native amd64) is in
   the tolerable range; the painful local slowness is an Apple-Silicon artifact.

**Resulting fast-start strategy (decided):**
- **Local:** keep the container **running** (long-lived) — pay the one-time init once, then
  leave it up; tests connect to it. The named volume persists the data; the Makefile's normal
  teardown is `db2-stop` (keep container), never `down` (which forces re-init). `db2-up` is
  idempotent (fast no-op if already healthy).
- **CI:** **no baked image** — run `compose up` fresh each run on native amd64 (init ~3–5 min as
  a background service while other steps proceed). Acceptable; avoids the impossible/fragile bake.

## Out of scope (ruled out / not pursued)
- **A pre-baked fast-start image.** Ruled out: commit/export can't capture the `VOLUME /database`
  data (finding 1). A Dockerfile that COPYs initialized `/database` into the image + recreates
  the user is theoretically possible but fragile (the entrypoint re-runs a ~300 s configure
  phase regardless, so it may not even beat container-reuse) — not worth the effort given CI on
  native amd64 is already tolerable and local is solved by keeping the container up. (Original
  framing as "deferred CI-speed optimization" was wrong; the snapshot is architecturally blocked.)
- Seeding any schema/tables (tests self-provision).
- Migrating the existing manually-created local `db2server` container — the new compose stack
  stands alongside; the README points new setups at compose.

## Error handling / constraints
- **No committed credentials** — placeholders only; password from gitignored `.env` (local) or
  GH secret (CI). The committed artifacts contain only the DSN *shape*.
- **Fail loud** — `dsn-env.sh` asserts `DB2_PASSWORD` + `PROLEAP_BRIDGE_JAR` are set (no silent
  default password). The healthcheck-wait fails loudly on timeout rather than running tests
  against a not-ready DB2 (which produced the confusing SQL30081N).
- Pin the image tag (`11.5.9.0`), not `:latest` — reproducibility.
- Idempotent init (re-running `db2-up` on an existing volume must not error).

## Testing / validation
- **Local:** from a clean state — `cp .env.example .env` (set password) → `make db2-up` (waits
  healthy) → `make test` → full suite green (incl. db2 integration + the `[db2]` unit tests).
- **CI:** the workflow runs the full suite green on a fresh runner (first-init path), with
  `DB2_PASSWORD` from the secret.
- **Idempotency:** `make db2-up` twice (second on the existing volume) succeeds; `make
  db2-clean && make db2-up` re-creates MOJO/MOJO2 from scratch.
- **No-secret check:** `git grep` for the password value finds nothing; Talisman/secret-scan
  clean.

## Bookkeeping
- squall-only. Eliminates the "DB2 was just not started / DSNs unset" class of failure
  (recently a long detour). Memo: the operational facts live in the project memory note
  `squall-db2-test-setup`.

# Cicada local development tasks.
#
# `make setup`  — one-time after clone: pulls all submodules and compiles all
#                 native/JVM artefacts.
# `make test`   — full suite (unit + integration + CardDemo e2e) with the
#                 toolchain env wired up; builds the JAR and hlasm_export if
#                 missing.  A bare `pytest tests/` without these env vars will
#                 hard-fail the carddemo_e2e modules by design (see
#                 tests/integration/cics/conftest.py).
#
# Override any path via the environment, e.g.:
#   CARDDEMO_HOME=/path/to/carddemo/app make test
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
HLASM_EXPORT       ?= $(CURDIR)/third-party/che-che4z-lsp-for-hlasm-fork/build/bin/hlasm_export
CARDDEMO_HOME      ?= $(CURDIR)/third-party/carddemo/app

E2E_ENV = PROLEAP_BRIDGE_JAR=$(PROLEAP_BRIDGE_JAR) CARDDEMO_HOME=$(CARDDEMO_HOME)
PYTEST       = uv run --no-sync python -m pytest
PYTEST_PATHS ?= tests/
PYTEST_ARGS  ?=

.PHONY: help setup build python jar jar-force hlasm hlasm-force test test-unit fmt lint

help:
	@echo "make setup       - init submodules + compile all artefacts (run once after clone)"
	@echo "make build       - ./build.sh: force-rebuild bridge JAR + hlasm_export (if missing) + uv sync"
	@echo "make jar         - build ProLeap bridge JAR (skipped if already built)"
	@echo "make jar-force   - force-rebuild ProLeap bridge JAR"
	@echo "make hlasm       - build hlasm_export binary (skipped if already built)"
	@echo "make hlasm-force - force-rebuild hlasm_export"
	@echo "make python      - uv sync (install / refresh Python deps)"
	@echo "make test        - full suite with CardDemo e2e toolchain wired up"
	@echo "make test-unit   - unit tests only (no JAR or hlasm_export required)"
	@echo "make test-one    - run a single test with live stdout (no xdist)"
	@echo "make fmt         - black-format the codebase"
	@echo "make lint        - import-linter architectural contracts"
	@echo ""
	@echo "Paths (override via env):"
	@echo "  PROLEAP_BRIDGE_JAR = $(PROLEAP_BRIDGE_JAR)"
	@echo "  HLASM_EXPORT       = $(HLASM_EXPORT)"
	@echo "  CARDDEMO_HOME      = $(CARDDEMO_HOME)"

# ── One-time setup ────────────────────────────────────────────────────────────

setup:
	git submodule update --init --recursive
	$(MAKE) build

# ── Artefact builds ───────────────────────────────────────────────────────────

python:
	uv sync

$(PROLEAP_BRIDGE_JAR):
	cd ../vendor/red-dragon/proleap-bridge && ./build.sh

jar: $(PROLEAP_BRIDGE_JAR)

jar-force:
	cd ../vendor/red-dragon/proleap-bridge && ./build.sh

$(HLASM_EXPORT):
	cd third-party/che-che4z-lsp-for-hlasm-fork && ./build.sh

hlasm: $(HLASM_EXPORT)

hlasm-force:
	cd third-party/che-che4z-lsp-for-hlasm-fork && ./build.sh

# Force-rebuilds the bridge JAR from the current submodule source (clean mvn
# package) so a red-dragon bump can't leave a stale JAR behind — unlike the
# mtime-gated `jar`/`hlasm` targets below, which are kept for incremental use.
build:
	./build.sh

# ── Tests ─────────────────────────────────────────────────────────────────────

test: jar hlasm
	$(E2E_ENV) $(PYTEST) $(PYTEST_PATHS) $(PYTEST_ARGS)

test-unit:
	$(PYTEST) tests/unit/ $(PYTEST_ARGS)

test-one:
	$(E2E_ENV) $(PYTEST) --override-ini="addopts=" -p no:xdist $(PYTEST_PATHS) $(PYTEST_ARGS)

# ── Code quality ──────────────────────────────────────────────────────────────

fmt:
	uv run --no-sync python -m black cics tests

lint:
	uv run --no-sync lint-imports

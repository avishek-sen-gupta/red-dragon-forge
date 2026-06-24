# Squall local development tasks.
#
# `make jar`       — build ALL Java artefacts: the ProLeap bridge (parser +
#                    bridge, from the vendored red-dragon submodule). Skipped if
#                    already built; use `make jar-force` after a red-dragon bump.
# `make build`     — ./build.sh: force-rebuild the JAR + uv sync (uniform across
#                    cicada/jackal/squall).
# `make test`      — full suite (needs the ProLeap JAR; integration also needs
#                    SQUALL_DB2_DSN for the Db2 contract tests).
#
# Override any path via the environment.
PROLEAP_BRIDGE_JAR ?= $(CURDIR)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar

PYTEST       = uv run --no-sync python -m pytest
PYTEST_PATHS ?= tests/
PYTEST_ARGS  ?=

.PHONY: help setup build python jar jar-force test test-unit fmt lint

help:
	@echo "make setup       - init submodules + build all Java + uv sync (run once after clone)"
	@echo "make jar         - build all Java: ProLeap bridge (parser+bridge) (skipped if built)"
	@echo "make jar-force   - force-rebuild all Java artefacts"
	@echo "make build       - ./build.sh: force-rebuild the JAR + uv sync"
	@echo "make python      - uv sync (install / refresh Python deps)"
	@echo "make test        - full suite (needs ProLeap JAR + SQUALL_DB2_DSN for Db2 tests)"
	@echo "make test-unit   - unit tests only"
	@echo "make fmt         - black-format squall + tests"
	@echo "make lint        - import-linter architectural contracts"
	@echo ""
	@echo "  PROLEAP_BRIDGE_JAR = $(PROLEAP_BRIDGE_JAR)"

setup:
	git submodule update --init --recursive
	$(MAKE) build

python:
	uv sync

# ProLeap bridge = the red-dragon submodule's parser + the bridge (build.sh does both).
$(PROLEAP_BRIDGE_JAR):
	cd vendor/red-dragon/proleap-bridge && ./build.sh

jar: $(PROLEAP_BRIDGE_JAR)

jar-force:
	cd vendor/red-dragon/proleap-bridge && ./build.sh

build:
	./build.sh

test: jar
	$(PYTEST) $(PYTEST_PATHS) $(PYTEST_ARGS)

test-unit:
	$(PYTEST) tests/unit $(PYTEST_ARGS)

fmt:
	uv run --no-sync python -m black squall tests

lint:
	uv run --no-sync lint-imports
